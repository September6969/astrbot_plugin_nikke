"""从官网公开资源生成带来源哈希的武器基础值和技能图标；不读取账号。"""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import sys
import types

import httpx
from PIL import Image
import io

ROOT = Path(__file__).resolve().parents[1]
if "astrbot_plugin_nikke" not in sys.modules:
    package = types.ModuleType("astrbot_plugin_nikke")
    package.__path__ = [str(ROOT)]
    sys.modules[package.__name__] = package
from astrbot_plugin_nikke.core.asset_manager import AssetManager


def main():
    cache = ROOT / "output/research/roledata"
    cache.mkdir(parents=True, exist_ok=True)
    characters = json.loads((ROOT / "assets/character_master.json").read_text(encoding="utf-8"))["characters"]
    icons = ROOT / "assets/skills"
    icons.mkdir(exist_ok=True)
    def fetch(character):
        rid = str(character["resource_id"])
        relative = f"roledata/{rid}-v2-en.json"
        url = AssetManager.game_resource_url(relative)
        path = cache / f"{rid}.json"
        try:
            if path.is_file():
                raw = path.read_bytes()
            else:
                response = httpx.get(url, timeout=15)
                response.raise_for_status()
                raw = response.content
                json.loads(raw)
                path.write_bytes(raw)
            data = json.loads(raw)
            if str(data.get("resource_id")) != rid:
                raise ValueError("资源身份不匹配")
            shot = data.get("shot_detail") or {}
            result = {"resource_id": rid, "source_url": url, "source_sha256": hashlib.sha256(raw).hexdigest(),
                      "max_ammo": shot.get("max_ammo"), "charge_time_centiseconds": shot.get("charge_time"),
                      "skills": {}}
            for key, field in (("skill1", "skill1_detail"), ("skill2", "skill2_detail"), ("burst", "ulti_skill_detail")):
                name = (data.get(field) or {}).get("icon")
                if isinstance(name, str) and name.replace("_", "").isalnum():
                    result["skills"][key] = name
            return rid, result
        except (httpx.HTTPError, ValueError, OSError) as exc:
            return rid, {"error": type(exc).__name__}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        rows = dict(pool.map(fetch, characters))
    names = sorted({name for row in rows.values() for name in row.get("skills", {}).values()})
    def fetch_icon(name):
        path = icons / f"{name}.webp"
        url = AssetManager.game_resource_url(f"icon/skill/char_skill/{name}.webp")
        try:
            raw = path.read_bytes() if path.exists() else httpx.get(url, timeout=15).raise_for_status().content
            with Image.open(io.BytesIO(raw)) as image:
                image.verify()
            path.write_bytes(raw)
            return name, {"source_url": url, "sha256": hashlib.sha256(raw).hexdigest()}
        except (httpx.HTTPError, OSError, ValueError):
            return name, {"error": "unavailable"}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        icon_rows = dict(pool.map(fetch_icon, names))
    payload = {"schema": 1, "records": rows, "icons": icon_rows}
    (ROOT / "assets/character_weapon_bases.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"characters": len(rows), "failed": [key for key, value in rows.items() if "error" in value],
                      "icons": len(icon_rows), "icons_failed": [key for key, value in icon_rows.items() if "error" in value]}))


if __name__ == "__main__":
    main()
