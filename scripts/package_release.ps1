param(
    [Parameter(Mandatory = $false)]
    [string]$Version = "0.1.0",

    [Parameter(Mandatory = $false)]
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
$VersionName = if ($Version.StartsWith("v")) { $Version } else { "v$Version" }
$ReleaseDir = Join-Path $Root "release"
$DistExe = Join-Path $Root "dist\vrclt.exe"
$ReleaseExe = Join-Path $ReleaseDir "vrclt-$VersionName-windows-x64.exe"
$ChecksumPath = "$ReleaseExe.sha256"

if (-not $SkipBuild) {
    $Python = Join-Path $Root ".venv\Scripts\python.exe"
    if (-not (Test-Path $Python)) {
        throw "Virtual environment not found: $Python"
    }

    & $Python -m pip install pyinstaller
    & $Python -m PyInstaller (Join-Path $Root "vrclt.spec") --noconfirm
}

if (-not (Test-Path $DistExe)) {
    throw "Build output not found. Expected: $DistExe"
}

New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
Remove-Item -Force $ReleaseExe, $ChecksumPath -ErrorAction SilentlyContinue
Copy-Item -Path $DistExe -Destination $ReleaseExe -Force

$Hash = Get-FileHash $ReleaseExe -Algorithm SHA256
Set-Content -Path $ChecksumPath -Encoding ascii -Value "$($Hash.Hash)  $(Split-Path $ReleaseExe -Leaf)"

Write-Host "Release executable created: $ReleaseExe"
Write-Host "SHA256 checksum:            $ChecksumPath"
