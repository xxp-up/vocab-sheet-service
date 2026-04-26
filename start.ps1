param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8000,
    [switch]$Background,
    [switch]$NoReload,
    [switch]$TailLogs
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path -LiteralPath $projectRoot).Path
$projectRootWithSlash = $projectRoot.TrimEnd("\") + "\"
$runtimeRoot = Join-Path $projectRoot ".runtime"
$logsRoot = Join-Path $runtimeRoot "logs"
$stdoutLog = Join-Path $logsRoot "uvicorn.stdout.log"
$stderrLog = Join-Path $logsRoot "uvicorn.stderr.log"
$envFile = Join-Path $projectRoot ".env"
$envExample = Join-Path $projectRoot ".env.example"
$legacyRuntimeRoot = Join-Path $projectRoot ".python312"

function Test-PythonCandidate {
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

function Resolve-PythonCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot
    )

    $directCandidates = @(
        @{
            Path = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
            Label = "project virtual environment"
            PrefixArgs = @()
        }
    )

    foreach ($candidate in $directCandidates) {
        if (Test-Path -LiteralPath $candidate.Path) {
            $venvConfig = Join-Path $ProjectRoot ".venv\pyvenv.cfg"
            if ($candidate.Label -eq "project virtual environment" -and (Test-Path -LiteralPath $venvConfig)) {
                $venvConfigContent = Get-Content -LiteralPath $venvConfig -ErrorAction SilentlyContinue
                if (($venvConfigContent -join "`n") -match [regex]::Escape($legacyRuntimeRoot)) {
                    continue
                }
            }

            $resolvedCandidate = [pscustomobject]@{
                FilePath = (Resolve-Path -LiteralPath $candidate.Path).Path
                Label = $candidate.Label
                PrefixArgs = $candidate.PrefixArgs
            }
            if (Test-PythonCandidate -FilePath $resolvedCandidate.FilePath -PrefixArgs $resolvedCandidate.PrefixArgs) {
                return $resolvedCandidate
            }
        }
    }

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        foreach ($line in (& $pyLauncher.Source -0p 2>$null)) {
            if ($line -match '^\s*-V:3\.12(?:-[0-9]+)?\s+\*?\s*(.+?)\s*$') {
                $candidatePath = $matches[1].Trim()
                if (-not $candidatePath.StartsWith($projectRootWithSlash, [System.StringComparison]::OrdinalIgnoreCase)) {
                    $candidate = [pscustomobject]@{
                        FilePath = $candidatePath
                        Label = "installed Python 3.12"
                        PrefixArgs = @()
                    }
                    if (Test-PythonCandidate -FilePath $candidate.FilePath -PrefixArgs $candidate.PrefixArgs) {
                        return $candidate
                    }
                }
            }
        }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        $candidatePath = $python.Source
        if (-not $candidatePath.StartsWith($projectRootWithSlash, [System.StringComparison]::OrdinalIgnoreCase)) {
            $candidate = [pscustomobject]@{
                FilePath = $candidatePath
                Label = "system python"
                PrefixArgs = @()
            }
            if (Test-PythonCandidate -FilePath $candidate.FilePath -PrefixArgs $candidate.PrefixArgs) {
                return $candidate
            }
        }
    }

    throw "Python 3.12 interpreter not found. Run .\setup.ps1 or install Python 3.12 on this machine first."
}

function Test-StartPreflight {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$PythonCommand
    )

    $preflightCode = @'
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.models.settings import get_settings

settings = get_settings()
settings.require_vision_api_key()
import fastapi  # noqa: F401
import uvicorn  # noqa: F401
from app.main import app  # noqa: F401
'@

    $preflightScript = Join-Path $projectRoot ".runtime\start-preflight.py"
    $stdoutFile = [System.IO.Path]::GetTempFileName()
    $stderrFile = [System.IO.Path]::GetTempFileName()

    try {
        Set-Content -LiteralPath $preflightScript -Value $preflightCode -Encoding ASCII
        $arguments = @() + $PythonCommand.PrefixArgs + @($preflightScript)
        $process = Start-Process `
            -FilePath $PythonCommand.FilePath `
            -ArgumentList $arguments `
            -WorkingDirectory $projectRoot `
            -RedirectStandardOutput $stdoutFile `
            -RedirectStandardError $stderrFile `
            -WindowStyle Hidden `
            -Wait `
            -PassThru
    }
    finally {
        $output = @()
        $stderrOutput = @()
        if (Test-Path -LiteralPath $stdoutFile) {
            $output = Get-Content -LiteralPath $stdoutFile -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath $stdoutFile -Force -ErrorAction SilentlyContinue
        }
        if (Test-Path -LiteralPath $stderrFile) {
            $stderrOutput = Get-Content -LiteralPath $stderrFile -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath $stderrFile -Force -ErrorAction SilentlyContinue
        }
        if (Test-Path -LiteralPath $preflightScript) {
            Remove-Item -LiteralPath $preflightScript -Force -ErrorAction SilentlyContinue
        }
    }

    if ($process.ExitCode -ne 0) {
        Write-Host "Startup preflight failed." -ForegroundColor Red
        if (($output -join "`n") -match "ModuleNotFoundError" -or ($stderrOutput -join "`n") -match "ModuleNotFoundError") {
            Write-Host "Project dependencies are missing in the selected Python 3.12 environment. Run .\setup.ps1 first." -ForegroundColor Yellow
        }
        if ($output) {
            $output | ForEach-Object { Write-Host $_ -ForegroundColor Red }
        }
        if ($stderrOutput) {
            $stderrOutput | ForEach-Object { Write-Host $_ -ForegroundColor Red }
        }
        exit 1
    }
}

function Start-LogTail {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Paths
    )

    $existing = $Paths | Where-Object { Test-Path -LiteralPath $_ }
    if (-not $existing) {
        Write-Host "No log files were created yet." -ForegroundColor Yellow
        return
    }

    Write-Host "Tailing logs. Press Ctrl+C to stop viewing logs; the service will keep running." -ForegroundColor Yellow
    Get-Content -Path $existing -Wait -Tail 20
}

Set-Location $projectRoot

$pythonCommand = Resolve-PythonCommand -ProjectRoot $projectRoot

New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
New-Item -ItemType Directory -Path $logsRoot -Force | Out-Null

if (-not (Test-Path -LiteralPath $envFile) -and (Test-Path -LiteralPath $envExample)) {
    Write-Host "Tip: .env was not found. Copy .env.example to .env and fill VISION_API_KEY before the first start." -ForegroundColor Yellow
}

$env:RUNTIME_ROOT = $runtimeRoot
Test-StartPreflight -PythonCommand $pythonCommand

$arguments = @() + $pythonCommand.PrefixArgs + @(
    "-m", "uvicorn", "app.main:app",
    "--host", $HostAddress,
    "--port", $Port.ToString()
)
if (-not $NoReload) {
    $arguments += "--reload"
}

Write-Host "Project root: $projectRoot"
Write-Host "Python: $($pythonCommand.FilePath) [$($pythonCommand.Label)]"
Write-Host "URL: http://$HostAddress`:$Port/"

if ($Background) {
    foreach ($logFile in @($stdoutLog, $stderrLog)) {
        if (Test-Path -LiteralPath $logFile) {
            Clear-Content -LiteralPath $logFile -ErrorAction SilentlyContinue
        }
    }

    $process = Start-Process `
        -FilePath $pythonCommand.FilePath `
        -ArgumentList $arguments `
        -WorkingDirectory $projectRoot `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -WindowStyle Hidden `
        -PassThru

    Start-Sleep -Seconds 2

    if ($process.HasExited) {
        Write-Host "Background startup failed, exit code: $($process.ExitCode)" -ForegroundColor Red
        if (Test-Path -LiteralPath $stderrLog) {
            Write-Host "Error log:" -ForegroundColor Red
            Get-Content -LiteralPath $stderrLog -Tail 50
        }
        exit 1
    }

    Write-Host "Background service started, PID: $($process.Id)" -ForegroundColor Green
    Write-Host "Stdout log: $stdoutLog"
    Write-Host "Stderr log: $stderrLog"

    if ($TailLogs) {
        Start-LogTail -Paths @($stderrLog, $stdoutLog)
    }
    exit 0
}

if ($TailLogs) {
    Write-Host "TailLogs only applies to background mode; continuing in foreground mode." -ForegroundColor Yellow
}

Write-Host "Starting in foreground mode. Press Ctrl+C to stop the service." -ForegroundColor Green
& $pythonCommand.FilePath @arguments
