param(
    [Parameter(Mandatory = $false)]
    [string]$Version = "",

    [Parameter(Mandatory = $false)]
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
$VersionSource = Get-Content -LiteralPath (Join-Path $Root "vrclt\__init__.py") -Raw
if ($VersionSource -notmatch '__version__\s*=\s*"([^"]+)"') {
    throw "Could not read the application version."
}
$AppVersion = $Matches[1]
$RequestedVersion = if ([string]::IsNullOrWhiteSpace($Version)) {
    $AppVersion
} else {
    $Version.TrimStart('v')
}
if ($RequestedVersion -ne $AppVersion) {
    throw "Release version $RequestedVersion does not match application version $AppVersion."
}
$VersionName = "v$AppVersion"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$ReleaseDir = Join-Path $Root "release"
$DistExe = Join-Path $Root "dist\vrclt.exe"
$ReleaseExe = Join-Path $ReleaseDir "vrclt-$VersionName-windows-x64.exe"
$ChecksumPath = "$ReleaseExe.sha256"

if (-not $SkipBuild) {
    if (-not (Test-Path $Python)) {
        throw "Virtual environment not found: $Python"
    }

    Push-Location -LiteralPath $Root
    try {
        & $Python -m PyInstaller (Join-Path $Root "vrclt.spec") --noconfirm
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller failed. Existing executables will not be packaged."
        }
    } finally {
        Pop-Location
    }
}

if (-not (Test-Path $DistExe)) {
    throw "Build output not found. Expected: $DistExe"
}

# -SkipBuild must not relabel an executable left over from an older version.
& $Python -c 'import sys; from PyInstaller.archive.readers import CArchiveReader; archive = CArchiveReader(sys.argv[1]).open_embedded_archive("PYZ.pyz"); code = archive.extract("vrclt"); assert sys.argv[2] in code.co_consts, "Packaged application version does not match release version"' $DistExe $AppVersion
if ($LASTEXITCODE -ne 0) {
    throw "The built executable does not match v$AppVersion. Rebuild before packaging."
}

New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
Copy-Item -LiteralPath $DistExe -Destination $ReleaseExe -Force

$Hash = Get-FileHash -LiteralPath $ReleaseExe -Algorithm SHA256
Set-Content -LiteralPath $ChecksumPath -Encoding ascii -Value "$($Hash.Hash)  $(Split-Path $ReleaseExe -Leaf)"

Write-Host "Release executable created: $ReleaseExe"
Write-Host "SHA256 checksum:            $ChecksumPath"
