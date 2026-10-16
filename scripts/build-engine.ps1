<#
.SYNOPSIS
    Freeze the Texora engine sidecar (PowerShell wrapper around scripts/build_engine.py).

.DESCRIPTION
    Prefers the engine venv interpreter (engine/.venv) so the freeze targets Python 3.11.
    All arguments are forwarded verbatim to the cross-platform driver.

.EXAMPLE
    scripts\build-engine.ps1
    scripts\build-engine.ps1 --triple x86_64-pc-windows-msvc
#>
[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Args
)

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir

$VenvWin = Join-Path $RepoRoot 'engine/.venv/Scripts/python.exe'
$VenvPosix = Join-Path $RepoRoot 'engine/.venv/bin/python'

if (Test-Path $VenvWin) {
    $Py = $VenvWin
} elseif (Test-Path $VenvPosix) {
    $Py = $VenvPosix
} else {
    $Py = 'python'
}

$Driver = Join-Path $ScriptDir 'build_engine.py'
& $Py $Driver @Args
exit $LASTEXITCODE
