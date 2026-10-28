param([string]$Gradle = '', [string]$Sdk = "$env:LOCALAPPDATA\Android\Sdk")
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:ANDROID_HOME = $Sdk
if (-not $env:JAVA_HOME) {
    $studioJdk = Join-Path $env:ProgramFiles 'Android\Android Studio\jbr'
    if (Test-Path -LiteralPath $studioJdk) { $env:JAVA_HOME = $studioJdk }
    else { throw 'Set JAVA_HOME to a JDK 17 or JDK 21 installation.' }
}
if (-not $Gradle) { $Gradle = Join-Path $PSScriptRoot 'android\gradlew.bat' }
& $Gradle --project-dir android :calibration:assembleDebug --console=plain
if ($LASTEXITCODE -ne 0) { throw 'Calibration client build failed' }
Copy-Item -LiteralPath android\calibration\build\outputs\apk\debug\calibration-debug.apk -Destination DualTheater-Calibration-debug.apk -Force
Write-Host 'Built phone preview APK: DualTheater-Calibration-debug.apk'
