# Builds the .exe and puts it on the bot PC: stops the bot there, swaps the .exe, starts it again, and shows
# the version its website reports. Usage: .\tools\deploy.ps1   (-NoBuild sends dist\UndergroundBot.exe as it is)
param([switch]$NoBuild)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$target = (Get-Content (Join-Path $PSScriptRoot "botpc.txt") -TotalCount 1).Trim()  # user@address (see remote.ps1)
$key = "$env:USERPROFILE\.ssh\fisher_ed25519"
$remote = Join-Path $PSScriptRoot "remote.ps1"
function On-BotPC($script) {
    # (PowerShell over SSH appends its progress records as CLIXML: only the real output is shown)
    & $remote $script 2>&1 | ForEach-Object { $_ -replace '(?s)#< CLIXML.*', '' } | Where-Object { $_ }
}

if (-not $NoBuild) {
    & .\build_exe.ps1 2>&1 | Select-Object -Last 1  # (PyInstaller's progress is long: only the result)
    $test = & .\dist\UndergroundBot.exe --selftest 2>&1
    $test | Select-Object -Last 3
    if ($LASTEXITCODE) { throw "The self-test failed: not deploying." }
}
Write-Host "Stopping the bot on $target..."
On-BotPC 'Stop-ScheduledTask -TaskName "Fisher-release"; Get-Process UndergroundBot -ErrorAction SilentlyContinue | Stop-Process -Force; Start-Sleep 3'
scp -q -i $key dist\UndergroundBot.exe "${target}:C:/fisher-release/UndergroundBot.exe"
Write-Host "Starting it again..."
On-BotPC 'Remove-Item C:\fisher-release\stop.flag -ErrorAction SilentlyContinue; Start-ScheduledTask -TaskName "Fisher-release"; Start-Sleep 40; "running: " + ((Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8080/api/state).Content | ConvertFrom-Json).version'
