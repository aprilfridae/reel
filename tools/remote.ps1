# Run a PowerShell script block on the bot PC over SSH without quoting trouble.
# Usage: .\tools\remote.ps1 'Get-Process | Select -First 3'
# The bot PC's login (user@address) is the first line of tools\botpc.txt, which stays on this PC (it isn't
# published); the SSH key is ~\.ssh\fisher_ed25519 (set the bot PC up for it with setup-ssh.ps1).
param([Parameter(Mandatory)][string]$Script)
$target = (Get-Content (Join-Path $PSScriptRoot "botpc.txt") -TotalCount 1).Trim()
$enc = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($Script))
ssh -i "$env:USERPROFILE\.ssh\fisher_ed25519" -o BatchMode=yes $target "powershell -NoProfile -EncodedCommand $enc"
