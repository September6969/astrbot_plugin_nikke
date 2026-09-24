"""Generate Pair-based Blind Review Package for face-guided body centering."""
import asyncio
import csv
import hashlib
from io import BytesIO
import json
import math
import random
import string
import sys
from pathlib import Path
from dataclasses import replace

from PIL import Image, ImageDraw, ImageFont
from playwright.async_api import async_playwright
from jinja2 import Environment

# Fully portable root resolution without hardcoded paths
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from astrbot_plugin_nikke.asset_manager import AssetManager
from astrbot_plugin_nikke.character_master_resolver import CharacterMasterResolver
from astrbot_plugin_nikke.card_models import CostumeSelection
from astrbot_plugin_nikke.character_weapon_bases import card_fields
from astrbot_plugin_nikke.ui.payloads.character import CharacterT2IPayloadBuilder
from astrbot_plugin_nikke.t2i_assets import T2IAssetResolver
from astrbot_plugin_nikke.t2i_templates import T2ITemplateLoader
from astrbot_plugin_nikke.tests.test_character_replica import example_card
from astrbot_plugin_nikke.face_anchor import framing
from astrbot_plugin_nikke.face_guided_centering import DEFAULT_CENTERING_CONFIG

def compute_soft_cap(dx: float, knee: float, cap: float) -> float:
    if abs(dx) <= knee:
        return dx
    sign = 1.0 if dx > 0 else -1.0
    u = (abs(dx) - knee) / (cap - knee)
    return sign * (knee + (cap - knee) * math.tanh(u))

def parse_style_transform(style_str: str) -> tuple[float, float, float, float]:
    import re
    w = float(re.search(r"width:([\d.]+)px", style_str).group(1))
    h = float(re.search(r"height:([\d.]+)px", style_str).group(1))
    l = float(re.search(r"left:([-\d.]+)px", style_str).group(1))
    t = float(re.search(r"top:([-\d.]+)px", style_str).group(1))
    return l, t, w, h

def generate_review_ids(count: int, seed: str) -> list[str]:
    rng = random.Random(seed)
    ids = set()
    chars = string.ascii_uppercase + string.digits
    while len(ids) < count:
        uid = ''.join(rng.choices(chars, k=6))
        if uid not in ids:
            ids.add(uid)
    return list(ids)

def shuffle_with_gap(items, gap, max_attempts=1000):
    for _ in range(max_attempts):
        shuffled = items.copy()
        random.shuffle(shuffled)
        valid = True
        for i in range(len(shuffled)):
            render_id = shuffled[i]['render_id']
            # Check previous 'gap' items
            start = max(0, i - gap)
            for j in range(start, i):
                if shuffled[j]['render_id'] == render_id:
                    valid = False
                    break
            if not valid:
                break
        if valid:
            return shuffled
    return None

async def main():
    evidence_dir = ROOT / "docs" / "evidence" / "face_guided_body_centering"
    pair_package_dir = evidence_dir / "pair_blind_review_package"
    pair_package_dir.mkdir(parents=True, exist_ok=True)

    # Empty out the pair_package_dir if it already has files
    for f in pair_package_dir.glob("*"):
        f.unlink(missing_ok=True)

    metrics_v5_path = evidence_dir / "metrics.json"
    with open(metrics_v5_path, "r", encoding="utf-8") as f:
        metrics_v5_data = json.load(f)
    samples_v5 = metrics_v5_data["samples"]

    manifest_path = ROOT / "assets" / "spine_manifest.json"
    png_dir = ROOT / "assets" / "spine-rendered"
    manager = AssetManager(ROOT / "cache", ROOT / "assets", remote=False,
                           spine_manifest_path=manifest_path, spine_rendered_dir=png_dir)
    master = CharacterMasterResolver()
    template_content = T2ITemplateLoader().load("character")
    template = Environment().from_string(template_content)

    # Prepare review pairs definitions
    all_pairs_def = []
    # 36 * 4 candidates = 144
    for s in samples_v5:
        render_id = s["render_id"]
        for pol in ["B", "C", "D", "E"]:
            all_pairs_def.append({
                "render_id": render_id,
                "type": "candidate",
                "policy": pol,
                "sample_info": s
            })
    
    # 12 controls
    rng = random.Random("nikke_control_seed_2026")
    control_samples = rng.sample(samples_v5, 12)
    for s in control_samples:
        all_pairs_def.append({
            "render_id": s["render_id"],
            "type": "control",
            "policy": "A",
            "sample_info": s
        })

    # Generate unique IDs
    review_ids = generate_review_ids(len(all_pairs_def), "nikke_review_ids_seed")
    for i, pdef in enumerate(all_pairs_def):
        pdef["review_id"] = review_ids[i]

    # Shuffle with gap
    rng_shuffle = random.Random("nikke_shuffle_seed")
    # try to shuffle with gap 8
    shuffled_pairs = shuffle_with_gap(all_pairs_def, gap=8)
    if not shuffled_pairs:
        # fallback to best effort or smaller gap
        shuffled_pairs = all_pairs_def.copy()
        rng_shuffle.shuffle(shuffled_pairs) # simple shuffle if gap 8 fails
    
    minimum_same_render_gap = len(shuffled_pairs)
    # calculate minimum gap in final shuffled
    for i in range(len(shuffled_pairs)):
        for j in range(i+1, len(shuffled_pairs)):
            if shuffled_pairs[i]["render_id"] == shuffled_pairs[j]["render_id"]:
                gap = j - i - 1
                if gap < minimum_same_render_gap:
                    minimum_same_render_gap = gap
                break
    
    manifest = {
        "schema": 1,
        "seed": "nikke_review_ids_seed",
        "samples": {}
    }
    
    csv_rows = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1600, "height": 2400}, device_scale_factor=1)

        # Cache images per render_id so we don't render multiple times
        render_cache = {}

        for i, pdef in enumerate(shuffled_pairs, 1):
            render_id = pdef["render_id"]
            review_id = pdef["review_id"]
            ptype = pdef["type"]
            policy = pdef["policy"]
            s = pdef["sample_info"]
            
            manifest["samples"][review_id] = {
                "type": ptype,
                "render_id": render_id,
                "policy": policy
            }

            csv_rows.append({
                "review_id": review_id,
                "overall": "unreviewed",
                "direction": "unreviewed",
                "magnitude": "unreviewed",
                "note": ""
            })

            print(f"[{i}/{len(shuffled_pairs)}] Generating Pair {review_id} (Render: {render_id}, Policy: {policy}, Type: {ptype})...")

            if render_id not in render_cache:
                rid = s["resource_id"]
                costume_id = s["costume_id"]
                orig_v5_shift = s["applied_shift_x"]

                rendered_path = png_dir / f"{render_id}.png"
                portrait = Image.open(rendered_path).convert("RGBA")
                alpha_box = portrait.getchannel("A").getbbox() or (0, 0, portrait.width, portrait.height)

                person = master.resolve_resource_id(rid)
                card = replace(
                    example_card(),
                    name_cn=person.name_cn,
                    name_en=person.name_en,
                    name_code=str(person.name_code),
                    resource_id=str(rid),
                    costume_id=costume_id,
                    spine_asset_id=person.spine_asset_id,
                    costume_selection=CostumeSelection(costume_id, "preview", "default" if not costume_id else "alternate"),
                    corporation=person.corporation,
                    element=person.element,
                    weapon=person.weapon,
                    burst=person.burst,
                    level=695,
                    combat=452890,
                    grade=3,
                    core=7,
                    skill1_level=10,
                    skill2_level=10,
                    burst_skill_level=10,
                    **card_fields(rid),
                )
                for slot, eid in zip(("head", "torso", "arm", "leg"), ("3111001", "3211001", "3311001", "3411001")):
                    card.equipment[slot].equipment_id = eid

                assets = await asyncio.to_thread(manager.resolve_character_assets, card)
                assets.portrait = portrait

                res_off = framing(
                    card, portrait, body_centering=False,
                    identity_resolver=manager.nikke_db,
                )
                base_l, base_t, base_w, base_h = parse_style_transform(res_off["style"])

                shifts = {
                    "A": 0.0,
                    "B": orig_v5_shift,
                    "C": compute_soft_cap(orig_v5_shift, 20.0, 40.0),
                    "D": compute_soft_cap(orig_v5_shift, 16.0, 32.0),
                    "E": compute_soft_cap(orig_v5_shift, 24.0, 48.0),
                }

                images = {
                    "A": Image.open(evidence_dir / f"{render_id}_off.png"),
                    "B": Image.open(evidence_dir / f"{render_id}_on.png"),
                }

                for pol_id in ["C", "D", "E"]:
                    c_shift = shifts[pol_id]
                    if abs(c_shift - shifts["B"]) < 0.01:
                        images[pol_id] = images["B"]
                    elif abs(c_shift - shifts["A"]) < 0.01:
                        images[pol_id] = images["A"]
                    else:
                        cand_l = base_l + c_shift
                        style = f"width:{base_w:.3f}px;height:{base_h:.3f}px;left:{cand_l:.3f}px;top:{base_t:.3f}px;object-fit:contain"
                        payload = CharacterT2IPayloadBuilder(T2IAssetResolver()).build(card, assets)
                        payload["art_style"] = style
                        html = template.render(**payload)
                        await page.set_content(html, wait_until="load")
                        await page.evaluate("document.fonts.ready")
                        buf = await page.screenshot(full_page=True)
                        images[pol_id] = Image.open(BytesIO(buf))
                
                render_cache[render_id] = images

            images = render_cache[render_id]
            img_ref = images["A"]
            img_opt = images[policy]

            # Resize to 800x1200 each. Combined image 1600x1200
            col_w, col_h = 800, 1200
            img_ref_resized = img_ref.resize((col_w, col_h), Image.Resampling.LANCZOS)
            img_opt_resized = img_opt.resize((col_w, col_h), Image.Resampling.LANCZOS)

            comp = Image.new("RGB", (col_w * 2, col_h))
            comp.paste(img_ref_resized, (0, 0))
            comp.paste(img_opt_resized, (col_w, 0))
            
            comp_path = pair_package_dir / f"{review_id}.png"
            comp.save(comp_path, optimize=True)

        await browser.close()
    manager.close()

    # Save manifest outside
    manifest_path = evidence_dir / "pair_blind_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    # Save CSV inside
    csv_path = pair_package_dir / "pair_blind_review.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["review_id", "overall", "direction", "magnitude", "note"])
        writer.writeheader()
        for r in csv_rows:
            writer.writerow(r)
    
    # Save INSTRUCTIONS
    instructions = """# Review Instructions

For each image, you will see two character cards side-by-side:
LEFT: Reference
RIGHT: Option

Your task is to evaluate the Option relative to the Reference on three dimensions.

### 1. overall (Better / Same / Worse)
- `better`: The overall framing and composition of the character in the Option is visually superior to the Reference.
- `same`: There is little to no perceivable difference, or neither is distinctly better.
- `worse`: The Option's framing makes the composition worse than the Reference.

### 2. direction (Correct / Neutral / Wrong)
- `correct`: The Option shifts the character in a direction that attempts to fix an off-center issue.
- `neutral`: The Option does not move the character, or the shift is so minimal it's inconsequential.
- `wrong`: The Option shifts the character in the wrong direction, making an already centered character uncentered or pushing an uncentered character further off.

### 3. magnitude (Insufficient / Appropriate / Excessive / Not Applicable)
- `insufficient`: The shift is in the correct direction but not enough to properly center the character.
- `appropriate`: The shift perfectly centers the character.
- `excessive`: The shift pushes the character too far.
- `not_applicable`: Use this if direction is `neutral` or if evaluating magnitude makes no sense.

**Important Note:**
Some Options might be **completely identical** to the Reference. If you see no reliable visual difference, you should answer `same`, `neutral`, `not_applicable`.
Please strictly evaluate based only on visual balance, independent of whatever policy you think might have generated the image.
"""
    with open(pair_package_dir / "REVIEW_INSTRUCTIONS.md", "w", encoding="utf-8") as f:
        f.write(instructions)

    # Save audit
    package_files = list(pair_package_dir.glob("*"))
    audit_path = evidence_dir / "pair_blind_package_audit.json"
    audit = {
        "candidate_count": 144,
        "control_count": 12,
        "total_count": 156,
        "unique_review_ids": len(review_ids),
        "minimum_same_render_gap": minimum_same_render_gap,
        "manifest_sha256": manifest_sha256,
        "package_file_count": len(package_files)
    }
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2)

    print("Audit:")
    print(json.dumps(audit, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
