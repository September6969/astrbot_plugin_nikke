# Live Deployment Acceptance — 2026-09-17 (Repository Finalization & Architecture Closure)

## Result

The latest `origin/main` commit `b1cf4a3` (incorporating PR #92 Batch A shim cleanup, PR #93 Batch B root finalization, and AstrBot plugin loader sys.path bootstrap) was successfully deployed to the production `serv` installation.

The previous plugin tree was retained at `/opt/nikke-bot/backups/astrbot_plugin_nikke-predeploy-b1cf4a3-20260917_011053.tar.gz` and `/opt/nikke-bot/backups/nikke.sqlite3.bak_20260917_011053`; the production database and `data/` directory were fully preserved and untouched.

Post-deployment in-container verification results:
- **Root Directory Files**: Exactly 4 `.py` files remain at root (`__init__.py`, `_version.py`, `container.py`, `main.py`). All 90 legacy root shims have been cleanly removed.
- **In-Container Full Pytest Suite**: **942 passed, 2 skipped, 0 failed, 656 subtests passed** in 75.82s.
- **In-Container Repository Integrity**: 8 passed, 0 failed, 151 subtests passed (`test_repository_integrity.py`).
- **In-Container Key Domain Tests**: 40 passed, 0 failed (`test_character_replica.py`, `test_character_pixel_calibration.py`, `test_face_anchor.py`, `test_calendar_v05.py`, `test_tarot_service.py`, `test_union_raid_state.py`).
- **Database Integrity**: `PRAGMA integrity_check;` returned `ok`.
- **Containers**: `astrbot`, `napcat`, and `nikke-caddy` are all running and healthy.
- **AstrBot Logs**:
  - `Plugin astrbot_plugin_nikke (0.2.0) by September` loaded cleanly without errors.
  - `[NIKKE] 绑定服务已监听 0.0.0.0:6210`
  - `[NIKKE] 已载入 200 条妮姬目录`
  - `[NIKKE] Exia/NIKKE 静态属性表已载入并缓存`
  - OneBot v11 adapter connected and actively handling messages.

Machine-readable evidence: [`docs/evidence/deployment_live_20260917.json`](..\evidence\deployment_live_20260917.json).

---

# Live Deployment Acceptance — 2026-09-09


## Result

The latest `origin/main` commit `39c469e7b95e20acae303af11273f43cba7ddfb0` was deployed to the existing `serv` installation using a staged archive. The previous plugin tree was retained at `/opt/nikke-bot/backups/astrbot_plugin_nikke-predeploy-39c469e-tree`; the data directory was not changed.

The post-deploy smoke checks passed:

- `healthz` returned `ok=true`, `storage=ready`, version `0.1.8`.
- `astrbot`, `napcat`, and `nikke-caddy` were running.
- The loaded plugin reported 135 valid OL entries and 109 valid state-effect entries.
- The database integrity check remained `ok` with schema 2, and the backup manifest remained present.
- The last five minutes of AstrBot logs contained no checked secret markers or error lines.

The complete machine-readable record is [`docs/evidence/deployment_live_20260909.json`](..\evidence\deployment_live_20260909.json).

## Remaining live gates

These are external evidence gates, not silently treated as complete:

1. NapCat is running but its session is not authenticated after the authorized adapter smoke attempt. It entered the official QR login flow. A maintainer must complete the official WebUI/QR login, then one text and one Record test can be retried. No QR, token, cookie, or account identifier was persisted.
2. The live roster exposed 13 non-default costume IDs and the public directory matched all of them to resource/index rows, but all checked non-default Nikke-DB FB candidates returned 404. No default costume was reused and no mapping was fabricated. The exact upstream asset path/content plus licensing evidence is required.
3. The live character detail contract exposed `combat` and `arena_combat`, while the profile exposed `team_combat`; it exposed no authoritative HP/ATK/DEF fields or formula source. The card therefore keeps those values as `—` rather than deriving them from combat, level, or a static database.

The synthetic WAV used during the adapter smoke was only a transport probe. It is not evidence of product Voice generation or QQ playback.
