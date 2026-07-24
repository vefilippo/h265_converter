from pathlib import Path

import transcoder.version as version_mod
from transcoder.version import read_version


def test_read_version_returns_file_contents():
    # Compare against the real VERSION file so releases don't break this test.
    expected = Path("solution/VERSION").read_text(encoding="utf-8").strip()
    assert read_version() == expected


def test_read_version_strips_whitespace(tmp_path, monkeypatch):
    vf = tmp_path / "VERSION"
    vf.write_text("2.3.4\n", encoding="utf-8")
    monkeypatch.setattr(version_mod, "_VERSION_PATH", vf)
    assert read_version() == "2.3.4"


def test_read_version_missing_file_falls_back(tmp_path, monkeypatch):
    missing = tmp_path / "nope" / "VERSION"
    monkeypatch.setattr(version_mod, "_VERSION_PATH", missing)
    assert read_version() == "0.0.0"
