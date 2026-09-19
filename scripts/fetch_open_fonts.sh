#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/fonts"
mkdir -p "$OUT"

fonts=(
  "NotoSansSC-wght.ttf https://raw.githubusercontent.com/google/fonts/main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf"
  "BarlowCondensed-SemiBold.ttf https://raw.githubusercontent.com/google/fonts/main/ofl/barlowcondensed/BarlowCondensed-SemiBold.ttf"
  "BarlowCondensed-Bold.ttf https://raw.githubusercontent.com/google/fonts/main/ofl/barlowcondensed/BarlowCondensed-Bold.ttf"
  "Rajdhani-SemiBold.ttf https://raw.githubusercontent.com/google/fonts/main/ofl/rajdhani/Rajdhani-SemiBold.ttf"
  "Rajdhani-Bold.ttf https://raw.githubusercontent.com/google/fonts/main/ofl/rajdhani/Rajdhani-Bold.ttf"
)

for entry in "${fonts[@]}"; do
  name="${entry%% *}"
  url="${entry#* }"
  dest="$OUT/$name"
  if [ ! -f "$dest" ]; then
    echo "Fetching $name ..."
    curl -L --fail --retry 3 "$url" -o "$dest"
  else
    echo "Already exists: $name"
  fi
done

echo "Open-source fonts verified in: $OUT"
