"""攻略目录查询用例，不依赖聊天框架。"""

from ...features.guide.application import GuideApplication
from .contracts import CommandContext, CommandResult, ImageReply, TextReply


class GuideCommandHandler:
    CATEGORY_ALIASES = {
        "练度": "progression",
        "progression": "progression",
        "红球": "red_orbs",
        "red球": "red_orbs",
        "red_orb": "red_orbs",
        "red_orbs": "red_orbs",
        "珍藏品": "favorite",
        "收藏品": "favorite",
        "favorite": "favorite",
        "favorite_item": "favorite",
        "充能": "arena_charge",
        "竞技场": "arena_charge",
        "竞技场充能": "arena_charge",
        "arena_charge": "arena_charge",
        "洗词条": "overload",
        "词条": "overload",
        "overload": "overload",
        "pvp": "pvp",
        "配队": "pvp",
        "pvp配队": "pvp",
        "竞技场配队": "pvp",
    }

    def __init__(self, application: GuideApplication):
        self.application = application

    async def handle(self, context: CommandContext) -> CommandResult:
        category = context.parameters.get("category", "")
        page = context.parameters.get("page", "1")
        category_key = category.strip().lower()
        folder_name = self.CATEGORY_ALIASES.get(category_key)
        if folder_name is None:
            return CommandResult(
                (
                    TextReply(
                        "【NIKKE 常用攻略一图流】\n\n"
                        "支持查看以下分类攻略图：\n"
                        "• /妮姬 攻略 练度 — 角色培养与技能升级一图流\n"
                        "• /妮姬 攻略 红球 — 同步器等级与红球消耗一览表\n"
                        "• /妮姬 攻略 珍藏品 — 珍藏品养成与材料汇总\n"
                        "• /妮姬 攻略 充能 — 竞技场爆裂充能速查表\n\n"
                        "• /妮姬 攻略 洗词条 — Overload 词条教学\n"
                        "• /妮姬 攻略 PVP — 竞技场配队参考\n\n"
                        "仅发送 registry 中已登记的授权素材或白名单 HTTPS 链接。"
                    ),
                )
            )
        if not page.isascii() or not page.isdigit() or not 1 <= int(page) <= 10000:
            return CommandResult(
                (TextReply("页码应为正整数，例如：/妮姬 攻略 练度 2"),)
            )

        page_number = int(page)
        try:
            page_result = self.application.page(folder_name, page_number=page_number)
        except (ValueError, OSError):
            return CommandResult(
                (TextReply("攻略索引暂不可用，请管理员核对授权和文件配置。"),)
            )

        if page_result.entries:
            messages = [
                TextReply(
                    f"【{category}】第 {page_result.page_number}/{page_result.total_pages} 页；"
                    f"使用 /妮姬 攻略 {category} <页码> 翻页。"
                )
            ]
            for entry in page_result.entries:
                messages.append(TextReply(entry.caption(now=page_result.current_date)))
                messages.extend(ImageReply(str(image)) for image in entry.files[:10])
                messages.extend(TextReply(link) for link in entry.links)
            return CommandResult(tuple(messages))

        if page_number > 1 or page_result.total_entries:
            return CommandResult((TextReply("该攻略页不存在。"),))
        return CommandResult(
            (TextReply(f"暂未收录【{category}】攻略图，当前保留占位，等待后续登记素材。"),)
        )
