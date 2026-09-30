$ErrorActionPreference = "Stop"
$project = $PSScriptRoot
# winsdk (Windows media controls) ships wheels for Python 3.10 to 3.12 only.
$supported = "3.12", "3.11", "3.10"
$python = $null
if (Get-Command py.exe -ErrorAction SilentlyContinue) {
    foreach ($version in $supported) {
        $found = & py.exe "-$version" -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $found) { $python = $found.Trim(); break }
    }
}
if (-not $python) {
    $candidate = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($candidate) {
        $version = & $candidate.Source -c "import sys; print('%d.%d' % sys.version_info[:2])"
        if ($supported -contains $version) { $python = $candidate.Source }
    }
}
if (-not $python) {
    throw "RoundScreen needs Python 3.10, 3.11 or 3.12 (64-bit) from python.org. Install one and run this script again."
}
Write-Host "Using $python"
$pythonw = Join-Path (Split-Path $python) "pythonw.exe"
if (-not (Test-Path $pythonw)) {
    throw "pythonw.exe was not found next to $python"
}

& $python -m pip install -r (Join-Path $project "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Installing Python dependencies failed"
}

$shell = New-Object -ComObject WScript.Shell
$locations = @(
    (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\RoundScreen.lnk"),
    (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\RoundScreen.lnk")
)
foreach ($path in $locations) {
    $shortcut = $shell.CreateShortcut($path)
    $shortcut.TargetPath = $pythonw
    $shortcut.Arguments = "-m roundscreen.app"
    $shortcut.WorkingDirectory = $project
    $shortcut.Description = "RoundScreen knob controls for volume, scrolling, brightness and media"
    $shortcut.Save()
}
Write-Host "RoundScreen installed in the Start Menu and enabled at Windows sign-in."
Write-Host "Settings are stored in $env:LOCALAPPDATA\RoundScreen\settings.json"
Write-Host "Run it now from the Start Menu; the USB device needs companion firmware."
