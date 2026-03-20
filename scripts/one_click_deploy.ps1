$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $PSScriptRoot "one_click_deploy.py"
$venvPython = Join-Path $repoRoot ".venv\\Scripts\\python.exe"

if (Test-Path $venvPython) {
  & $venvPython $scriptPath --mode auto --host 127.0.0.1 --port 8000 @Args
  exit $LASTEXITCODE
}

if (Get-Command py -ErrorAction SilentlyContinue) {
  & py -3 $scriptPath --mode auto --host 127.0.0.1 --port 8000 @Args
  exit $LASTEXITCODE
}

if (Get-Command python -ErrorAction SilentlyContinue) {
  & python $scriptPath --mode auto --host 127.0.0.1 --port 8000 @Args
  exit $LASTEXITCODE
}

throw "Python 3.9+ was not found. Install Python first, then rerun this script."
