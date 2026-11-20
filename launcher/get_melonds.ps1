# Lädt die offizielle melonDS-Version (Windows, x86_64) von GitHub nach launcher\melonDS\
# Aufruf: powershell -NoProfile -ExecutionPolicy Bypass -File get_melonds.ps1 [-Target <Ordner>] [-Tag 1.1]
param([string]$Target = (Join-Path $PSScriptRoot "melonDS"), [string]$Tag = "1.1")
$ErrorActionPreference = "Stop"
if (Test-Path (Join-Path $Target "melonDS.exe")) { Write-Host "melonDS ist schon da: $Target"; exit 0 }
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$headers = @{ "User-Agent" = "cars-ror-online" }
if ($env:GITHUB_TOKEN) { $headers["Authorization"] = "Bearer $env:GITHUB_TOKEN" }
$rel = Invoke-RestMethod -Headers $headers "https://api.github.com/repos/melonDS-emu/melonDS/releases/tags/$Tag"
$assets = $rel.assets | Where-Object { $_.name -match "win" -and $_.name -match "\.zip$" }
$asset = ($assets | Where-Object { $_.name -match "x86_64|x64|amd64" } | Select-Object -First 1)
if (-not $asset) { $asset = $assets | Select-Object -First 1 }
if (-not $asset) { throw "Kein Windows-Download in melonDS $Tag gefunden: $($rel.assets.name -join ', ')" }
Write-Host "Lade $($asset.name) ..."
$tmp = Join-Path ([IO.Path]::GetTempPath()) ("melonds_" + [Guid]::NewGuid())
New-Item -ItemType Directory -Path $tmp | Out-Null
$zip = Join-Path $tmp $asset.name
Invoke-WebRequest -Headers $headers -Uri $asset.browser_download_url -OutFile $zip
Expand-Archive -Path $zip -DestinationPath (Join-Path $tmp "x") -Force
$exe = Get-ChildItem -Path (Join-Path $tmp "x") -Recurse -Filter "melonDS.exe" | Select-Object -First 1
if (-not $exe) { throw "melonDS.exe nicht im Archiv gefunden" }
New-Item -ItemType Directory -Force -Path $Target | Out-Null
Copy-Item -Path (Join-Path $exe.DirectoryName "*") -Destination $Target -Recurse -Force
Remove-Item -Recurse -Force $tmp
Write-Host "melonDS $Tag -> $Target"
