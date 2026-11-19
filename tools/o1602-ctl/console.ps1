# Text console for the Open1602 control port: shows what the agent sees, then takes commands.
# Usage: .\tools\o1602-ctl\console.ps1 [-Island 9]
param([int]$Island = 9)

$ctl = Join-Path $PSScriptRoot '..\..\bin\o1602-ctl.exe'

function Show([string]$title, [string[]]$cmd) {
    Write-Host ''
    Write-Host ("=== " + $title + "   (o1602-ctl " + ($cmd -join ' ') + ")") -ForegroundColor Cyan
    & $ctl @cmd
}

Show 'Spielstand' @('state')
Show "Stadt auf Insel $Island" @('cities', "$Island", '0')
Show "Warnungen auf Insel $Island" @('alerts', "$Island")
Show "Karte von Insel $Island" @('map', "$Island")
Show 'Produktion' @('production')

Write-Host ''
Write-Host "Befehle wie der Agent sie schickt, z.B.: help | state | alerts $Island | map $Island | buildings | ships | camera follow on" -ForegroundColor Yellow
Write-Host 'Leere Zeile oder "exit" beendet.' -ForegroundColor Yellow
while ($true) {
    $line = Read-Host 'o1602'
    if ([string]::IsNullOrWhiteSpace($line) -or $line -eq 'exit') { break }
    & $ctl @($line -split '\s+')
}
