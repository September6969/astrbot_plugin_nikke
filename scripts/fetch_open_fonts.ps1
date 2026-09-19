$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Out = Join-Path $Root "fonts"
New-Item -ItemType Directory -Force -Path $Out | Out-Null

$fonts = @{
  "NotoSansSC-wght.ttf" = "https://raw.githubusercontent.com/google/fonts/main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf"
  "BarlowCondensed-SemiBold.ttf" = "https://raw.githubusercontent.com/google/fonts/main/ofl/barlowcondensed/BarlowCondensed-SemiBold.ttf"
  "BarlowCondensed-Bold.ttf" = "https://raw.githubusercontent.com/google/fonts/main/ofl/barlowcondensed/BarlowCondensed-Bold.ttf"
  "Rajdhani-SemiBold.ttf" = "https://raw.githubusercontent.com/google/fonts/main/ofl/rajdhani/Rajdhani-SemiBold.ttf"
  "Rajdhani-Bold.ttf" = "https://raw.githubusercontent.com/google/fonts/main/ofl/rajdhani/Rajdhani-Bold.ttf"
}

foreach ($name in $fonts.Keys) {
  $dest = Join-Path $Out $name
  if (-not (Test-Path $dest)) {
    Write-Host "Fetching $name ..."
    Invoke-WebRequest -Uri $fonts[$name] -OutFile $dest
  } else {
    Write-Host "Already exists: $name"
  }
}

Write-Host "Open-source fonts verified in: $Out"
