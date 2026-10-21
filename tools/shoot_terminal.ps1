# Открывает окно PowerShell с этапом stage.ps1, растягивает его, ждет окончания и снимает скриншот окна (PrintWindow).
# Пример: .\scripts\shoot_terminal.ps1 s1 screenshots\04_scenario1.png
param([string]$Stage, [string]$Out, [int]$Width = 1500, [int]$Height = 1060)
Set-Location "$PSScriptRoot\.."
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices;
public class WinShot {
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint f);
  [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr h, int x, int y, int w, int hh, bool repaint);
  public struct RECT { public int L, T, R, B; }
}
"@
function Find-Win { Get-Process | Where-Object { $_.MainWindowTitle -eq "hw3-$Stage" } | Select-Object -First 1 }

$done = "screenshots\_done_$Stage"
Remove-Item -LiteralPath $done -ErrorAction SilentlyContinue
$script = (Resolve-Path "tools\stage.ps1").Path
Start-Process conhost.exe -ArgumentList "powershell.exe -NoLogo -ExecutionPolicy Bypass -File `"$script`" -Stage $Stage"

# ждем появления окна и сразу растягиваем его
$p = $null; $t0 = Get-Date
while (-not $p -and ((Get-Date) - $t0).TotalSeconds -lt 30) { Start-Sleep -Milliseconds 300; $p = Find-Win }
if (-not $p) { throw "window hw3-$Stage not found" }
[WinShot]::MoveWindow($p.MainWindowHandle, 20, 20, $Width, $Height, $true) | Out-Null

$deadline = (Get-Date).AddMinutes(8)
while (-not (Test-Path $done) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
Start-Sleep -Seconds 2
$p = Find-Win; $h = $p.MainWindowHandle
$r = New-Object WinShot+RECT; [WinShot]::GetWindowRect($h, [ref]$r) | Out-Null
$bmp = New-Object System.Drawing.Bitmap ($r.R - $r.L), ($r.B - $r.T)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$hdc = $g.GetHdc(); [WinShot]::PrintWindow($h, $hdc, 2) | Out-Null; $g.ReleaseHdc($hdc); $g.Dispose()
$bmp.Save((Join-Path (Get-Location) $Out), [System.Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()
Stop-Process -Id $p.Id -Confirm:$false
Remove-Item -LiteralPath $done -ErrorAction SilentlyContinue
"saved $Out ($($r.R - $r.L)x$($r.B - $r.T))"
