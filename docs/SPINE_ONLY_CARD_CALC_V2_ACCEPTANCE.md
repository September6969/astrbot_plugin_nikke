# Spine-only Portrait & Card Calculation v2

## Implemented in this revision

- Character portraits no longer call `get_full_body_url()`, generate `images/FB` URLs, read legacy portrait caches, or download remote FB images.
- `NikkeDbProvider.resolve_spine_asset_id()` resolves default `cXXX` or verified Costume `cXXX_YY` and requires the canonical identity to exist in the cached L2D index.
- `assets/costumes.json` now uses schema v3 with `costume_id`, owner `character_resource_id`, a typed `spine` representation, source, source hash and verification date. Historical v2 input remains readable for migration only; new entries require exact evidence and unknown Costume IDs remain fail-closed.
- L2D index warming is a single service-start action; card rendering reads the local index and versioned Spine PNG cache without per-card index requests.
- OL rows retain three positions per equipment slot and now render a tier badge: neutral T1–T11, blue-emphasis T12–T14, and dark high-contrast T15.
- `CharacterStatCalculator` ports the verified ExiaInvasion calculation order and fails closed. It returns `calculated_verified` only when the complete verified static-table bundle and all player inputs are present; otherwise all three values are `None` with `unavailable_missing_input`.
- Direct `CharacterDetails.hp`, `attack`, and `defense` fields are intentionally ignored as unverified values.
- Voice mappings accept the same canonical Spine identity as a required skin key; the current map remains empty because no exact Poke voice evidence is registered.

## Verification

- Targeted behavior tests: 67 passed, 22 subtests passed.
- Added calculator tests for complete tables, missing tables, and incomplete equipment.
- Added tests proving legacy FB cache and remote FB requests are not used by the character path.
- `compileall` and `git diff --check` are required before PR submission; CI must still pass Python 3.10–3.13, Node and Spine jobs.

## Explicitly not complete

- No real Linux Spine render was claimed by this offline revision; the deployed environment still needs a legal bundle, matching runtime and transparent RGBA render evidence.
- No Costume mapping was invented. The live 13-ID probe found directory identities but no verified public non-default FB assets; this revision correctly changes the blocker to missing canonical L2D/Spine evidence.
- No HP/ATK/DEF output is claimed for the live account. The repository does not yet contain the complete verified level, research, bond, equipment, cube and favorite static tables, and no comparison against one real in-game character has been recorded.
