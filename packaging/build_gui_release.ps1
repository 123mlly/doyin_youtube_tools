# Build standalone GUI on Windows (PowerShell). Run from repo root or any cwd.
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root
python -m pip install -q -e ".[gui,build-gui]"
python -m PyInstaller --noconfirm --clean (Join-Path $Root "packaging\DouyinDownloaderGui.spec")
Write-Host "Done. See $Root\dist\"
