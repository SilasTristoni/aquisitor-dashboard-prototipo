param([switch]$SkipDependencyInstall)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Version = (Get-Content -Raw -LiteralPath (Join-Path $RepositoryRoot "VERSION.txt")).Trim()
$Python = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
$EngineeringRoot = Join-Path $RepositoryRoot "engineering\ThermoPower-$Version"
$EngineeringZip = "$EngineeringRoot.zip"
$StagingRoot = Join-Path $RepositoryRoot "dist\ThermoPowerMonitor"
$ValidatedZip = Join-Path $RepositoryRoot "dist\ThermoPower-$Version.validated.zip"

if ($Version -ne "0.6.0-client-preview") {
    throw "Este script aceita somente a versao 0.6.0-client-preview."
}
if (-not (Test-Path -LiteralPath $Python)) { throw "Ambiente .venv ausente." }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "npm nao encontrado." }

if (-not $SkipDependencyInstall) {
    & $Python -m pip install -r (Join-Path $RepositoryRoot "backend\requirements.txt") "pyinstaller==6.15.0"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Push-Location (Join-Path $RepositoryRoot "frontend")
    try {
        npm ci
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    finally { Pop-Location }
}

Push-Location (Join-Path $RepositoryRoot "backend")
try {
    & $Python -m ruff check . --no-cache
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $PhysicalRegressionOutput = @()
    & $Python -m pytest -p no:cacheprovider -m physical_regression_fixtures |
        Tee-Object -Variable PhysicalRegressionOutput | ForEach-Object { Write-Host $_ }
    $PhysicalRegressionExitCode = $LASTEXITCODE
    if ($PhysicalRegressionExitCode -ne 0) { exit $PhysicalRegressionExitCode }
    $BackendTestOutput = @()
    & $Python -m pytest -p no:cacheprovider |
        Tee-Object -Variable BackendTestOutput | ForEach-Object { Write-Host $_ }
    $BackendTestExitCode = $LASTEXITCODE
    if ($BackendTestExitCode -ne 0) { exit $BackendTestExitCode }
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
        $DockerResult = "not available on build host (optional gate)"
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
    $FrontendTestOutput = @()
    npm test -- --run |
        Tee-Object -Variable FrontendTestOutput | ForEach-Object { Write-Host $_ }
    $FrontendTestExitCode = $LASTEXITCODE
    if ($FrontendTestExitCode -ne 0) { exit $FrontendTestExitCode }
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

if (-not (Test-Path -LiteralPath (Join-Path $StagingRoot "ThermoPowerMonitor.exe") -PathType Leaf)) {
    throw "Executavel PyInstaller ausente no staging da build."
}

# PyInstaller's Matplotlib hook adds its demonstration dataset after the spec data list is
# evaluated. It is not required by ThermoPower and must not be shipped in a client preview.
$MatplotlibSampleData = Join-Path $StagingRoot "_internal\matplotlib\mpl-data\sample_data"
if (Test-Path -LiteralPath $MatplotlibSampleData -PathType Container) {
    $ResolvedStagingRoot = [IO.Path]::GetFullPath($StagingRoot).TrimEnd("\")
    $ResolvedSampleData = [IO.Path]::GetFullPath($MatplotlibSampleData)
    $ExpectedSampleDataPrefix = "$ResolvedStagingRoot\_internal\matplotlib\mpl-data\sample_data"
    if (-not $ResolvedSampleData.Equals(
        $ExpectedSampleDataPrefix,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Diretorio sample_data resolvido fora do staging esperado."
    }
    Remove-Item -LiteralPath $ResolvedSampleData -Recurse -Force
}
$ForbiddenPackageFiles = Get-ChildItem -LiteralPath $StagingRoot -File -Recurse |
    Where-Object {
        $_.Extension -in @(".db", ".csv", ".xlsx") -or
        $_.Name -match "sessao-4|PRIMEIRO-ACESSO" -or
        $_.FullName -match "[\\/]sample_data[\\/]"
    }
if ($ForbiddenPackageFiles) {
    $ForbiddenRelativePaths = $ForbiddenPackageFiles | ForEach-Object {
        $_.FullName.Substring($StagingRoot.Length).TrimStart("\")
    }
    throw "Dados de avaliacao ou arquivos locais presentes no pacote: $($ForbiddenRelativePaths -join ', ')"
}
$Smoke = & (Join-Path $RepositoryRoot "scripts\smoke-windows-package.ps1") `
    -Executable (Join-Path $StagingRoot "ThermoPowerMonitor.exe") | Out-String

$ResolvedEngineeringParent = [IO.Path]::GetFullPath((Split-Path $EngineeringRoot -Parent))
$ExpectedEngineeringParent = [IO.Path]::GetFullPath((Join-Path $RepositoryRoot "engineering"))
if (-not $ResolvedEngineeringParent.Equals(
    $ExpectedEngineeringParent,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "Destino de engenharia fora do repositorio."
}
Set-Content -LiteralPath (Join-Path $StagingRoot "CLIENT-PREVIEW.txt") -Encoding utf8 -Value @(
    "ThermoPower $Version",
    "PREVIA PARA AVALIACAO INTERNA - NAO E INSTALADOR FINAL",
    "Interface cliente sem simulador e sem credenciais incorporadas ao pacote.",
    "Primeiro acesso: senha aleatoria gerada localmente na primeira execucao.",
    "Dashboard executivo, periodo analisado e KPIs termicos/eletricos.",
    "Relatorio PDF tecnico, resumo executivo e XLSX profissional.",
    "GPM-8213: integracao fisica validada no firmware V1.05.",
    "AT4532: FETCH fisico TCP-32/CP936 suportado; IDN timeout permanece warning.",
    "AT4532 continuo: 3 s apos RX + guarda serial calculada de 0,4 s; soak 100 amostras.",
    "Cadastro AT duplicado: historico preservado e neutralizado; uma COM tem um controlador ativo.",
    "Fallback: somente associacao manual exata + 19200/8-N-1 + medicao estrutural valida.",
    "Dashboard/sessao: fontes eletrica e termica simultaneas com ciclos independentes.",
    "Use o Teste de Protocolo Documentado somente apos fechar o software do fabricante."
)
Set-Content -LiteralPath (Join-Path $StagingRoot "PROTOCOL-SOURCES.txt") -Encoding utf8 -Value @(
    "AT4532 User's Guide Rev.A6:",
    "https://www.anbai.cn/app_file/products/AT4532/ug_en_AT4532.pdf",
    "SCPI: *IDN?, SYST:UNIT CEL e FETCH?; LF; 8-N-1; 19200 confirmado no equipamento.",
    "Evidencia fisica: *IDN? em COM5 retornou 0 bytes; identidade permanece unconfirmed.",
    "FETCH fisico: frame TCP-32 com byte A1 E6 para Celsius, decodificado estritamente em CP936.",
    "Open|K|Celsius foi confirmado no RX para CH01-CH24; CH25-CH32 foram numericos.",
    "Cadencia continua: FETCH ancorado no RX anterior + 0,4 s de guarda calculada para 694 bytes em 19200 8-N-1.",
    "Campos posteriores ao bloco primario de 32 canais permanecem auxiliares sem semantica.",
    "",
    "GPM-8213 User Manual G_20230828:",
    "https://www.gwinstek.com/en-US/download/downloadFile/11551",
    "SCPI: *IDN?, NUMBER/NUMBER?, ITEM U,I,P,S,FU,LAMBDA,Q,FI, HEADER? e VALUE?.",
    "Identidade fisica: GWInstek,GPM-8213,GES913349,V1.05.",
    "HEADER fisico V1.05: Urms,Irms,P,S,fU,PF,Q,fI.",
    "",
    "GPM-8213 physical_validation: passed.",
    "AT4532 protocol_status: verified_by_measurement quando a estrutura e a leitura forem validas.",
    "AT4532 identity_status: unconfirmed enquanto *IDN? permanecer sem resposta."
)
Set-Content -LiteralPath (Join-Path $StagingRoot "TEST-RESULTS.txt") -Encoding utf8 -Value @(
    "ThermoPower $Version",
    "Ruff: passed",
    "Physical regression fixtures gate: passed",
    "Pytest completo: passed",
    "GPM V1.05 / NUMBER abreviado / HEADER / VALUE / NAN: passed",
    "GPM fragmented, stale e multiple buffered responses: passed",
    "AT IDN timeout + manual COM5 + TCP-32 CP936 32 channels: passed",
    "AT continuous acquisition 100 samples with fake clock: passed",
    "AT FETCH cadence anchored after RX with calculated serial guard: passed",
    "AT duplicate COM registration neutralization and warning: passed",
    "AT unknown COM fallback rejection: passed",
    "AT CH25-CH32 mapping and CH29 heating series: passed",
    "Combined and partial-source acquisition: passed",
    "Runtime diagnostic log export: passed",
    "Alembic upgrade/check: passed",
    "pip check: passed",
    "ESLint: passed",
    "Typecheck: passed",
    "Frontend tests: passed",
    "Vite build: passed",
    "Client-preview without simulator: passed",
    "Professional PDF/XLSX/PNG/CSV report contracts: passed",
    "docker compose config: $DockerResult",
    "Packaged executable smoke: passed",
    "",
    $Smoke.Trim(),
    "",
    "Physical pytest summary:",
    ($PhysicalRegressionOutput | Select-Object -Last 3 | Out-String).Trim(),
    "",
    "Backend pytest summary:",
    ($BackendTestOutput | Select-Object -Last 3 | Out-String).Trim(),
    "",
    "Frontend test summary:",
    ($FrontendTestOutput | Select-Object -Last 8 | Out-String).Trim()
)
$RequiredPackagePaths = @(
    "ThermoPowerMonitor.exe",
    "_internal",
    "CLIENT-PREVIEW.txt",
    "PROTOCOL-SOURCES.txt",
    "TEST-RESULTS.txt"
)
foreach ($RelativePath in $RequiredPackagePaths) {
    $RequiredPath = Join-Path $StagingRoot $RelativePath
    $RequiredPathType = if ($RelativePath -eq "_internal") { "Container" } else { "Leaf" }
    if (-not (Test-Path -LiteralPath $RequiredPath -PathType $RequiredPathType)) {
        throw "Conteudo obrigatorio ausente da engineering build: $RelativePath"
    }
}
$ManifestPath = Join-Path $StagingRoot "SHA256SUMS.txt"
$HashFiles = Get-ChildItem -LiteralPath $StagingRoot -File -Recurse |
    Where-Object { $_.FullName -ne $ManifestPath } |
    Sort-Object FullName
$HashEntries = foreach ($File in $HashFiles) {
    $Hash = Get-FileHash -Algorithm SHA256 -LiteralPath $File.FullName
    $RelativePath = $File.FullName.Substring($StagingRoot.Length).TrimStart("\").Replace("\", "/")
    [pscustomobject]@{ Hash = $Hash.Hash; RelativePath = $RelativePath }
}
$HashLines = $HashEntries | ForEach-Object { "$($_.Hash)  $($_.RelativePath)" }
Set-Content -LiteralPath $ManifestPath -Encoding ascii -Value $HashLines
foreach ($Entry in $HashEntries) {
    $FilePath = Join-Path $StagingRoot $Entry.RelativePath.Replace("/", "\")
    $VerifiedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $FilePath).Hash
    if ($VerifiedHash -ne $Entry.Hash) {
        throw "Falha ao verificar SHA256 de $($Entry.RelativePath)."
    }
}
if (Test-Path -LiteralPath $ValidatedZip) {
    Remove-Item -LiteralPath $ValidatedZip -Force
}
Compress-Archive -Path (Join-Path $StagingRoot "*") -DestinationPath $ValidatedZip -CompressionLevel Optimal
$ZipVerificationRoot = Join-Path ([IO.Path]::GetTempPath()) `
    ("thermopower-zip-verification-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $ZipVerificationRoot | Out-Null
try {
    Expand-Archive -LiteralPath $ValidatedZip -DestinationPath $ZipVerificationRoot
    $ExtractedManifest = Join-Path $ZipVerificationRoot "SHA256SUMS.txt"
    if (-not (Test-Path -LiteralPath $ExtractedManifest -PathType Leaf)) {
        throw "SHA256SUMS.txt ausente do ZIP."
    }
    $OriginalManifestHash = (
        Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $StagingRoot "SHA256SUMS.txt")
    ).Hash
    $ExtractedManifestHash = (
        Get-FileHash -Algorithm SHA256 -LiteralPath $ExtractedManifest
    ).Hash
    if ($OriginalManifestHash -ne $ExtractedManifestHash) {
        throw "SHA256SUMS.txt divergiu apos extrair o ZIP."
    }
    $ExtractedFiles = Get-ChildItem -LiteralPath $ZipVerificationRoot -File -Recurse |
        Where-Object { $_.FullName -ne $ExtractedManifest }
    if ($ExtractedFiles.Count -ne $HashEntries.Count) {
        throw "O ZIP nao contem exatamente o conjunto de arquivos do manifesto."
    }
    foreach ($Entry in $HashEntries) {
        $ExtractedPath = Join-Path $ZipVerificationRoot $Entry.RelativePath.Replace("/", "\")
        if (-not (Test-Path -LiteralPath $ExtractedPath -PathType Leaf)) {
            throw "Arquivo ausente no ZIP: $($Entry.RelativePath)."
        }
        $ExtractedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $ExtractedPath).Hash
        if ($ExtractedHash -ne $Entry.Hash) {
            throw "SHA256 divergente apos extrair o ZIP: $($Entry.RelativePath)."
        }
    }
}
finally {
    if (Test-Path -LiteralPath $ZipVerificationRoot) {
        Remove-Item -LiteralPath $ZipVerificationRoot -Recurse -Force
    }
}
$ValidatedZipHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $ValidatedZip).Hash

# Promote only the fully assembled, hashed, extracted and reverified package. Older versioned
# engineering builds are never touched. An existing package for this exact version is moved to
# same-volume backups and restored if either promotion or the final byte verification fails.
$PromotionId = [guid]::NewGuid().ToString("N")
$PreviousEngineeringRoot = "$EngineeringRoot.previous-$PromotionId"
$PreviousEngineeringZip = "$EngineeringZip.previous-$PromotionId"
$FolderBackedUp = $false
$ZipBackedUp = $false
$FolderPromoted = $false
$ZipPromoted = $false
try {
    if (Test-Path -LiteralPath $EngineeringRoot) {
        Move-Item -LiteralPath $EngineeringRoot -Destination $PreviousEngineeringRoot
        $FolderBackedUp = $true
    }
    if (Test-Path -LiteralPath $EngineeringZip) {
        Move-Item -LiteralPath $EngineeringZip -Destination $PreviousEngineeringZip
        $ZipBackedUp = $true
    }
    Move-Item -LiteralPath $StagingRoot -Destination $EngineeringRoot
    $FolderPromoted = $true
    Move-Item -LiteralPath $ValidatedZip -Destination $EngineeringZip
    $ZipPromoted = $true

    $FinalManifestHash = (
        Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $EngineeringRoot "SHA256SUMS.txt")
    ).Hash
    if ($FinalManifestHash -ne $OriginalManifestHash) {
        throw "SHA256SUMS.txt divergiu durante a promocao final."
    }
    foreach ($Entry in $HashEntries) {
        $FinalPath = Join-Path $EngineeringRoot $Entry.RelativePath.Replace("/", "\")
        $FinalHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $FinalPath).Hash
        if ($FinalHash -ne $Entry.Hash) {
            throw "SHA256 divergente apos promocao final: $($Entry.RelativePath)."
        }
    }
    $ZipHash = Get-FileHash -Algorithm SHA256 -LiteralPath $EngineeringZip
    if ($ZipHash.Hash -ne $ValidatedZipHash) {
        throw "SHA256 do ZIP divergiu durante a promocao final."
    }
}
catch {
    $PromotionFailure = $_
    try {
        if ($ZipPromoted -and (Test-Path -LiteralPath $EngineeringZip)) {
            Move-Item -LiteralPath $EngineeringZip -Destination $ValidatedZip
        }
        if ($FolderPromoted -and (Test-Path -LiteralPath $EngineeringRoot)) {
            Move-Item -LiteralPath $EngineeringRoot -Destination $StagingRoot
        }
        if ($ZipBackedUp -and (Test-Path -LiteralPath $PreviousEngineeringZip)) {
            Move-Item -LiteralPath $PreviousEngineeringZip -Destination $EngineeringZip
        }
        if ($FolderBackedUp -and (Test-Path -LiteralPath $PreviousEngineeringRoot)) {
            Move-Item -LiteralPath $PreviousEngineeringRoot -Destination $EngineeringRoot
        }
    }
    catch {
        throw "Falha na promocao e no rollback da engineering build: $PromotionFailure / $_"
    }
    throw $PromotionFailure
}
if ($FolderBackedUp -and (Test-Path -LiteralPath $PreviousEngineeringRoot)) {
    Remove-Item -LiteralPath $PreviousEngineeringRoot -Recurse -Force
}
if ($ZipBackedUp -and (Test-Path -LiteralPath $PreviousEngineeringZip)) {
    Remove-Item -LiteralPath $PreviousEngineeringZip -Force
}
Write-Host "Build de engenharia concluida: $EngineeringRoot"
Write-Host "ZIP de engenharia: $EngineeringZip"
Write-Host "SHA256 ZIP: $($ZipHash.Hash)"
