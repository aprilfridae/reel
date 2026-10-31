# Builds dist\UndergroundBot.exe: one file, no Python needed on the PC that runs it.
#   pip install pyinstaller flask dxcam opencv-python numpy comtypes winrt-runtime ...   (once)
#   .\build_exe.ps1
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here
python -m PyInstaller --noconfirm --onefile --name UndergroundBot `
    --distpath dist --workpath build_tmp --specpath build_tmp --paths . `
    --add-data "$here\templates;templates" --add-data "$here\web\index.html;web" `
    $(if (Test-Path "$here\web\static\logo.png") { "--add-data"; "$here\web\static\logo.png;web\static" }) `
    --collect-submodules winrt --collect-all dxcam --hidden-import comtypes `
    --hidden-import bot --hidden-import web.app main.py
Get-Item dist\UndergroundBot.exe | Select-Object Name, Length
