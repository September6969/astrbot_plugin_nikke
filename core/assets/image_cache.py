# SPDX-License-Identifier: GPL-3.0-or-later
"""安全的本地图片缓存与原子写入。"""

from __future__ import annotations

import re
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath

from PIL import Image

from .image_codec import AssetImageCodec


class AssetImageCache:
    def __init__(
        self,
        cache_dir: str | Path,
        asset_dir: str | Path,
        *,
        extra_roots: tuple[str | Path, ...] = (),
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.asset_dir = Path(asset_dir)
        self.extra_roots = tuple(Path(path) for path in extra_roots)

    @staticmethod
    def normalize_relative(relative: str) -> str | None:
        if not isinstance(relative, str) or not relative or "\\" in relative:
            return None
        if PureWindowsPath(relative).drive or PurePosixPath(relative).is_absolute():
            return None
        path = PurePosixPath(relative)
        if any(part in {"", ".", ".."} for part in path.parts):
            return None
        if any(not re.fullmatch(r"[A-Za-z0-9_.@+-]+", part) for part in path.parts):
            return None
        return path.as_posix()

    def roots(self) -> tuple[Path, ...]:
        return tuple(dict.fromkeys((self.cache_dir, self.asset_dir, self.asset_dir.parent, *self.extra_roots)))

    @staticmethod
    def _relative_candidates(relative: str) -> list[str]:
        raw = [relative]
        if relative.startswith("data/nikke/blabla-assets/"):
            raw.append(relative[len("data/nikke/blabla-assets/"):])
        if relative.startswith("assets/"):
            raw.append(relative[len("assets/"):])
        if relative.startswith("icons/"):
            raw.append(relative[len("icons/"):])
        else:
            for icon_sub in ("cube/", "favorite/", "currency/"):
                if relative.startswith(icon_sub):
                    raw.insert(0, f"icons/{relative}")
                    break
        if relative.startswith("data/"):
            raw.append(relative[len("data/"):])
        else:
            raw.append(f"data/{relative}")

        candidates: list[str] = []
        for candidate in raw:
            candidates.append(candidate)
            if candidate.endswith(".png"):
                candidates.append(candidate[:-4] + ".webp")
            elif candidate.endswith(".webp"):
                candidates.append(candidate[:-5] + ".png")
        return candidates

    def load(self, relative: str) -> Image.Image | None:
        normalized = self.normalize_relative(relative)
        if normalized is None:
            return None
        for base in self.roots():
            try:
                resolved_base = base.resolve()
            except (OSError, RuntimeError):
                continue
            for candidate in self._relative_candidates(normalized):
                try:
                    path = (base / candidate).resolve()
                    if not path.is_relative_to(resolved_base) or not path.is_file():
                        continue
                    if path.stat().st_size > AssetImageCodec.MAX_BYTES:
                        continue
                    return AssetImageCodec.validate(path)
                except (OSError, ValueError, Image.DecompressionBombError, RuntimeError):
                    continue
        return None

    def save(self, relative: str, image: Image.Image) -> bool:
        normalized = self.normalize_relative(relative)
        if normalized is None:
            return False
        try:
            root = self.cache_dir.resolve()
            destination = (self.cache_dir / normalized).resolve()
            if not destination.is_relative_to(root):
                return False
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(f".{uuid.uuid4().hex}.tmp")
            try:
                image.save(temporary, format="PNG")
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
            return True
        except (OSError, RuntimeError, ValueError):
            return False
