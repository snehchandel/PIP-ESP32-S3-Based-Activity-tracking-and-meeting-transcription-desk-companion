# Builds the packaged PIP Companion app (ADR-034):
#   1. the companion UI (host/desktop_ui -> dist/)
#   2. PIP.exe with PyInstaller (tools/pip.spec -> build/app/dist/PIP/)
#   3. a smoke test of the built exe (tools/smoke_exe.py, on a spare port with a throw-away data folder)
#   4. the installer with Inno Setup (tools/installer/pip.iss -> build/app/PIP-Setup-<version>.exe)
# Usage (repo root):  powershell -ExecutionPolicy Bypass -File tools\build_exe.ps1 [-SkipUi] [-SkipSmoke] [-SkipInstaller]
param([switch]$SkipUi, [switch]$SkipSmoke, [switch]$SkipInstaller)
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Python venv not found at $py - run setup first (see README)." }

# App version = host/pyproject.toml [project] version
$version = (Select-String -Path (Join-Path $root "host\pyproject.toml") -Pattern '^version\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
Write-Host "PIP Companion $version"

if (-not $SkipUi) {
    Push-Location (Join-Path $root "host\desktop_ui")
    try { npm run build; if ($LASTEXITCODE) { throw "UI build failed" } } finally { Pop-Location }
}
if (-not (Test-Path (Join-Path $root "host\desktop_ui\dist\index.html"))) { throw "Desktop UI not built" }
if (-not (Test-Path (Join-Path $root "firmware\build\pip_firmware.bin"))) {
    Write-Warning "firmware\build\pip_firmware.bin missing - the app will ship without a bundled firmware image"
}

& $py -m pip install --quiet -r (Join-Path $root "host\requirements-runtime.txt") "pyinstaller>=6.10"
if ($LASTEXITCODE) { throw "pip install failed" }

$ico = Join-Path $root "tools\pip.ico"  # generated (gitignored): exe, window and shortcut icon
& $py -c "import sys; sys.path.insert(0, r'$root\host'); from service.desktop import main; main(['--write-icon', r'$ico'])"
if ($LASTEXITCODE) { throw "icon generation failed" }

$env:PIP_APP_VERSION = $version
& $py -m PyInstaller (Join-Path $root "tools\pip.spec") --noconfirm --clean `
    --distpath (Join-Path $root "build\app\dist") --workpath (Join-Path $root "build\app\work")
if ($LASTEXITCODE) { throw "PyInstaller failed" }
$exe = Join-Path $root "build\app\dist\PIP\PIP.exe"
$size = (Get-ChildItem (Split-Path $exe) -Recurse | Measure-Object Length -Sum).Sum / 1MB
Write-Host ("built {0} ({1:N0} MB)" -f $exe, $size)

if (-not $SkipSmoke) {
    & $py (Join-Path $root "tools\smoke_exe.py") $exe
    if ($LASTEXITCODE) { throw "smoke test failed" }
}

if (-not $SkipInstaller) {
    $iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
              "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $iscc) { throw "Inno Setup 6 not found - winget install JRSoftware.InnoSetup" }
    & $iscc "/DAppVersion=$version" (Join-Path $root "tools\installer\pip.iss")
    if ($LASTEXITCODE) { throw "Inno Setup failed" }
    Write-Host "installer: $(Join-Path $root "build\app\PIP-Setup-$version.exe")"
}
