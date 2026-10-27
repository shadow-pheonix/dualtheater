param(
    [string]$MpvPath = '',
    [string]$PythonPath = '',
    [string]$Device = '',
    [string]$LanAddress = '',
    [switch]$ListDevices,
    [switch]$Diagnostic
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not $PythonPath) {
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python -and $python.Source -notlike '*\WindowsApps\*') { $PythonPath = $python.Source }
    if (-not $PythonPath) {
        $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($launcher) { $PythonPath = (& $launcher.Source -3 -c 'import sys; print(sys.executable)').Trim() }
    }
    if (-not $PythonPath -or -not (Test-Path -LiteralPath $PythonPath)) {
        throw 'Install Python 3.10+ or supply -PythonPath with the full python.exe path.'
    }
}
if (-not $MpvPath) {
    $mpv = Get-Command mpv.exe -ErrorAction SilentlyContinue
    if ($mpv) { $MpvPath = $mpv.Source }
    elseif (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'tools\mpv.exe')) {
        $MpvPath = Join-Path $PSScriptRoot 'tools\mpv.exe'
    } else { $MpvPath = (Read-Host 'Full path to mpv.exe').Trim('"') }
}
if (-not (Test-Path -LiteralPath $MpvPath)) { throw 'mpv.exe was not found. Supply -MpvPath.' }
if ($ListDevices) {
    & $PythonPath -m host.server --mpv $MpvPath --list-devices
    exit $LASTEXITCODE
}
if (-not $Device -and -not $Diagnostic) {
    & $PythonPath -m host.server --mpv $MpvPath --list-devices
    Write-Host 'Copy the wasapi/... name for your HDMI soundbar or receiver, without quotes.'
    $Device = Read-Host 'HDMI device'
    if (-not $Device.StartsWith('wasapi/')) { throw 'An explicit wasapi/... HDMI endpoint is required.' }
}
$launchArgs = @('-m', 'host.server', '--mpv', $MpvPath)
if ($Device) { $launchArgs += @('--device', $Device) }
if ($LanAddress) { $launchArgs += @('--host', $LanAddress) }
if ($Diagnostic) { $launchArgs += '--diagnostic' }
Write-Host 'Experimental beta. Open http://localhost:8764 after startup. Ctrl+C stops playback.'
& $PythonPath @launchArgs
exit $LASTEXITCODE
