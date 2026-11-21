# Builds dist\DPCReader-<version>-setup.msi. Needs Python 3.10+ and the .NET SDK.
# Native tools write progress to stderr, which Windows PowerShell 5.1 turns into errors
# under 'Stop', so failures are detected by exit code instead.
$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot
function Check($what) { if ($LASTEXITCODE) { throw "$what failed (exit $LASTEXITCODE)" } }
if (-not (Test-Path .venv)) { python -m venv .venv; Check 'venv' }
.\.venv\Scripts\python -m pip install -q --disable-pip-version-check pyserial pyinstaller reportlab pillow; Check 'pip install'
.\.venv\Scripts\python -m unittest discover tests; Check 'tests'
.\.venv\Scripts\python -m PyInstaller --noconfirm --clean --windowed --name DPCReader --onedir --exclude-module numpy --exclude-module pypdfium2 run_dpcreader.py; Check 'PyInstaller'
if (-not (Test-Path .tools\wix.exe)) { dotnet tool install --tool-path .tools wix --version 5.0.2; Check 'wix install' }
$p = Start-Process .\dist\DPCReader\DPCReader.exe -ArgumentList '--selftest' -Wait -PassThru
if ($p.ExitCode) { throw 'packaged app self-test failed' }
Push-Location installer
..\.tools\wix.exe build Product.wxs -arch x64 -o ..\dist\DPCReader-0.3.1-setup.msi; Check 'wix build'
Pop-Location
Get-Item dist\*.msi
