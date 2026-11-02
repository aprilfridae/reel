# Builds dist\UndergroundBot.exe: one file, no Python needed on the PC that runs it.
#   pip install -r requirements.txt   (once)
#   .\build_exe.ps1
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here
# venv312 (Python 3.12 + numpy 1.26) runs on older / weaker PCs than the newest numpy does
$py = if (Test-Path "$here\venv312\Scripts\python.exe") { "$here\venv312\Scripts\python.exe" } else { "python" }
& $py -m PyInstaller --noconfirm --onefile --name UndergroundBot `
    --distpath dist --workpath build_tmp --specpath build_tmp --paths . `
    --add-data "$here\web\index.html;web" `
    $(if (Test-Path "$here\web\static\logo.png") { "--add-data"; "$here\web\static\logo.png;web\static" }) `
    --collect-data tzdata --hidden-import comtypes `
    --hidden-import bot --hidden-import web.app main.py
Get-Item dist\UndergroundBot.exe | Select-Object Name, Length
