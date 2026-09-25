from __future__ import annotations

from pathlib import Path

import pytest

from scripts.phase3_output_guard import require_new_external_path


def test_maintenance_output_must_be_external_and_not_exist(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    external = tmp_path / "evidence" / "baseline.json"

    assert require_new_external_path(external, repository, label="baseline") == external

    with pytest.raises(ValueError, match="仓库外"):
        require_new_external_path(repository / "assets" / "spine_manifest.json", repository, label="batch")

    external.parent.mkdir()
    external.write_text("existing", encoding="utf-8")
    with pytest.raises(ValueError, match="拒绝覆盖"):
        require_new_external_path(external, repository, label="baseline")
