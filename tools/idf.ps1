# Run idf.py inside the pinned ESP-IDF v5.5.5 environment.
# Usage: powershell -File tools/idf.ps1 <idf.py args...>
$ErrorActionPreference = "Continue"
$idf = if ($env:PIP_IDF_PATH) { $env:PIP_IDF_PATH } else { "C:\esp\esp-idf-v5.5.5" }
. "$idf\export.ps1" *> $null
Set-Location (Join-Path $PSScriptRoot "..\firmware")
idf.py @args
exit $LASTEXITCODE
