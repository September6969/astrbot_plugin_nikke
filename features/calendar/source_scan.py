"""依据来源分页元数据扫描，无法确认结束时不宣称完整。"""
from __future__ import annotations

import json


async def scan_gamekee(client, url, headers, params):
    """单次最多二十页，异常页保留此前有效响应供部分更新。"""
    rows, seen = [], set()
    expected_total = None
    completeness = "UNKNOWN"
    for page in range(1, 21):
        try:
            payload = await client.get_json(url, headers=headers, params={**params, "page_no": page})
        except Exception:
            if page == 1:
                raise
            completeness = "PARTIAL"
            break
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list) or str(payload.get("code", 0)) not in {"0", "200"}:
            if page == 1:
                return payload, "UNKNOWN"
            completeness = "PARTIAL"
            break
        batch = payload["data"]
        signature = json.dumps(batch, sort_keys=True, ensure_ascii=False)
        if signature in seen:
            completeness = "PARTIAL"
            break
        seen.add(signature)
        rows.extend(batch)
        meta = payload.get("meta")
        pagination = meta.get("pagination") if isinstance(meta, dict) else None
        if not isinstance(pagination, dict):
            break
        def integer(key):
            value = pagination.get(key)
            return int(value) if type(value) is int or (isinstance(value, str) and value.isascii() and value.isdecimal()) else None
        total, pages, current = integer("total"), integer("page_total"), integer("page_no")
        if total is None or total < 0 or pages is None or pages < 0 or current != page:
            break
        if expected_total is None:
            expected_total = total
        if total != expected_total:
            completeness = "PARTIAL"
            break
        if page >= pages:
            completeness = "COMPLETE" if len(rows) == total else "PARTIAL"
            break
        if not batch:
            completeness = "PARTIAL"
            break
        completeness = "PARTIAL"
    return {"code": 0, "data": rows}, completeness
