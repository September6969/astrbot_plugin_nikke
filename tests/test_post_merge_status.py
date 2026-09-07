from pathlib import Path


def test_post_merge_entry_records_current_a_b_completion_and_profile_boundary():
    root = Path(__file__).resolve().parents[1]
    status = (root / "docs" / "POST_MERGE_STATUS.md").read_text(encoding="utf-8")
    phase2 = (root / "docs" / "POST_MERGE_PHASE2_PLAN.md").read_text(encoding="utf-8")

    for document in (status, phase2):
        assert "bada0b3aafcd7127d07ca40f554808b0433540f8" in document
        assert "PR #6" in document
        assert "PR #7" in document

    assert "READY_OFFLINE" in status
    assert "真实账号" in status
    assert "完成快照" in phase2
