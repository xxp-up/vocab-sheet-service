[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path -LiteralPath $projectRoot).Path
$distRoot = Join-Path $projectRoot "dist"
$shareRoot = Join-Path $distRoot "windows-share"
$internalRoot = Join-Path $distRoot "windows-internal"

function Copy-PackageItem {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RelativePath,
        [Parameter(Mandatory = $true)]
        [string]$DestinationRoot
    )

    $sourcePath = Join-Path $projectRoot $RelativePath
    if (-not (Test-Path -LiteralPath $sourcePath)) {
        Write-Warning "Skipped missing item: $RelativePath"
        return
    }

    $destinationPath = Join-Path $DestinationRoot $RelativePath
    $destinationParent = Split-Path -Parent $destinationPath
    if ($destinationParent) {
        New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
    }

    Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Recurse -Force
}

if (Test-Path -LiteralPath $distRoot) {
    Remove-Item -LiteralPath $distRoot -Recurse -Force
}

New-Item -ItemType Directory -Path $shareRoot -Force | Out-Null
New-Item -ItemType Directory -Path $internalRoot -Force | Out-Null

$packageItems = @(
    "app",
    "template",
    "pyproject.toml",
    "setup.ps1",
    "start.ps1",
    "clean-generated.ps1",
    "README.md",
    ".env.example"
)

foreach ($item in $packageItems) {
    Copy-PackageItem -RelativePath $item -DestinationRoot $shareRoot
    Copy-PackageItem -RelativePath $item -DestinationRoot $internalRoot
}

$envPath = Join-Path $projectRoot ".env"
if (Test-Path -LiteralPath $envPath) {
    Copy-PackageItem -RelativePath ".env" -DestinationRoot $internalRoot
}
else {
    Write-Warning ".env was not found. The internal package was created without private configuration."
}

Write-Host "Windows share package: $shareRoot"
Write-Host "Windows internal package: $internalRoot"
Write-Host "Both packages require Python 3.12 to be installed on the target machine."
Write-Host "Run .\setup.ps1 once before .\start.ps1 -NoReload."
