# Decrypts the Vita dump (game, update and DLC) with psvpfsparser.
# The key is read from the game's NoNpDRM work.bin at offset 0x50. The update (patch/) has no
# work.bin of its own and uses the game's key. Each DLC uses its own work.bin.
#
# Usage (from the project root):
#   powershell -ExecutionPolicy Bypass -File scripts\decrypt_vita.ps1 -Parser "C:\path\to\psvpfsparser.exe"
#
# psvpfsparser: https://github.com/motoharu-gosuto/psvpfstools/releases (release_win64_7.zip)
# The tool contacts the F00D key service (cma.henkaku.xyz), so this needs internet access.

param(
    [Parameter(Mandatory = $true)][string]$Parser,
    [string]$Source  = "dump",
    [string]$Dest    = "decrypted",
    [string]$TitleId = "PCSG00675",
    [string]$F00d    = "cma.henkaku.xyz"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Get-Klicensee([string]$workBin) {
    $b = [IO.File]::ReadAllBytes($workBin)
    $magic = -join ($b[8..15] | ForEach-Object { $_.ToString("x2") })
    if ($magic -ne "efcdab8967452301") { throw "$workBin is not a NoNpDRM fake license" }
    return -join ($b[0x50..0x5F] | ForEach-Object { $_.ToString("x2") })
}

$appDir = Join-Path $root "$Source\app\$TitleId"
$gameKey = Get-Klicensee (Join-Path $appDir "sce_sys\package\work.bin")

$targets = @(@{ In = $appDir; Rel = "app\$TitleId"; Key = $gameKey })
$patchDir = Join-Path $root "$Source\patch\$TitleId"
if (Test-Path $patchDir) { $targets += @{ In = $patchDir; Rel = "patch\$TitleId"; Key = $gameKey } }
$dlcRoot = Join-Path $root "$Source\addcont\$TitleId"
if (Test-Path $dlcRoot) {
    Get-ChildItem $dlcRoot -Directory | ForEach-Object {
        $targets += @{ In = $_.FullName; Rel = "addcont\$TitleId\$($_.Name)"; Key = (Get-Klicensee (Join-Path $_.FullName "sce_sys\package\work.bin")) }
    }
}

$failed = @()
foreach ($t in $targets) {
    $out = Join-Path $root "$Dest\$($t.Rel)"
    New-Item -ItemType Directory -Force $out | Out-Null
    Write-Host "== $($t.Rel)  (key $($t.Key))"
    & $Parser -i $t.In -o $out -k $t.Key -f $F00d
    if ($LASTEXITCODE -ne 0) { $failed += $t.Rel; Write-Warning "FAILED: $($t.Rel)" }
}

Write-Host ""
if ($failed.Count) { Write-Warning "Failed: $($failed -join ', ')" } else { Write-Host "All done -> $Dest" }
