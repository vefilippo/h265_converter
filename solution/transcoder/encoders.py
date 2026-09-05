"""HandBrake encoder families: catalog, capability detection, preset resolution.

The transcoder used to hardcode NVENC presets, which fail on any non-NVIDIA host.
This module makes the encoder a first-class, detectable choice.

Everything here is pure except ``probe()``, which shells out to HandBrakeCLI.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone

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
# "Cannot load nvEncodeAPI64.dll" with no family prefix at all.
#
# Positive and negative signals are parsed SEPARATELY, and a family the banner
# mentions in neither form stays UNKNOWN. Absence must not imply unavailable:
# only the AMD positive and the two negatives above were observed on real
# hardware, so if some NVIDIA build words its positive line differently, an
# absence-means-unavailable parser would silently divert every NVIDIA user onto
# an hours-long CPU x265 encode (resolve() substitutes on "known unavailable").
# Under-detection must cost us a missing checkmark, never a substitution.
_AVAILABLE_RE = re.compile(
    r"^\s*(?:\[[\d:]+\]\s*)?(vcn|nvenc|qsv):\s*is available\s*$",
    re.MULTILINE | re.IGNORECASE,
)

# The verified negative forms. "<family>: not available on this system" is
# printed for vcn/nvenc/qsv; a missing NVIDIA runtime prints the DLL line
# instead, with no family prefix, and means nvenc specifically.
_UNAVAILABLE_RE = re.compile(
    r"^\s*(?:\[[\d:]+\]\s*)?(vcn|nvenc|qsv):\s*not available on this system\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_NVENC_DLL_RE = re.compile(r"Cannot load nvEncodeAPI64\.dll", re.IGNORECASE)

# HandBrake 1.11 always mentions each hardware family in its banner in one form
# or another (e.g. "vcn: is available", "qsv: not available on this system",
# "Cannot load nvEncodeAPI64.dll"). If a banner mentions NONE of these, we did
# not understand the output — an older/newer HandBrake with a different format,
# or some other executable that happens to exit 0 — and must report unknown
# rather than a confident (and wrong) {cpu}. See parse_capabilities().
_BANNER_MENTIONS_RE = re.compile(r"(vcn|nvenc|qsv|nvEncodeAPI)", re.IGNORECASE)


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

    ``cpu`` is always included when the banner is RECOGNISED: x265 is built
    into every HandBrake build. But if the banner does not mention any of
    vcn/nvenc/qsv in any form, we could not interpret it at all — an
    older/newer HandBrake with a different banner format, or some other
    executable that exits 0 — and must return the EMPTY set (unknown) rather
    than a confident-but-wrong {cpu}. Otherwise an explicitly chosen hardware
    family would look "known unavailable" and get silently substituted with
    CPU by resolve(), defeating the "unknown is not unavailable" rule.
    """
    if not _BANNER_MENTIONS_RE.search(banner or ""):
        return set()
    found = {m.group(1).lower() for m in _AVAILABLE_RE.finditer(banner or "")}
    found.add(CPU)
    return found


def parse_unavailable(banner: str) -> set[str]:
    """Families the banner EXPLICITLY reports as absent.

    This is the only thing that may trigger a CPU substitution. A family that
    appears in neither this set nor parse_capabilities() is unknown, and unknown
    is not unavailable — it runs as configured.
    """
    text = banner or ""
    found = {m.group(1).lower() for m in _UNAVAILABLE_RE.finditer(text)}
    if _NVENC_DLL_RE.search(text):
        found.add("nvenc")
    return found


def _presets(family: str) -> tuple[str, str]:
    meta = FAMILIES[family]
    return meta["preset_1080"], meta["preset_4k"]


def resolve(
    family: str,
    available: set[str],
    unavailable: set[str] | frozenset[str] = frozenset(),
    *,
    fallback_cpu: bool = True,
    custom_1080: str = "",
    custom_4k: str = "",
) -> Resolution:
    """Pick the preset pair for a job.

    ``available`` and ``unavailable`` are the banner's POSITIVE and NEGATIVE
    reports; a family in neither is unknown. Unknown is deliberately not the
    same as unavailable: an explicitly chosen family is run as configured unless
    the banner explicitly said it is absent, so neither a broken probe nor a
    banner wording we failed to recognise can silently divert the user onto an
    hours-long CPU encode. ``unavailable`` defaults to empty, which is the safe
    direction — that is also what an old cached blob (written before negatives
    were recorded) resolves to.
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
        # Fall back to cpu rather than raising StopIteration: a capabilities
        # blob containing only non-catalog ids (e.g. from a hand-edited or
        # future-version DB) must never crash job resolution.
        chosen = next((f for f in AUTO_PRIORITY if f in available), CPU)
        p1080, p4k = _presets(chosen)
        return Resolution(p1080, p4k, chosen, AUTO, False, False)

    if family not in FAMILIES:
        # Defensive: an unrecognised stored value behaves like custom.
        return Resolution(custom_1080, custom_4k, CUSTOM, family, False, unknown)

    # Substitute ONLY on an explicit negative. A positive report wins over a
    # contradictory negative in the same blob: substitution is the harmful
    # direction, so it takes the stronger evidence.
    if (family != CPU and fallback_cpu
            and family in unavailable and family not in available):
        p1080, p4k = _presets(CPU)
        return Resolution(p1080, p4k, CPU, family, True, unknown)

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


def probe(handbrake_cli: str, timeout: float = 30.0) -> tuple[set[str], set[str]]:
    """Ask HandBrake what it can encode with, by running ``--version``.

    HandBrake prints its capability banner on every invocation, so ``--version``
    is a ~1s probe. Returns ``(available, unavailable)``: the families reported
    present and the families reported explicitly absent. Two EMPTY SETS mean
    "unknown" — a missing executable, a timeout, or any other failure. Callers
    must treat empty as unknown, never as "nothing available"; and a family in
    neither set is unknown too, never "unavailable".
    """
    if not handbrake_cli:
        return set(), set()
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
        return set(), set()
    banner = proc.stdout or ""
    return parse_capabilities(banner), parse_unavailable(banner)


# ── DB-aware helpers ─────────────────────────────────────────────────────────
# These read and write the ordinary key/value `setting` table. Callers own the
# transaction boundary and must commit, matching the convention in repo.py.

CAPABILITIES_KEY = "encoder_capabilities"
FAMILY_KEY = "encoder_family"
FALLBACK_KEY = "encoder_fallback_cpu"


def load_capabilities(session) -> tuple[set[str], set[str], str | None]:
    """Read the cached probe result as ``(available, unavailable, detected_at)``.

    Returns ``(set(), set(), None)`` when unknown. A blob written before
    negatives were recorded has no ``unavailable`` key and therefore reports
    nothing as explicitly absent — the safe direction, since only an explicit
    negative may substitute an encoder away from the user's choice.
    """
    from transcoder.repo import get_setting

    raw = get_setting(session, CAPABILITIES_KEY)
    if not raw:
        return set(), set(), None
    try:
        blob = json.loads(raw)
        return (set(blob["available"]),
                set(blob.get("unavailable") or []),
                blob.get("detected_at"))
    except (ValueError, KeyError, TypeError):
        log.warning("Ignoring corrupt %s setting", CAPABILITIES_KEY)
        return set(), set(), None


def store_capabilities(
    session,
    available: set[str],
    unavailable: set[str] | frozenset[str] = frozenset(),
) -> str:
    """Cache a probe result; returns the ISO-8601 detection timestamp."""
    from transcoder.repo import set_setting

    detected_at = datetime.now(timezone.utc).isoformat()
    set_setting(session, CAPABILITIES_KEY, json.dumps({
        "available": sorted(available),
        "unavailable": sorted(unavailable),
        "detected_at": detected_at,
    }))
    return detected_at


def detect_and_store(
    session, handbrake_cli: str
) -> tuple[set[str], set[str], str | None]:
    """Probe and cache. A failed probe caches NOTHING, so 'unknown' never
    hardens into a stored 'nothing is available'."""
    available, unavailable = probe(handbrake_cli)
    if not available:
        return set(), set(), None
    return available, unavailable, store_capabilities(session, available, unavailable)


def get_or_detect_capabilities(
    session, handbrake_cli: str
) -> tuple[set[str], set[str], str | None]:
    """Cached capabilities, probing once lazily if nothing is cached yet.

    This is what lets 'auto' work on a fresh install without adding a subprocess
    call to every server start.
    """
    available, unavailable, detected_at = load_capabilities(session)
    if available:
        return available, unavailable, detected_at
    return detect_and_store(session, handbrake_cli)


def resolve_for_job(session) -> Resolution:
    """Resolve the preset pair for a job from stored settings + capabilities."""
    from transcoder.config import settings as cfg
    from transcoder.repo import get_effective

    family = get_effective(session, FAMILY_KEY, cfg.ENCODER_FAMILY)
    fallback = get_effective(session, FALLBACK_KEY, "true") == "true"
    custom_1080 = get_effective(session, "handbrake_preset_1080", cfg.PRESET_1080)
    custom_4k = get_effective(session, "handbrake_preset_4k", cfg.PRESET_4K)
    handbrake_cli = get_effective(session, "handbrake_cli", cfg.HANDBRAKE_CLI)

    available, unavailable, _ = get_or_detect_capabilities(session, handbrake_cli)
    return resolve(
        family, available, unavailable,
        fallback_cpu=fallback,
        custom_1080=custom_1080,
        custom_4k=custom_4k,
    )


def migrate_encoder_family(session) -> str | None:
    """One-time backfill of `encoder_family`. Returns the value written, or None
    if it was already set. Caller commits.

    MUST run BEFORE seed_settings_from_env(): that seeder writes the NVENC
    config defaults into `handbrake_preset_1080`/`_4k` on every startup, so once
    it has run there is no way to tell a fresh install from a deliberate NVIDIA
    setup. The presence of `handbrake_preset_1080` in the DB is therefore the
    signal for "this install predates encoder families".
    """
    from transcoder.config import settings as cfg
    from transcoder.repo import get_setting, set_setting

    if get_setting(session, FAMILY_KEY) is not None:
        return None

    stored_1080 = get_setting(session, "handbrake_preset_1080")
    if stored_1080 is None:
        # Fresh install: nothing seeded yet. Seed from ENCODER_FAMILY — this
        # backfill runs at startup before anything reads the family, so once a
        # row exists get_effective() never consults the env fallback again.
        # Without this, the documented ENCODER_FAMILY setting is dead config.
        value = cfg.ENCODER_FAMILY or AUTO
    else:
        value = infer_family(stored_1080, get_setting(session, "handbrake_preset_4k") or "")
    set_setting(session, FAMILY_KEY, value)
    log.info("Backfilled encoder_family=%s", value)
    return value
