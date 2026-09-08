from pathlib import Path


def test_post_merge_entry_records_dated_a_b_completion_and_profile_boundary():
    root = Path(__file__).resolve().parents[1]
    status = (root / "docs" / "POST_MERGE_STATUS.md").read_text(encoding="utf-8")
    phase2 = (root / "docs" / "POST_MERGE_PHASE2_PLAN.md").read_text(encoding="utf-8")
    acceptance = (root / "docs" / "PROFILE_V2_ACCEPTANCE.md").read_text(encoding="utf-8")

    for document in (status, phase2):
        assert "bada0b3aafcd7127d07ca40f554808b0433540f8" in document
        assert "PR #6" in document
        assert "PR #7" in document

    assert "READY_OFFLINE" in status
    assert "真实账号" in status
    assert "完成快照" in phase2
    assert "不是会自动更新的运行时状态源" in status
    assert "后续执行前仍须重新 fetch" in status
    assert "当前远端基线" not in status
    assert "当前 main：`origin/main@" not in acceptance
    assert "历史开发 base：`origin/main@a812b724" in acceptance
    assert "验收快照，不是后续 session 的实时 main" in acceptance
