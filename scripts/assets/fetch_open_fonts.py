"""从官方源拉取开源字体（Noto Sans SC, Barlow Condensed, Rajdhani）。"""

# 支持直接执行、模块导入及从其他工作目录调用。
import sys as _bootstrap_sys
from pathlib import Path as _BootstrapPath
_bootstrap_root = _BootstrapPath(__file__).resolve().parents[2]
for _bootstrap_path in (_bootstrap_root.parent, _bootstrap_root):
    if str(_bootstrap_path) not in _bootstrap_sys.path:
        _bootstrap_sys.path.insert(0, str(_bootstrap_path))

import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "assets" / "fonts"
OUT.mkdir(parents=True, exist_ok=True)

FONTS = {
    "NotoSansSC-wght.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf",
    "BarlowCondensed-SemiBold.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/barlowcondensed/BarlowCondensed-SemiBold.ttf",
    "BarlowCondensed-Bold.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/barlowcondensed/BarlowCondensed-Bold.ttf",
    "Rajdhani-SemiBold.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/rajdhani/Rajdhani-SemiBold.ttf",
    "Rajdhani-Bold.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/rajdhani/Rajdhani-Bold.ttf",
}


def main():
    print(f"Downloading open fonts to: {OUT}")
    for name, url in FONTS.items():
        dest = OUT / name
        if dest.exists():
            print(f"  [Exists] {name} ({dest.stat().st_size:,} bytes)")
            continue
        print(f"  [Fetching] {name} from {url} ...")
        urllib.request.urlretrieve(url, dest)
        print(f"  [Done] {name} ({dest.stat().st_size:,} bytes)")
    print("All open fonts ready.")


if __name__ == "__main__":
    main()
