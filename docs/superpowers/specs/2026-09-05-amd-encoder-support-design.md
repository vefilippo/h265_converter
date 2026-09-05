# AMD Encoder Support — Design

**Date:** 2026-09-05
**Status:** Approved for planning
**Scope:** Make the transcoder work on non-NVIDIA hardware by making the HandBrake
encoder a first-class, detectable setting instead of a hardcoded NVENC assumption.

## Problem

`config.py` hardcodes `PRESET_1080 = "H.265 NVENC 1080p"` and
`PRESET_4K = "H.265 NVENC 2160p 4K"`. On a machine with no NVIDIA GPU every job
fails. The presets are editable as free text in Settings, so a user who already
knows the correct HandBrake preset name can work around it — but nothing tells
them what their hardware supports, and a fresh install on AMD or Intel is broken
out of the box.

The reference machine for this work is AMD Ryzen 7 9800X3D + Radeon RX 9070 XT
(RDNA 4), with no NVIDIA hardware present.

## Verified facts

All confirmed against HandBrakeCLI **1.11.2** on the reference machine. These were
probed, not recalled; two of them contradict common assumptions.

**HandBrake reports encoder availability in its startup banner**, emitted on every
invocation including `--version`:

```
[17:01:27] Compile-time hardening features are enabled
Cannot load nvEncodeAPI64.dll
[17:01:27] vcn: is available
[17:01:27] qsv: not available on this system
[17:01:27] hb_init: starting libhb thread
```

`--version` is therefore a cheap (~1s) capability probe.

**`--preset-list` is a static catalog, not a capability check.** It lists NVENC,
QSV, VideoToolbox and MF presets on this AMD-only box. Detection must come from
the banner; the preset list cannot be used to infer what works.

**AMD presets are named VCN, not VCE.** HandBrake 1.11 renamed them. The encoder
*ids* remain `vce_h265` / `vce_h265_10bit` while the *presets* say VCN. Designing
from the older "VCE" naming would have produced preset strings that do not resolve.

**There is no adapter/device selection flag** anywhere in `--help` — no
`--qsv-adapter`, no VCE device selector. Consequently the integrated Radeon in the
9800X3D **cannot be targeted separately** from the discrete RX 9070 XT; AMF picks
the device. "Transcode on the iGPU while gaming on the dGPU" is not buildable and
is out of scope.

**HandBrake exits 2 on failure**, so the existing `returncode != 0` check in
`convert.py:88` is sound.

### Preset catalog

| Family | 1080p preset | 4K preset | Kind |
|---|---|---|---|
| `vcn` | `H.265 VCN 1080p` | `H.265 VCN 2160p 4K` | hardware (AMD) |
| `nvenc` | `H.265 NVENC 1080p` | `H.265 NVENC 2160p 4K` | hardware (NVIDIA) |
| `qsv` | `H.265 QSV 1080p` | `H.265 QSV 2160p 4K` | hardware (Intel) |
| `cpu` | `H.265 MKV 1080p30` | `H.265 MKV 2160p60 4K` | software (x265) |

`H.265 MF` (Media Foundation) is **deliberately excluded**: HandBrake never reports
it in the banner, so it cannot participate in detection, and as a generic wrapper
over the same vendor hardware it offers nothing the vendor family does not.

### Known unverified assumption

The reference machine has neither NVIDIA nor Intel hardware, so only the *negative*
signals for those families were observed (`Cannot load nvEncodeAPI64.dll`,
`qsv: not available on this system`) alongside the *positive* AMD signal
(`vcn: is available`). The parser therefore treats `<family>: is available` as the
positive pattern and absence-of-positive as unavailable. This fails safe: the worst
outcome is under-reporting an encoder that the user can still select manually.

## Architecture

### New module: `solution/transcoder/encoders.py`

Almost entirely pure, so it is cheap to test. One impure function, isolated.

- `FAMILIES` — the catalog above: family id to label, `preset_1080`, `preset_4k`,
  and hardware/software kind.
- `parse_capabilities(banner: str) -> set[str]` — pure. Parses HandBrake's startup
  text into the set of available families. `cpu` is always present; x265 is built in.
- `probe(handbrake_cli: str) -> set[str]` — the only impure function. Runs
  `HandBrakeCLI --version` with a timeout and parses the output. A missing
  executable or a timeout returns an empty set rather than raising.

  The empty set is load-bearing: a *successful* parse always contains at least
  `cpu`, so an empty set unambiguously means "probe failed / capabilities
  unknown" and is never confused with "nothing is available".
- `resolve(family, available, custom_1080, custom_4k)` — pure. Returns the preset
  pair, the family actually used, and whether a substitution occurred.
- `infer_family(preset_1080, preset_4k) -> str` — pure reverse lookup, used for
  read-time migration.

### Settings

Two new key/value settings, threaded through the existing machinery. No schema
change — `setting` is already a key/value table.

- `encoder_family` — one of `auto | vcn | nvenc | qsv | cpu | custom`
- `encoder_fallback_cpu` — boolean, defaults to **on**, stored as the strings
  `"true"` / `"false"` to match the existing `scheduler_run_at_startup` convention
- `encoder_capabilities` — the cached probe result, a JSON object of the shape
  `{"available": ["vcn", "cpu"], "detected_at": "<ISO-8601>"}`

`config.py` gains `ENCODER_FAMILY: str = "auto"`. `PRESET_1080` / `PRESET_4K` are
left unchanged: with a family set they matter only in `custom` mode, and altering
them would change behaviour for existing `.env` files.

### Job-time resolution — replaces `worker.py:85-87`

The worker currently reads two preset strings and picks by resolution. It instead
calls into the encoder module, which:

1. Reads `encoder_family`. `custom` uses today's free-text presets unchanged — the
   compatibility escape hatch.
2. `auto` selects the best *available* family by priority
   **`vcn` > `nvenc` > `qsv` > `cpu`** — hardware before software.
3. Capability-checks the chosen family. If it is known-unavailable and
   `encoder_fallback_cpu` is on, substitutes the CPU presets and writes a loud line
   to the job log and the activity ring buffer, naming the substitution and warning
   that it will be substantially slower.
4. Picks the 4K or 1080p preset from the resolved pair exactly as today.

CPU fallback fires **only** on a capability mismatch, never on a general encode
failure. A corrupt input cannot trigger a multi-hour CPU encode.

**Resolution when capabilities are unknown** (probe failed or never ran). The two
cases differ deliberately:

- An **explicit** family (`vcn`, `nvenc`, `qsv`, `cpu`, or `custom`) runs exactly as
  configured, with no substitution. This is the "unknown is not unavailable" rule:
  a broken probe must not override a deliberate choice.
- **`auto`** has nothing to select from, so it resolves to `cpu` — the only family
  guaranteed present in any HandBrake build — and logs that detection failed. In
  practice a failed probe means HandBrake itself is missing or broken, so the job
  would fail on any preset; this rule exists for determinism, not rescue.

### Capability caching

Probing is not run at server startup. The probe result is cached in the DB as a
normal setting (JSON plus a timestamp), written by the setup wizard and by the
Detect button. If the cache is absent — a fresh install, or an upgrade that never
ran the wizard — the worker probes once, lazily, on its first job and caches the
result. `auto` therefore works out of the box without adding a subprocess call to
every boot.

## API

New `solution/transcoder/api/routers/encoders.py`:

- `GET /api/encoders` — catalog plus cached availability. Each family with id,
  label, preset pair, hardware flag and `available` boolean, plus `detected_at`.
  Pure read, no subprocess.
- `POST /api/encoders/detect` — runs the probe, caches the result, returns the same
  shape. Accepts an optional `handbrake_cli` in the body, falling back to the stored
  value, mirroring `POST /api/settings/test/{service}` (`routers/settings.py:126`)
  so the wizard can detect against a path typed but not yet saved.

Both require auth. The wizard is already authenticated by the time it reaches the
HandBrake step: `/api/setup/password` establishes the session and the connections
step already calls the authenticated `PUT /api/settings`.

`encoder_family` and `encoder_fallback_cpu` are added to `SettingsOut`,
`SettingsUpdate` and the `simple_fields` list at `routers/settings.py:73`.

## Migration

No DB migration. `encoder_family` resolves at read time via `infer_family()`:

- Nothing stored (fresh install) → `auto`
- Stored presets matching a catalog family → that family, so an existing NVIDIA
  install keeps behaving exactly as it does today
- Stored presets matching nothing → `custom`, preserving hand-tuned presets

The inferred value is persisted the first time settings are saved.

## Error handling

**Unknown is not unavailable.** If the probe fails — bad CLI path, timeout,
unparseable output — nothing is cached and the configured presets run as-is. A
broken probe must never silently divert a user onto an hours-long CPU encode.
Fallback requires positive knowledge that the family is missing.

Detect surfaces failures as `{ok: false, error}`, matching the existing connection
tests. Fallback substitutions are written to both the job log and the activity ring
buffer.

## UI

**Settings → Encoder** keeps the CLI path field and gains:

- an encoder dropdown: Auto / AMD VCN / NVIDIA NVENC / Intel QSV / CPU x265 / Custom
- a **Detect** button rendering per-family availability badges
- a "fall back to CPU when the hardware encoder is unavailable" checkbox
- the two preset text fields, now shown only under `Custom` — nothing is lost, they
  are simply no longer the default way in
- an inline warning, non-blocking, when the selected hardware family is known to be
  unavailable

**Setup wizard**, `handbrake` step (`Setup.tsx:117-128`): after the CLI path, a
Detect button that reports what it found and preselects the family. On the reference
machine: *"Found AMD VCN — using hardware H.265 encoding."*

## Testing

TDD per `CLAUDE.md`: tests describing the behaviour come first.

**`tests/test_encoders.py`** — the centre of gravity. The parser is tested against
the **literal banner text captured from the reference machine**, not an invented
string, plus synthetic NVENC/QSV variants. Also covers `resolve()` across
auto-priority / explicit family / custom passthrough / fallback-on / fallback-off,
and `infer_family()` round-trips including unknown → `custom`.

**`tests/test_api_encoders.py`** — both endpoints, auth enforcement, caching
behaviour, and probe-failure responses.

**Worker tests** — resolution feeds the right preset, the fallback log line is
emitted, and the no-fallback-on-generic-failure guarantee holds.

**`tests/test_config.py`** — the new `ENCODER_FAMILY` default.

**Frontend** — `Settings.test.tsx` (dropdown renders, Custom toggles the preset
fields, Detect calls the endpoint) and `Setup.test.tsx` (detect step).

## Documentation

`CLAUDE.md` gains the two new endpoints, the updated Settings screen description,
and a note that presets are now family-derived.

## Out of scope

- **Targeting the integrated Radeon separately** — HandBrake exposes no adapter
  selector, so this is not buildable.
- **AV1** — the RX 9070 XT supports `AV1 VCN 2160p 4K` / `vce_av1`, but this is an
  H.265 pipeline.
- **`H.265 MF`** — undetectable and redundant, see the catalog note above.
- **Replacing presets with raw `--encoder` flags** — considered and rejected; it
  discards HandBrake's tuned presets and rewrites the encode path for control that
  was not asked for.
