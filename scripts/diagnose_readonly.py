"""一次性只读诊断：默认离线，显式 --live-readonly 才读取本机绑定账号。"""
import argparse
import asyncio
import json
import shutil
from collections import Counter
from pathlib import Path


def summarize(bundle):
    """仅输出布尔值、计数和固定状态名，未知字段及身份绝不透传。"""
    raid = bundle.get("raid", {})
    rows = raid.get("participate_data", []) if isinstance(raid, dict) else []
    rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    canonical = bundle.get("canonical_openid")
    common = bundle.get("xcommon_openid")
    members = bundle.get("members", [])
    members = [m for m in members if isinstance(m, dict)] if isinstance(members, list) else []
    names = Counter(str(m.get("nickname")) for m in members if m.get("nickname"))
    def distinct(key):
        return len({str(row[key]) for row in rows if key in row})
    return {
        "raid": {
            "rows": len(rows), "participants": distinct("openid"),
            "canonical_matches": sum(bool(canonical) and row.get("openid") == canonical for row in rows),
            "xcommon_matches": sum(bool(common) and row.get("openid") == common for row in rows),
            "distinct_days": distinct("day"), "distinct_levels": distinct("level"),
            "pagination_field_found": any(k in raid for k in ("page", "cursor", "next_cursor", "has_more", "offset")),
            "timestamp_field_found": any(any(k in row for k in ("timestamp", "attack_at", "created_at")) for row in rows),
            "scope": "CURRENT_RESPONSE",
        },
        "member_mapping": {
            "direct_mapping_rows": sum(bool(m.get("member_id")) and bool(m.get("openid")) for m in members),
            "duplicate_nicknames": sum(n > 1 for n in names.values()),
            "status": "NEEDS_LIVE_EVIDENCE",
        },
        "daily": {"status_read": isinstance(bundle.get("daily"), dict), "writes_performed": 0},
        "cdk": {"history_rows": len(bundle.get("cdk_history", [])) if isinstance(bundle.get("cdk_history"), list) else 0},
        "voice": {"ffmpeg_found": shutil.which("ffmpeg") is not None, "actual_send": "NOT_RUN"},
    }


async def live_bundle(data_dir):
    from astrbot_plugin_nikke.client import BlaBlaClient
    from astrbot_plugin_nikke.storage import NikkeStore
    accounts = NikkeStore(data_dir).list_accounts(with_cookie=True)
    if len(accounts) != 1:
        raise ValueError("需要恰好一个绑定账号的诊断目录，避免错误选择账号")
    account = accounts[0]
    client = BlaBlaClient()
    bundle = {"canonical_openid": account.get("game_openid")}
    try:
        bundle["xcommon_openid"] = json.loads(account.get("x_common_params") or "{}").get("openid")
    except (ValueError, TypeError, AttributeError):
        pass
    outcomes = {}
    # 白名单仅包含读取接口；逐项失败不会阻止其它诊断。
    for key, read in [("raid", client.get_union_raid_data), ("daily", client.get_daily_signin), ("cdk_history", client.get_cdk_redemption_history)]:
        try:
            bundle[key] = await read(account)
            outcomes[key] = "OK"
        except Exception:
            outcomes[key] = "READ_FAILED"
    return bundle, outcomes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, help="本地 JSON 输入，仅输出计数；不要上传原文件")
    parser.add_argument("--live-readonly", action="store_true")
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
    if args.live_readonly and (not args.data_dir or args.bundle):
        parser.error("线上只读模式需要 --data-dir 且不能同时指定 --bundle")
    try:
        if args.live_readonly:
            bundle, outcomes = asyncio.run(live_bundle(args.data_dir))
        else:
            bundle = json.loads(args.bundle.read_text(encoding="utf-8")) if args.bundle else {}
            outcomes = {"mode": "OFFLINE"}
        report = summarize(bundle)
        report["reads"] = outcomes
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except Exception:
        # 不输出上游异常文本，避免 URL/身份/凭据混入报告。
        print(json.dumps({"status": "DIAGNOSTIC_FAILED", "writes_performed": 0}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
