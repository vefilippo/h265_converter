from transcoder import encoders
from transcoder.encoders import (
    AUTO, CPU, CUSTOM, infer_family, parse_capabilities, parse_unavailable, resolve,
)

# Captured verbatim from HandBrakeCLI 1.11.2 on an AMD Ryzen 9800X3D / RX 9070 XT
# box. Real output, not invented: NVENC fails to load, VCN is present, QSV is not.
AMD_BANNER = """[17:01:27] Compile-time hardening features are enabled
Cannot load nvEncodeAPI64.dll
[17:01:27] vcn: is available
[17:01:27] qsv: not available on this system
[17:01:27] hb_init: starting libhb thread
[17:01:27] thread 2 started ("libhb")
HandBrake 1.11.2
"""

NVIDIA_BANNER = """[10:00:00] Compile-time hardening features are enabled
[10:00:00] nvenc: is available
[10:00:00] vcn: not available on this system
[10:00:00] qsv: not available on this system
"""

INTEL_BANNER = """[10:00:00] qsv: is available
[10:00:00] nvenc: not available on this system
"""

# A recognised banner that mentions vcn but says NOTHING about nvenc — neither
# "is available" nor "not available on this system". Real HandBrake builds vary,
# and the positive NVENC/QSV wordings were never observed on real hardware, so
# "unmentioned" must mean UNKNOWN, not unavailable.
SILENT_ON_NVENC_BANNER = """[10:00:00] vcn: is available
[10:00:00] qsv: not available on this system
"""


def test_parse_nvidia_banner():
    assert parse_capabilities(NVIDIA_BANNER) == {"nvenc", CPU}


def test_parse_intel_banner():
    assert parse_capabilities(INTEL_BANNER) == {"qsv", CPU}


def test_parse_returns_empty_set_for_unrecognisable_output():
    # Empty output mentions none of vcn/nvenc/qsv, so it's unrecognised, not a
    # confident "cpu only" result. Returning {CPU} here would make resolve()
    # treat an explicitly-chosen nvenc/vcn as known-unavailable and silently
    # substitute CPU — exactly the multi-hour-CPU-encode bug the "unknown is
    # not unavailable" rule exists to prevent. The EMPTY set is reserved by
    # probe() to mean "capabilities unknown".
    assert parse_capabilities("") == set()


def test_parse_returns_empty_set_for_unparseable_banner():
    # Some future/older HandBrake banner format, or a different executable
    # entirely that exits 0 with unrelated output, must not be confidently
    # read as "cpu only" — that would make resolve() substitute CPU under an
    # explicitly-chosen hardware family.
    assert parse_capabilities("garbage output\n") == set()


def test_auto_prefers_vcn_over_cpu():
    r = resolve(AUTO, {"vcn", CPU})
    assert r.family == "vcn"
    assert r.preset_1080 == "H.265 VCN 1080p"
    assert r.preset_4k == "H.265 VCN 2160p 4K"
    assert r.substituted is False


def test_auto_priority_order_is_vcn_nvenc_qsv_cpu():
    assert resolve(AUTO, {"vcn", "nvenc", "qsv", CPU}).family == "vcn"
    assert resolve(AUTO, {"nvenc", "qsv", CPU}).family == "nvenc"
    assert resolve(AUTO, {"qsv", CPU}).family == "qsv"
    assert resolve(AUTO, {CPU}).family == CPU


def test_auto_with_unknown_capabilities_falls_to_cpu_and_flags_unknown():
    r = resolve(AUTO, set())
    assert r.family == CPU
    assert r.detection_unknown is True
    assert r.substituted is False


def test_explicit_available_family_is_used_as_is():
    r = resolve("nvenc", {"nvenc", CPU})
    assert r.family == "nvenc"
    assert r.preset_1080 == "H.265 NVENC 1080p"
    assert r.substituted is False


def test_explicit_unavailable_family_falls_back_to_cpu_when_enabled():
    r = resolve("nvenc", {"vcn", CPU}, {"nvenc"}, fallback_cpu=True)
    assert r.family == CPU
    assert r.requested == "nvenc"
    assert r.substituted is True
    assert r.preset_1080 == "H.265 MKV 1080p30"
    assert r.preset_4k == "H.265 MKV 2160p60 4K"


def test_explicit_unavailable_family_runs_as_configured_when_fallback_disabled():
    r = resolve("nvenc", {"vcn", CPU}, {"nvenc"}, fallback_cpu=False)
    assert r.family == "nvenc"
    assert r.substituted is False


def test_unknown_capabilities_never_substitute_an_explicit_family():
    # "Unknown is not unavailable" — a broken probe must not override a
    # deliberate choice, even with fallback enabled.
    r = resolve("nvenc", set(), fallback_cpu=True)
    assert r.family == "nvenc"
    assert r.substituted is False
    assert r.detection_unknown is True


def test_custom_passes_through_free_text_presets():
    r = resolve(CUSTOM, {"vcn", CPU}, custom_1080="My 1080", custom_4k="My 4K")
    assert r.family == CUSTOM
    assert r.preset_1080 == "My 1080"
    assert r.preset_4k == "My 4K"
    assert r.substituted is False


def test_custom_is_never_substituted_even_when_unavailable():
    r = resolve(CUSTOM, set(), fallback_cpu=True, custom_1080="X", custom_4k="Y")
    assert r.family == CUSTOM
    assert r.substituted is False


def test_infer_family_matches_catalog_presets():
    assert infer_family("H.265 VCN 1080p", "H.265 VCN 2160p 4K") == "vcn"
    assert infer_family("H.265 NVENC 1080p", "H.265 NVENC 2160p 4K") == "nvenc"
    assert infer_family("H.265 QSV 1080p", "H.265 QSV 2160p 4K") == "qsv"
    assert infer_family("H.265 MKV 1080p30", "H.265 MKV 2160p60 4K") == CPU


def test_infer_family_returns_auto_for_empty_presets():
    assert infer_family("", "") == AUTO


def test_infer_family_returns_custom_for_unrecognised_presets():
    assert infer_family("Fast 1080p30", "Fast 2160p60") == CUSTOM


def test_infer_family_returns_custom_for_mismatched_pair():
    # A half-matching pair is a hand-tuned setup; preserve it verbatim.
    assert infer_family("H.265 VCN 1080p", "H.265 NVENC 2160p 4K") == CUSTOM


def test_mf_is_not_in_the_catalog():
    assert "mf" not in encoders.FAMILIES


def test_auto_with_only_non_catalog_ids_falls_back_to_cpu_without_raising():
    # A capabilities blob containing only non-catalog ids (e.g. {"mf"} from a
    # hand-edited or future-version DB) must not raise StopIteration.
    r = resolve(AUTO, {"mf"})
    assert r.family == CPU


def test_explicit_cpu_is_never_reported_as_substituted():
    # family == requested == cpu must never produce substituted=True, which
    # would render a nonsense "substituted to CPU" message.
    r = resolve(CPU, {"vcn"})
    assert r.substituted is False


def test_unrecognised_explicit_family_behaves_like_custom():
    # Non-blank presets: the blank-preset fallback-to-CPU path is covered
    # separately by test_unrecognised_family_with_blank_presets_falls_back_to_cpu.
    r = resolve("vce", {"vcn", CPU}, custom_1080="Fast 1080p30", custom_4k="Fast 2160p60")
    assert r.family == CUSTOM
    assert r.requested == "vce"


# ── "Unmentioned is unknown", at HandBrake's own reporting granularity ────────


def test_parse_unavailable_is_empty_for_unrecognisable_output():
    assert parse_unavailable("") == set()
    assert parse_unavailable("garbage output") == set()


def test_amd_banner_splits_into_available_and_unavailable():
    assert parse_capabilities(AMD_BANNER) == {"vcn", CPU}
    assert parse_unavailable(AMD_BANNER) == {"qsv", "nvenc"}


def test_unmentioned_family_is_neither_available_nor_unavailable():
    assert "nvenc" not in parse_capabilities(SILENT_ON_NVENC_BANNER)
    assert "nvenc" not in parse_unavailable(SILENT_ON_NVENC_BANNER)


def test_explicit_family_unmentioned_by_the_banner_is_not_substituted():
    """The whole point of FIX 4: under-DETECTION must not cause SUBSTITUTION.

    A banner we parsed successfully but that never mentions nvenc tells us
    nothing about nvenc. Swapping the user onto a multi-hour CPU x265 encode on
    that basis is a regression for every NVIDIA user whose banner wording the
    anchored positive regex happens to miss.
    """
    available = parse_capabilities(SILENT_ON_NVENC_BANNER)
    unavailable = parse_unavailable(SILENT_ON_NVENC_BANNER)
    r = resolve("nvenc", available, unavailable, fallback_cpu=True)
    assert r.family == "nvenc"
    assert r.substituted is False
    assert r.preset_1080 == "H.265 NVENC 1080p"


def test_explicit_family_with_an_explicit_negative_is_substituted():
    available = parse_capabilities(AMD_BANNER)
    unavailable = parse_unavailable(AMD_BANNER)
    r = resolve("nvenc", available, unavailable, fallback_cpu=True)
    assert r.family == CPU
    assert r.requested == "nvenc"
    assert r.substituted is True


def test_explicit_negative_is_still_honoured_when_fallback_is_disabled():
    r = resolve("qsv", {"vcn", CPU}, {"qsv"}, fallback_cpu=False)
    assert r.family == "qsv"
    assert r.substituted is False


def test_omitted_unavailable_argument_never_substitutes():
    # Backward-compatible default: callers (and old cached blobs) that know
    # nothing about negatives must run the configured family as set.
    r = resolve("nvenc", {"vcn", CPU}, fallback_cpu=True)
    assert r.family == "nvenc"
    assert r.substituted is False


def test_a_positive_report_beats_a_contradictory_negative():
    # Substitution is the harmful direction, so a family reported available
    # wins over a stale/contradictory negative signal in the same blob.
    r = resolve("nvenc", {"nvenc", CPU}, {"nvenc"}, fallback_cpu=True)
    assert r.family == "nvenc"
    assert r.substituted is False


def test_auto_selection_ignores_the_unavailable_set():
    # 'auto' still picks the first AUTO_PRIORITY entry present in `available`.
    r = resolve(AUTO, {"vcn", CPU}, {"qsv", "nvenc"})
    assert r.family == "vcn"
    assert r.substituted is False


def test_nvenc_dll_line_alone_is_a_recognised_banner():
    """The real-world NVIDIA-missing banner has no '<family>:' line at all.
    It must still count as 'we understood this banner', otherwise a working
    AMD box with no NVIDIA runtime would report unknown."""
    banner = "[11:44:47] Cannot load nvEncodeAPI64.dll\nHandBrake 1.11.2\n"
    assert encoders.parse_capabilities(banner) == {"cpu"}
    assert encoders.parse_unavailable(banner) == {"nvenc"}


# ── Blank custom presets must not reach HandBrake ─────────────────────────────


def test_custom_with_blank_presets_falls_back_to_cpu():
    """Handing HandBrake --preset "" fails the job with an opaque error. CPU
    x265 is slow but correct, and substituted=True makes the swap visible in
    the job log."""
    r = encoders.resolve("custom", {"vcn", "cpu"}, custom_1080="", custom_4k="")
    assert (r.preset_1080, r.preset_4k) == ("H.265 MKV 1080p30", "H.265 MKV 2160p60 4K")
    assert r.family == "cpu"
    assert r.requested == "custom"
    assert r.substituted is True


def test_custom_with_one_blank_preset_falls_back_to_cpu():
    r = encoders.resolve("custom", {"cpu"}, custom_1080="Fast 1080p30", custom_4k="   ")
    assert r.family == "cpu"
    assert r.substituted is True


def test_custom_with_both_presets_set_is_untouched():
    r = encoders.resolve("custom", {"cpu"}, custom_1080="Fast 1080p30", custom_4k="Fast 2160p60")
    assert (r.preset_1080, r.preset_4k) == ("Fast 1080p30", "Fast 2160p60")
    assert r.family == "custom"
    assert r.substituted is False


def test_unrecognised_family_with_blank_presets_falls_back_to_cpu():
    r = encoders.resolve("wat", {"cpu"}, custom_1080="", custom_4k="")
    assert r.family == "cpu"
    assert r.requested == "wat"
    assert r.substituted is True


def test_banner_parsing_is_case_insensitive():
    banner = "[11:44:47] VCN: IS AVAILABLE\n[11:44:47] QSV: NOT AVAILABLE ON THIS SYSTEM\n"
    assert encoders.parse_capabilities(banner) == {"vcn", "cpu"}
    assert encoders.parse_unavailable(banner) == {"qsv"}
