param(
    [string]$Version = "1.4.0",
    [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

function Remove-ReleaseBuildPath([string]$Path) {
    $fullPath = [IO.Path]::GetFullPath($Path)
    $repoPrefix = $repoRoot.TrimEnd('\') + '\'
    if (-not $fullPath.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a path outside the repository: $fullPath"
    }
    if ($fullPath -eq $repoRoot) {
        throw "Refusing to remove the repository root."
    }
    if (Test-Path -LiteralPath $fullPath) {
        Remove-Item -LiteralPath $fullPath -Recurse -Force
    }
}

if (-not $SkipFrontend) {
    Push-Location (Join-Path $repoRoot "frontend")
    try {
        npm ci
        npm run typecheck
        npm run lint
        npm test
        npm run build
    }
    finally {
        Pop-Location
    }
}

$releaseVenv = Join-Path $repoRoot "build\release-venv"
if (Test-Path -LiteralPath $releaseVenv) {
    Remove-ReleaseBuildPath $releaseVenv
}
python -m venv $releaseVenv
$releasePython = Join-Path $releaseVenv "Scripts\python.exe"
& $releasePython -m pip install --upgrade pip build pyinstaller
& $releasePython -m pip install -e ".[ui,ocr]"
& $releasePython scripts/verify_release.py --source-only

Remove-ReleaseBuildPath (Join-Path $repoRoot "build\ielts-study-desk")
Remove-ReleaseBuildPath (Join-Path $repoRoot "dist\IELTS Study Desk")
Remove-ReleaseBuildPath (Join-Path $repoRoot "release-artifacts")

& $releasePython -m PyInstaller `
    --noconfirm `
    --clean `
    --workpath (Join-Path $repoRoot "build\ielts-study-desk") `
    --distpath (Join-Path $repoRoot "dist") `
    (Join-Path $repoRoot "packaging\windows\ielts-study-desk.spec")

$isccCandidates = @(
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }

if (-not $isccCandidates) {
    throw "Inno Setup 6 was not found. Install it, then rerun this script."
}

& $isccCandidates[0] "/DMyAppVersion=$Version" `
    (Join-Path $repoRoot "packaging\windows\ielts-study-desk.iss")

Get-ChildItem -LiteralPath (Join-Path $repoRoot "release-artifacts")
