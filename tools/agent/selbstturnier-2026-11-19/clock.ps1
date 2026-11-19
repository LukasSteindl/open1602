# The referee's clock of the self-tournament: starts the game after a reading time, logs every
# player's state once a game minute, pauses at the end time, saves and reads the scores.
param(
    [int]$ReadSeconds = 120,
    [int]$EndSeconds = 1800,   # game time
    [int]$Speed = 2,
    [string]$SaveName = "Selbstturnier-2026-11-19"
)
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ctl = "D:\anno\open1602\bin\o1602-ctl.exe"
$tool = "D:\anno\open1602\bin\o1602-tool.exe"
$log = Join-Path $dir "timeline.log"
$players = @{ 7702 = "Fable"; 7703 = "Opus"; 7704 = "Sonnet"; 7705 = "Haiku" }

function Game-Seconds {
    $first = (& $ctl --port 7701 --timeout 20 state | Select-Object -First 1)
    if ($first -match 'time (\d+):(\d+):(\d+)') { return [int]$Matches[1] * 3600 + [int]$Matches[2] * 60 + [int]$Matches[3] }
    return -1
}

"clock: reading time $ReadSeconds s" | Tee-Object -FilePath $log
Start-Sleep -Seconds $ReadSeconds
for ($i = 0; $i -lt 20; $i++) {
    & $ctl --port 7701 resume | Out-Null
    Start-Sleep -Seconds 2
    if ((& $ctl --port 7701 state | Select-Object -First 1) -match "running") { break }
}
& $ctl --port 7701 speed $Speed | Out-Null
"clock: running at x$Speed, real time $(Get-Date -Format HH:mm:ss)" | Tee-Object -FilePath $log -Append

$next = 60
while ($true) {
    $t = Game-Seconds
    if ($t -ge $EndSeconds) { break }
    if ($t -ge $next) {
        foreach ($port in ($players.Keys | Sort-Object)) {
            $line = (& $ctl --port $port --timeout 20 state | Select-Object -Skip 1 -First 1)
            if ($line -match 'money (-?\d+).*balance (-?\d+); inhabitants (\d+)') {
                "{0,5} {1,-7} inhabitants {2,4} money {3,6} balance {4,5}" -f $t, $players[$port], $Matches[3], $Matches[1], $Matches[2] | Add-Content $log
            }
        }
        $next = $t - ($t % 60) + 60
    }
    Start-Sleep -Milliseconds 1500
}
& $ctl --port 7701 pause | Out-Null
Start-Sleep -Seconds 2
$end = (& $ctl --port 7701 state | Select-Object -First 1)
"clock: paused at $end, real time $(Get-Date -Format HH:mm:ss)" | Tee-Object -FilePath $log -Append
& $ctl --port 7701 save $SaveName | Tee-Object -FilePath $log -Append
$save = Join-Path $env:APPDATA "Open1602\saves\$SaveName.o1602"
& $tool state $save --scores | Tee-Object -FilePath (Join-Path $dir "scores.txt")
