# Maintainer build script: run on Windows with Python 3.12 installed.
# End users receive the release ZIP; Python is bundled in that download.
[CmdletBinding()]
param([switch]$SkipInstall)
$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne 'Win32NT') {
    throw 'Build the Windows application on a Windows machine.'
}
Set-Location (Join-Path $PSScriptRoot '..')
$env:PYINSTALLER_CONFIG_DIR = Join-Path (Get-Location) 'build\pyinstaller-cache'
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Creating the Python environment failed.' }
}
$Python = Join-Path (Get-Location) '.venv\Scripts\python.exe'
if (-not $SkipInstall) {
    & $Python -m pip install -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw 'Installing build dependencies failed.' }
}
$env:SAFE_GUI_TEST = '1'
& $Python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'The Windows PDF or GUI tests failed.' }
& $Python -m PyInstaller --noconfirm --clean --workpath build/pyinstaller --distpath dist 'SAFE PDF Formatter.spec'
if ($LASTEXITCODE -ne 0) { throw 'Building the application failed.' }
& $Python scripts/package_release.py
if ($LASTEXITCODE -ne 0) { throw 'Assembling the release failed.' }
& $Python scripts/verify_build.py --gui --from-zip
if ($LASTEXITCODE -ne 0) { throw 'Verifying the standalone application failed.' }
Write-Host 'Built release\SAFE PDF Formatter-Windows-AMD64'
