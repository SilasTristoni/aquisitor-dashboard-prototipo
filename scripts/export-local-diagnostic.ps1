param(
    [string]$AppData = (Join-Path $env:LOCALAPPDATA 'ThermoPower Monitor'),
    [string]$Database,
    [string]$Output = (Join-Path (Get-Location) ('ThermoPower-Diagnostico-Local-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.zip')),
    [string]$Executable
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$arguments = @('--app-data', $AppData, '--output', $Output)
if ($Database) { $arguments += @('--database', $Database) }
if ($Executable) {
    & $Executable '--export-local-diagnostic' @arguments
} else {
    $python = Join-Path $root '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        throw 'Python local ausente. Informe -Executable com o caminho do executável que contém a coleta local.'
    }
    $previousPythonPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = Join-Path $root 'backend'
        & $python '-m' 'app.engineering.local_diagnostic' @arguments
    } finally { $env:PYTHONPATH = $previousPythonPath }
}
if ($LASTEXITCODE -ne 0) { throw 'A coleta local falhou. Nenhuma aquisição foi iniciada.' }
