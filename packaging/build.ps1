<#
.SYNOPSIS
    Builds RoundScreen.exe with PyInstaller and packs it into
    dist\RoundScreen-Setup-<version>.exe with Inno Setup.

.DESCRIPTION
    Needs Python 3.10+ and Inno Setup 6 (winget install JRSoftware.InnoSetup).
    The installer targets the architecture of the Python used to build it, so
    build with 64-bit x64 Python for the release.

.EXAMPLE
    .\packaging\build.ps1
.EXAMPLE
    .\packaging\build.ps1 -Python C:\Python312\python.exe
#>
param(
    [string]$Python = "python"
)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot
Set-Location $root

function Invoke-Checked {
    $file, $rest = $args
    & $file @rest
    if ($LASTEXITCODE -ne 0) { throw "$file $($rest -join ' ') failed ($LASTEXITCODE)" }
}

$version = [regex]::Match((Get-Content roundscreen\__init__.py -Raw), '__version__ = "([^"]+)"').Groups[1].Value
# The Python build decides the app's architecture (platform.machine() reports
# the host's, even for x64 Python emulated on Windows on ARM).
$machine = (& $Python -c "import sysconfig; print(sysconfig.get_platform())").Trim()
$arch = switch ($machine) {
    "win-arm64" { "arm64" }
    "win-amd64" { "x64compatible" }
    default { throw "Build with 64-bit Python (x64 or ARM64); this one is $machine." }
}
Write-Host "RoundScreen $version for $machine"

Invoke-Checked $Python -m pip install --quiet --disable-pip-version-check -r requirements.txt "pyinstaller>=6.10,<7"
# Built outside the source tree: sync tools such as OneDrive lock files in
# the work folder while PyInstaller rewrites them.
$work = Join-Path ([IO.Path]::GetTempPath()) "RoundScreen-build"
Invoke-Checked $Python -m PyInstaller --noconfirm --clean `
    --distpath "$work\dist" --workpath "$work\work" packaging\RoundScreen.spec

$iscc = @(
    (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source,
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 was not found. Install it with: winget install JRSoftware.InnoSetup" }

Invoke-Checked $iscc /Qp "/DAppVersion=$version" "/DArch=$arch" "/DSourceDir=$work\dist\RoundScreen" "/DOutputDir=$root\dist" packaging\RoundScreen.iss
Get-ChildItem dist -Filter "RoundScreen-Setup-$version*.exe" | ForEach-Object { Write-Host "Built $($_.FullName)" }
