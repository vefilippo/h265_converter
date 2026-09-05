"""HandBrake encoder families: catalog, capability detection, preset resolution.

The transcoder used to hardcode NVENC presets, which fail on any non-NVIDIA host.
This module makes the encoder a first-class, detectable choice.

Everything here is pure except ``probe()``, which shells out to HandBrakeCLI.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass

AUTO = "auto"
CUSTOM = "custom"
CPU = "cpu"

# Preset names are verbatim from HandBrakeCLI 1.11.2 --preset-list. Note that
# AMD presets are named "VCN" (HandBrake 1.11 renamed them) even though the
# underlying encoder ids are still vce_h265 / vce_h265_10bit.
FAMILIES: dict[str, dict] = {
    "vcn": {
        "label": "AMD VCN",
        "preset_1080": "H.265 VCN 1080p",
        "preset_4k": "H.265 VCN 2160p 4K",
        "hardware": True,
    },
    "nvenc": {
        "label": "NVIDIA NVENC",
        "preset_1080": "H.265 NVENC 1080p",
        "preset_4k": "H.265 NVENC 2160p 4K",
        "hardware": True,
    },
    "qsv": {
        "label": "Intel QSV",
        "preset_1080": "H.265 QSV 1080p",
        "preset_4k": "H.265 QSV 2160p 4K",
        "hardware": True,
    },
    "cpu": {
        "label": "CPU (x265)",
        "preset_1080": "H.265 MKV 1080p30",
        "preset_4k": "H.265 MKV 2160p60 4K",
        "hardware": False,
    },
}

# Hardware before software; on a multi-GPU host the discrete vendor encoder wins.
AUTO_PRIORITY: tuple[str, ...] = ("vcn", "nvenc", "qsv", "cpu")

# HandBrake announces hardware support in its startup banner on every
# invocation, e.g. "[17:01:27] vcn: is available". Unavailable families print
# "<name>: not available on this system", and a missing NVIDIA runtime prints
# "Cannot load nvEncodeAPI64.dll" with no family prefix at all — so we match
# only the positive form and treat absence as unavailable. That fails safe: at
# worst we under-report an encoder the user can still select by hand.
_AVAILABLE_RE = re.compile(
    r"^\s*(?:\[[\d:]+\]\s*)?(vcn|nvenc|qsv):\s*is available\s*$",
    re.MULTILINE | re.IGNORECASE,
)


@dataclass(frozen=True)
class Resolution:
    """The outcome of choosing presets for a job."""

    preset_1080: str
    preset_4k: str
    family: str            # the family actually used
    requested: str         # what was configured
    substituted: bool      # swapped away from a KNOWN-unavailable explicit family
    detection_unknown: bool  # capabilities could not be determined


def parse_capabilities(banner: str) -> set[str]:
    """Parse HandBrake's startup banner into the set of available families.

    ``cpu`` is always included: x265 is built into every HandBrake build. This
    means a successful parse never returns an empty set, which is what lets
    ``probe()`` use the empty set to mean "unknown" (see its docstring).
    """
    found = {m.group(1).lower() for m in _AVAILABLE_RE.finditer(banner or "")}
    found.add(CPU)
    return found


def _presets(family: str) -> tuple[str, str]:
    meta = FAMILIES[family]
    return meta["preset_1080"], meta["preset_4k"]


def resolve(
    family: str,
    available: set[str],
    *,
    fallback_cpu: bool = True,
    custom_1080: str = "",
    custom_4k: str = "",
) -> Resolution:
    """Pick the preset pair for a job.

    An EMPTY ``available`` means capabilities are unknown, which is deliberately
    not the same as "unavailable": an explicitly chosen family is always run as
    configured, so a broken probe can never silently divert the user onto an
    hours-long CPU encode.
    """
    unknown = not available

    if family == CUSTOM:
        return Resolution(custom_1080, custom_4k, CUSTOM, CUSTOM, False, unknown)

    if family == AUTO:
        if unknown:
            # Nothing to choose from. cpu is the only family guaranteed present
            # in any HandBrake build. In practice a failed probe means HandBrake
            # is missing or broken and the job fails regardless; this branch
            # exists for determinism, not rescue.
            p1080, p4k = _presets(CPU)
            return Resolution(p1080, p4k, CPU, AUTO, False, True)
        chosen = next(f for f in AUTO_PRIORITY if f in available)
        p1080, p4k = _presets(chosen)
        return Resolution(p1080, p4k, chosen, AUTO, False, False)

    if family not in FAMILIES:
        # Defensive: an unrecognised stored value behaves like custom.
        return Resolution(custom_1080, custom_4k, CUSTOM, family, False, unknown)

    if not unknown and family not in available and fallback_cpu:
        p1080, p4k = _presets(CPU)
        return Resolution(p1080, p4k, CPU, family, True, False)

    p1080, p4k = _presets(family)
    return Resolution(p1080, p4k, family, family, False, unknown)


def infer_family(preset_1080: str, preset_4k: str) -> str:
    """Reverse-map a stored preset pair onto a family, for read-time migration.

    Both presets must match the same family; a half-match is a hand-tuned setup
    and is preserved as ``custom``.
    """
    if not preset_1080 and not preset_4k:
        return AUTO
    for fid, meta in FAMILIES.items():
        if preset_1080 == meta["preset_1080"] and preset_4k == meta["preset_4k"]:
            return fid
    return CUSTOM


log = logging.getLogger("transcoder")


def probe(handbrake_cli: str, timeout: float = 30.0) -> set[str]:
    """Ask HandBrake what it can encode with, by running ``--version``.

    HandBrake prints its capability banner on every invocation, so ``--version``
    is a ~1s probe. Returns the available families, or an EMPTY SET meaning
    "unknown" — a missing executable, a timeout, or any other failure. Callers
    must treat empty as unknown, never as "nothing available".
    """
    if not handbrake_cli:
        return set()
    try:
        # CREATE_NO_WINDOW keeps a console window from flashing when the app
        # runs from the tray or a scheduled task; absent on non-Windows.
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.run(
            [handbrake_cli, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=creationflags,
        )
    except Exception as exc:  # missing exe, timeout, permission error, ...
        log.warning("Encoder probe failed for %r: %s", handbrake_cli, exc)
        return set()
    return parse_capabilities(proc.stdout or "")
