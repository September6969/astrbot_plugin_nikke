"""组装远程渲染器可独立使用的可信模板。"""
from pathlib import Path
from threading import Lock

PAGES = frozenset({
    "campaign", "calendar_schedule", "union_overview", "union_records", "union_member",
    "profile", "character", "roster", "arena_matchup", "arena_three_teams",
})
SHARED_CSS = ("reset.css", "tokens.css", "components.css", "utilities.css")
# 页面族共享的样式片段：占位符 -> 片段文件。
FRAGMENTS = {
    "union_": ("<!-- RAID_CSS -->", "raid.css"),
    "arena_": ("<!-- ARENA_CSS -->", "arena.css"),
}


class T2ITemplateLoader:
    def __init__(self, root: Path | None = None):
        self.root = root or Path(__file__).resolve().parent.parent / "templates" / "t2i"
        self._cache: dict[str, str] = {}
        self._lock = Lock()

    def load(self, page: str = "campaign") -> str:
        if page not in PAGES:
            raise ValueError("尚未支持该页面")
        cached = self._cache.get(page)
        if cached is not None:
            return cached
        # 模板随插件版本发布、运行期只读，首次组装后按页面复用，避免每次渲染重复读盘拼接。
        with self._lock:
            cached = self._cache.get(page)
            if cached is None:
                cached = self._cache[page] = self._compose(page)
        return cached

    def _compose(self, page: str) -> str:
        shared = self.root / "_shared"
        css = "\n".join((shared / name).read_text(encoding="utf-8") for name in SHARED_CSS)
        macros = (shared / "macros.jinja").read_text(encoding="utf-8")
        page_text = (self.root / f"{page}.html").read_text(encoding="utf-8")
        for prefix, (placeholder, fragment) in FRAGMENTS.items():
            if page.startswith(prefix):
                page_text = page_text.replace(placeholder, (shared / fragment).read_text(encoding="utf-8"))
        return "{% autoescape true %}\n" + macros + page_text.replace("<!-- SHARED_CSS -->", css) + "\n{% endautoescape %}"
