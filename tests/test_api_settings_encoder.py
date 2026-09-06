from typing import Literal, get_args

import pytest

from transcoder.repo import get_setting


def test_settings_exposes_encoder_family_and_fallback(api):
    client, _Session = api
    body = client.get("/api/settings").json()
    assert body["encoder_family"] == "auto"
    assert body["encoder_fallback_cpu"] == "true"


def test_settings_update_persists_encoder_family(api):
    client, Session = api
    r = client.put("/api/settings", json={"encoder_family": "vcn"})
    assert r.status_code == 200
    assert "encoder_family" in r.json()["updated"]
    with Session() as db:
        assert get_setting(db, "encoder_family") == "vcn"


def test_settings_update_can_disable_cpu_fallback(api):
    client, Session = api
    client.put("/api/settings", json={"encoder_fallback_cpu": "false"})
    with Session() as db:
        assert get_setting(db, "encoder_fallback_cpu") == "false"
    assert client.get("/api/settings").json()["encoder_fallback_cpu"] == "false"


def test_custom_family_keeps_free_text_presets_editable(api):
    client, Session = api
    client.put("/api/settings", json={
        "encoder_family": "custom",
        "handbrake_preset_1080": "Mine 1080",
        "handbrake_preset_4k": "Mine 4K",
    })
    body = client.get("/api/settings").json()
    assert body["encoder_family"] == "custom"
    assert body["handbrake_preset_1080"] == "Mine 1080"


# --- encoder_family validation at the API boundary -------------------------
#
# The .env half of this defect was fixed in 3b9a5c6 (migrate_encoder_family
# validates). PUT /api/settings wrote the field through an untyped
# simple_fields loop, so any string persisted. A stored bad value is sticky and
# resolve() routes it through the CUSTOM branch onto whatever presets are
# stored -- the hardcoded NVENC defaults on a fresh install -- which fails every
# job on AMD or Intel hardware. It has to be rejected at the boundary.

VALID = ["auto", "vcn", "nvenc", "qsv", "cpu", "custom"]


@pytest.mark.parametrize("family", VALID)
def test_valid_encoder_family_is_accepted(api, family):
    client, _Session = api
    r = client.put("/api/settings", json={"encoder_family": family})
    assert r.status_code == 200


@pytest.mark.parametrize("family", ["amd", "vce", "nvidia", "x265", "VCN ", "wat"])
def test_invalid_encoder_family_is_rejected(api, family):
    """A typo must fail loudly at the boundary rather than persisting into a
    sticky row that silently degrades to the custom-preset path."""
    client, _Session = api
    r = client.put("/api/settings", json={"encoder_family": family})
    assert r.status_code == 422


def test_rejected_family_is_not_persisted(api):
    client, Session = api
    client.put("/api/settings", json={"encoder_family": "amd"})
    with Session() as db:
        assert get_setting(db, "encoder_family") != "amd"


def _schema_allowed_families() -> set[str]:
    """The literal values SettingsUpdate.encoder_family accepts.

    The annotation is ``Literal[...] | None``, so unwrap the optional first and
    then read the literal's members.
    """
    from transcoder.api import schemas

    annotation = schemas.SettingsUpdate.model_fields["encoder_family"].annotation
    allowed: set[str] = set()
    for arg in get_args(annotation):
        if arg is type(None):
            continue
        allowed.update(get_args(arg))
    return allowed


def test_schema_family_literal_matches_the_catalog():
    """The schema's allowed set is the encoder catalog plus auto/custom. If the
    two drift, a family added to encoders.py would be rejected by the API it is
    supposed to be selectable through."""
    from transcoder.encoders import AUTO, CUSTOM, FAMILIES

    assert _schema_allowed_families() == {AUTO, *FAMILIES, CUSTOM}


def test_settings_update_family_annotation_is_a_literal():
    """Guards the fix itself: a plain `str | None` would let any value through
    even while the catalog test above still passed vacuously."""
    from transcoder.api import schemas

    annotation = schemas.SettingsUpdate.model_fields["encoder_family"].annotation
    literals = [a for a in get_args(annotation) if a is not type(None)]
    assert literals, "encoder_family must be a constrained union, not a bare str"
    for arg in literals:
        assert getattr(arg, "__origin__", None) is Literal
