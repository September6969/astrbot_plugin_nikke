# SPDX-License-Identifier: GPL-3.0-or-later
"""REFACTOR_PLAN_V2 PR-4A 前置验证：批量 GetUserCharacterDetails 是否与单角色请求一致。

默认离线：对已保存的两份脱敏响应做比较。只有显式 --live-readonly 才读取本机唯一绑定
账号并发起只读请求（1 次名单 + 1 次全量批量 + 1 次 Top N 批量 + N 次单角色），不执行
任何写操作。输出只含 name_code、字段名、计数与是否一致，不含 Cookie、OpenID 或数值。
"""

# 支持直接执行、模块导入及从其他工作目录调用。
import sys as _bootstrap_sys
from pathlib import Path as _BootstrapPath
_bootstrap_root = _BootstrapPath(__file__).resolve().parents[2]
for _bootstrap_path in (_bootstrap_root.parent, _bootstrap_root):
    if str(_bootstrap_path) not in _bootstrap_sys.path:
        _bootstrap_sys.path.insert(0, str(_bootstrap_path))

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

SLOTS = ("head", "torso", "arm", "leg")
EQUIPMENT_SUFFIXES = ("_equip_tid", "_equip_lv", "_equip_option1_id", "_equip_option2_id", "_equip_option3_id")


def _equipment_view(detail: dict[str, Any]) -> dict[str, Any]:
    """只抽取判定一致性所需的装备/词条字段。"""
    return {f"{slot}{suffix}": detail.get(f"{slot}{suffix}") for slot in SLOTS for suffix in EQUIPMENT_SUFFIXES}


def _by_code(response: Any) -> dict[str, dict[str, Any]]:
    data = response.get("data") if isinstance(response, dict) else None
    rows = data.get("character_details") if isinstance(data, dict) else None
    return {str(row.get("name_code")): row for row in rows or [] if isinstance(row, dict) and row.get("name_code")}


def _effect_ids(response: Any) -> set[str]:
    data = response.get("data") if isinstance(response, dict) else None
    effects = data.get("state_effects") if isinstance(data, dict) else None
    return {str(item.get("id")) for item in effects or [] if isinstance(item, dict) and item.get("id") is not None}


def compare(batch: Any, singles: dict[str, Any]) -> dict[str, Any]:
    """比较批量响应与各单角色响应；返回不含数值的结构化结论。"""
    batch_rows = _by_code(batch)
    batch_effects = _effect_ids(batch)
    report: dict[str, Any] = {"codes": len(singles), "missing_in_batch": [], "equipment_mismatch": [],
                              "state_effects_missing": [], "all_consistent": True}
    for code, single in singles.items():
        single_row = _by_code(single).get(code)
        batch_row = batch_rows.get(code)
        if single_row is None:
            continue
        if batch_row is None:
            report["missing_in_batch"].append(code)
            continue
        expected, actual = _equipment_view(single_row), _equipment_view(batch_row)
        diff = sorted(key for key in expected if expected[key] != actual.get(key))
        if diff:
            report["equipment_mismatch"].append({"name_code": code, "fields": diff})
        missing_effects = _effect_ids(single) - batch_effects
        if missing_effects:
            report["state_effects_missing"].append({"name_code": code, "count": len(missing_effects)})
    report["all_consistent"] = not (report["missing_in_batch"] or report["equipment_mismatch"]
                                    or report["state_effects_missing"])
    return report


async def _live(data_dir: Path, top: int, delay: float) -> dict[str, Any]:
    from astrbot_plugin_nikke.core.storage import NikkeStore
    from astrbot_plugin_nikke.features.character.roster_ranking import select_top_codes
    from astrbot_plugin_nikke.integrations.blablalink.client import (
        CHARACTER_DETAILS, BlaBlaClient, _require_area_id,
    )

    accounts = NikkeStore(data_dir).list_accounts(with_cookie=True)
    if len(accounts) != 1:
        raise ValueError("需要恰好一个绑定账号的诊断目录，避免错误选择账号")
    account = accounts[0]
    client = BlaBlaClient()
    try:
        roster = await client.get_roster(account, include_details=False)
        codes = [str(item.get("name_code")) for item in roster if isinstance(item, dict) and item.get("name_code")]
        top_codes = [str(code) for code in select_top_codes(roster, top)]
        base = {"intl_open_id": account.get("game_openid", ""), "nikke_area_id": _require_area_id(account.get("area_id"))}

        async def details(name_codes: list[str]) -> Any:
            return await client._post(CHARACTER_DETAILS, account["cookie"], {**base, "name_codes": name_codes})

        full = await details(codes)
        top_batch = await details(top_codes)
        singles = {}
        for code in top_codes:
            await asyncio.sleep(delay)
            singles[code] = await details([code])
        return {
            "roster_size": len(codes),
            "full_batch_rows": len(_by_code(full)),
            "requests": 3 + len(top_codes),
            "full_batch_vs_single": compare(full, singles),
            "top_batch_vs_single": compare(top_batch, singles),
        }
    finally:
        await client.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, help="离线：脱敏批量响应 JSON")
    parser.add_argument("--singles", type=Path, help="离线：{name_code: 单角色响应} JSON")
    parser.add_argument("--live-readonly", action="store_true", help="读取本机唯一绑定账号并发起只读请求")
    parser.add_argument("--data-dir", type=Path, help="包含 nikke.sqlite3 与 secret.key 的目录")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--delay", type=float, default=1.0, help="单角色请求间隔秒数，避免触发频控")
    args = parser.parse_args()
    if args.live_readonly:
        if args.data_dir is None:
            parser.error("--live-readonly 需要 --data-dir")
        report = asyncio.run(_live(args.data_dir, args.top, max(0.5, args.delay)))
    else:
        if args.batch is None or args.singles is None:
            parser.error("离线模式需要 --batch 与 --singles")
        report = compare(json.loads(args.batch.read_text(encoding="utf-8")),
                         json.loads(args.singles.read_text(encoding="utf-8")))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
