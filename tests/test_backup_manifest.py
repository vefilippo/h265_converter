import pytest
from transcoder import backup


def test_build_manifest_shape():
    m = backup.build_manifest("1.2.3", {"cipher": "AES-256-GCM"}, "2026-06-23T10:00:00Z")
    assert m["app"] == backup.APP_ID
    assert m["schema_version"] == backup.SCHEMA_VERSION
    assert m["app_version"] == "1.2.3"
    assert m["created_at"] == "2026-06-23T10:00:00Z"
    assert m["crypto"]["cipher"] == "AES-256-GCM"


def test_validate_accepts_current():
    m = backup.build_manifest("1.0.0", {}, "now")
    backup.validate_manifest(m)  # no raise


def test_validate_rejects_foreign_app():
    with pytest.raises(ValueError, match="not an H.265"):
        backup.validate_manifest({"app": "something-else", "schema_version": 1})


def test_validate_rejects_newer_schema():
    with pytest.raises(ValueError, match="newer"):
        backup.validate_manifest({"app": backup.APP_ID, "schema_version": backup.SCHEMA_VERSION + 1})
