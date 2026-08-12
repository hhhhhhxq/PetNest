param(
    [string]$GodotExecutable = $env:PETNEST_GODOT_EXE,
    [switch]$Optional,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$ProjectDirectory = $PSScriptRoot
$RepositoryRoot = (Resolve-Path (Join-Path $ProjectDirectory "..\..")).Path
$ExportDirectory = Join-Path $RepositoryRoot "dist\PetNestGodot"
$EffectsDirectory = Join-Path $RepositoryRoot "effects"
$BundledEffectsDirectory = Join-Path $ExportDirectory "effects"
$CursorStylesDirectory = Join-Path $RepositoryRoot "assets\cursors"
$BundledCursorStylesDirectory = Join-Path $ExportDirectory "cursors"
$NativePresenter = Join-Path $ProjectDirectory "windows-native-presenter.ps1"
$BundledNativePresenter = Join-Path $ExportDirectory "windows-native-presenter.ps1"
$ObsoleteTransparencyHelper = Join-Path $ExportDirectory "windows-transparency-helper.ps1"

function Find-GodotExecutable {
    param([string]$Configured)

    if ($Configured -and (Test-Path -LiteralPath $Configured -PathType Leaf)) {
        return (Resolve-Path -LiteralPath $Configured).Path
    }
    foreach ($commandName in @("godot4", "godot")) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
    }
    foreach ($candidate in @(
        "D:\Tools\Godot\4.7.1\Godot_v4.7.1-stable_win64_console.exe",
        "$env:LOCALAPPDATA\Programs\Godot\Godot_v4.7.1-stable_win64_console.exe",
        "$env:ProgramFiles\Godot\Godot_v4.7.1-stable_win64_console.exe"
    )) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return $null
}

$godot = Find-GodotExecutable $GodotExecutable
if (-not $godot) {
    if ($Optional) {
        Write-Host "Godot 4.7.1 was not found; skipping the optional advanced client."
        exit 0
    }
    throw "Godot 4.7.1 was not found. Set PETNEST_GODOT_EXE to the console executable."
}

Write-Host "Using Godot: $godot"
if (-not $SkipTests) {
    & $godot --headless --path $ProjectDirectory --script "res://tests/smoke_test.gd"
    if ($LASTEXITCODE -ne 0) {
        throw "Godot smoke tests failed with exit code $LASTEXITCODE."
    }
}

& $godot --headless --path $ProjectDirectory --editor --quit
if ($LASTEXITCODE -ne 0) {
    throw "Godot project import failed with exit code $LASTEXITCODE."
}

New-Item -ItemType Directory -Path $ExportDirectory -Force | Out-Null
& $godot --headless --path $ProjectDirectory --export-release "Windows Desktop" (Join-Path $ExportDirectory "PetNestGodot.exe")
if ($LASTEXITCODE -ne 0) {
	throw "Godot export failed with exit code $LASTEXITCODE. Install the Godot 4.7.1 export templates."
}

if (Test-Path -LiteralPath $BundledEffectsDirectory -PathType Container) {
    Remove-Item -LiteralPath $BundledEffectsDirectory -Recurse -Force
}
Copy-Item -LiteralPath $EffectsDirectory -Destination $BundledEffectsDirectory -Recurse -Force
if (Test-Path -LiteralPath $BundledCursorStylesDirectory -PathType Container) {
    Remove-Item -LiteralPath $BundledCursorStylesDirectory -Recurse -Force
}
Copy-Item -LiteralPath $CursorStylesDirectory -Destination $BundledCursorStylesDirectory -Recurse -Force
Copy-Item -LiteralPath $NativePresenter -Destination $BundledNativePresenter -Force
if (Test-Path -LiteralPath $ObsoleteTransparencyHelper -PathType Leaf) {
    Remove-Item -LiteralPath $ObsoleteTransparencyHelper -Force
}

Write-Host "PetNest Advanced exported to $ExportDirectory"
