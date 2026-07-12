[CmdletBinding()]
param(
    [switch]$Clean,
    [switch]$Installer,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$scriptDir = $PSScriptRoot
$projectRoot = (Resolve-Path (Join-Path $scriptDir "..\..")).Path
$specPath = Join-Path $scriptDir "retrovault.spec"
$distPath = Join-Path $projectRoot "dist"
$workPath = Join-Path $projectRoot "build\pyinstaller"

Push-Location $projectRoot
try {
    & $Python -m PyInstaller --version *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller is not installed. Run: $Python -m pip install pyinstaller"
    }

    $arguments = @(
        "-m", "PyInstaller",
        "--distpath", $distPath,
        "--workpath", $workPath,
        "--noconfirm"
    )
    if ($Clean) {
        $arguments += "--clean"
    }
    $arguments += $specPath

    & $Python @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed with exit code $LASTEXITCODE."
    }

    if ($Installer) {
        $iscc = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
        if (-not $iscc) {
            $defaultIscc = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
            if (Test-Path $defaultIscc) {
                $iscc = Get-Item $defaultIscc
            } else {
                throw "Inno Setup 6 was not found. Install it or add ISCC.exe to PATH."
            }
        }
        & $iscc.Source (Join-Path $scriptDir "setup.iss")
        if ($LASTEXITCODE -ne 0) {
            throw "Inno Setup failed with exit code $LASTEXITCODE."
        }
    }
} finally {
    Pop-Location
}
