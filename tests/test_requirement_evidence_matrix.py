"""确保路线图需求矩阵不会悄然丢失需求或重复编号。"""

from __future__ import annotations

import re
from pathlib import Path


REQUIRED_IDS = {
    "REQ-ACCOUNT-001",
    "REQ-ACCOUNT-002",
    "REQ-PROFILE-001",
    "REQ-CHAR-001",
    "REQ-CAMPAIGN-001",
    "REQ-TOWER-001",
    "REQ-RAID-001",
    "REQ-RAID-002",
    "REQ-RAID-003",
    "REQ-RAID-004",
    "REQ-CDK-001",
    "REQ-CDK-002",
    "REQ-ANN-001",
    "REQ-ANN-002",
    "REQ-ANN-003",
    "REQ-DAILY-001",
    "REQ-DAILY-002",
    "REQ-DAILY-003",
    "REQ-VOICE-001",
    "REQ-SPINE-001",
    "REQ-DATA-001",
    "REQ-DATA-002",
    "REQ-DATA-003",
    "REQ-DATA-004",
    "REQ-DATA-005",
    "REQ-GUIDE-001",
    "REQ-RELEASE-001",
}


def test_requirement_matrix_contains_unique_complete_requirement_set() -> None:
    path = Path(__file__).resolve().parents[1] / "docs" / "REQUIREMENT_EVIDENCE_MATRIX.md"
    text = path.read_text(encoding="utf-8")
    found = re.findall(r"\| (REQ-[A-Z0-9-]+) \|", text)

    assert set(found) == REQUIRED_IDS
    assert len(found) == len(set(found))
    for heading in ("生产入口", "代码与离线证据", "现场证据 / 授权边界", "产品状态", "剩余任务"):
        assert heading in text


def test_matrix_explicitly_preserves_evidence_boundaries() -> None:
    path = Path(__file__).resolve().parents[1] / "docs" / "REQUIREMENT_EVIDENCE_MATRIX.md"
    text = path.read_text(encoding="utf-8")

    assert "不视为已进入主线" in text
    assert "没有执行真实账号读取" in text
    assert "不能替代真实账号响应" in text


def test_each_requirement_row_has_all_evidence_columns() -> None:
    path = Path(__file__).resolve().parents[1] / "docs" / "REQUIREMENT_EVIDENCE_MATRIX.md"
    rows = [line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("| REQ-")]

    assert len(rows) == len(REQUIRED_IDS)
    for row in rows:
        cells = row[1:-1].split(" | ")
        assert len(cells) == 7
        requirement_id, *evidence_columns = [cell.strip() for cell in cells]
        assert requirement_id in REQUIRED_IDS
        assert all(evidence_columns)
