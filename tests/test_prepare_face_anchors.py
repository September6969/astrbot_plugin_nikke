from scripts.prepare_face_anchors import _registry_key, _role_override, merge_records


def test_manifest_rebuild_preserves_records_outside_explicit_scope():
    old = {
        "legacy": {"pixel_sha256": "legacy-digest"},
        "c010": {"pixel_sha256": "old-digest"},
    }
    rebuilt = {
        "c010": {"pixel_sha256": "new-digest"},
        "c352": {"pixel_sha256": "new-record"},
    }

    merged, preserved = merge_records(old, rebuilt)

    assert preserved == 1
    assert merged["legacy"] == old["legacy"]
    assert merged["c010"] == rebuilt["c010"]
    assert merged["c352"] == rebuilt["c352"]


def test_partial_c401_c581_rebuild_preserves_existing_production_records():
    old = {
        "c010": {"pixel_sha256": "c010-old"},
        "c016": {"pixel_sha256": "c016-old"},
        "c191": {"pixel_sha256": "c191-old"},
    }
    rebuilt = {
        "c401": {"pixel_sha256": "c401-new"},
        "c581": {"pixel_sha256": "c581-new"},
    }

    merged, preserved = merge_records(old, rebuilt)

    assert preserved == 3
    assert merged == {**old, **rebuilt}


def test_registry_key_requires_explicit_default_identity():
    assert _registry_key("c401", {}) == "401:default"
    assert _registry_key("c401_01", {}) is None
    assert _registry_key("c401_01", {"resource_id": 401, "costume_id": 60004}) == "401:60004"


def test_structured_torso_override_wins_over_legacy_chest_value():
    structured = {
        "upper_torso": {"kind": "attachment", "slot": "body_total"},
        "chest": "legacy_bone",
    }
    assert _role_override(structured) == structured["upper_torso"]
    assert _role_override({"chest": "legacy_bone"}) == "legacy_bone"
