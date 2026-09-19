"""为 NIKKE Character Card 构建专用 Noto Sans SC WOFF2 子集字体。

提取全部官方中文角色名、固定 UI 标签、装备词条与全套基础标点/数字/字母，
将 17.7MB Variable TTF 压缩实例化为 700 (Bold) 与 800 (ExtraBold) 轻量级 WOFF2 子集。
"""
import argparse
import json
from pathlib import Path
import string
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
GOOGLE_FONTS_NOTO_URL = (
    "https://raw.githubusercontent.com/google/fonts/main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf"
)


def collect_character_set(root: Path) -> set[str]:
    chars = set()

    # A. 现有全部角色 master 数据与中文名
    master_path = root / "assets/character_master.json"
    if master_path.is_file():
        try:
            master = json.loads(master_path.read_text(encoding="utf-8"))
            for item in master.get("characters", []):
                chars.update(item.get("name_cn", ""))
                chars.update(item.get("name_en", ""))
        except Exception as exc:
            print(f"Warning reading character_master.json: {exc}")

    # B. Character Card 固定 UI 文案
    fixed_ui = [
        "拉毗：小红帽",
        "白雪公主：重型武装",
        "这是用于验证中英文超长角色名称的练度卡 Long Character Name",
        "词条合计",
        "已知词条合计",
        "阶",
        "技能",
        "技能1",
        "技能2",
        "爆裂",
        "未装备",
        "未获得效果",
        "纸面合计",
        "已知部分",
        "立绘暂不可用",
        "已装备",
        "名称",
        "突破",
        "核心",
        "好感",
        "指挥官",
        "更新",
        "版本",
        "生命",
        "攻击力",
        "防御力",
        "纸面",
        "合计",
        "部分",
        "有效",
        "收益",
        "EMPTY",
        "UNKNOWN",
        "BATTLE",
        "Lv.",
        "LV.",
        "HP",
        "ATK",
        "DEF",
    ]
    for text in fixed_ui:
        chars.update(text)

    # C. 装备词条名称与短名称
    options = [
        "攻击力增加",
        "防御力增加",
        "最大装弹数增加",
        "蓄力速度增加",
        "优越代码伤害增加",
        "暴击率增加",
        "暴击伤害增加",
        "命中率增加",
        "蓄力伤害增加",
        "攻击",
        "防御",
        "装弹",
        "蓄速",
        "优越",
        "暴率",
        "暴伤",
        "命中",
        "蓄伤",
    ]
    for opt in options:
        chars.update(opt)

    # D. 基础字符与标点
    chars.update(string.ascii_letters)
    chars.update(string.digits)
    chars.update(string.punctuation)
    chars.update(" ：:+-%.（）()【】[]/ ✦★·—~，。、“”‘’#@_")

    # 包含阶数标记 T1 ~ T15
    for i in range(1, 16):
        chars.update(f"T{i}")
        chars.update(f"{i}阶")

    return chars


def build_subsets(source_ttf: Path, out_dir: Path, weights: list[int], text: str):
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont
    from fontTools import subset

    out_dir.mkdir(parents=True, exist_ok=True)
    options = subset.Options()
    options.flavor = "woff2"
    options.desubroutinize = True

    results = {}
    for weight in weights:
        print(f"Instantiating variable font at weight {weight}...")
        font = TTFont(source_ttf)
        instantiated = instantiateVariableFont(font, {"wght": weight})

        print(f"Subsetting {len(text)} unique glyphs for weight {weight} (WOFF2)...")
        sub = subset.Subsetter(options=options)
        sub.populate(text=text)
        sub.subset(instantiated)

        out_name = f"NotoSansSC-ReplicaSubset-{weight}.woff2"
        out_path = out_dir / out_name
        instantiated.save(out_path)
        size = out_path.stat().st_size
        results[weight] = {"path": out_path, "size": size}
        print(f"  -> Generated {out_name} ({size:,} bytes)")

    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "fonts/NotoSansSC-wght.ttf",
        help="Path to source NotoSansSC variable TTF font",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "fonts",
        help="Output directory for generated subset woff2 files",
    )
    parser.add_argument(
        "--weights",
        type=str,
        default="700,800",
        help="Comma-separated font weights to generate",
    )
    args = parser.parse_args()

    weights = [int(w.strip()) for w in args.weights.split(",") if w.strip()]
    chars = collect_character_set(ROOT)
    sorted_text = "".join(sorted(chars))
    print(f"Aggregated {len(sorted_text)} unique characters for subset.")

    source_ttf = args.source
    if not source_ttf.is_file():
        print(f"Source TTF not found at {source_ttf}, downloading from Google Fonts OFL repository...")
        source_ttf.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(GOOGLE_FONTS_NOTO_URL, source_ttf)
        print(f"Downloaded source TTF ({source_ttf.stat().st_size:,} bytes).")

    results = build_subsets(source_ttf, args.out_dir, weights, sorted_text)
    print("\nSubset Generation Summary:")
    print(f"Unique Characters: {len(sorted_text)}")
    for weight, info in results.items():
        print(f"Weight {weight}: {info['path'].name} ({info['size']:,} bytes)")


if __name__ == "__main__":
    main()
