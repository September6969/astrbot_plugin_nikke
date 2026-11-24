# SPDX-License-Identifier: GPL-3.0-or-later
"""生产路径使用的角色立绘透明度轮廓边界（robust_alpha_bounds）。

从实验性 face_guided_centering.py 原样拆出（PR-6B G6-character-spine-a2），
算法与 PR-4A 的 Pillow C 级投影实现逐字节一致；face_anchor.framing 的回退取景
依赖它，而面部引导整体居中实验路径（NIKKE_FACE_GUIDED_CENTERING）仍留在原模块。
features 层不直接导入 PIL，只依赖下列结构化协议。
"""
from __future__ import annotations

import math
from array import array
from typing import Protocol, Sequence


class AlphaPixels(Protocol):
    """可按像素坐标读取透明度的视图。"""

    def __getitem__(self, point: tuple[int, int]) -> int: ...


class ProjectionImage(Protocol):
    """C 级投影计算使用的单通道浮点图。"""

    def resize(self, size: tuple[int, int], resample: int) -> ProjectionImage: ...

    def tobytes(self) -> bytes: ...


class ThresholdMask(Protocol):
    """阈值查表后的 0/1 掩码。"""

    def convert(self, mode: str) -> ProjectionImage: ...


class AlphaChannel(Protocol):
    """RGBA 图像的透明度通道。"""

    @property
    def size(self) -> tuple[int, int]: ...

    def load(self) -> AlphaPixels: ...

    def point(self, lut: Sequence[int]) -> ThresholdMask: ...


class RasterImage(Protocol):
    """图像算法实际使用的最小结构化接口。"""

    @property
    def width(self) -> int: ...

    @property
    def height(self) -> int: ...

    def convert(self, mode: str) -> RasterImage: ...

    def getchannel(self, channel: str) -> AlphaChannel: ...


_BOX_RESAMPLE = 4  # PIL.Image.Resampling.BOX；features 层不直接导入 PIL


def _alpha_histograms(portrait: RasterImage, threshold: int):
    """生成阈值化透明度在横纵轴上的投影。

    用 Pillow C 级运算代替逐像素 Python 双重循环（2k×2k 图约 4M 次迭代）：
    阈值查表得到 0/1 掩码，转 F 模式后用 BOX 缩放到单行/单列得到精确均值，
    乘以边长并取整即为与原逐像素计数完全一致的投影。
    """
    alpha = portrait.convert("RGBA").getchannel("A")
    width, height = alpha.size
    pixels = alpha.load()
    mask = alpha.point([0] * threshold + [1] * (256 - threshold)).convert("F")
    # F 模式像素为本机字节序 float32；array 解码兼容 Pillow 11–13（getdata 已弃用）。
    rows = array("f", mask.resize((1, height), _BOX_RESAMPLE).tobytes())
    columns = array("f", mask.resize((width, 1), _BOX_RESAMPLE).tobytes())
    y_hist = [int(round(value * width)) for value in rows]
    x_hist = [int(round(value * height)) for value in columns]
    return pixels, width, height, x_hist, y_hist, sum(y_hist)


def _robust_alpha_bounds_from_histograms(
    x_hist: Sequence[int], y_hist: Sequence[int], trim_fraction: float
) -> tuple[int, int, int, int] | None:
    left = _hist_quantile_index(x_hist, trim_fraction)
    right = _hist_quantile_index(x_hist, 1.0 - trim_fraction)
    top = _hist_quantile_index(y_hist, trim_fraction)
    bottom = _hist_quantile_index(y_hist, 1.0 - trim_fraction)
    if None in (left, right, top, bottom):
        return None
    assert left is not None and right is not None and top is not None and bottom is not None
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def robust_alpha_bounds(
    portrait: RasterImage,
    *,
    alpha_threshold: int = 24,
    trim_fraction: float = 0.015,
) -> tuple[int, int, int, int] | None:
    """返回忽略少量透明度离群像素后的角色轮廓边界。"""
    if type(alpha_threshold) is not int or not 0 <= alpha_threshold <= 255:
        raise ValueError("alpha_threshold must be an integer in [0, 255]")
    if (
        not isinstance(trim_fraction, (int, float))
        or isinstance(trim_fraction, bool)
        or not math.isfinite(trim_fraction)
        or not 0.0 <= trim_fraction < 0.5
    ):
        raise ValueError("trim_fraction must be finite and in [0, 0.5)")
    _, _, _, x_hist, y_hist, alpha_pixels = _alpha_histograms(
        portrait, alpha_threshold
    )
    if alpha_pixels == 0:
        return None
    return _robust_alpha_bounds_from_histograms(x_hist, y_hist, float(trim_fraction))


def _hist_quantile_index(hist: Sequence[int], quantile: float) -> int | None:
    total = sum(hist)
    if total <= 0:
        return None
    target = max(1.0, _clamp(quantile, 0.0, 1.0) * total)
    cumulative = 0
    for index, weight in enumerate(hist):
        cumulative += weight
        if cumulative >= target:
            return index
    return len(hist) - 1


def _clamp(value: float, lower: float, upper: float) -> float:
    if lower > upper:
        lower, upper = upper, lower
    return min(max(value, lower), upper)
