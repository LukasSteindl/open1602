# Starts a multiplayer game of two agents on this computer, side by side (README: "Two agents
# against each other"): the host's player "Jev" at control port 7602 (sound from this window), the
# joining player "Claude" at control port 7603 (no sound). The Jev driver is started separately:
#   python -I tools/agent/jev_driver.py --port 7602 --state-dir tools/agent/duel --island 13 --cx 55 --cy 27 --speed 2
# Usage:
#   .\tools\agent\start_duel.ps1                     # a new endless game for two (seed 4711)
#   .\tools\agent\start_duel.ps1 -Load Duell-Test    # a saved game (saves\NAME.o1602) goes on
param(
    [string]$Load = "",
    [int]$Seed = 4711,
    [string]$Size = "940x880"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$exe = Join-Path $root "bin\open1602.exe"
$ctl = Join-Path $root "bin\o1602-ctl.exe"

if ($Load) {
    $save = Join-Path $env:APPDATA "Open1602\saves\$Load.o1602"
    $game = @("--load", "`"$save`"")
} else {
    $game = @("--new-game", "1", "--players", "2", "--seed", "$Seed")
}
$common = @("--size", $Size, "--zoom", "1", "--no-videos")

$env:O1602_AUDIO_DEVICE = "Realtek Digital"
Start-Process -FilePath $exe -WorkingDirectory $root -ArgumentList ($game + @("--name", "Jev", "--host", "--control", "7602") + $common)
Remove-Item Env:O1602_AUDIO_DEVICE

# The host must be listening before the second game joins.
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    & $ctl --port 7602 state *> $null
    if ($LASTEXITCODE -eq 0) { break }
}

# Another player ID than settings.cfg's, else the host gives the joiner its own slot.
$env:O1602_PLAYER_ID = "00000000c1a0de02"
Start-Process -FilePath $exe -WorkingDirectory $root -ArgumentList (@("--join", "127.0.0.1", "--name", "Claude", "--control", "7603", "--no-sound") + $common)
Remove-Item Env:O1602_PLAYER_ID

for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    & $ctl --port 7603 state *> $null
    if ($LASTEXITCODE -eq 0) { break }
}
& $ctl --port 7602 state
& $ctl --port 7603 state
