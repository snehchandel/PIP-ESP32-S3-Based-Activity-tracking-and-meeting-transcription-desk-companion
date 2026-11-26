# Creates "PIP Companion (dev)" shortcuts on the Desktop and in the Start menu that run PIP from this repository.
# For the packaged app use the installer instead (tools\build_exe.ps1 -> build\app\PIP-Setup-<version>.exe), which
# owns the plain "PIP Companion" shortcut names.
# Usage:  powershell -ExecutionPolicy Bypass -File tools\install_windows.ps1
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
$tray = Join-Path $root "tools\pip_tray.pyw"
$ico = Join-Path $root "tools\pip.ico"
if (-not (Test-Path $pythonw)) { throw "Python venv not found at $pythonw - run setup first (see README)." }
if (-not (Test-Path (Join-Path $root "host\desktop_ui\dist\index.html"))) { throw "Desktop UI not built - run: cd host\desktop_ui; npm run build" }

& (Join-Path $root ".venv\Scripts\python.exe") -c "import sys; sys.path.insert(0, r'$root\host'); from service.desktop import main; main(['--write-icon', r'$ico'])"

$shell = New-Object -ComObject WScript.Shell
foreach ($folder in @([Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs"))) {
    # older versions of this script used the plain name: remove those (only if they point at this venv)
    $old = Join-Path $folder "PIP Companion.lnk"
    if ((Test-Path $old) -and ($shell.CreateShortcut($old).TargetPath -eq $pythonw)) { Remove-Item $old; Write-Host "removed $old" }
    $lnk = Join-Path $folder "PIP Companion (dev).lnk"
    $s = $shell.CreateShortcut($lnk)
    $s.TargetPath = $pythonw
    $s.Arguments = "`"$tray`""
    $s.WorkingDirectory = "$root"
    $s.IconLocation = $ico
    $s.Description = "PIP - your focus companion (from the source folder)"
    $s.Save()
    Write-Host "created $lnk"
}
Write-Host "Done. Open 'PIP Companion (dev)' from the Desktop or Start menu. Right-click the tray icon for 'Start with Windows'."
