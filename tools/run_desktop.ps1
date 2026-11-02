# Runs a Python script of this repo in the signed-in desktop session (where it can see and click the game), on the
# PC it's started on, and prints its output. Programs started from an SSH or agent shell can't see the screen, so this
# goes through a scheduled task.  Usage: .\tools\run_desktop.ps1 tools\dump_screen.py [args] [-Wait 120]
param([Parameter(Mandatory)][string]$Script, [string]$ScriptArgs = "", [int]$Wait = 120)
$dir = Split-Path -Parent $PSScriptRoot
$py = if (Test-Path "$dir\venv312\Scripts\python.exe") { "$dir\venv312\Scripts\python.exe" } else { "python" }
$name = [IO.Path]::GetFileNameWithoutExtension($Script)
$log = "$dir\tools\$name.out"
$task = "Fisher-dev-$name"
$cmd = "cd /d `"$dir`" && `"$py`" -u $Script $ScriptArgs < nul > `"$log`" 2>&1"
$action = New-ScheduledTaskAction -Execute "conhost.exe" -Argument "--headless cmd.exe /c $cmd"
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive
Register-ScheduledTask -TaskName $task -Action $action -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName $task
Start-Sleep 1
for ($i = 0; $i -lt $Wait; $i++) {
    if ((Get-ScheduledTask -TaskName $task).State -ne "Running") { break }
    Start-Sleep 1
}
if ((Get-ScheduledTask -TaskName $task).State -eq "Running") { Write-Host "(still running after $Wait s)" }
Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue
if (Test-Path $log) { Get-Content $log }
