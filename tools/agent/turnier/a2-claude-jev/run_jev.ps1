# Runs this agent's Jev driver (its own copy in this folder) and starts it again whenever it ends:
# after the coach changed jev_driver.py or strategy.py (the driver ends itself, code 3), or after a
# crash. Everything it prints also goes to state\driver.log, where the coach reads it.
# Usage (in this agent's folder): .\run_jev.ps1 -Port 7603
param([Parameter(Mandatory = $true)][int]$Port)
$here = $PSScriptRoot
$root = (Resolve-Path (Join-Path $here "..\..\..\..")).Path
$env:O1602_CTL = Join-Path $root "bin\o1602-ctl.exe"
$env:O1602_PLANNER = Join-Path $here "planner"
$env:PYTHONIOENCODING = "utf-8"
New-Item -ItemType Directory -Force (Join-Path $here "state") | Out-Null
$log = Join-Path $here "state\driver.log"
while ($true) {
    "=== driver start $(Get-Date -Format s)" | Tee-Object -FilePath $log -Append
    python -I (Join-Path $here "jev_driver.py") --port $Port --state-dir (Join-Path $here "state") `
        --island auto --speed 2 --interval 3 --restart-on-change 2>&1 | Tee-Object -FilePath $log -Append
    "=== driver ended (exit $LASTEXITCODE) $(Get-Date -Format s); again in 5 s" | Tee-Object -FilePath $log -Append
    Start-Sleep -Seconds 5
}
