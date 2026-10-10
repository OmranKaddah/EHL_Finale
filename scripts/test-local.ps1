param([switch]$Browser)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
& uv run ruff check .
if ($LASTEXITCODE) { exit $LASTEXITCODE }
if ($Browser) { & uv run pytest -q } else { & uv run pytest -q -m 'not browser' }
exit $LASTEXITCODE
