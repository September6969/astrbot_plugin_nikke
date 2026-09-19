"""从官方源拉取开源字体（Noto Sans SC, Barlow Condensed, Rajdhani）。"""
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fonts"
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
