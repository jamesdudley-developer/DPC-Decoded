# Builds dist\DPCReader-<version>-setup.msi. Needs Python 3.10+ and the .NET SDK.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python -m pip install -q pyserial pyinstaller
.\.venv\Scripts\python tests\test_app_logic.py
if ($LASTEXITCODE) { throw 'tests failed' }
.\.venv\Scripts\python -m PyInstaller --noconfirm --clean --windowed --name DPCReader --onedir --exclude-module PIL --exclude-module numpy run_dpcreader.py
if (-not (Test-Path .tools\wix.exe)) { dotnet tool install --tool-path .tools wix --version 5.0.2 }
$p = Start-Process .\dist\DPCReader\DPCReader.exe -ArgumentList '--selftest' -Wait -PassThru
if ($p.ExitCode) { throw 'packaged app self-test failed' }
Push-Location installer
..\.tools\wix.exe build Product.wxs -arch x64 -o ..\dist\DPCReader-0.1.0-setup.msi
Pop-Location
Get-Item dist\*.msi
