from transcoder import encoders
from transcoder.encoders import AUTO, CPU, CUSTOM, infer_family, parse_capabilities, resolve

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


def test_parse_amd_banner_finds_vcn_and_cpu():
    assert parse_capabilities(AMD_BANNER) == {"vcn", CPU}


def test_parse_treats_nvenc_dll_failure_as_unavailable():
    assert "nvenc" not in parse_capabilities(AMD_BANNER)


def test_parse_does_not_confuse_not_available_with_available():
    assert "qsv" not in parse_capabilities(AMD_BANNER)


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


def test_parse_recognised_banner_still_includes_cpu():
    assert CPU in parse_capabilities(NVIDIA_BANNER)


def test_parse_amd_banner_returns_exactly_vcn_and_cpu():
    assert parse_capabilities(AMD_BANNER) == {"vcn", CPU}


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
    r = resolve("nvenc", {"vcn", CPU}, fallback_cpu=True)
    assert r.family == CPU
    assert r.requested == "nvenc"
    assert r.substituted is True
    assert r.preset_1080 == "H.265 MKV 1080p30"
    assert r.preset_4k == "H.265 MKV 2160p60 4K"


def test_explicit_unavailable_family_runs_as_configured_when_fallback_disabled():
    r = resolve("nvenc", {"vcn", CPU}, fallback_cpu=False)
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
    r = resolve("vce", {"vcn", CPU})
    assert r.family == CUSTOM
    assert r.requested == "vce"
