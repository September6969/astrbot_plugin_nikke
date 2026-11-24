# SPDX-License-Identifier: GPL-3.0-or-later
"""离线证据图表头字体：优先仓库内已核验的 CJK 字体，再回退到系统字体。

PR-6A 删除未被运行时使用的 NotoSansHans-*.otf 后，两个 Spine 证据脚本改用本模块。
所有支持中文的候选都排在纯拉丁字体（Barlow/Arial/DejaVu）之前。
注意：仓库子集字体总能加载，因此系统 CJK 字体实际不会被尝试；子集目前覆盖全部现有
角色名用字，但未来新增的生僻字仍可能显示为豆腐块，届时需重新生成子集字体。
"""

# 支持直接执行、模块导入及从其他工作目录调用。
import sys as _bootstrap_sys
from pathlib import Path as _BootstrapPath
_bootstrap_root = _BootstrapPath(__file__).resolve().parents[2]
for _bootstrap_path in (_bootstrap_root.parent, _bootstrap_root):
    if str(_bootstrap_path) not in _bootstrap_sys.path:
        _bootstrap_sys.path.insert(0, str(_bootstrap_path))

from pathlib import Path

from PIL import ImageFont

FONTS_DIR = _bootstrap_root / "assets" / "fonts"


def evidence_font_candidates(*, bold: bool = False) -> tuple[Path, ...]:
    """按优先级返回候选字体路径（只列出，不检查存在性）。"""
    bundled = (
        # WOFF2 需要带 Brotli 的 FreeType；CFF 的 ReplicaSans 作为不依赖 Brotli 的仓库内回退。
        FONTS_DIR / ("NotoSansSC-ReplicaSubset-800.woff2" if bold else "NotoSansSC-ReplicaSubset-700.woff2"),
        FONTS_DIR / "ReplicaSans.otf",
    )
    system_cjk = (
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/System/Library/Fonts/PingFang.ttc"),
        Path("/Library/Fonts/Arial Unicode.ttf"),
    )
    latin_only = (
        FONTS_DIR / ("BarlowCondensed-Bold.ttf" if bold else "BarlowCondensed-SemiBold.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    )
    return bundled + system_cjk + latin_only


def get_evidence_font(size: int, *, bold: bool = False):
    """加载失败永不抛出；全部失败时返回 Pillow 默认字体（极端情况下为 None）。"""
    for path in evidence_font_candidates(bold=bold):
        try:
            if path.exists():
                return ImageFont.truetype(str(path), size)
        except Exception:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None
