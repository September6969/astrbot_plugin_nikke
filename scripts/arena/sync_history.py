"""离线读取指定赛事的授权统计并原子保存脱敏快照。"""

import argparse
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

SOURCE = "https://nikkeari.cc"
MAX_BYTES = 8 * 1024 * 1024
RETRYABLE_STATUS = {408, 500, 502, 503, 504}
MAX_RETRY_WAIT = 5


def retry_wait(value):
    if not value:
        return 1
    if value.isascii() and value.isdigit():
        return int(value)
    try:
        until = parsedate_to_datetime(value)
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        return max(0, (until - datetime.now(timezone.utc)).total_seconds())
    except (ValueError, TypeError, OverflowError):
        return 1


def request_json(path, body=None):
    headers = {"User-Agent": "AstrBot-Nikke/arena-offline-sync", "Accept-Encoding": "identity"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    for attempt in range(2):
        try:
            request = urllib.request.Request(SOURCE + path, data=data, headers=headers)
            with urllib.request.urlopen(request, timeout=20) as response:
                raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("统计响应超过大小预算。")
            return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            with exc:
                if exc.code == 429:
                    raise RuntimeError("统计源已限流，本次同步停止并保留旧快照。") from exc
                if attempt or exc.code not in RETRYABLE_STATUS:
                    raise
                wait = retry_wait(exc.headers.get("Retry-After"))
                if wait > MAX_RETRY_WAIT:
                    raise RuntimeError("统计源要求稍后重试，本次同步保留旧快照。") from exc
            time.sleep(max(1, wait))
        except (urllib.error.URLError, TimeoutError):
            if attempt:
                raise
            time.sleep(1)


def normalize(value):
    return re.sub(r"[\s:：・･·_+\-（）()]", "", value).casefold()


def character_mapping(rules, characters):
    names = {}
    for key, translations in rules["names"].items():
        for name in translations.values():
            names.setdefault(normalize(name), set()).add(key)
    mapping = {}
    for char in characters:
        matches = names.get(normalize(char["name"]), set())
        if len(matches) == 1:
            mapping[char["id"]] = next(iter(matches))
    return mapping


def build_snapshot(rules, characters, tournament, matchups, game_patch, *,
                   registration_phase=None):
    mapping = character_mapping(rules, characters)
    usage = Counter()
    records = {}
    rejected = 0
    for row in matchups:
        def team(side):
            identifiers = row[side + "_team"]
            collections = row.get(side + "_collections") or [None] * 5
            if len(identifiers) != 5 or len(collections) != 5:
                return None
            keys = []
            for identifier, collection in zip(identifiers, collections):
                key = mapping.get(identifier)
                if key is None:
                    return None
                if str(collection or "").startswith("treasure") and not key.endswith("_treasure"):
                    key += "_treasure"
                    if key not in rules["parameters"]:
                        return None
                keys.append(key)
            return tuple(keys) if len(set(keys)) == 5 else None
        attacker, defender = team("attacker"), team("defender")
        winner = row.get("winner_player_id")
        if (not attacker or not defender or winner is None
                or winner not in {row.get("attacker_player_id"), row.get("defender_player_id")}):
            rejected += 1
            continue
        attacker_won = winner == row.get("attacker_player_id")
        # 攻守顺序与解队输入一致。镜像阵容也只为这一场计一次。
        counts = records.setdefault((attacker, defender), [0, 0])
        counts[0 if attacker_won else 1] += 1
        usage.update(attacker)
        usage.update(defender)
    return {
        "schema_version": 2, "source": SOURCE, "fetched_at": datetime.now(timezone.utc).isoformat(),
        "game_patch": game_patch, "server": tournament["play_server"], "seasons": [tournament["season"]],
        "tournament_ids": [tournament["id"]], "registration_scope": tournament.get("registration_scope", "unknown"),
        "registration_phase": registration_phase,
        "event_date": tournament.get("date"),
        "sample_size": len(matchups) - rejected, "rejected_rows": rejected,
        "matchup_direction": "attacker_vs_defender",
        "license": "user_confirmed_source_permission_2026-11-17",
        "mapping_coverage": len(mapping) / len(characters) if characters else 0,
        "source_is_champion_arena": tournament.get("is_champion_arena"),
        "character_usage": dict(sorted(usage.items())),
        "records": [{"mine": mine, "enemy": enemy, "wins": counts[0], "losses": counts[1]}
                    for (mine, enemy), counts in sorted(records.items())],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tournament-id", type=int, required=True)
    parser.add_argument("--server", choices=("GLOBAL", "JP", "KR"), required=True)
    parser.add_argument("--game-patch", default="unknown")
    parser.add_argument("--registration-phase", default="legacy")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", args.registration_phase) or args.registration_phase == "all":
        parser.error("请选择一个明确的赛事登记阶段。")
    tournaments = request_json("/api/tournaments")
    selected = [item for item in tournaments
                if item["id"] == args.tournament_id and item["play_server"] == args.server]
    if len(selected) != 1:
        raise ValueError("赛事与服务器不匹配。")
    tournament = selected[0]
    characters = request_json("/api/characters")
    body = {"tournament_ids": [args.tournament_id], "play_server": args.server,
            "championship_id": tournament.get("championship_id"), "registration_phase": args.registration_phase}
    data = request_json("/api/dashboard/cross-tournament/matchups", body)
    if not isinstance(data, dict) or not isinstance(data.get("matchups"), list):
        raise ValueError("对位统计响应格式发生变化。")
    rules = json.loads((Path(__file__).resolve().parents[2] / "assets/data/arena/rules.json").read_text(encoding="utf-8"))
    stats = request_json("/api/dashboard/cross-tournament/stats", body)
    if (not isinstance(stats, dict) or stats.get("registration_phase") != args.registration_phase
            or not isinstance(stats.get("character_stats"), list)):
        raise ValueError("角色出场统计未返回所选登记阶段。")
    snapshot = build_snapshot(rules, characters, tournament, data["matchups"], args.game_patch,
                              registration_phase=args.registration_phase)
    if not snapshot["sample_size"]:
        raise ValueError("所选赛事暂无可映射对位，保留现有快照。")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.output.parent,
                                         prefix=args.output.name + ".tmp-", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(snapshot, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, args.output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(f"保存 {snapshot['sample_size']} 条有效对局，未映射 {snapshot['rejected_rows']} 条。")


if __name__ == "__main__":
    main()
