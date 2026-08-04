param(
    [string]$Version = "0.4.0-beta",
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "O pacote Windows deve ser compilado em um host Windows."
}
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Ambiente .venv ausente. Execute: python -m venv .venv"
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm não encontrado. Instale Node.js LTS antes de compilar."
}

Write-Host "[1/5] Instalando dependências de build..."
& $Python -m pip install -r (Join-Path $RepositoryRoot "backend\requirements.txt") "pyinstaller==6.15.0"

Write-Host "[2/5] Validando e compilando frontend..."
Push-Location (Join-Path $RepositoryRoot "frontend")
try {
    npm ci
    npm run lint
    npm run typecheck
    npm test -- --run
    npm run build
} finally {
    Pop-Location
}

Write-Host "[3/5] Executando testes do backend..."
Push-Location (Join-Path $RepositoryRoot "backend")
try {
    & $Python -m pytest
} finally {
    Pop-Location
}

Write-Host "[4/5] Empacotando aplicação com PyInstaller..."
Push-Location $RepositoryRoot
try {
    & $Python -m PyInstaller --clean --noconfirm thermopower.spec
} finally {
    Pop-Location
}

if ($SkipInstaller) {
    Write-Host "Pacote portátil disponível em dist\ThermoPowerMonitor."
    exit 0
}

$InnoCandidates = @(
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
$InnoCompiler = $InnoCandidates | Select-Object -First 1
if (-not $InnoCompiler) {
    throw "Inno Setup 6 não encontrado. O pacote portátil foi gerado; instale o Inno e execute novamente."
}

Write-Host "[5/5] Gerando instalador Inno Setup..."
& $InnoCompiler "/DAppVersion=$Version" (Join-Path $RepositoryRoot "installer\ThermoPower.iss")
Write-Host "Concluído: dist\ThermoPower-Setup-$Version.exe"
