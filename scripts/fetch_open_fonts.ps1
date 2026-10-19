# 旧命令兼容入口；在当前 PowerShell 中转发参数和取消信号。
$global:LASTEXITCODE = 0
& (Join-Path $PSScriptRoot "assets/fetch_open_fonts.ps1") @args
exit $LASTEXITCODE
