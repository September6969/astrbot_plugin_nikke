from scripts.prepare_face_anchors import merge_records


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
