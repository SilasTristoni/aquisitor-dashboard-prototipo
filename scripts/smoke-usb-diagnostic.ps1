$ErrorActionPreference = "Stop"
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) { throw "Ambiente Python de build ausente." }
Push-Location (Join-Path $RepositoryRoot "backend")
try {
    & $Python -m pytest -q tests/test_virtual_usb_lab.py::test_snapshot_diff_export_and_secret_masking
    if ($LASTEXITCODE -ne 0) { throw "Smoke do diagnóstico falhou." }
} finally { Pop-Location }
[pscustomobject]@{ Snapshot=$true; Diff=$true; Zip=$true; RequiredFiles=$true; SecretsAbsent=$true; SerialWrites=0 }
