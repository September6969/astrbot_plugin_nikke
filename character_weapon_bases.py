"""读取离线官网武器基础值，不在出卡路径发起网络请求。"""
from functools import lru_cache
import json
from pathlib import Path
import re


@lru_cache(maxsize=1)
def records():
    try:
        cand = Path(__file__).parent / "assets" / "data" / "character_weapon_bases.json"
        if not cand.is_file():
            cand = Path(__file__).parent / "assets" / "character_weapon_bases.json"
        payload = json.loads(cand.read_text(encoding="utf-8"))
        return payload.get("records", {}) if payload.get("schema") == 1 else {}
    except (OSError, ValueError, AttributeError):
        return {}


def resolve(resource_id):
    row = records().get(str(resource_id), {})
    if not isinstance(row, dict) or "error" in row or str(row.get("resource_id")) != str(resource_id):
        return {}
    if not re.fullmatch(r"[a-f0-9]{64}", str(row.get("source_sha256", ""))):
        return {}
    if not str(row.get("source_url", "")).startswith("https://sg-tools-cdn.blablalink.com/"):
        return {}
    return row


def card_fields(resource_id):
    from decimal import Decimal
    row = resolve(resource_id)
    ammo, charge = row.get("max_ammo"), row.get("charge_time_centiseconds")
    return {"base_ammo": ammo if type(ammo) is int and ammo > 0 else None,
            "base_charge_seconds": str(Decimal(charge) / 100) if type(charge) is int and charge > 0 else None,
            "weapon_base_source": row.get("source_url")}
