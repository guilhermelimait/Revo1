$ErrorActionPreference = "Stop"
$project = $PSScriptRoot
# Runs Revo1 from source. Most people should use Revo1-Setup.exe
# from the GitHub releases instead, which needs no Python.
$supported = "3.14", "3.13", "3.12", "3.11", "3.10"
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
    throw "Running from source needs Python 3.10 or newer from python.org. Install it and run this script again."
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
    (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Revo1.lnk"),
    (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\Revo1.lnk")
)
foreach ($path in $locations) {
    $shortcut = $shell.CreateShortcut($path)
    $shortcut.TargetPath = $pythonw
    $shortcut.Arguments = if ($path -like "*\Startup\*") { "-m revo1.app --minimized" } else { "-m revo1.app" }
    $shortcut.WorkingDirectory = $project
    $shortcut.Description = "Revo1 knob controls for volume, scrolling, brightness and media"
    $shortcut.Save()
}
Write-Host "Revo1 installed in the Start Menu and enabled at Windows sign-in."
Write-Host "Settings are stored in $env:LOCALAPPDATA\Revo1\settings.json"
Write-Host "Run it now from the Start Menu; the USB device needs companion firmware."
