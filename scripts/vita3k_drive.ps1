# Starts the game in Vita3K, then runs a script of steps: wait, key press, screenshot of the game window.
#
#   powershell -ExecutionPolicy Bypass -File scripts\vita3k_drive.ps1 -Exe <Vita3K.exe> -Out <prefix> -Steps "w25 s k:C w3 s"
#
# Steps (space separated):  wN = wait N seconds   s = screenshot (<prefix>-<n>.png)   k:KEY[xN] = press a key (N times)
# KEY is a Vita3K keyboard binding: C circle, X cross, Z square, V triangle, Enter start, Up/Down/Left/Right, Q/E L/R.
# The emulator is closed at the end unless -Keep is given.
param([Parameter(Mandatory = $true)][string]$Exe, [Parameter(Mandatory = $true)][string]$Out,
      [string]$Steps = "w25 s", [string]$TitleId = "PCSG00675", [switch]$Keep)
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System; using System.Text; using System.Threading; using System.Runtime.InteropServices;
public class W {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc f, IntPtr l);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint f);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
  [DllImport("user32.dll")] public static extern uint MapVirtualKey(uint code, uint type);
  public struct RECT { public int L, T, R, B; }
  public static IntPtr Find(uint pid, string needle) {
    IntPtr found = IntPtr.Zero;
    EnumWindows((h, l) => { uint p; GetWindowThreadProcessId(h, out p);
      if (p == pid && IsWindowVisible(h)) { var s = new StringBuilder(512); GetWindowText(h, s, 512);
        if (s.ToString().Contains(needle)) { found = h; return false; } } return true; }, IntPtr.Zero);
    return found;
  }
  public static void Press(byte vk, bool ext) {
    byte sc = (byte)MapVirtualKey(vk, 0); uint e = ext ? 1u : 0u;
    keybd_event(vk, sc, e, UIntPtr.Zero); Thread.Sleep(120); keybd_event(vk, sc, e | 2u, UIntPtr.Zero); Thread.Sleep(250);
  }
}
"@
$vk = @{ Up = 0x26; Down = 0x28; Left = 0x25; Right = 0x27; Enter = 0x0D }
$p = Start-Process -FilePath $Exe -ArgumentList "-r", $TitleId -WorkingDirectory (Split-Path $Exe) -PassThru
$n = 0
function Get-Game { [W]::Find([uint32]$p.Id, $TitleId) }
foreach ($step in ($Steps -split '\s+' | Where-Object { $_ })) {
  if ($step -match '^w(\d+(\.\d+)?)$') { Start-Sleep -Milliseconds ([double]$Matches[1] * 1000); continue }
  $h = Get-Game
  if ($h -eq [IntPtr]::Zero) { "no game window for step $step"; continue }
  if ($step -eq 's') {
    $n++
    $r = New-Object W+RECT; [W]::GetWindowRect($h, [ref]$r) | Out-Null
    $bmp = New-Object System.Drawing.Bitmap ($r.R - $r.L), ($r.B - $r.T)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $dc = $g.GetHdc(); [W]::PrintWindow($h, $dc, 2) | Out-Null; $g.ReleaseHdc($dc)
    $file = "{0}-{1:D2}.png" -f $Out, $n
    $bmp.Save($file); $g.Dispose(); $bmp.Dispose(); "saved $file"
  } elseif ($step -match '^k:(\w+?)(x(\d+))?$') {
    $key = $Matches[1]; $times = if ($Matches[3]) { [int]$Matches[3] } else { 1 }
    $code = if ($vk.ContainsKey($key)) { $vk[$key] } else { [byte][char]$key.ToUpper() }
    [W]::SetForegroundWindow($h) | Out-Null; Start-Sleep -Milliseconds 150
    for ($i = 0; $i -lt $times; $i++) { [W]::Press([byte]$code, $vk.ContainsKey($key) -and $key -ne 'Enter') }
  } else { "unknown step $step" }
}
if (-not $Keep) { Stop-Process -Id $p.Id -Force }
