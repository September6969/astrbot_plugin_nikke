"""公开角色基础资料页面的 T2I payload。"""

from astrbot_plugin_nikke.ui.t2i_assets import T2IAssetResolver


class CharacterInfoT2IPayloadBuilder:
    """仅使用公开资料字段与身份已核验的本地头像。"""

    def __init__(self, assets=None, resolver=None):
        self.assets = assets
        self.resolver = resolver or T2IAssetResolver()

    def build(self, data):
        portrait_data_uri = None
        resource_id = getattr(data, "resource_id", None)
        master = getattr(self.assets, "character_master", None)
        resolve_resource_id = getattr(master, "resolve_resource_id", None)
        if resource_id not in (None, "") and callable(resolve_resource_id):
            try:
                canonical = resolve_resource_id(resource_id)
                canonical_id = getattr(canonical, "resource_id", None)
                asset_provider = getattr(self.assets, "get_character_asset", None)
                if canonical_id is not None and callable(asset_provider):
                    result = asset_provider(canonical_id, kind="icon")
                    image = getattr(result, "image", None)
                    if image is not None and getattr(result, "exact_match", False):
                        portrait_data_uri = self.resolver.encode(
                            image, (256, 256), cover_crop=True
                        )
            except Exception:
                portrait_data_uri = None

        return {
            "canvas": {"width": 1080, "height": 680},
            "name": str(getattr(data, "name", "未知妮姬")),
            "title": str(getattr(data, "title", "妮姬基础资料")),
            "portrait_data_uri": portrait_data_uri,
            "portrait_label": "静态目录头像" if portrait_data_uri else "头像待核验",
            "rows": [
                {"label": str(label), "value": str(value)}
                for label, value in getattr(data, "rows", ())
            ],
            "footer": "信息来自公开角色目录；头像仅在身份核验通过时显示",
        }
