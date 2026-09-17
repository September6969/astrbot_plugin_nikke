"""组装远程渲染器可独立使用的可信模板。"""
from pathlib import Path


class T2ITemplateLoader:
    def __init__(self, root: Path | None = None):
        self.root = root or Path(__file__).resolve().parent.parent / "templates" / "t2i"

    def load(self, page: str = "campaign") -> str:
        if page not in {"campaign", "calendar_schedule", "union_overview", "union_records", "union_member", "profile", "character"}:
            raise ValueError("尚未支持该页面")
        shared = self.root / "_shared"
        css = "\n".join((shared / name).read_text(encoding="utf-8") for name in
                        ("reset.css", "tokens.css", "components.css", "utilities.css"))
        macros = (shared / "macros.jinja").read_text(encoding="utf-8")
        page_text = (self.root / f"{page}.html").read_text(encoding="utf-8")
        return "{% autoescape true %}\n" + macros + page_text.replace("<!-- SHARED_CSS -->", css) + "\n{% endautoescape %}"
