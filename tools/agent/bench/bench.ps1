# A fixed test game for agents: the same world for every run, a clock that starts and ends all runs
# alike, and one line per run in results.csv. Use it to tell whether a change to the skills, the
# control port or an agent's tools helps, with more than one run per variant.
#
#   .\tools\agent\bench\bench.ps1 -Mode start -Runs 6                 # six games alone, paused, ports 7801..7806
#   (start one agent per port with PROMPT.md, then:)
#   .\tools\agent\bench\bench.ps1 -Mode clock -Runs 6 -Labels a,a,a,b,b,b -ReadSeconds 120
#
# The clock waits the reading time, lets every game run at the speed given, and when a game's clock
# reaches the end it reads `state` (residents, money, balance), pauses the game and writes the line.
# A game alone obeys its agent's `pause` and `speed`; the clock notes it when it finds a game paused.
param(
    [Parameter(Mandatory = $true)][ValidateSet("start", "clock", "stop")][string]$Mode,
    [int]$Runs = 3,
    [int]$BasePort = 7801,
    [int]$Seed = 42,
    [int]$Difficulty = 1,
    [int]$Minutes = 30,
    [int]$Speed = 2,
    [int]$ReadSeconds = 120,
    [string[]]$Labels = @(),
    [string]$Results = ""
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$exe = Join-Path $root "bin\open1602.exe"
$ctl = Join-Path $root "bin\o1602-ctl.exe"
$pidFile = Join-Path $PSScriptRoot "bench-pids.txt"
if (-not $Results) { $Results = Join-Path $PSScriptRoot "results.csv" }
$ports = 0..($Runs - 1) | ForEach-Object { $BasePort + $_ }
# -File passes "a,b,c" as one string: split it.
$Labels = @($Labels | ForEach-Object { $_ -split "," } | Where-Object { $_ })

function Game-Seconds([int]$port) {
    $first = (& $ctl --port $port --timeout 20 state | Select-Object -First 1)
    if ($first -match 'time (\d+):(\d+):(\d+)') { return [int]$Matches[1] * 3600 + [int]$Matches[2] * 60 + [int]$Matches[3] }
    return -1
}

if ($Mode -eq "start") {
    $pids = @()
    foreach ($port in $ports) {
        $pids += (Start-Process $exe -WorkingDirectory (Join-Path $root "bin") -PassThru -ArgumentList @(
                "--new-game", "$Difficulty", "--seed", "$Seed", "--name", "Bench$port", "--control", "$port",
                "--no-videos", "--no-sound", "--no-music", "--size", "640x400", "--zoom", "1")).Id
    }
    Set-Content $pidFile ($pids -join " ")
    foreach ($port in $ports) {
        for ($i = 0; $i -lt 120; $i++) { Start-Sleep -Milliseconds 500; & $ctl --port $port state *> $null; if ($LASTEXITCODE -eq 0) { break } }
        "$port : " + (& $ctl --port $port state | Select-Object -First 1)
    }
    "The games stand paused. Start the agents, then run: bench.ps1 -Mode clock -Runs $Runs"
    return
}

if ($Mode -eq "stop") {
    if (Test-Path $pidFile) {
        (Get-Content $pidFile) -split " " | ForEach-Object { Stop-Process -Id ([int]$_) -Force -ErrorAction SilentlyContinue }
        Remove-Item $pidFile
    }
    return
}

# clock
"clock: reading time $ReadSeconds s"
Start-Sleep -Seconds $ReadSeconds
foreach ($port in $ports) { & $ctl --port $port resume | Out-Null; & $ctl --port $port speed $Speed | Out-Null }
"clock: $Runs games running at x$Speed, $(Get-Date -Format HH:mm:ss)"
$end = $Minutes * 60
$open = [System.Collections.Generic.List[int]]::new(); $ports | ForEach-Object { $open.Add($_) }
$paused = @{}
if (-not (Test-Path $Results)) { Set-Content $Results "date,label,port,seed,minutes,speed,residents,inhabitants,money,balance,found_paused" }
while ($open.Count -gt 0) {
    foreach ($port in @($open)) {
        $state = & $ctl --port $port --timeout 20 state
        if (-not $state) { continue }
        if ($state[0] -match ' paused ') { $paused[$port] = 1 + [int]$paused[$port] }
        if ($state[0] -match 'time (\d+):(\d+):(\d+)' -and ([int]$Matches[1] * 3600 + [int]$Matches[2] * 60 + [int]$Matches[3]) -ge $end) {
            & $ctl --port $port pause | Out-Null
            $you = $state[1]
            $label = if ($Labels.Count -gt ($port - $BasePort)) { $Labels[$port - $BasePort] } else { "run" }
            if ($you -match 'money (-?\d+).*balance (-?\d+); inhabitants (\d+), residents (\d+)') {
                $line = "{0},{1},{2},{3},{4},{5},{6},{7},{8},{9},{10}" -f (Get-Date -Format "yyyy-MM-dd HH:mm"), $label, $port, $Seed, $Minutes, $Speed, $Matches[4], $Matches[3], $Matches[1], $Matches[2], [int]$paused[$port]
                Add-Content $Results $line
                "done: $line"
            }
            $open.Remove($port) | Out-Null
        }
    }
    Start-Sleep -Milliseconds 800
}
"clock: all games ended and paused, $(Get-Date -Format HH:mm:ss); results in $Results"
