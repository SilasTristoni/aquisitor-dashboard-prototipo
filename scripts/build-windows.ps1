param(
    [string]$Version,
    [switch]$SkipInstaller,
    [switch]$SkipDependencyInstall
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ReleaseConfigurationPath = Join-Path $RepositoryRoot "release-config.json"
$ReleaseConfiguration = Get-Content -Raw -LiteralPath $ReleaseConfigurationPath | ConvertFrom-Json
if (-not $Version) { $Version = [string]$ReleaseConfiguration.version }
if ($Version -ne [string]$ReleaseConfiguration.version) {
    throw "A versão solicitada ($Version) difere de release-config.json ($($ReleaseConfiguration.version))."
}
$FrontendPackageVersion = [string](Get-Content -Raw -LiteralPath (Join-Path $RepositoryRoot "frontend\package.json") | ConvertFrom-Json).version
if ($FrontendPackageVersion -ne $Version) {
    throw "frontend/package.json ($FrontendPackageVersion) difere da versão da release ($Version)."
}
$Python = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
$ReleaseRoot = Join-Path $RepositoryRoot "release\ThermoPower-Monitor-$Version"
$DistRoot = Join-Path $RepositoryRoot "dist"

function Invoke-Step([int]$Number, [string]$Message, [scriptblock]$Action) {
    Write-Host "[$Number/19] $Message"
    $global:LASTEXITCODE = 0
    & $Action
    if ($LASTEXITCODE -ne 0) { throw "Falha: $Message (código $LASTEXITCODE)" }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "O pacote Windows deve ser compilado em um host Windows."
}
foreach ($Required in @("AGENTS.md", "release-config.json", "backend\requirements.txt", "frontend\package-lock.json", "thermopower.spec", "installer\ThermoPower.iss")) {
    if (-not (Test-Path -LiteralPath (Join-Path $RepositoryRoot $Required))) {
        throw "Repositório inválido: arquivo ausente $Required"
    }
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "npm não encontrado." }
if (-not (Test-Path -LiteralPath $Python)) {
    Invoke-Step 1 "Criando ambiente Python" { python -m venv (Join-Path $RepositoryRoot ".venv") }
}

Invoke-Step 2 "Limpando saídas anteriores" {
    foreach ($Target in @((Join-Path $RepositoryRoot "build"), $DistRoot, $ReleaseRoot)) {
        $ResolvedParent = [IO.Path]::GetFullPath((Split-Path $Target -Parent))
        if (-not $ResolvedParent.StartsWith($RepositoryRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Destino de limpeza fora do repositório: $Target"
        }
        if (Test-Path -LiteralPath $Target) { Remove-Item -LiteralPath $Target -Recurse -Force }
    }
}
if (-not $SkipDependencyInstall) {
    Invoke-Step 3 "Instalando dependências Python" { & $Python -m pip install -r (Join-Path $RepositoryRoot "backend\requirements.txt") "pyinstaller==6.15.0" }
    Invoke-Step 4 "Instalando dependências frontend" { Push-Location (Join-Path $RepositoryRoot "frontend"); try { npm ci } finally { Pop-Location } }
}
Invoke-Step 5 "Executando Ruff" { Push-Location (Join-Path $RepositoryRoot "backend"); try { & $Python -m ruff check . } finally { Pop-Location } }
Invoke-Step 6 "Executando Pytest" { Push-Location (Join-Path $RepositoryRoot "backend"); try { & $Python -m pytest } finally { Pop-Location } }
Invoke-Step 7 "Executando ESLint" { Push-Location (Join-Path $RepositoryRoot "frontend"); try { npm run lint } finally { Pop-Location } }
Invoke-Step 8 "Executando typecheck" { Push-Location (Join-Path $RepositoryRoot "frontend"); try { npm run typecheck } finally { Pop-Location } }
Invoke-Step 9 "Executando testes frontend" { Push-Location (Join-Path $RepositoryRoot "frontend"); try { npm test -- --run } finally { Pop-Location } }
Invoke-Step 10 "Auditando dependências npm (alto/crítico bloqueiam)" { Push-Location (Join-Path $RepositoryRoot "frontend"); try { npm audit --audit-level=high } finally { Pop-Location } }
Invoke-Step 11 "Gerando frontend" { Push-Location (Join-Path $RepositoryRoot "frontend"); try { npm run build } finally { Pop-Location } }
Invoke-Step 12 "Gerando executáveis principal e Virtual Lab" { Push-Location $RepositoryRoot; try { & $Python -m PyInstaller --clean --noconfirm thermopower.spec } finally { Pop-Location } }
Invoke-Step 13 "Executando smoke do pacote principal" { & (Join-Path $PSScriptRoot "smoke-windows-package.ps1") }
Invoke-Step 14 "Executando smoke do Virtual Lab" { & (Join-Path $PSScriptRoot "smoke-virtual-lab.ps1") }
Invoke-Step 15 "Executando smoke do diagnóstico" { & (Join-Path $PSScriptRoot "smoke-usb-diagnostic.ps1") }

$Installer = Join-Path $DistRoot "ThermoPower-Setup-$Version.exe"
if (-not $SkipInstaller) {
    $InnoCandidates = @(
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    $InnoCompiler = $InnoCandidates | Select-Object -First 1
    if (-not $InnoCompiler) { throw "Inno Setup 6 não encontrado. Use -SkipInstaller somente para CI portátil." }
    Invoke-Step 16 "Gerando instalador Inno Setup" { & $InnoCompiler "/DAppVersion=$Version" (Join-Path $RepositoryRoot "installer\ThermoPower.iss") }
}

Invoke-Step 17 "Gerando documentação PDF" { & $Python (Join-Path $PSScriptRoot "generate-client-docs.py") --output $DistRoot --version $Version }
Invoke-Step 18 "Montando ZIPs e pasta release" {
    New-Item -ItemType Directory -Path $ReleaseRoot -Force | Out-Null
    Compress-Archive -Path (Join-Path $DistRoot "ThermoPowerMonitor\*") -DestinationPath (Join-Path $ReleaseRoot "ThermoPower-Portable-$Version.zip") -CompressionLevel Optimal
    Compress-Archive -Path (Join-Path $DistRoot "ThermoPowerVirtualLab\*") -DestinationPath (Join-Path $ReleaseRoot "ThermoPower-Virtual-Lab-$Version.zip") -CompressionLevel Optimal
    if (Test-Path -LiteralPath $Installer) { Copy-Item -LiteralPath $Installer -Destination $ReleaseRoot }
    Copy-Item -LiteralPath (Join-Path $DistRoot "Manual-de-Homologacao.pdf") -Destination $ReleaseRoot
    Copy-Item -LiteralPath (Join-Path $DistRoot "Roteiro-de-Testes.pdf") -Destination $ReleaseRoot
    Copy-Item -LiteralPath (Join-Path $RepositoryRoot "docs\release-assets\LEIA-ME.txt") -Destination $ReleaseRoot
    $ReleaseNotes = Get-Content -Raw -LiteralPath (Join-Path $RepositoryRoot "docs\release-assets\release-notes.txt")
    Set-Content -LiteralPath (Join-Path $ReleaseRoot "release-notes.txt") -Value $ReleaseNotes.Replace("{{VERSION}}", $Version) -Encoding utf8
    Set-Content -LiteralPath (Join-Path $ReleaseRoot "VERSION.txt") -Value $Version -Encoding utf8
}
Invoke-Step 19 "Gerando e validando SHA-256" {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Files = Get-ChildItem -LiteralPath $ReleaseRoot -File | Where-Object Name -ne "SHA256SUMS.txt"
    $Lines = foreach ($File in $Files) { "{0}  {1}" -f (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash.ToLowerInvariant(), $File.Name }
    Set-Content -LiteralPath (Join-Path $ReleaseRoot "SHA256SUMS.txt") -Value $Lines -Encoding ascii
    foreach ($Zip in Get-ChildItem -LiteralPath $ReleaseRoot -Filter "*.zip") {
        $Archive = [IO.Compression.ZipFile]::OpenRead($Zip.FullName)
        try { if ($Archive.Entries.Count -eq 0) { throw "ZIP vazio: $($Zip.Name)" } } finally { $Archive.Dispose() }
    }
    git diff --quiet -- legacy
    if ($LASTEXITCODE -ne 0) { throw "A pasta legacy foi alterada." }
}

Write-Host "Pacote concluído: $ReleaseRoot"
Get-ChildItem -LiteralPath $ReleaseRoot -File | ForEach-Object { Write-Host $_.FullName }
