[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$LegacyPython,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$LegacyArguments
)

$ErrorActionPreference = "Stop"
$SkillDir = Split-Path -Parent $PSScriptRoot
$PythonVersion = "3.12.6"
$UvVersion = "0.12.11"
$RuntimeDir = if ($env:CTRIP_RUNTIME_DIR) { $env:CTRIP_RUNTIME_DIR } else { Join-Path $SkillDir ".runtime" }
$VenvDir = if ($env:CTRIP_VENV_DIR) { $env:CTRIP_VENV_DIR } else { Join-Path $SkillDir ".venv" }
$UvBinDir = Join-Path $RuntimeDir "bin"
$LocalUvBin = Join-Path $UvBinDir "uv.exe"
$UvBin = if ($env:CTRIP_UV_BIN) { $env:CTRIP_UV_BIN } else { $LocalUvBin }
$PythonInstallDir = Join-Path $RuntimeDir "python"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$UvCacheDir = if ($env:CTRIP_UV_CACHE_DIR) { $env:CTRIP_UV_CACHE_DIR } else { Join-Path $RuntimeDir "uv-cache" }
$CloakCacheDir = if ($env:CTRIP_CLOAK_CACHE_DIR) { $env:CTRIP_CLOAK_CACHE_DIR } else { Join-Path $RuntimeDir "cloakbrowser" }
$LockFile = Join-Path $SkillDir "requirements-cloak.lock"
$PreflightScript = Join-Path $SkillDir "scripts\verify_ctrip_hotel_environment.py"
$CurrentStage = "initialization"

function Invoke-CheckedCommand {
    param([string]$FilePath, [string[]]$Arguments)

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE: $FilePath $($Arguments -join ' ')"
    }
}

if ($DryRun) {
    Write-Host "Installation preview (no files will be changed)"
    Write-Host "- Local uv: $UvBin"
    Write-Host "- Local Python 3.12: $(Join-Path $PythonInstallDir $PythonVersion)"
    Write-Host "- Local virtual environment: $VenvDir"
    Write-Host "- Locked dependencies: $LockFile"
    Write-Host "- CloakBrowser runtime: $CloakCacheDir"
    exit 0
}

if ($LegacyPython) {
    $PythonBin = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { "py" }
    Invoke-CheckedCommand $PythonBin (@((Join-Path $SkillDir "scripts\bootstrap_ctrip_hotel_skill.py")) + $LegacyArguments)
    exit 0
}

try {
    New-Item -ItemType Directory -Force -Path $RuntimeDir, $UvCacheDir, $CloakCacheDir | Out-Null
    $env:UV_PYTHON_INSTALL_DIR = $PythonInstallDir
    $env:UV_CACHE_DIR = $UvCacheDir
    $env:CLOAKBROWSER_CACHE_DIR = $CloakCacheDir
    if (-not $env:CLOAKBROWSER_AUTO_UPDATE) {
        $env:CLOAKBROWSER_AUTO_UPDATE = "false"
    }

    if (-not (Test-Path -Path $UvBin -PathType Leaf)) {
        $CurrentStage = "downloading local uv runtime"
        Write-Host "[1/4] Downloading local runtime manager"
        New-Item -ItemType Directory -Force -Path $UvBinDir | Out-Null
        $Installer = Join-Path ([System.IO.Path]::GetTempPath()) ("ctrip-uv-installer-" + [guid]::NewGuid().ToString() + ".ps1")
        try {
            $DownloadParameters = @{ Uri = "https://astral.sh/uv/$UvVersion/install.ps1"; OutFile = $Installer }
            if ($PSVersionTable.PSVersion.Major -lt 6) {
                $DownloadParameters.UseBasicParsing = $true
            }
            Invoke-WebRequest @DownloadParameters
            $env:UV_UNMANAGED_INSTALL = $UvBinDir
            $env:UV_NO_MODIFY_PATH = "1"
            & $Installer
            if ($LASTEXITCODE -ne 0) {
                throw "uv installer failed with exit code $LASTEXITCODE"
            }
        }
        finally {
            Remove-Item -Force -ErrorAction SilentlyContinue $Installer
        }
        if (-not (Test-Path -Path $LocalUvBin -PathType Leaf)) {
            throw "Local uv executable was not created: $LocalUvBin"
        }
        $UvBin = $LocalUvBin
    }

    $CurrentStage = "installing local Python $PythonVersion"
Write-Host "[2/4] Installing local Python $PythonVersion"
    Invoke-CheckedCommand $UvBin @("python", "install", "--no-bin", $PythonVersion)

    $CurrentStage = "creating and syncing virtual environment"
    Write-Host "[3/4] Creating virtual environment and installing locked dependencies"
    Invoke-CheckedCommand $UvBin @("venv", "--clear", "--managed-python", "--python", $PythonVersion, $VenvDir)
    if (-not (Test-Path -Path $VenvPython -PathType Leaf)) {
        throw "Virtual environment Python was not created: $VenvPython"
    }
    Invoke-CheckedCommand $UvBin @("pip", "sync", "--strict", "--require-hashes", "--python", $VenvPython, $LockFile)

    $CurrentStage = "validating CloakBrowser runtime"
    Write-Host "[4/4] Downloading and validating CloakBrowser runtime"
    Invoke-CheckedCommand $VenvPython @($PreflightScript, "--skill-dir", $SkillDir, "--cache-dir", $CloakCacheDir)

    Write-Host ""
    Write-Host "Deployment complete. Run collection with:"
    Write-Host "$VenvPython $SkillDir\scripts\ctrip_cli.py collect --config <absolute-config-path>"
}
catch {
    Write-Error "Installation did not complete during $CurrentStage."
    Write-Error "Confirm access to PyPI, Astral, and CloakBrowser download services; confirm the skill directory is writable and at least 2 GB is free."
    Write-Error $_
    exit 1
}
