"""AstrBot 框架版本兼容边界。"""

from importlib.metadata import PackageNotFoundError, version

from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version


_SUPPORTED_ASTRBOT_VERSIONS = SpecifierSet(">=4.24,<5")


class AstrBotCompatibilityError(RuntimeError):
    """AstrBot 安装版本不满足插件声明的兼容范围。"""


def require_supported_astrbot_version() -> str:
    """在插件装配前确认当前宿主满足 AstrBot 版本合同。"""
    try:
        installed_version = version("AstrBot")
    except PackageNotFoundError as error:
        raise AstrBotCompatibilityError(
            "无法确定 AstrBot 版本：未找到 AstrBot 安装元数据。"
            "请确认宿主为 AstrBot >=4.24,<5 后再加载本插件。"
        ) from error

    try:
        parsed_version = Version(installed_version)
    except InvalidVersion as error:
        raise AstrBotCompatibilityError(
            f"无法解析 AstrBot 版本 {installed_version!r}；"
            "本插件要求 AstrBot >=4.24,<5。"
        ) from error

    if parsed_version not in _SUPPORTED_ASTRBOT_VERSIONS:
        raise AstrBotCompatibilityError(
            f"当前 AstrBot 版本为 {installed_version}，"
            "本插件要求 AstrBot >=4.24,<5；请升级宿主后再加载插件。"
        )

    return installed_version
