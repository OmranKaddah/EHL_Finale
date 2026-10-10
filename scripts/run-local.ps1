param([switch]$ModelSmoke, [switch]$ResearchOnly, [int]$MaxSteps = 450, [string]$TraceDir = '')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
$atiraCommand = Get-Command atira -ErrorAction SilentlyContinue
$atiraPath = if ($atiraCommand) { $atiraCommand.Source } else { Join-Path $env:LOCALAPPDATA 'atira\bin\atira.cmd' }
if (-not (Test-Path -LiteralPath $atiraPath)) { throw 'Atira CLI missing. Install it from the official Windows installer.' }
if (-not $env:CHALLENGE_SCOUTING) { & $atiraPath scout --env | Out-String | Invoke-Expression }
if (-not $TraceDir) { $TraceDir = 'artifacts/' + (Get-Date -Format 'yyyyMMdd-HHmmss') }
$agentArgs = @('run','--no-sync','python','agent.py','--debug','--headful','--dashboard','--trace-dir',$TraceDir,'--max-steps',"$MaxSteps")
if ($ModelSmoke) { $agentArgs += '--model-smoke' }
if ($ResearchOnly) { $agentArgs += '--research-only' }
& uv @agentArgs
exit $LASTEXITCODE
