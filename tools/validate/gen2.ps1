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
  [DllImport(D, EntryPoint="_MEM3createAtom@28")] public static extern int createAtom(out uint l, out int g, out int a, int vendor, int type, int ver, uint size);
  [DllImport(D, EntryPoint="_MEM3writeAtom@24")] public static extern int writeAtom(int l, int g, int a, int off, byte[] buf, uint len);
  [DllImport(D, EntryPoint="_MEM3instrCalResultInfo@52")] public static extern int calResult(int l, int g, int a, out uint l1, out int g1, out int a1, out uint l2, out int g2, out int a2, out uint n, out uint p11, out uint p12, out uint p13);
  [DllImport(D, EntryPoint="_MEM3instrCalResultStepInfo@28")] public static extern int calStep(int l, int g, int a, int step, out uint sl, out int sg, out int sa);
  [DllImport(D, EntryPoint="_MEM3promptResultInfo@28")] public static extern int promptResult(int l, int g, int a, out uint dl, out int dg, out int da, out int type);
  [DllImport(D, EntryPoint="_MEM3lastResultFloatValue@8")] public static extern int lastFloat(int idx, out float v);
  [DllImport(D, EntryPoint="_MEM3listResultInfo@40", CharSet=CharSet.Ansi)] public static extern int listResult(int l, int g, int a, out uint dl, out int dg, out int da, out uint count, int idx, StringBuilder item, int n);
  [DllImport(D, EntryPoint="_MEM3switchTestResultInfo@36")] public static extern int switchResult(int l, int g, int a, out uint l1, out int g1, out int a1, out uint l2, out int g2, out int a2);
  [DllImport(D, EntryPoint="_MEM3taskResultRefInfo@20")] public static extern int resultRef(int l, int g, int a, out uint rl, out int rg);
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
$idx=@{}
foreach ($line in Get-Content "$PSScriptRoot\in2.txt") {
  $t,$hex = $line.Split(' '); $t=[int]$t
  $b = New-Object byte[] ($hex.Length/2); for ($i=0;$i -lt $b.Length;$i++){ $b[$i]=[Convert]::ToByte($hex.Substring(2*$i,2),16) }
  $rc=[L]::createAtom([ref]$l,[ref]$g,[ref]$a,1,$t,0,$b.Length); $rc2=[L]::writeAtom($l,$g,$a,0,$b,$b.Length)
  Write-Output "# create type $t -> $rc write $rc2 at $l,$g,$a"; $idx[$t]=$a
}
$x1=0;$y1=0;$z1=0;$x2=0;$y2=0;$z2=0;$n=0;$p=0;$q=0;$r=0;$f=[single]0;$ty=0
$rc=[L]::calResult(1,0,$idx[4],[ref]$x1,[ref]$y1,[ref]$z1,[ref]$x2,[ref]$y2,[ref]$z2,[ref]$n,[ref]$p,[ref]$q,[ref]$r)
Write-Output "R4 rc=$rc first=$x1,$y1,$z1 second=$x2,$y2,$z2 n=$n p11=$p p12=$q p13=$r"
for ($s2=0;$s2 -lt 5;$s2++){ $rc=[L]::calStep(1,0,$idx[4],$s2,[ref]$x1,[ref]$y1,[ref]$z1); Write-Output "R4STEP $s2 rc=$rc addr=$x1,$y1,$z1" }
$rc=[L]::promptResult(1,0,$idx[8],[ref]$x1,[ref]$y1,[ref]$z1,[ref]$ty); $rc2=[L]::lastFloat(0,[ref]$f)
Write-Output "R8 rc=$rc defn=$x1,$y1,$z1 type=$ty frc=$rc2 value=$f"
$sb=New-Object Text.StringBuilder 100
for ($k=0;$k -lt 2;$k++){ $rc=[L]::listResult(1,0,$idx[14],[ref]$x1,[ref]$y1,[ref]$z1,[ref]$n,$k,$sb,100); Write-Output "R14 rc=$rc list=$x1,$y1,$z1 count=$n item$k=[$sb]" }
$rc=[L]::switchResult(1,0,$idx[17],[ref]$x1,[ref]$y1,[ref]$z1,[ref]$x2,[ref]$y2,[ref]$z2)
Write-Output "R17 rc=$rc a=$x1,$y1,$z1 b=$x2,$y2,$z2"
$rc=[L]::resultRef(1,0,$idx[18],[ref]$x1,[ref]$y1)
Write-Output "R18 rc=$rc list=$x1 group=$y1"
Check 'endTask' ([L]::endTask())
