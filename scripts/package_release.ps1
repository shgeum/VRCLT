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
$PackageName = "vrclt-$VersionName-windows-x64"
$DistApp = Join-Path $Root "dist\vrclt"
$ReleaseDir = Join-Path $Root "release"
$StageDir = Join-Path $ReleaseDir $PackageName
$ZipPath = Join-Path $ReleaseDir "$PackageName.zip"
$ChecksumPath = "$ZipPath.sha256"

if (-not $SkipBuild) {
    $Python = Join-Path $Root ".venv\Scripts\python.exe"
    $PyInstaller = Join-Path $Root ".venv\Scripts\pyinstaller.exe"
    if (-not (Test-Path $Python)) {
        throw "Virtual environment not found: $Python"
    }

    & $Python -m pip install pyinstaller
    if (-not (Test-Path $PyInstaller)) {
        throw "PyInstaller executable not found after install: $PyInstaller"
    }

    & $PyInstaller (Join-Path $Root "vrclt.spec") --noconfirm
}

if (-not (Test-Path (Join-Path $DistApp "vrclt.exe"))) {
    throw "Build output not found. Expected: $(Join-Path $DistApp 'vrclt.exe')"
}

New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
Remove-Item -Recurse -Force $StageDir -ErrorAction SilentlyContinue
Remove-Item -Force $ZipPath, $ChecksumPath -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $StageDir | Out-Null

Copy-Item -Path (Join-Path $DistApp "*") -Destination $StageDir -Recurse -Force -Exclude "config.yaml"
Remove-Item -Force (Join-Path $StageDir "config.yaml") -ErrorAction SilentlyContinue

Copy-Item (Join-Path $Root "config.example.yaml") $StageDir -Force
Copy-Item (Join-Path $Root "README.md") $StageDir -Force
Copy-Item (Join-Path $Root "README.en.md") $StageDir -Force

$StageDocs = Join-Path $StageDir "docs"
New-Item -ItemType Directory -Force -Path $StageDocs | Out-Null
Copy-Item (Join-Path $Root "docs\RELEASING.md") $StageDocs -Force

$GitCommit = "unknown"
try {
    $GitCommit = (& git -C $Root rev-parse --short HEAD 2>$null).Trim()
    if (-not $GitCommit) { $GitCommit = "unknown" }
} catch {
    $GitCommit = "unknown"
}

Set-Content -Path (Join-Path $StageDir "VERSION.txt") -Encoding utf8 -Value @(
    "vrclt $VersionName",
    "commit: $GitCommit",
    "built: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')",
    "",
    "Copy config.example.yaml to config.yaml before running vrclt.exe."
)

Compress-Archive -Path $StageDir -DestinationPath $ZipPath -Force
$Hash = Get-FileHash $ZipPath -Algorithm SHA256
Set-Content -Path $ChecksumPath -Encoding ascii -Value "$($Hash.Hash)  $(Split-Path $ZipPath -Leaf)"

Write-Host "Release package created: $ZipPath"
Write-Host "SHA256 checksum:       $ChecksumPath"
Write-Host "Upload both files to the GitHub Release for $VersionName."
