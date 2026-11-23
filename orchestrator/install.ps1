# Orchestrator installer (wrapper). Usage:  pwsh install.ps1 [-Check] [-DryRun]
param([switch]$Check, [switch]$DryRun)
$script = Join-Path $PSScriptRoot 'bin/install.mjs'
$argsList = @()
if ($Check) { $argsList += '--check' }
if ($DryRun) { $argsList += '--dry-run' }
& node $script @argsList
exit $LASTEXITCODE
