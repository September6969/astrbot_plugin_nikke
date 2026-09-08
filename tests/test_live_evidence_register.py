from pathlib import Path


def test_live_evidence_register_keeps_required_boundaries_and_actions():
    document = (Path(__file__).resolve().parents[1] / "docs" / "LIVE_EVIDENCE_REGISTER.md").read_text(encoding="utf-8")

    for record in (
        "E-PROFILE-01",
        "E-RAID-01",
        "E-ANN-01",
        "E-DAILY-01",
        "E-VOICE-01",
        "E-SPINE-01",
    ):
        assert record in document

    for boundary in (
        "get_profile_dashboard",
        "GetUnionRaidData",
        "DAILY_CHECK_IN",
        "UNKNOWN_AFTER_ACTION",
        "AUTHORIZED_LIVE_READ",
        "NEEDS_HUMAN_DECISION",
        "mock",
    ):
        assert boundary in document
