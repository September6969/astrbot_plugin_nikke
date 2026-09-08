"""使用脱敏fixture生成可重复的UI2验收图片，不读取真实账号。"""

import argparse
import shutil
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from astrbot_plugin_nikke.asset_manager import AssetManager
from astrbot_plugin_nikke.character_card_renderer import CharacterCardRenderer
from astrbot_plugin_nikke.tests.test_card_builder import build_card


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--remote", action="store_true")
    args = parser.parse_args()
    output = Path(args.output)
    manager = AssetManager(output / "cache", ROOT / "assets", remote=args.remote)
    try:
        renderer = CharacterCardRenderer(output, ROOT / "fonts", manager)
        original = build_card()
        cards = {
            "red-hood": original,
            "alice": replace(original, name_code="5004", resource_id="191", name_cn="爱丽丝", name_en="Alice",
                             corporation="TETRA", element="Fire", burst="Step3"),
            "missilis-water": replace(original, name_cn="米西利斯 · 水冷预览", name_en="MISSILIS / WATER",
                                       corporation="MISSILIS", element="Water"),
            "elysion-wind-long-name": replace(original, name_cn="极乐净土超长角色名称裁切与排版验收预览",
                                               name_en="ELYSION LONG CHARACTER NAME PREVIEW",
                                               corporation="ELYSION", element="Wind"),
            "abnormal": replace(original, name_cn="反常者 · 合成预览", name_en="ABNORMAL SYNTHETIC PREVIEW",
                                corporation="ABNORMAL", element="Iron"),
            "fallback": replace(original, name_code="missing", resource_id=None, name_cn="未知角色 · 素材缺失预览", name_en="UNKNOWN NIKKE"),
        }
        for name, card in cards.items():
            generated = Path(renderer.render_character(card))
            path = output / f"{name}.png"
            shutil.move(str(generated), path)
            print(path)
    finally:
        manager.close()


if __name__ == "__main__":
    main()
