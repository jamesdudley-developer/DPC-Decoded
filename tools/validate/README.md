# Validation against the original link library

Optional, Windows only. These scripts cross-check `dpcreader/memfmt.py` against
`dpclnk3.dll` from **your own** DPCTrack2 installation. The DLL is not part of
this repository and must not be added to it.

    $env:DPCLNK3_DLL = 'C:\path\to\dpclnk3.dll'
    # must be 32-bit PowerShell, because the DLL is 32-bit
    & "$env:WINDIR\SysWOW64\WindowsPowerShell\v1.0\powershell.exe" -ExecutionPolicy Bypass -File gen.ps1  > out.txt
    & "$env:WINDIR\SysWOW64\WindowsPowerShell\v1.0\powershell.exe" -ExecutionPolicy Bypass -File gen2.ps1 > out2.txt
    python build3.py > in3.txt; python build2.py > in2.txt
    & "$env:WINDIR\SysWOW64\WindowsPowerShell\v1.0\powershell.exe" -ExecutionPolicy Bypass -File gen3.ps1 > out3.txt
    python check.py; python check2.py      # both should print ALL MATCH
