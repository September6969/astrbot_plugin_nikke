#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""按正式 render_id 审计角色 registry、Nikke-db l2d 与本地 Spine manifest。

默认只读本地快照，不访问网络。使用 ``--fetch-upstream`` 时才读取一次
Nikke-db 的 Git tree，并把结果写成可提交、可复现的覆盖快照。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import urllib.request
from pathlib import Path
from typing import Any


SOURCE_REPO = "https://github.com/Nikke-db/Nikke-db.github.io"
SOURCE_API = "https://api.github.com/repos/Nikke-db/Nikke-db.github.io"
RENDER_ID_RE = re.compile(r"^c\d+(?:_\d+)?$", re.ASCII)
REQUIRED_FILES = ("skel", "atlas", "texture")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 根节点必须是对象: {path}")
    return value


def _api_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "nikke-spine-resource-audit"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def fetch_upstream_snapshot() -> dict[str, Any]:
    """通过一次递归 Git tree 请求获取 l2d 文件索引。"""
    ref = _api_json(f"{SOURCE_API}/git/ref/heads/main")
    commit_sha = ref["object"]["sha"]
    tree = _api_json(f"{SOURCE_API}/git/trees/{commit_sha}?recursive=1")
    files = []
    for item in tree.get("tree", []):
        path = item.get("path")
        if not isinstance(path, str) or not path.startswith("l2d/"):
            continue
        if item.get("type") != "blob":
            continue
        files.append({"path": path, "sha": item.get("sha"), "size": item.get("size")})
    return {
        "schema_version": 1,
        "source_repo": SOURCE_REPO,
        "ref": "main",
        "commit_sha": commit_sha,
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "files": sorted(files, key=lambda row: row["path"]),
    }


def _formal_characters(root: Path) -> dict[str, dict[str, Any]]:
    data = _read_json(root / "assets/character_master.json")
    rows = data.get("characters", [])
    result = {}
    if not isinstance(rows, list):
        raise ValueError("character_master.characters 必须是数组")
    for row in rows:
        if not isinstance(row, dict):
            continue
        render_id = row.get("spine_asset_id") or row.get("render_id")
        if isinstance(render_id, str) and RENDER_ID_RE.fullmatch(render_id):
            result[render_id] = {
                "resource_id": row.get("resource_id"),
                "name_cn": row.get("name_cn"),
                "name_en": row.get("name_en"),
                "costume_id": row.get("costume_id"),
            }
    return result


def _manifest_entries(root: Path) -> dict[str, dict[str, Any]]:
    data = _read_json(root / "assets/spine_manifest.json")
    entries = data.get("characters", data.get("assets", {}))
    if not isinstance(entries, dict):
        raise ValueError("spine_manifest.characters/assets 必须是对象")
    return {key: value for key, value in entries.items() if isinstance(key, str) and isinstance(value, dict)}


def _upstream_assets(snapshot: dict[str, Any]) -> tuple[set[str], dict[str, dict[str, Any]]]:
    files = snapshot.get("files", [])
    by_id: dict[str, dict[str, Any]] = {}
    for item in files:
        path = item.get("path") if isinstance(item, dict) else None
        if not isinstance(path, str):
            continue
        match = re.fullmatch(r"l2d/(c\d+(?:_\d+)?)/(.*)", path)
        if not match:
            continue
        render_id, name = match.groups()
        row = by_id.setdefault(render_id, {"render_id": render_id, "files": {}})
        row["files"][name] = {"sha": item.get("sha"), "size": item.get("size"), "path": path}
    complete: set[str] = set()
    for render_id, row in by_id.items():
        prefix = f"{render_id}_00."
        expected = {
            "skel": f"{render_id}_00.skel",
            "atlas": f"{render_id}_00.atlas",
            "texture": f"{render_id}_00.png",
        }
        row["expected"] = expected
        row["complete"] = all(name in row["files"] for name in expected.values())
        row["missing_files"] = [name for name in expected.values() if name not in row["files"]]
        if row["complete"]:
            complete.add(render_id)
    return complete, by_id


def _render_asset_gap(root: Path, formal: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    path = root / "assets/mappings/costume_visual_assets.json"
    if not path.is_file():
        return []
    data = _read_json(path)
    characters = data.get("characters", {})
    result = []
    for render_id, identity in formal.items():
        resource_id = str(identity.get("resource_id"))
        row = characters.get(resource_id) if isinstance(characters, dict) else None
        default = row.get("default", {}) if isinstance(row, dict) else {}
        if not isinstance(default, dict):
            default = {}
        if default.get("icon") and not any(default.get(key) for key in ("portrait", "fullbody", "spine")):
            result.append({
                "resource_id": identity.get("resource_id"),
                "render_id": render_id,
                "name_cn": identity.get("name_cn"),
                "name_en": identity.get("name_en"),
                "status": "icon_only",
            })
    return result


def audit(root: Path, snapshot: dict[str, Any], approved: set[str]) -> dict[str, Any]:
    formal = _formal_characters(root)
    manifest = _manifest_entries(root)
    upstream_complete, upstream = _upstream_assets(snapshot)
    manifest_ids = set(manifest)
    formal_ids = set(formal)
    upstream_missing = sorted(formal_ids - upstream_complete)
    manifest_missing = sorted(formal_ids & upstream_complete - manifest_ids)
    orphan = sorted(manifest_ids - formal_ids)
    unsupported = sorted(
        render_id for render_id, row in upstream.items() if render_id in formal_ids and not row.get("complete")
    )

    missing_rows = []
    for render_id in manifest_missing:
        identity = formal[render_id]
        source = upstream[render_id]
        expected = source["expected"]
        missing_rows.append({
            **identity,
            "render_id": render_id,
            "spine": True,
            "fb": False,
            "status": "auto_fixable" if render_id in approved else "manual_review_required",
            "explicitly_waived": render_id not in approved,
            "reason": "仅本 PR 批准的正式 ID 自动补齐" if render_id not in approved else "已通过三件套、版本与身份核验",
            "source_files": {kind: source["files"].get(path) for kind, path in expected.items()},
        })
    covered = []
    for render_id in sorted(formal_ids & upstream_complete & manifest_ids):
        covered.append({"render_id": render_id, **formal[render_id]})
    completed = [row for row in covered if row["render_id"] in approved]

    return {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_repo": SOURCE_REPO,
        "source_ref": snapshot.get("ref", "main"),
        "source_commit": snapshot.get("commit_sha", "unknown"),
        "character_count": len(formal_ids),
        "upstream_l2d_count": len(upstream),
        "manifest_count": len(manifest_ids),
        "upstream_exists_but_manifest_missing": missing_rows,
        "upstream_spine_missing": [
            {"render_id": rid, **formal[rid], "status": "not_found_or_incomplete"} for rid in upstream_missing
        ],
        "manifest_orphan": [{"render_id": rid, **manifest[rid]} for rid in orphan],
        "render_asset_gap": _render_asset_gap(root, formal),
        "covered_verified": covered,
        "auto_fixable_completed": completed,
        "auto_fixable": [row for row in missing_rows if row["status"] == "auto_fixable"],
        "manual_review_required": [row for row in missing_rows if row["status"] == "manual_review_required"],
        "unsupported": [{"render_id": rid, "status": "invalid_layout", "missing_files": upstream[rid]["missing_files"]} for rid in unsupported],
    }


def render_markdown(report: dict[str, Any]) -> str:
    missing = report["upstream_exists_but_manifest_missing"]
    lines = [
        "# Spine Resource Coverage Audit",
        "",
        f"- CharacterMaster render ids: `{report['character_count']}`",
        f"- Upstream l2d directories observed: `{report['upstream_l2d_count']}`",
        f"- Local manifest entries: `{report['manifest_count']}`",
        f"- upstream_exists_but_manifest_missing: `{len(missing)}`",
        f"- auto-fixable in this PR: `{len(report['auto_fixable'])}`",
        f"- auto-fixable completed in this PR: `{len(report['auto_fixable_completed'])}`",
        f"- manual review required: `{len(report['manual_review_required'])}`",
        f"- unsupported / invalid layout: `{len(report['unsupported'])}`",
        f"- manifest orphan: `{len(report['manifest_orphan'])}`",
        "",
        "## c018",
        "",
    ]
    c018 = next((row for row in report["covered_verified"] if row["render_id"] == "c018"), None)
    if c018:
        lines.append("- `c018`：upstream 三件套存在，已进入本地 manifest。")
    else:
        candidate = next((row for row in missing if row["render_id"] == "c018"), None)
        lines.append(f"- `c018`：{candidate['status'] if candidate else '未在当前集合中'}。")
    lines.extend(["", "## 其它漏项", ""])
    if missing:
        lines.append("| render_id | resource_id | 状态 |")
        lines.append("|---|---:|---|")
        for row in missing:
            lines.append(f"| `{row['render_id']}` | `{row.get('resource_id')}` | {row['status']} |")
    else:
        lines.append("没有 registry 与上游三件套同时存在、但 manifest 缺失的条目。")
    lines.extend([
        "",
        "本审计只按正式 `resource_id/render_id` 比对；其它条目不因名称、顺序或相邻 ID 自动补齐。",
        "`manual_review_required` 不代表资源不存在，而表示本 PR 未自动下载、渲染或提交该条目。",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--upstream-snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument("--approved-render-id", action="append", default=[])
    parser.add_argument("--fetch-upstream", action="store_true")
    parser.add_argument("--write-fetched-snapshot", action="store_true")
    args = parser.parse_args()
    if args.fetch_upstream:
        snapshot = fetch_upstream_snapshot()
        if args.write_fetched_snapshot:
            args.upstream_snapshot.parent.mkdir(parents=True, exist_ok=True)
            args.upstream_snapshot.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        snapshot = _read_json(args.upstream_snapshot)
    report = audit(args.repo_root.resolve(), snapshot, set(args.approved_render_id))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({
        "character_count": report["character_count"],
        "upstream_l2d_count": report["upstream_l2d_count"],
        "manifest_count": report["manifest_count"],
        "upstream_exists_but_manifest_missing": len(report["upstream_exists_but_manifest_missing"]),
        "auto_fixable": len(report["auto_fixable"]),
        "manual_review_required": len(report["manual_review_required"]),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
