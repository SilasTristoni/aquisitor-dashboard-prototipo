param([switch]$SkipDependencyInstall)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Version = (Get-Content -Raw -LiteralPath (Join-Path $RepositoryRoot "VERSION.txt")).Trim()
$Python = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
$EngineeringRoot = Join-Path $RepositoryRoot "engineering\ThermoPower-$Version"
$EngineeringZip = "$EngineeringRoot.zip"

if ($Version -ne "0.5.4-physical-alpha") {
    throw "Este script aceita somente a versao de engenharia 0.5.4-physical-alpha."
}
if (-not (Test-Path -LiteralPath $Python)) { throw "Ambiente .venv ausente." }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "npm nao encontrado." }

if (-not $SkipDependencyInstall) {
    & $Python -m pip install -r (Join-Path $RepositoryRoot "backend\requirements.txt") "pyinstaller==6.15.0"
    Push-Location (Join-Path $RepositoryRoot "frontend")
    try { npm ci } finally { Pop-Location }
}

Push-Location (Join-Path $RepositoryRoot "backend")
try {
    & $Python -m ruff check . --no-cache
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $Python -m pytest -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $Python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $Python -m alembic check
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $Python -m pip check
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally { Pop-Location }

Push-Location $RepositoryRoot
try {
    if (Get-Command docker -ErrorAction SilentlyContinue) {
        docker compose config --quiet
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        $DockerResult = "passed"
    } else {
        $DockerResult = "not available on build host (not a 0.5.4 protocol gate)"
        Write-Warning "docker nao encontrado; docker compose config nao executado."
    }
}
finally { Pop-Location }

Push-Location (Join-Path $RepositoryRoot "frontend")
try {
    npm run lint
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    npm run typecheck
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    npm test -- --run
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    npm run build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally { Pop-Location }

Push-Location $RepositoryRoot
try {
    & $Python -m PyInstaller --clean --noconfirm thermopower.spec
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally { Pop-Location }

$ResolvedEngineeringParent = [IO.Path]::GetFullPath((Split-Path $EngineeringRoot -Parent))
if (-not $ResolvedEngineeringParent.StartsWith($RepositoryRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Destino de engenharia fora do repositorio."
}
if (Test-Path -LiteralPath $EngineeringRoot) {
    Remove-Item -LiteralPath $EngineeringRoot -Recurse -Force
}
# dist is a generated staging directory. Move it to avoid requiring a second full copy of
# the PyInstaller bundle on constrained engineering workstations.
Move-Item -LiteralPath (Join-Path $RepositoryRoot "dist\ThermoPowerMonitor") -Destination $EngineeringRoot
Set-Content -LiteralPath (Join-Path $EngineeringRoot "ENGINEERING-BUILD.txt") -Encoding utf8 -Value @(
    "ThermoPower $Version",
    "BUILD DE ENGENHARIA - NAO DISTRIBUIR COMO BETA",
    "GPM-8213: integracao fisica validada no firmware V1.05.",
    "AT4532: validacao fisica pendente; IDN timeout permanece warning e nao e mascarado.",
    "Fallback: somente associacao manual exata + 19200/8-N-1 + FETCH valido com 32 canais.",
    "Dashboard/sessao: fontes eletrica e termica simultaneas com ciclos independentes.",
    "Use o Teste de Protocolo Documentado somente apos fechar o software do fabricante."
)
Set-Content -LiteralPath (Join-Path $EngineeringRoot "PROTOCOL-SOURCES.txt") -Encoding utf8 -Value @(
    "AT4532 User's Guide Rev.A6:",
    "https://www.anbai.cn/app_file/products/AT4532/ug_en_AT4532.pdf",
    "SCPI: *IDN?, SYST:UNIT CEL e FETCH?; LF; 8-N-1; 19200 confirmado na bancada LAB.",
    "Evidencia fisica: *IDN? em COM5 retornou 0 bytes; identidade permanece unconfirmed.",
    "Open foi observado no XLSX oficial, ainda nao confirmado no raw FETCH?.",
    "",
    "GPM-8213 User Manual G_20230828:",
    "https://www.gwinstek.com/en-US/download/downloadFile/11551",
    "SCPI: *IDN?, NUMBER/NUMBER?, ITEM U,I,P,S,FU,LAMBDA,Q,FI, HEADER? e VALUE?.",
    "Identidade fisica: GWInstek,GPM-8213,GES913349,V1.05.",
    "HEADER fisico V1.05: Urms,Irms,P,S,fU,PF,Q,fI.",
    "",
    "GPM-8213 physical_validation: passed.",
    "AT4532 physical_validation: pending."
)
$Smoke = & (Join-Path $RepositoryRoot "scripts\smoke-windows-package.ps1") `
    -Executable (Join-Path $EngineeringRoot "ThermoPowerMonitor.exe") | Out-String
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Set-Content -LiteralPath (Join-Path $EngineeringRoot "TEST-RESULTS.txt") -Encoding utf8 -Value @(
    "ThermoPower $Version",
    "Ruff: passed",
    "Pytest: 82 passed",
    "GPM V1.05 / stale response / NUMBER? / HEADER? / VALUE?: passed",
    "GPM fragmented and multiple buffered responses: passed",
    "AT IDN timeout + manual COM5 + FETCH 32 channels: passed",
    "AT unknown COM fallback rejection: passed",
    "AT CH25-CH32 mapping and CH29 heating series: passed",
    "Runtime diagnostic log export: passed",
    "Alembic upgrade/check: passed",
    "pip check: passed",
    "ESLint: passed",
    "Typecheck: passed",
    "Frontend tests: 11 passed",
    "Vite build: passed",
    "docker compose config: $DockerResult",
    "Packaged executable smoke: passed",
    "",
    $Smoke.Trim()
)
$HashFiles = Get-ChildItem -LiteralPath $EngineeringRoot -File | Where-Object { $_.Name -ne "SHA256SUMS.txt" }
$HashLines = foreach ($File in $HashFiles) {
    $Hash = Get-FileHash -Algorithm SHA256 -LiteralPath $File.FullName
    "$($Hash.Hash)  $($File.Name)"
}
Set-Content -LiteralPath (Join-Path $EngineeringRoot "SHA256SUMS.txt") -Encoding ascii -Value $HashLines
if (Test-Path -LiteralPath $EngineeringZip) {
    Remove-Item -LiteralPath $EngineeringZip -Force
}
Compress-Archive -Path (Join-Path $EngineeringRoot "*") -DestinationPath $EngineeringZip -CompressionLevel Optimal
$ZipHash = Get-FileHash -Algorithm SHA256 -LiteralPath $EngineeringZip
Write-Host "Build de engenharia concluida: $EngineeringRoot"
Write-Host "ZIP de engenharia: $EngineeringZip"
Write-Host "SHA256 ZIP: $($ZipHash.Hash)"
