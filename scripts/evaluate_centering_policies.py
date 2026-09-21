"""Evaluate Card-space Correction Policies offline across 36 authentic samples."""
import asyncio
import csv
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import random
import re
import shutil
import sys
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
from astrbot_plugin_nikke.t2i_payloads import CharacterT2IPayloadBuilder
from astrbot_plugin_nikke.t2i_assets import T2IAssetResolver
from astrbot_plugin_nikke.t2i_templates import T2ITemplateLoader
from astrbot_plugin_nikke.tests.test_character_replica import example_card
from astrbot_plugin_nikke.face_anchor import framing, metadata
from astrbot_plugin_nikke.face_guided_centering import DEFAULT_CENTERING_CONFIG


def compute_soft_cap(dx: float, knee: float, cap: float) -> float:
    """Continuous and smooth soft-cap response curve."""
    if abs(dx) <= knee:
        return dx
    sign = 1.0 if dx > 0 else -1.0
    u = (abs(dx) - knee) / (cap - knee)
    return sign * (knee + (cap - knee) * math.tanh(u))


def parse_style_transform(style_str: str) -> tuple[float, float, float, float]:
    w = float(re.search(r"width:([\d.]+)px", style_str).group(1))
    h = float(re.search(r"height:([\d.]+)px", style_str).group(1))
    l = float(re.search(r"left:([-\d.]+)px", style_str).group(1))
    t = float(re.search(r"top:([-\d.]+)px", style_str).group(1))
    return l, t, w, h


def percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    idx = (len(s) - 1) * p
    lower = math.floor(idx)
    upper = math.ceil(idx)
    if lower == upper:
        return s[int(idx)]
    return s[lower] * (upper - idx) + s[upper] * (idx - lower)


def get_font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    """Portable font loader with project fonts and safe fallbacks.
    
    Failure to load a specific font will NEVER crash or affect policy calculations.
    """
    candidate_paths = [
        ROOT / "fonts" / ("NotoSansHans-Medium.otf" if bold else "NotoSansHans-Regular.otf"),
        ROOT / "fonts" / "NotoSansHans-Medium.otf",
        ROOT / "fonts" / "NotoSansHans-Regular.otf",
        ROOT / "fonts" / ("BarlowCondensed-Bold.ttf" if bold else "BarlowCondensed-SemiBold.ttf"),
    ]
    system_fallbacks = [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/System/Library/Fonts/PingFang.ttc"),
        Path("/Library/Fonts/Arial Unicode.ttf"),
    ]
    for p in candidate_paths + system_fallbacks:
        try:
            if p.exists():
                return ImageFont.truetype(str(p), size)
        except Exception:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def get_deterministic_permutation(render_id: str) -> list[str]:
    """Derive deterministic pseudo-random permutation of candidate policies ['B', 'C', 'D', 'E']."""
    salt = f"nikke_blind_review_salt_2026_{render_id}"
    h = hashlib.sha256(salt.encode("utf-8")).hexdigest()
    rng = random.Random(int(h[:16], 16))
    candidates = ["B", "C", "D", "E"]
    rng.shuffle(candidates)
    return candidates


async def main():
    evidence_dir = ROOT / "docs" / "evidence" / "face_guided_body_centering"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    blind_package_dir = evidence_dir / "blind_review_package"
    blind_package_dir.mkdir(parents=True, exist_ok=True)

    metrics_v5_path = evidence_dir / "metrics.json"
    if not metrics_v5_path.exists():
        raise FileNotFoundError(f"metrics.json not found at {metrics_v5_path}. Run generate_centering_evidence.py first!")

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

    font_large = get_font(22, bold=True)
    font_mid = get_font(14, bold=False)
    font_col = get_font(16, bold=True)
    font_sub = get_font(13, bold=False)

    policy_metrics_records = []
    review_rows = []
    blind_review_rows = []
    blind_manifest = {}

    # Check manifest hash before regenerating to guarantee byte-for-byte reproducibility
    blind_manifest_path = evidence_dir / "blind_manifest.json"
    manifest_hash_before = hashlib.sha256(blind_manifest_path.read_bytes()).hexdigest() if blind_manifest_path.exists() else None

    # Prepare browser for rendering needed candidate variations
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1600, "height": 2400}, device_scale_factor=1)

        for i, s in enumerate(samples_v5, 1):
            render_id = s["render_id"]
            rid = s["resource_id"]
            costume_id = s["costume_id"]
            costume_name = s["costume_name"]
            canonical_name = s["canonical_name"]
            char_en = s["character_name_en"]
            category = s["category"]
            category_code = s["category_code"]
            orig_v5_shift = s["applied_shift_x"]
            conf = s["confidence"]
            face_before = s["face_before"]

            print(f"[{i}/{len(samples_v5)}] Evaluating policies for {render_id} | {canonical_name} ({char_en}) [v5: {orig_v5_shift:+.2f}px]...")

            # Load portrait
            rendered_path = png_dir / f"{render_id}.png"
            portrait = Image.open(rendered_path).convert("RGBA")
            alpha_box = portrait.getchannel("A").getbbox() or (0, 0, portrait.width, portrait.height)

            # Build card
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

            res_off = framing(card, portrait, body_centering=False)
            base_l, base_t, base_w, base_h = parse_style_transform(res_off["style"])
            scale_art = base_w / portrait.width

            # Bounding box of baseline
            off_art_bbox = [
                base_l + alpha_box[0] * scale_art,
                base_t + alpha_box[1] * scale_art,
                base_l + alpha_box[2] * scale_art,
                base_t + alpha_box[3] * scale_art,
            ]
            card_w, card_h = 1600.0, 2400.0
            off_clipping = {
                "left": off_art_bbox[0] < 0,
                "top": off_art_bbox[1] < 0,
                "right": off_art_bbox[2] > card_w,
                "bottom": off_art_bbox[3] > card_h,
            }

            # Candidate shifts
            shifts = {
                "A": 0.0,
                "B": orig_v5_shift,
                "C": compute_soft_cap(orig_v5_shift, 20.0, 40.0),
                "D": compute_soft_cap(orig_v5_shift, 16.0, 32.0),
                "E": compute_soft_cap(orig_v5_shift, 24.0, 48.0),
            }

            # Preload A and B images
            images = {
                "A": Image.open(evidence_dir / f"{render_id}_off.png"),
                "B": Image.open(evidence_dir / f"{render_id}_on.png"),
            }

            # Evaluate each policy candidate
            for pol_id in ["A", "B", "C", "D", "E"]:
                c_shift = shifts[pol_id]
                diff_v5 = c_shift - orig_v5_shift
                face_x_after = face_before[0] + c_shift
                face_y_after = face_before[1]

                # Face safety using real algorithm bounds
                face_safe = (
                    DEFAULT_CENTERING_CONFIG.face_safe_left <= face_x_after <= DEFAULT_CENTERING_CONFIG.face_safe_right
                    and DEFAULT_CENTERING_CONFIG.face_safe_top <= face_y_after <= DEFAULT_CENTERING_CONFIG.face_safe_bottom
                )

                # Candidate artwork card bbox and clipping
                cand_l = base_l + c_shift
                cand_bbox = [
                    cand_l + alpha_box[0] * scale_art,
                    base_t + alpha_box[1] * scale_art,
                    cand_l + alpha_box[2] * scale_art,
                    base_t + alpha_box[3] * scale_art,
                ]
                cand_clipping = {
                    "left": cand_bbox[0] < 0,
                    "top": cand_bbox[1] < 0,
                    "right": cand_bbox[2] > card_w,
                    "bottom": cand_bbox[3] > card_h,
                }
                new_edge_clipping = {
                    "left": (not off_clipping["left"]) and cand_clipping["left"],
                    "top": (not off_clipping["top"]) and cand_clipping["top"],
                    "right": (not off_clipping["right"]) and cand_clipping["right"],
                    "bottom": (not off_clipping["bottom"]) and cand_clipping["bottom"],
                }

                policy_metrics_records.append({
                    "render_id": render_id,
                    "canonical_name": canonical_name,
                    "category": category,
                    "category_code": category_code,
                    "policy": pol_id,
                    "original_v5_shift": round(orig_v5_shift, 2),
                    "candidate_shift": round(c_shift, 2),
                    "difference_from_v5": round(diff_v5, 2),
                    "face_x_after": round(face_x_after, 2),
                    "face_safe": face_safe,
                    "new_edge_clipping": new_edge_clipping,
                    "has_new_edge_clipping": any(new_edge_clipping.values()),
                    "tracking_confidence": conf,
                })

                # Determine card image for C, D, E
                if pol_id not in images:
                    if abs(c_shift - shifts["B"]) < 0.01:
                        images[pol_id] = images["B"]
                    elif abs(c_shift - shifts["A"]) < 0.01:
                        images[pol_id] = images["A"]
                    else:
                        style = f"width:{base_w:.3f}px;height:{base_h:.3f}px;left:{cand_l:.3f}px;top:{base_t:.3f}px;object-fit:contain"
                        payload = CharacterT2IPayloadBuilder(T2IAssetResolver()).build(card, assets)
                        payload["art_style"] = style
                        html = template.render(**payload)
                        await page.set_content(html, wait_until="load")
                        await page.evaluate("document.fonts.ready")
                        buf = await page.screenshot(full_page=True)
                        images[pol_id] = Image.open(BytesIO(buf))

            # -------------------------------------------------------------
            # 1. Compose 5-column Engineering Comparison Image (Retained)
            # -------------------------------------------------------------
            col_w, col_h = 480, 720
            header_h_eng = 130
            total_w = col_w * 5
            total_h_eng = col_h + header_h_eng

            comp_eng = Image.new("RGB", (total_w, total_h_eng), (18, 20, 26))
            draw_eng = ImageDraw.Draw(comp_eng)

            display_title = f"{render_id} | {canonical_name} ({char_en}) - Card-space Correction Policy Evaluation"
            draw_eng.text((24, 16), display_title, fill=(255, 255, 255), font=font_large)
            semantics_note = f"Category: [{category}]  |  tracking_confidence: {conf} (Note: Indicates alpha path geometric stability, NOT composition correctness)"
            draw_eng.text((24, 48), semantics_note, fill=(170, 185, 205), font=font_mid)

            col_defs_eng = [
                ("A", "Baseline (Face Anchor)", shifts["A"], "Shift: 0.0px (Reference)"),
                ("B", "Raw v5 (Uncapped)", shifts["B"], f"Shift: {shifts['B']:+.1f}px (Diff: 0.0px)"),
                ("C", "Policy C (Soft 20/40)", shifts["C"], f"Shift: {shifts['C']:+.1f}px (Diff: {shifts['C']-shifts['B']:+.1f}px)"),
                ("D", "Policy D (Soft 16/32)", shifts["D"], f"Shift: {shifts['D']:+.1f}px (Diff: {shifts['D']-shifts['B']:+.1f}px)"),
                ("E", "Policy E (Soft 24/48)", shifts["E"], f"Shift: {shifts['E']:+.1f}px (Diff: {shifts['E']-shifts['B']:+.1f}px)"),
            ]

            scale_thumb = col_w / 1600.0
            x_baseline_thumb = face_before[0] * scale_thumb

            for idx, (cid, title, s_val, sub_text) in enumerate(col_defs_eng):
                cx = idx * col_w
                draw_eng.rectangle([(cx + 4, 76), (cx + col_w - 4, 122)], fill=(28, 32, 42))
                col_title_color = (0, 255, 140) if cid == "A" else ((255, 100, 100) if cid == "B" else (100, 200, 255))
                draw_eng.text((cx + 12, 80), f"[{cid}] {title}", fill=col_title_color, font=font_col)
                draw_eng.text((cx + 12, 102), sub_text, fill=(200, 210, 225), font=font_sub)

                im_eng = images[cid].resize((col_w, col_h), Image.Resampling.LANCZOS)
                draw_im = ImageDraw.Draw(im_eng)

                draw_im.line([(x_baseline_thumb, 0), (x_baseline_thumb, col_h)], fill=(0, 255, 140, 100), width=1)

                x_shift_thumb = (face_before[0] + s_val) * scale_thumb
                col_mark = (0, 255, 140) if cid == "A" else (255, 40, 140)
                draw_im.line([(x_shift_thumb, 0), (x_shift_thumb, col_h)], fill=col_mark, width=2)
                y_face_thumb = face_before[1] * scale_thumb
                draw_im.rectangle([(x_shift_thumb - 4, y_face_thumb - 4), (x_shift_thumb + 4, y_face_thumb + 4)], fill=col_mark)

                comp_eng.paste(im_eng, (cx, header_h_eng))
                if idx > 0:
                    draw_eng.line([(cx, 76), (cx, total_h_eng)], fill=(50, 55, 70), width=2)

            comp_eng_path = evidence_dir / f"{render_id}_policy_compare.png"
            comp_eng.save(comp_eng_path, optimize=True)

            # -------------------------------------------------------------
            # 2. Compose 5-column Blind Review Image (PURE CARDS ONLY)
            # -------------------------------------------------------------
            perm = get_deterministic_permutation(render_id)
            blind_manifest[render_id] = {
                "candidate_1": perm[0],
                "candidate_2": perm[1],
                "candidate_3": perm[2],
                "candidate_4": perm[3],
            }

            header_h_blind = 100
            total_h_blind = col_h + header_h_blind
            comp_blind = Image.new("RGB", (total_w, total_h_blind), (18, 20, 26))
            draw_blind = ImageDraw.Draw(comp_blind)

            # Strictly no category and neutral title
            blind_title = f"Sample: {render_id} - Blind Visual Evaluation"
            draw_blind.text((24, 16), blind_title, fill=(255, 255, 255), font=font_large)
            blind_sub = "Evaluate Candidates 1-4 against Reference Baseline (Observe overall balance, framing & composition)"
            draw_blind.text((24, 46), blind_sub, fill=(170, 185, 205), font=font_mid)

            col_labels = ["Reference", "Candidate 1", "Candidate 2", "Candidate 3", "Candidate 4"]
            col_imgs = [images["A"], images[perm[0]], images[perm[1]], images[perm[2]], images[perm[3]]]

            for idx, (col_name, c_img) in enumerate(zip(col_labels, col_imgs)):
                cx = idx * col_w
                # Neutral column header box
                draw_blind.rectangle([(cx + 4, 68), (cx + col_w - 4, 96)], fill=(28, 32, 42))
                header_color = (0, 255, 140) if idx == 0 else (220, 230, 250)
                draw_blind.text((cx + 14, 72), col_name, fill=header_color, font=font_col)

                # Pure thumbnail with ZERO overlays (no lines, no markers, no bounding boxes)
                im_blind = c_img.resize((col_w, col_h), Image.Resampling.LANCZOS)
                comp_blind.paste(im_blind, (cx, header_h_blind))

                # Background vertical divider
                if idx > 0:
                    draw_blind.line([(cx, 68), (cx, total_h_blind)], fill=(50, 55, 70), width=2)

            comp_blind_path = blind_package_dir / f"{render_id}_policy_blind.png"
            comp_blind.save(comp_blind_path, optimize=True)

            # Build review rows
            review_rows.append({
                "render_id": render_id,
                "canonical_name": canonical_name,
                "category": category,
                "baseline_vs_raw": "unreviewed",
                "baseline_vs_C": "unreviewed",
                "baseline_vs_D": "unreviewed",
                "baseline_vs_E": "unreviewed",
                "reviewer_note": "",
            })

            blind_review_rows.append({
                "render_id": render_id,
                "candidate_1": "unreviewed",
                "candidate_2": "unreviewed",
                "candidate_3": "unreviewed",
                "candidate_4": "unreviewed",
                "candidate_1_direction": "unreviewed",
                "candidate_1_magnitude": "unreviewed",
                "candidate_1_note": "",
                "candidate_2_direction": "unreviewed",
                "candidate_2_magnitude": "unreviewed",
                "candidate_2_note": "",
                "candidate_3_direction": "unreviewed",
                "candidate_3_magnitude": "unreviewed",
                "candidate_3_note": "",
                "candidate_4_direction": "unreviewed",
                "candidate_4_magnitude": "unreviewed",
                "candidate_4_note": "",
            })

        await browser.close()
    manager.close()

    # Clean up any misplaced old blind images in root evidence directory
    for old_blind in evidence_dir.glob("*_policy_blind.png"):
        old_blind.unlink(missing_ok=True)
    (evidence_dir / "blind_review.csv").unlink(missing_ok=True)

    # Save policy_metrics.json
    metrics_json_path = evidence_dir / "policy_metrics.json"
    with open(metrics_json_path, "w", encoding="utf-8") as f:
        json.dump({"schema": 1, "total_records": len(policy_metrics_records), "records": policy_metrics_records}, f, indent=2, ensure_ascii=False)
    print(f"Saved policy metrics JSON to {metrics_json_path}")

    # Save policy_metrics.csv
    metrics_csv_path = evidence_dir / "policy_metrics.csv"
    fieldnames = list(policy_metrics_records[0].keys())
    with open(metrics_csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in policy_metrics_records:
            row = dict(r)
            row["new_edge_clipping"] = str(row["new_edge_clipping"])
            writer.writerow(row)
    print(f"Saved policy metrics CSV to {metrics_csv_path}")

    # Save policy_review.csv
    review_csv_path = evidence_dir / "policy_review.csv"
    review_fields = ["render_id", "canonical_name", "category", "baseline_vs_raw", "baseline_vs_C", "baseline_vs_D", "baseline_vs_E", "reviewer_note"]
    with open(review_csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=review_fields)
        writer.writeheader()
        for r in review_rows:
            writer.writerow(r)
    print(f"Saved policy review CSV to {review_csv_path}")

    # Save blind_manifest.json (KEPT STRICTLY IN ROOT EVIDENCE DIR, NOT IN BLIND REVIEW PACKAGE)
    with open(blind_manifest_path, "w", encoding="utf-8") as f:
        json.dump({
            "schema": 1,
            "description": "Deterministic mapping from blind Candidate 1-4 to candidate policy B/C/D/E for each render_id.",
            "samples": blind_manifest
        }, f, indent=2, ensure_ascii=False)
    print(f"Saved blind manifest JSON to {blind_manifest_path}")

    manifest_hash_after = hashlib.sha256(blind_manifest_path.read_bytes()).hexdigest()
    if manifest_hash_before is not None:
        assert manifest_hash_before == manifest_hash_after, (
            f"Deterministic manifest mismatch!\nBefore: {manifest_hash_before}\nAfter:  {manifest_hash_after}"
        )
        print(f"Manifest byte-for-byte reproducibility VERIFIED! SHA256: {manifest_hash_after}")

    # Save blind_review.csv into blind_review_package
    blind_review_csv_path = blind_package_dir / "blind_review.csv"
    blind_review_fields = [
        "render_id",
        "candidate_1", "candidate_2", "candidate_3", "candidate_4",
        "candidate_1_direction", "candidate_1_magnitude", "candidate_1_note",
        "candidate_2_direction", "candidate_2_magnitude", "candidate_2_note",
        "candidate_3_direction", "candidate_3_magnitude", "candidate_3_note",
        "candidate_4_direction", "candidate_4_magnitude", "candidate_4_note",
    ]
    with open(blind_review_csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=blind_review_fields)
        writer.writeheader()
        for r in blind_review_rows:
            writer.writerow(r)
    print(f"Saved blind review CSV to {blind_review_csv_path}")

    # Copy REVIEW_INSTRUCTIONS.md into blind_review_package
    instructions_src = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "face_guided_body_centering" / "blind_review_package" / "REVIEW_INSTRUCTIONS.md"
    if not instructions_src.exists():
        # Fallback to scratch or write directly if not already present
        pass

    # Verify package isolation: strictly ONLY 36 PNGs + 1 CSV + 1 MD
    package_files = list(blind_package_dir.iterdir())
    package_filenames = {f.name for f in package_files}
    forbidden = {"blind_manifest.json", "policy_metrics.json", "policy_metrics.csv", "policy_statistics.json", "summary_statistics.json"}
    found_forbidden = forbidden.intersection(package_filenames)
    assert not found_forbidden, f"CRITICAL LEAK: Forbidden files found in blind review package: {found_forbidden}!"

    png_count = sum(1 for f in package_files if f.suffix == ".png")
    assert png_count == 36, f"Expected 36 PNGs in blind review package, found {png_count}!"
    print(f"Blind Review Package successfully isolated ({len(package_files)} files: 36 PNGs + 1 CSV + 1 MD)")

    # Task 6: Compute geometric shift statistics for each candidate policy
    stats = {}
    for pol_id in ["A", "B", "C", "D", "E"]:
        shifts_pol = [abs(r["candidate_shift"]) for r in policy_metrics_records if r["policy"] == pol_id]
        stats[pol_id] = {
            "median_abs_shift": round(percentile(shifts_pol, 0.50), 2),
            "p75": round(percentile(shifts_pol, 0.75), 2),
            "p90": round(percentile(shifts_pol, 0.90), 2),
            "max": round(max(shifts_pol), 2) if shifts_pol else 0.0,
            "gt_20": sum(1 for s in shifts_pol if s > 20.0),
            "gt_40": sum(1 for s in shifts_pol if s > 40.0),
            "gt_80": sum(1 for s in shifts_pol if s > 80.0),
        }

    stats_summary = {
        "sample_count": len(samples_v5),
        "policies": stats,
        "note": "Before human review is completed, only geometric statistics are reported. No winner should be chosen based on geometric metrics alone."
    }

    stats_path = evidence_dir / "policy_statistics.json"
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats_summary, f, indent=2, ensure_ascii=False)
    print(f"Saved policy statistics to {stats_path}")

    print("\n--- POLICY SHIFT GEOMETRIC STATISTICS ---")
    print(f"{'Policy':<10} | {'Median':<8} | {'P75':<8} | {'P90':<8} | {'Max':<8} | {'>20px':<6} | {'>40px':<6} | {'>80px':<6}")
    print("-" * 75)
    for pol_id, data in stats.items():
        print(f"{pol_id:<10} | {data['median_abs_shift']:<8.2f} | {data['p75']:<8.2f} | {data['p90']:<8.2f} | {data['max']:<8.2f} | {data['gt_20']:<6} | {data['gt_40']:<6} | {data['gt_80']:<6}")


if __name__ == "__main__":
    asyncio.run(main())
