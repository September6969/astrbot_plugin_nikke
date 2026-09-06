"""本地授权攻略索引：来源、版本、顺序和路径边界。"""
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class GuideEntry:
    id: str
    category: str
    title: str
    files: tuple[Path, ...]
    source: str
    credit: str
    license: str
    updated_at: str
    game_version: str

    def caption(self, now: date | None = None) -> str:
        stale = ((now or date.today()) - date.fromisoformat(self.updated_at)).days > 90
        return f"{self.title}\n版本：{self.game_version} · 更新：{self.updated_at}\n来源：{self.source}\n作者：{self.credit}\n授权：{self.license}" + ("\n内容可能过期，请核对当前版本。" if stale else "")


class GuideRegistry:
    def __init__(self, root: Path):
        self.root = root.resolve()
        path = self.root / "registry.json"
        self.entries = []
        if not path.is_file():
            return
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise ValueError("攻略索引必须是数组")
        identifiers = set()
        for row in rows:
            fields = ["id", "category", "title", "source", "credit", "license", "updated_at", "game_version"]
            if not isinstance(row, dict) or any(not isinstance(row.get(k), str) or not row[k].strip() for k in fields):
                raise ValueError("攻略索引缺少来源、授权或版本信息")
            if row["id"] in identifiers:
                raise ValueError("攻略 ID 重复")
            identifiers.add(row["id"])
            date.fromisoformat(row["updated_at"])
            if not isinstance(row.get("files"), list) or not row["files"]:
                raise ValueError("攻略没有图片")
            files = []
            for relative in row["files"]:
                if not isinstance(relative, str):
                    raise ValueError("图片路径无效")
                image = (self.root / relative).resolve()
                if not image.is_relative_to(self.root) or not image.is_file() or image.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                    raise ValueError("攻略图片路径越界或不可用")
                if image.stat().st_size > 12 * 1024 * 1024:
                    raise ValueError("攻略图片过大")
                files.append(image)
            self.entries.append(GuideEntry(**{k: row[k] for k in fields}, files=tuple(files)))

    def page(self, category: str, page: int = 1, size: int = 3):
        if page < 1 or not 1 <= size <= 10:
            raise ValueError("分页参数无效")
        entries = [item for item in self.entries if item.category == category]
        return entries[(page-1)*size:page*size]
