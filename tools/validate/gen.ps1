# Runs under 32-bit PowerShell. Loads the original dpclnk3.dll, builds a task with
# its own MEM3 API, then dumps every atom's raw bytes for memfmt.py to decode.
$ErrorActionPreference = 'Stop'
if (-not $env:DPCLNK3_DLL) { throw 'Set DPCLNK3_DLL to the full path of dpclnk3.dll from your own DPCTrack2 install.' }
$dll = (Resolve-Path $env:DPCLNK3_DLL).Path
$src = @"
using System; using System.Text; using System.Runtime.InteropServices;
public static class L {
  const string D = @"$($dll.Replace('\','\'))";
  [DllImport(D, EntryPoint="_MEM3startTask@16", CharSet=CharSet.Ansi)] public static extern int startTask(out uint l, out int g, string name, string text);
  [DllImport(D, EntryPoint="_MEM3endTask@0")] public static extern int endTask();
  [DllImport(D, EntryPoint="_MEM3strategyDefn@24", CharSet=CharSet.Ansi)] public static extern int strategyDefn(out uint l, out int g, out int a, string name, float[] pts, int n);
  [DllImport(D, EntryPoint="_MEM3listDefn@24", CharSet=CharSet.Ansi)] public static extern int listDefn(out uint l, out int g, out int a, string name, IntPtr[] items, int n);
  [DllImport(D, EntryPoint="_MEM3instrCalTemplate@56", CharSet=CharSet.Ansi)] public static extern int calTemplate(out uint l, out int g, out int a, int sl, int sg, int sa, int tl, int tg, int ta, ushort p10, ushort p11, uint p12, string s1, string s2);
  [DllImport(D, EntryPoint="_MEM3ngroups@8")] public static extern void ngroups(int list, out int n);
  [DllImport(D, EntryPoint="_MEM3natoms@12")] public static extern void natoms(int list, int group, out int n);
  [DllImport(D, EntryPoint="_MEM3atomDir@36", CharSet=CharSet.Ansi)] public static extern int atomDir(int list, int group, int atom, out uint vendor, out uint type, out uint ver, StringBuilder name, int nameSize, out uint alias);
  [DllImport(D, EntryPoint="_MEM3readAtom@24")] public static extern int readAtom(int list, int group, int atom, int offset, byte[] buf, ref uint len);
  [DllImport(D, EntryPoint="_DPC3mapCache@16", CharSet=CharSet.Ansi)] public static extern int mapCache(string map, int value, string text, string extra);
  [DllImport(D, EntryPoint="_MEM3promptDefn@28", CharSet=CharSet.Ansi)] public static extern int promptDefn(out uint l, out int g, out int a, string text, string p5, string kind, string font);
  [DllImport(D, EntryPoint="_STA3beginOps@0")] public static extern int beginOps();
  [DllImport(D, EntryPoint="_STA3initOp@0")] public static extern int initOp();
  [DllImport(D, EntryPoint="_STA3evalOp@0")] public static extern int evalOp();
  [DllImport(D, EntryPoint="_STA3setFloatOp@12", CharSet=CharSet.Ansi)] public static extern int setFloatOp(string list, string bucket, float v);
  [DllImport(D, EntryPoint="_STA3setIntOp@12", CharSet=CharSet.Ansi)] public static extern int setIntOp(string list, string bucket, int v);
  [DllImport(D, EntryPoint="_STA3setStrOp@12", CharSet=CharSet.Ansi)] public static extern int setStrOp(string list, string bucket, string v);
  [DllImport(D, EntryPoint="_STA3saveOps@12")] public static extern int saveOps(out uint l, out int g, out int a);
  [DllImport(D, EntryPoint="_DPC3version@8", CharSet=CharSet.Ansi)] public static extern void version(StringBuilder s, int n);
}
"@
Add-Type -TypeDefinition $src
function Check($what, $rc) { Write-Output "# $what -> $rc" }
$v = New-Object Text.StringBuilder 32; [L]::version($v, 32); Write-Output "# dll version $v  ptrsize $([IntPtr]::Size)"
$l=0;$g=0;$a=0
$m = @(@('font',0,'small',$null),@('font',1,'big',$null),@('sbucket',2,'meas',$null),@('sbucket',5,'src',$null),@('sbucket',0,'root',$null),
       @('sbucket/root',1,'dummy','I'),
       @('sbucket/meas',18,'value','V,exp'),@('sbucket/meas',19,'count','I,exp'),@('sbucket/meas',200,'big','V,exp'),@('sbucket/meas',20,'label','ST[16],exp'),
       @('sbucket/src',3,'mode','I,exp'))
foreach ($e in $m) { $rc=[L]::mapCache($e[0],$e[1],$e[2],$e[3]); if ($rc) { Write-Output "# mapCache $($e[0]) -> $rc" } }
Check 'startTask' ([L]::startTask([ref]$l,[ref]$g,'PT-101 cal','Loop check'))
Write-Output "# task at list $l group $g"
$sl=0;$sg=0;$sa=0
Check 'strategyDefn' ([L]::strategyDefn([ref]$sl,[ref]$sg,[ref]$sa,'5pt up',[single[]](0,0.25,0.5,0.75,1.0),5))
Write-Output "# strategy at $sl,$sg,$sa"
$items = 'Good','Bad','Needs, repair' | ForEach-Object { [Runtime.InteropServices.Marshal]::StringToHGlobalAnsi($_) }
Check 'listDefn' ([L]::listDefn([ref]$l,[ref]$g,[ref]$a,'Condition',[IntPtr[]]$items,3))
Write-Output "# list at $l,$g,$a"
$ll=$l;$lg=$g;$la=$a
Check 'calTemplate' ([L]::calTemplate([ref]$l,[ref]$g,[ref]$a,$sl,$sg,$sa,$sl,$sg,$sa,1,2,0x01020304,'viewA','viewB'))
Write-Output "# template at $l,$g,$a"
Check 'promptDefn' ([L]::promptDefn([ref]$l,[ref]$g,[ref]$a,'Enter ambient temp','degC','numeric','big'))
Write-Output "# prompt at $l,$g,$a"
Check 'beginOps' ([L]::beginOps())
Check 'setFloat' ([L]::setFloatOp('meas','value',4.002))
Check 'setFloat0' ([L]::setFloatOp('meas','value',0))
Check 'setFloat20' ([L]::setFloatOp('meas','value',20))
Check 'setFloatBig' ([L]::setFloatOp('meas','big',-1.5))
Check 'setInt5' ([L]::setIntOp('meas','count',5))
Check 'setInt-200' ([L]::setIntOp('meas','count',-200))
Check 'setInt70000' ([L]::setIntOp('meas','count',70000))
Check 'setInt300' ([L]::setIntOp('src','mode',300))
Check 'setStr' ([L]::setStrOp('meas','label','hello'))
Check 'evalOp' ([L]::evalOp())
Check 'saveOps' ([L]::saveOps([ref]$l,[ref]$g,[ref]$a))
Write-Output "# ops at $l,$g,$a"
Check 'endTask' ([L]::endTask())
foreach ($list in 1,2) {
  $ng=0; [L]::ngroups($list,[ref]$ng)
  for ($gi=0; $gi -lt $ng; $gi++) {
    $na=0; [L]::natoms($list,$gi,[ref]$na)
    for ($ai=0; $ai -lt $na; $ai++) {
      $vn=0;$ty=0;$ve=0;$al=0; $nm = New-Object Text.StringBuilder 130
      $rc=[L]::atomDir($list,$gi,$ai,[ref]$vn,[ref]$ty,[ref]$ve,$nm,130,[ref]$al)
      $buf = New-Object byte[] 4096; $len=[uint32]4096
      $rc2=[L]::readAtom($list,$gi,$ai,0,$buf,[ref]$len)
      $hex = -join ($buf[0..([Math]::Max(0,$len-1))] | ForEach-Object { $_.ToString('x2') })
      if ($len -eq 0) { $hex = '' }
      Write-Output "ATOM $list $gi $ai $vn $ty $ve $al $rc $rc2 $len [$nm] $hex"
    }
  }
}
