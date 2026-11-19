# Starts the four-agent tournament: one multiplayer endless game, five slots.
#   7601  Referee   the host; nobody plays its slot, only the operator sets pause/speed here
#   7602  Claude    agent 1: Claude Opus alone
#   7603  ClaudeJev agent 2: Claude Opus as coach of a Jev driver
#   7604  Sol       agent 3: ChatGPT Sol alone
#   7605  SolJev    agent 4: ChatGPT Sol as coach of a Jev driver
# The agents' control ports refuse pause/resume/speed/autoplay (O1602_CONTROL_NO_SPEED); each agent
# joins with its own player ID, so it always gets its own slot back. The game stands paused until all
# four are in, so no computer plays a vacant slot meanwhile.
# Usage: .\tools\agent\turnier\start_turnier.ps1 [-Load NAME] [-Seed 1602] [-Speed 2]
param(
    [string]$Load = "",
    [int]$Seed = 1602,
    [int]$Speed = 2,
    [switch]$Run  # resume at once (default: paused until the operator resumes on port 7601)
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$exe = Join-Path $root "bin\open1602.exe"
$ctl = Join-Path $root "bin\o1602-ctl.exe"

function Wait-Port([int]$port) {
    for ($i = 0; $i -lt 120; $i++) {
        Start-Sleep -Milliseconds 500
        & $ctl --port $port state *> $null
        if ($LASTEXITCODE -eq 0) { return }
    }
    throw "no game answers on port $port"
}

if ($Load) {
    $save = Join-Path $env:APPDATA "Open1602\saves\$Load.o1602"
    $game = @("--load", "`"$save`"")
} else {
    $game = @("--new-game", "1", "--players", "5", "--seed", "$Seed")
}
Start-Process -FilePath $exe -WorkingDirectory $root -ArgumentList ($game + @(
    "--name", "Referee", "--host", "--control", "7601", "--size", "640x360", "--zoom", "1", "--no-videos", "--no-sound"))
Wait-Port 7601
& $ctl --port 7601 pause | Out-Null

$agents = @(
    @{ Port = 7602; Name = "Claude";    Id = "00000000a9e70001"; Sound = $true },
    @{ Port = 7603; Name = "ClaudeJev"; Id = "00000000a9e70002"; Sound = $false },
    @{ Port = 7604; Name = "Sol";       Id = "00000000a9e70003"; Sound = $false },
    @{ Port = 7605; Name = "SolJev";    Id = "00000000a9e70004"; Sound = $false }
)
foreach ($a in $agents) {
    $env:O1602_PLAYER_ID = $a.Id
    $env:O1602_CONTROL_NO_SPEED = "1"
    $args = @("--join", "127.0.0.1", "--name", $a.Name, "--control", "$($a.Port)", "--size", "960x540", "--zoom", "1", "--no-videos")
    if ($a.Sound) { $env:O1602_AUDIO_DEVICE = "Realtek Digital" } else { $args += "--no-sound" }
    Start-Process -FilePath $exe -WorkingDirectory $root -ArgumentList $args
    Remove-Item Env:O1602_AUDIO_DEVICE -ErrorAction SilentlyContinue
    Remove-Item Env:O1602_PLAYER_ID, Env:O1602_CONTROL_NO_SPEED
    Wait-Port $a.Port
}

foreach ($a in $agents) {
    $first = (& $ctl --port $a.Port state | Select-Object -Skip 1 -First 1)
    "$($a.Port): $first"
}
if ($Run) {
    # The last one in may still be loading the game: resume until the game runs.
    for ($i = 0; $i -lt 20; $i++) {
        & $ctl --port 7601 resume | Out-Null
        Start-Sleep -Seconds 2
        if ((& $ctl --port 7601 state | Select-Object -First 1) -match "running") { break }
    }
    & $ctl --port 7601 speed $Speed | Out-Null  # after the resume: a pause order would set it back
} else {
    "The game stands paused. Once all four agents are started: $ctl --port 7601 resume ; then: speed $Speed"
}
