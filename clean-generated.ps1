[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$IncludeRuntimeBootstrap
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path -LiteralPath $projectRoot).Path
$runtimeRoot = Join-Path $projectRoot ".runtime"
$projectRootWithSlash = $projectRoot.TrimEnd("\") + "\"
$targets = New-Object System.Collections.Generic.List[string]

function Add-Target {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    $resolved = (Resolve-Path -LiteralPath $Path).Path
    if (-not $resolved.StartsWith($projectRootWithSlash, [System.StringComparison]::OrdinalIgnoreCase) -and $resolved -ne $projectRoot) {
        throw "Refusing to remove a path outside the project root: $resolved"
    }

    if (-not $targets.Contains($resolved)) {
        $targets.Add($resolved)
    }
}

foreach ($fixedPath in @(
    (Join-Path $projectRoot ".pytest_cache"),
    (Join-Path $projectRoot "dist"),
    (Join-Path $projectRoot "vocab_sheet_service.egg-info"),
    (Join-Path $runtimeRoot "logs")
)) {
    Add-Target -Path $fixedPath
}

if (Test-Path -LiteralPath $runtimeRoot) {
    Get-ChildItem -LiteralPath $runtimeRoot -Force -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "test-*" } |
        ForEach-Object { Add-Target -Path $_.FullName }
}

if ($IncludeRuntimeBootstrap) {
    Add-Target -Path (Join-Path $runtimeRoot "bootstrap")
}

Get-ChildItem -LiteralPath $projectRoot -Force -ErrorAction SilentlyContinue |
    Where-Object {
        $_.PSIsContainer -and (
            $_.Name -like "pytest-cache-files-*" -or
            $_.Name -like "tmp*" -or
            $_.Name -like "*.egg-info"
        )
    } |
    ForEach-Object { Add-Target -Path $_.FullName }

foreach ($scanRoot in @(
    (Join-Path $projectRoot "app"),
    (Join-Path $projectRoot "tests")
)) {
    if (Test-Path -LiteralPath $scanRoot) {
        Get-ChildItem -LiteralPath $scanRoot -Directory -Recurse -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -eq "__pycache__" } |
            ForEach-Object { Add-Target -Path $_.FullName }
    }
}

$orderedTargets = $targets | Sort-Object Length -Descending
if (-not $orderedTargets) {
    Write-Host "No generated files or directories were found."
    exit 0
}

foreach ($target in $orderedTargets) {
    if ($PSCmdlet.ShouldProcess($target, "Remove generated path")) {
        Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path -LiteralPath $target) {
            Write-Warning "Could not fully remove: $target"
        }
        else {
            Write-Host "Removed: $target"
        }
    }
}
