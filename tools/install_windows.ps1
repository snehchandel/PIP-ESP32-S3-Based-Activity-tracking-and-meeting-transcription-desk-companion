# Creates "PIP Companion" shortcuts on the Desktop and in the Start menu.
# PIP then runs on its own (tray app) - no terminal or Claude Code needed.
# Usage:  powershell -ExecutionPolicy Bypass -File tools\install_windows.ps1
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
$tray = Join-Path $root "tools\pip_tray.pyw"
$ico = Join-Path $root "tools\pip.ico"
if (-not (Test-Path $pythonw)) { throw "Python venv not found at $pythonw - run setup first (see README)." }
if (-not (Test-Path (Join-Path $root "host\desktop_ui\dist\index.html"))) { throw "Desktop UI not built - run: cd host\desktop_ui; npm run build" }

& (Join-Path $root ".venv\Scripts\python.exe") -c "import sys; sys.path.insert(0, r'$root\tools'); from pathlib import Path; import importlib.util as u; s=u.spec_from_file_location('t', r'$tray'); m=u.module_from_spec(s); s.loader.exec_module(m); m.icon_image().save(r'$ico', sizes=[(16,16),(32,32),(48,48),(64,64)])"

$shell = New-Object -ComObject WScript.Shell
$targets = @(
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "PIP Companion.lnk"),
    (Join-Path ([Environment]::GetFolderPath("Programs")) "PIP Companion.lnk")
)
foreach ($lnk in $targets) {
    $s = $shell.CreateShortcut($lnk)
    $s.TargetPath = $pythonw
    $s.Arguments = "`"$tray`""
    $s.WorkingDirectory = "$root"
    $s.IconLocation = $ico
    $s.Description = "PIP - your focus companion"
    $s.Save()
    Write-Host "created $lnk"
}
Write-Host "Done. Open 'PIP Companion' from the Desktop or Start menu. Right-click the tray icon for 'Start with Windows'."
