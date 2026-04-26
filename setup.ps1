param(
    [switch]$Dev
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path -LiteralPath $projectRoot).Path
$projectRootWithSlash = $projectRoot.TrimEnd("\") + "\"
$venvRoot = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venvRoot "Scripts\python.exe"
$envFile = Join-Path $projectRoot ".env"
$envExample = Join-Path $projectRoot ".env.example"
$pyprojectPath = Join-Path $projectRoot "pyproject.toml"
$legacyRuntimeRoot = Join-Path $projectRoot ".python312"

function Test-Python312Candidate {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$PrefixArgs = @()
    )

    $probeScript = [System.IO.Path]::GetTempFileName() + ".py"
    $stdoutFile = [System.IO.Path]::GetTempFileName()
    $stderrFile = [System.IO.Path]::GetTempFileName()

    try {
        Set-Content -LiteralPath $probeScript -Value "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" -Encoding ASCII
        try {
            $process = Start-Process `
                -FilePath $FilePath `
                -ArgumentList @($PrefixArgs + @($probeScript)) `
                -RedirectStandardOutput $stdoutFile `
                -RedirectStandardError $stderrFile `
                -WindowStyle Hidden `
                -Wait `
                -PassThru
        }
        catch {
            return $false
        }
        return $process.ExitCode -eq 0
    }
    finally {
        foreach ($path in @($probeScript, $stdoutFile, $stderrFile)) {
            if (Test-Path -LiteralPath $path) {
                Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

function Resolve-SystemPython312 {
    $candidates = New-Object System.Collections.Generic.List[object]
    $candidateKeys = New-Object System.Collections.Generic.HashSet[string]([System.StringComparer]::OrdinalIgnoreCase)

    function Add-Candidate {
        param(
            [string]$FilePath,
            [string]$Label,
            [string[]]$PrefixArgs = @()
        )

        if ([string]::IsNullOrWhiteSpace($FilePath)) {
            return
        }

        $resolvedPath = $null
        if (Test-Path -LiteralPath $FilePath) {
            $resolvedPath = (Resolve-Path -LiteralPath $FilePath).Path
        }
        else {
            $resolvedPath = $FilePath
        }

        if ($resolvedPath.StartsWith($projectRootWithSlash, [System.StringComparison]::OrdinalIgnoreCase)) {
            return
        }

        if ($candidateKeys.Add($resolvedPath)) {
            $candidates.Add([pscustomobject]@{
                FilePath = $resolvedPath
                Label = $Label
                PrefixArgs = $PrefixArgs
            })
        }
    }

    Add-Candidate -FilePath (Join-Path $env:LocalAppData "Programs\Python\Python312\python.exe") -Label "per-user Python 3.12"
    Add-Candidate -FilePath "C:\Program Files\Python312\python.exe" -Label "all-users Python 3.12"

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        foreach ($line in (& $pyLauncher.Source -0p 2>$null)) {
            if ($line -match '^\s*-V:3\.12(?:-[0-9]+)?\s+\*?\s*(.+?)\s*$') {
                Add-Candidate -FilePath $matches[1].Trim() -Label "py launcher discovered Python 3.12"
            }
        }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        Add-Candidate -FilePath $python.Source -Label "system python"
    }

    foreach ($candidate in $candidates) {
        if (Test-Python312Candidate -FilePath $candidate.FilePath -PrefixArgs $candidate.PrefixArgs) {
            return $candidate
        }
    }

    throw "Python 3.12 was not found. Install Python 3.12 first, then rerun setup."
}

function Test-VenvVersion {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonPath
    )

    if (-not (Test-Path -LiteralPath $PythonPath)) {
        return $false
    }

    return Test-Python312Candidate -FilePath $PythonPath
}

function Test-LegacyProjectVenv {
    param(
        [Parameter(Mandatory = $true)]
        [string]$VenvRoot
    )

    $configPath = Join-Path $VenvRoot "pyvenv.cfg"
    if (-not (Test-Path -LiteralPath $configPath)) {
        return $false
    }

    $content = Get-Content -LiteralPath $configPath -ErrorAction SilentlyContinue
    return ($content -join "`n") -match [regex]::Escape($legacyRuntimeRoot)
}

function Test-VenvPip {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonPath
    )

    if (-not (Test-Path -LiteralPath $PythonPath)) {
        return $false
    }

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $PythonPath -m pip --version *> $null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

if (-not (Test-Path -LiteralPath $pyprojectPath)) {
    throw "pyproject.toml was not found. Setup must be run from the project root package."
}

Set-Location $projectRoot

$pythonCommand = Resolve-SystemPython312

Write-Host "Project root: $projectRoot"
Write-Host "Python 3.12: $($pythonCommand.FilePath) [$($pythonCommand.Label)]"

$recreateVenv = $false

if (Test-Path -LiteralPath $venvRoot) {
    if (Test-LegacyProjectVenv -VenvRoot $venvRoot) {
        Write-Host "Existing .venv still points to the legacy project runtime .python312. Recreating it with the installed Python 3.12 interpreter." -ForegroundColor Yellow
        $recreateVenv = $true
    }
    elseif (-not (Test-VenvVersion -PythonPath $venvPython)) {
        Write-Host "Existing .venv is not using Python 3.12. Recreating it with the system Python 3.12 interpreter." -ForegroundColor Yellow
        $recreateVenv = $true
    }
    elseif (-not (Test-VenvPip -PythonPath $venvPython)) {
        Write-Host "Existing .venv is missing pip. Recreating it with the system Python 3.12 interpreter." -ForegroundColor Yellow
        $recreateVenv = $true
    }
    else {
        Write-Host "Reusing existing Python 3.12 virtual environment: $venvRoot"
    }
}
else {
    $recreateVenv = $true
}

if ($recreateVenv) {
    Write-Host "Creating Python 3.12 virtual environment: $venvRoot"
    $venvArgs = @("-m", "venv")
    if (Test-Path -LiteralPath $venvRoot) {
        $venvArgs += "--clear"
    }
    $venvArgs += $venvRoot
    & $pythonCommand.FilePath @($pythonCommand.PrefixArgs + $venvArgs)
}

$installArgs = @("-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel")
Write-Host "Upgrading packaging tools..."
& $venvPython @installArgs

$packageSpec = if ($Dev) { ".[dev]" } else { "." }
$packageDescription = if ($Dev) { "runtime + development dependencies" } else { "runtime dependencies" }

Write-Host "Installing $packageDescription..."
& $venvPython -m pip install -e $packageSpec

if (-not (Test-Path -LiteralPath $envFile) -and (Test-Path -LiteralPath $envExample)) {
    Copy-Item -LiteralPath $envExample -Destination $envFile
    Write-Host "Created .env from .env.example"
}

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "Next steps:"
Write-Host "1. Edit .env and set VISION_API_KEY."
Write-Host "2. Start the service with .\start.ps1 -NoReload."
