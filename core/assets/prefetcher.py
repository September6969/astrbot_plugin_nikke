# SPDX-License-Identifier: GPL-3.0-or-later
"""角色卡图片并发预取与有界 executor 生命周期。"""

from __future__ import annotations

import concurrent.futures
import logging
import re
import threading

from PIL import Image

from ...core.privacy import safe_exception_message, sanitize_log_text
from ...features.character.models import CharacterCardAssets, CharacterCardData
from .environment import AssetEnvironment
from .icon_assets import IconAssetService
from .spine_assets import CharacterAssetService

logger = logging.getLogger("nikke.asset_manager")


class CharacterCardPrefetcher:
    MAX_PREFETCH_TASKS = 16

    def __init__(
        self,
        environment: AssetEnvironment,
        characters: CharacterAssetService,
        icons: IconAssetService,
    ) -> None:
        self.env = environment
        self.characters = characters
        self.icons = icons
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="nikke_asset")
        self.slots = threading.BoundedSemaphore(self.MAX_PREFETCH_TASKS)
        self._closed = False
        self._close_lock = threading.Lock()

    def submit(self, func) -> concurrent.futures.Future | None:
        if self._closed or not self.slots.acquire(blocking=False):
            return None
        try:
            future = self.executor.submit(func)
        except Exception:
            self.slots.release()
            raise
        future.add_done_callback(lambda _: self.slots.release())
        return future

    def resolve_character_assets(self, data: CharacterCardData, timeout: float = 6.0) -> CharacterCardAssets:
        equipment = data.equipment
        favorite = data.favorite_item
        cube = data.cube
        tasks = {
            "portrait": (
                lambda: self.characters.get_character_portrait(data.name_code, data.resource_id, data.costume_id),
                lambda: self.env.fallback("portrait"),
            ),
            "head": (lambda: self.icons.get_equipment_icon("head", equipment.get("head").equipment_id if equipment.get("head") and equipment["head"].equipped else None), lambda: self.env.fallback("head")),
            "torso": (lambda: self.icons.get_equipment_icon("torso", equipment.get("torso").equipment_id if equipment.get("torso") and equipment["torso"].equipped else None), lambda: self.env.fallback("torso")),
            "arm": (lambda: self.icons.get_equipment_icon("arm", equipment.get("arm").equipment_id if equipment.get("arm") and equipment["arm"].equipped else None), lambda: self.env.fallback("arm")),
            "leg": (lambda: self.icons.get_equipment_icon("leg", equipment.get("leg").equipment_id if equipment.get("leg") and equipment["leg"].equipped else None), lambda: self.env.fallback("leg")),
            "favorite_item": (lambda: self.icons.get_favorite_item_icon(favorite.tid if favorite else None), lambda: self.env.fallback("favorite")),
            "cube": (lambda: self.icons.get_cube_icon(cube.tid if cube else None), lambda: self.env.fallback("cube")),
            "element": (lambda: self.icons.get_element_icon(data.element), lambda: self.env.fallback("element")),
            "corporation": (lambda: self.icons.get_corporation_icon(data.corporation), lambda: self.env.fallback("corporation")),
            "weapon": (lambda: self.icons.get_weapon_icon(data.weapon), lambda: self.env.fallback("weapon")),
            "burst": (lambda: self.icons.get_burst_icon(data.burst), lambda: self.env.fallback("burst")),
        }
        from ...features.character.weapon_bases import resolve

        for key, name in resolve(data.resource_id).get("skills", {}).items():
            if key in ("skill1", "skill2", "burst") and re.fullmatch(r"[A-Za-z0-9_]+", name):
                tasks["skill_" + key] = (
                    lambda name=name: self.env.load_cached(f"skills/{name}.webp"),
                    lambda: None,
                )

        results: dict[str, Image.Image | None] = {}
        future_map: dict[concurrent.futures.Future, str] = {}
        for key, (func, on_failure) in tasks.items():
            try:
                future = self.submit(func)
                if future is None:
                    logger.warning("素材预取队列已满 [%s]，使用降级 fallback", key)
                    results[key] = on_failure()
                else:
                    future_map[future] = key
            except Exception as exc:
                logger.warning(
                    "提交素材获取任务失败 [%s]: %s",
                    sanitize_log_text(key, max_length=120), safe_exception_message(exc),
                )
                results[key] = on_failure()

        if future_map:
            done, not_done = concurrent.futures.wait(future_map, timeout=timeout)
            for future in done:
                key = future_map[future]
                try:
                    result = future.result()
                    results[key] = result if result is not None else tasks[key][1]()
                except Exception as exc:
                    logger.warning(
                        "素材获取执行异常 [%s]: %s",
                        sanitize_log_text(key, max_length=120), safe_exception_message(exc),
                    )
                    results[key] = tasks[key][1]()
            for future in not_done:
                key = future_map[future]
                safe_key = sanitize_log_text(key, max_length=120)
                if future.cancel():
                    logger.warning("素材获取超时 (硬预算 %.1fs) [%s]，已取消未启动任务并使用 fallback", timeout, safe_key)
                else:
                    logger.warning("素材获取超时 (硬预算 %.1fs) [%s]，任务已运行并使用 fallback", timeout, safe_key)
                results[key] = tasks[key][1]()

        return CharacterCardAssets(
            portrait=results.get("portrait") or tasks["portrait"][1](),
            equipment={slot: results.get(slot) or tasks[slot][1]() for slot in ("head", "torso", "arm", "leg")},
            favorite_item=results.get("favorite_item") or tasks["favorite_item"][1](),
            cube=results.get("cube") or tasks["cube"][1](),
            element=results.get("element") or tasks["element"][1](),
            corporation=results.get("corporation") or tasks["corporation"][1](),
            weapon=results.get("weapon") or tasks["weapon"][1](),
            burst=results.get("burst") or tasks["burst"][1](),
            skills={key: results["skill_" + key] for key in ("skill1", "skill2", "burst") if results.get("skill_" + key) is not None},
        )

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        try:
            try:
                self.executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                self.executor.shutdown(wait=False)
        except Exception:
            pass
