# Baut das fertige Windows-Paket: release\RORM-Online\ (+ Zip)
#   RORM Online.exe (Launcher), server\RORM-Server.exe, melonDS\, mod\net.elf, LICENSE, Lies-mich
# Voraussetzung: Python 3.11+ und Internet (Pakete + melonDS-Download)
param([string]$Version = "1.0.0-beta1")
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot; $repo = Split-Path $here -Parent
Set-Location $here
function Run($exe, [string[]]$a) { & $exe @a; if ($LASTEXITCODE -ne 0) { throw "$exe $($a -join ' ') fehlgeschlagen ($LASTEXITCODE)" } }

$py = "python"
Run $py @("-c", "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)")
if (-not (Test-Path ".venv")) { Run $py @("-m", "venv", ".venv") }
$vpy = Join-Path $here ".venv\Scripts\python.exe"
Run $vpy @("-m", "pip", "install", "--upgrade", "pip", "-q")
Run $vpy @("-m", "pip", "install", "-q", "pywebview", "pyinstaller", "pysdl2", "pysdl2-dll")

# Launcher (Ordner-Build: weniger Fehlalarme von Virenscannern als eine Einzeldatei)
Run $vpy @("-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", "RORM Online",
    "--icon", "assets\icon.ico", "--add-data", "ui;ui", "--add-data", "assets\melonDS.default.toml;assets",
    "--add-data", "core\patch_rom.py;core", "--add-data", "core\blzlib.py;core", "--collect-all", "sdl2dll",
    "--distpath", "dist", "--workpath", "build", "main.py")
# Server (ebenfalls Ordner-Build, eigener Unterordner)
Run $vpy @("-m", "PyInstaller", "--noconfirm", "--clean", "--console", "--name", "RORM-Server",
    "--icon", "assets\icon.ico", "--distpath", "dist", "--workpath", "build", (Join-Path $repo "server\server.py"))

& (Join-Path $here "get_melonds.ps1")

$out = Join-Path $here "release\RORM-Online"
if (Test-Path (Join-Path $here "release")) { Remove-Item -Recurse -Force (Join-Path $here "release") }
New-Item -ItemType Directory -Force -Path $out | Out-Null
Copy-Item -Recurse -Force "dist\RORM Online\*" $out
New-Item -ItemType Directory -Force -Path (Join-Path $out "server"), (Join-Path $out "mod"), (Join-Path $out "melonDS") | Out-Null
Copy-Item -Recurse -Force "dist\RORM-Server\*" (Join-Path $out "server")
Copy-Item -Force (Join-Path $repo "patch\net.elf") (Join-Path $out "mod")
Copy-Item -Recurse -Force "melonDS\*" (Join-Path $out "melonDS") -Exclude "melonDS.toml", "*.sav", "*.ml*"
Copy-Item -Force (Join-Path $repo "LICENSE") (Join-Path $out "LICENSE.txt")
Copy-Item -Force (Join-Path $here "release_readme.txt") (Join-Path $out "README.txt")
Set-Content -Path (Join-Path $out "VERSION.txt") -Value $Version
$zip = Join-Path $here "release\RORM-Online-$Version-windows.zip"
Compress-Archive -Path $out -DestinationPath $zip -Force
Write-Host ""
Write-Host "Fertig: $out"
Write-Host "       $zip"
