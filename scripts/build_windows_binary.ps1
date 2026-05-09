param(
    [switch]$InstallDeps,
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $RootDir

if (-not $IsWindows -and $PSVersionTable.PSVersion.Major -ge 6) {
    throw "Windows binary builds must run on Windows. PyInstaller does not cross-compile reliably."
}

if ([string]::IsNullOrWhiteSpace($Python)) {
    $pythonCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $Python = "py"
    } else {
        $Python = "python"
    }
}

function Invoke-Python {
    param([string[]]$Arguments)

    if ($Python -eq "py") {
        & py -3 @Arguments
    } else {
        & $Python @Arguments
    }
}

if ($InstallDeps) {
    Invoke-Python -Arguments @("-m", "pip", "install", "-r", "requirements.txt", "-r", "requirements-desktop.txt")
}

Invoke-Python -Arguments @("-m", "PyInstaller", "--clean", "-y", "nixai.spec")

Write-Host "Built $RootDir\dist\nixai.exe"
