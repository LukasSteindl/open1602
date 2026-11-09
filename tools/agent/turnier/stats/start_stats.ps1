# Starts the tournament's stats panel in a window of its own (http://127.0.0.1:7690/).
# Start it from a normal PowerShell, not from the Terminal panel of the Claude desktop app: that one
# sees a redirected AppData folder and never finds the referee's savegame.
# Usage: .\tools\agent\turnier\stats\start_stats.ps1 [-Port 7690] [-Interval 15]
param(
    [int]$Port = 7690,
    [int]$Interval = 15
)
$ErrorActionPreference = "Stop"
$script = Join-Path $PSScriptRoot "stats_panel.py"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..")).Path
Start-Process -FilePath "powershell.exe" -WorkingDirectory $root -ArgumentList @(
    "-NoExit", "-NoProfile", "-Command",
    "`$Host.UI.RawUI.WindowTitle = 'Turnier-Stats $Port'; python -I `"$script`" --port $Port --interval $Interval")
"stats panel starting on http://127.0.0.1:$Port/"
