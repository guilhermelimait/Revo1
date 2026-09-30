<#
.SYNOPSIS
    Flashes the RoundScreen firmware onto a Waveshare ESP32-S3-Knob-Touch-LCD-1.8.

.DESCRIPTION
    Finds the ESP32-S3 port (USB ID 303A:1001), saves a full backup of the
    current 16 MB flash before the first RoundScreen flash (so the stock
    firmware can be put back with -Restore),
    then writes the merged RoundScreen image at address 0x0.

.EXAMPLE
    .\scripts\flash-firmware.ps1 -Firmware .\roundscreen-firmware-1.0.0.bin

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
$root = Split-Path $PSScriptRoot

$python = (Get-Command py.exe -ErrorAction SilentlyContinue).Source
$pythonArgs = @("-3")
if (-not $python) {
    $python = (Get-Command python.exe -ErrorAction Stop).Source
    $pythonArgs = @()
}

function Invoke-Python {
    & $python @pythonArgs @args
    if ($LASTEXITCODE -ne 0) { throw "python $($args -join ' ') failed" }
}

Write-Host "Installing esptool..."
Invoke-Python -m pip install --quiet --user "esptool>=5,<6"

if (-not $Port) {
    $detect = "import serial.tools.list_ports as p; print(next((x.device for x in p.comports() if (x.vid, x.pid) == (0x303A, 0x1001)), ''))"
    $Port = "$(& $python @pythonArgs -c $detect)".Trim()
    if (-not $Port) {
        throw ("No ESP32-S3 found (USB ID 303A:1001). The knob's single USB-C socket reaches " +
               "a different chip depending on which way the plug is inserted: flip the plug and try again.")
    }
}
Write-Host "ESP32-S3 on $Port"

$esptool = @("-m", "esptool", "--chip", "esp32s3", "--port", $Port, "--baud", "921600")

if ($Restore) {
    if (-not (Test-Path $Restore)) { throw "Backup file not found: $Restore" }
    Invoke-Python @esptool write-flash 0x0 $Restore
    Write-Host "Original firmware restored."
    return
}

if (-not $Firmware) {
    $Firmware = Get-ChildItem (Join-Path $root "dist") -Filter "roundscreen-firmware-*.bin" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
    if (-not $Firmware) {
        throw "Pass -Firmware <file>. Download roundscreen-firmware-<version>.bin from the GitHub Releases page."
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
        Invoke-Python @esptool read-flash 0x0 0x1000000 $backup
    }
}

Write-Host "Flashing $Firmware..."
Invoke-Python @esptool write-flash 0x0 $Firmware
Write-Host "Done. The screen restarts; start the RoundScreen app to connect."
