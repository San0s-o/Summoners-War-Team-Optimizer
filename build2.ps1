[CmdletBinding()]
param(
    [string]$ConfigPath = ".\license_config.json",
    [string]$AppId = "",
    [string]$AppVersion = "",
    [string]$IsccPath = "",
    [switch]$SkipClean,
    [switch]$SkipInstaller
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-ProjectPath {
    param([Parameter(Mandatory = $true)][string]$RelativeOrAbsolutePath)
    if ([System.IO.Path]::IsPathRooted($RelativeOrAbsolutePath)) {
        return $RelativeOrAbsolutePath
    }
    return Join-Path $PSScriptRoot $RelativeOrAbsolutePath
}

function Get-ConfigValue {
    param(
        [Parameter(Mandatory = $true)]$ConfigObject,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $value = ""
    if ($null -ne $ConfigObject.PSObject.Properties[$Name]) {
        $value = [string]$ConfigObject.$Name
    }
    return $value.Trim()
}

# ── Konfiguration laden ──────────────────────────────────────────────────────
$resolvedConfigPath = Resolve-ProjectPath -RelativeOrAbsolutePath $ConfigPath
$config = $null
if (Test-Path -LiteralPath $resolvedConfigPath) {
    $config = Get-Content -LiteralPath $resolvedConfigPath -Raw | ConvertFrom-Json
}

if ([string]::IsNullOrWhiteSpace($AppId) -and $null -ne $config) {
    $AppId = Get-ConfigValue -ConfigObject $config -Name "app_id"
}
if ([string]::IsNullOrWhiteSpace($AppVersion) -and $null -ne $config) {
    $AppVersion = Get-ConfigValue -ConfigObject $config -Name "app_version"
}

if ([string]::IsNullOrWhiteSpace($AppId)) {
    throw "appId ist leer. Setze -AppId oder trage app_id in $resolvedConfigPath ein."
}
if ([string]::IsNullOrWhiteSpace($AppVersion)) {
    throw "appVersion ist leer. Setze -AppVersion oder trage app_version in $resolvedConfigPath ein."
}

$pythonExe = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Python nicht gefunden: $pythonExe"
}

# ── Inno Setup ISCC suchen ───────────────────────────────────────────────────
if (-not $SkipInstaller) {
    if ([string]::IsNullOrWhiteSpace($IsccPath)) {
        $candidates = @(
            "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
            "C:\Program Files\Inno Setup 6\ISCC.exe"
        )
        foreach ($c in $candidates) {
            if (Test-Path -LiteralPath $c) { $IsccPath = $c; break }
        }
    }
    if ([string]::IsNullOrWhiteSpace($IsccPath) -or -not (Test-Path -LiteralPath $IsccPath)) {
        throw "Inno Setup (ISCC.exe) nicht gefunden. Inno Setup 6 installieren oder -IsccPath angeben."
    }
}

# ── Alte Artefakte entfernen ─────────────────────────────────────────────────
$buildTargetPath = Join-Path $PSScriptRoot ("build\" + $AppId)
$distTargetPath  = Join-Path $PSScriptRoot ("dist\"  + $AppId)

if (-not $SkipClean) {
    Remove-Item -LiteralPath $buildTargetPath -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $distTargetPath  -Recurse -Force -ErrorAction SilentlyContinue
}

# ── PyInstaller ──────────────────────────────────────────────────────────────
$pyInstallerArgs = @(
    ".\app\__main__.py",
    "--onedir",
    "--noconsole",
    "--clean",
    "--name",        $AppId,
    "--icon",        "app/assets/app_icon.ico",
    "--add-data",    "app/assets;app/assets",
    "--add-data",    "app/config/artifact_scoring.json;app/config",
    "--add-data",    "app/config/monster_rune_set_preferences.json;app/config",
    "--add-data",    "app/config/monster_artifact_preferences.json;app/config",
    "--add-data",    "Datenschutz_de.txt;.",
    "--add-data",    "Datenschutz_en.txt;.",
    "--exclude-module", "torch",
    "--exclude-module", "torchvision",
    "--exclude-module", "torchaudio"
)

Push-Location $PSScriptRoot
try {
    & $pythonExe -m PyInstaller @pyInstallerArgs
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller ist mit ExitCode $LASTEXITCODE fehlgeschlagen."
    }
}
finally {
    Pop-Location
}

# ── license_config.json nach _internal kopieren ──────────────────────────────
$internalDir = Join-Path $distTargetPath "_internal"
New-Item -ItemType Directory -Path $internalDir -Force | Out-Null

if (Test-Path -LiteralPath $resolvedConfigPath) {
    Copy-Item -LiteralPath $resolvedConfigPath -Destination (Join-Path $internalDir "license_config.json") -Force
}
else {
    Write-Warning "Konfigurationsdatei nicht gefunden: $resolvedConfigPath (Copy nach _internal uebersprungen)."
}

# ── Inno Setup – Installer bauen ─────────────────────────────────────────────
if (-not $SkipInstaller) {
    $issPath = Join-Path $PSScriptRoot "installer.iss"
    if (-not (Test-Path -LiteralPath $issPath)) {
        throw "installer.iss nicht gefunden: $issPath"
    }

    Write-Host "Erstelle Installer mit Inno Setup..."
    & $IsccPath /DAppVersion="$AppVersion" /DAppId="$AppId" $issPath
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup ist mit ExitCode $LASTEXITCODE fehlgeschlagen."
    }

    $setupExe = Join-Path $PSScriptRoot "dist\${AppId}-Setup-${AppVersion}.exe"
    if (Test-Path -LiteralPath $setupExe) {
        Write-Host "Installer: $setupExe"
    }
}

"Built: $AppId $AppVersion"
"Tag fuer Release: v$AppVersion"
