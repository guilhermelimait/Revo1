<#
.SYNOPSIS
    Flashes the Revo1 firmware onto a Waveshare ESP32-S3-Knob-Touch-LCD-1.8.

.DESCRIPTION
    Finds the ESP32-S3 port (USB ID 303A:1001), saves a full backup of the
    current 16 MB flash before the first Revo1 flash (so the stock
    firmware can be put back with -Restore), then writes the merged
    Revo1 image at address 0x0.

    Needs no Python: it uses an installed esptool if there is one, and
    otherwise downloads Espressif's standalone esptool once.

.EXAMPLE
    .\scripts\flash-firmware.ps1 -Firmware .\revo1-firmware-1.0.0.bin

.EXAMPLE
    .\scripts\flash-firmware.ps1 -Restore .\backups\flash-backup-COM9.bin
#>
param(
    [string]$Firmware,
    [string]$Port,
    [string]$Restore,
    [switch]$NoBackup
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$root = Split-Path $PSScriptRoot
$EsptoolVersion = "v5.4.0"

function Find-Esptool {
    # Windows PowerShell turns a native command's stderr into a terminating
    # error under "Stop", so probe with errors allowed.
    $ErrorActionPreference = "Continue"
    foreach ($launcher in @(@("py.exe", "-3"), @("python.exe"))) {
        if (Get-Command $launcher[0] -ErrorAction SilentlyContinue) {
            & $launcher[0] @($launcher | Select-Object -Skip 1) -c "import esptool" 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                return ,@($launcher + @("-m", "esptool"))
            }
        }
    }
    $ErrorActionPreference = "Stop"
    $tools = Join-Path $env:LOCALAPPDATA "Revo1\tools\esptool-$EsptoolVersion"
    $exe = Get-ChildItem $tools -Recurse -Filter esptool.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $exe) {
        $url = "https://github.com/espressif/esptool/releases/download/$EsptoolVersion/esptool-$EsptoolVersion-windows-amd64.zip"
        $zip = Join-Path ([IO.Path]::GetTempPath()) "esptool-$EsptoolVersion.zip"
        Write-Host "Downloading esptool $EsptoolVersion (about 65 MB, only once)..."
        Invoke-WebRequest $url -OutFile $zip -UseBasicParsing
        Expand-Archive $zip $tools -Force
        Remove-Item $zip
        $exe = Get-ChildItem $tools -Recurse -Filter esptool.exe | Select-Object -First 1
        if (-not $exe) { throw "esptool.exe was not found in the downloaded archive." }
    }
    # The comma keeps a one-item array from being unrolled into a string.
    return ,@($exe.FullName)
}

function Find-Port {
    $device = Get-CimInstance Win32_PnPEntity -Filter "PNPDeviceID LIKE 'USB\\VID_303A&PID_1001%'" |
        Where-Object { $_.Name -match "\((COM\d+)\)" } | Select-Object -First 1
    if ($device -and $device.Name -match "\((COM\d+)\)") { return $Matches[1] }
    return $null
}

if (-not $Port) {
    $Port = Find-Port
    if (-not $Port) {
        throw ("No ESP32-S3 found (USB ID 303A:1001). The knob's single USB-C socket reaches " +
               "a different chip depending on which way the plug is inserted: turn the plug over and try again.")
    }
}
Write-Host "ESP32-S3 on $Port"

$tool = Find-Esptool
$command = $tool[0]
$base = @($tool | Select-Object -Skip 1) + @("--chip", "esp32s3", "--port", $Port, "--baud", "921600")

function Invoke-Esptool {
    $ErrorActionPreference = "Continue"
    & $command @base @args
    if ($LASTEXITCODE -ne 0) { throw "esptool $($args -join ' ') failed" }
}

# Close the Revo1 app if it is running, since it holds the serial port.
Get-Process Revo1 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.Id }

if ($Restore) {
    if (-not (Test-Path $Restore)) { throw "Backup file not found: $Restore" }
    Invoke-Esptool write-flash 0x0 $Restore
    Write-Host "Original firmware restored."
    return
}

if (-not $Firmware) {
    $Firmware = Get-ChildItem (Join-Path $root "dist") -Filter "revo1-firmware-*.bin" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
    if (-not $Firmware) {
        throw "Pass -Firmware <file>. Download revo1-firmware-<version>.bin from the GitHub Releases page."
    }
}
if (-not (Test-Path $Firmware)) { throw "Firmware file not found: $Firmware" }

if (-not $NoBackup) {
    $backups = Join-Path $root "backups"
    New-Item -ItemType Directory -Force $backups | Out-Null
    $backup = Join-Path $backups "flash-backup-$Port.bin"
    if (Test-Path $backup) {
        Write-Host "Keeping the existing backup $backup"
    } else {
        Write-Host "Backing up the current 16 MB flash to $backup (a few minutes)..."
        Invoke-Esptool read-flash 0x0 0x1000000 $backup
    }
}

Write-Host "Flashing $Firmware..."
Invoke-Esptool write-flash 0x0 $Firmware
Write-Host "Done. The screen restarts; start Revo1 to connect."
