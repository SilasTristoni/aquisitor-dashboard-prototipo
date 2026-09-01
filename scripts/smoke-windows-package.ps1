param([string]$Executable)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ExpectedVersion = (Get-Content -Raw -LiteralPath (Join-Path $RepositoryRoot "VERSION.txt")).Trim()
$SmokeData = Join-Path $RepositoryRoot ("build\smoke-runtime-" + [guid]::NewGuid().ToString("N"))
if (-not $Executable) {
    $Executable = Join-Path $RepositoryRoot "dist\ThermoPowerMonitor\ThermoPowerMonitor.exe"
}

if (-not (Test-Path -LiteralPath $Executable)) {
    throw "Pacote portátil ausente. Execute scripts\build-windows-engineering.ps1."
}
New-Item -ItemType Directory -Path $SmokeData -Force | Out-Null
$ManagedEnvironmentVariables = @(
    "THERMOPOWER_APP_DATA_DIR",
    "THERMOPOWER_DATABASE_URL",
    "THERMOPOWER_DEMO_ADMIN_EMAIL",
    "THERMOPOWER_DEMO_ADMIN_PASSWORD",
    "THERMOPOWER_ENVIRONMENT",
    "THERMOPOWER_FRONTEND_DIST",
    "THERMOPOWER_JWT_SECRET",
    "THERMOPOWER_MUTEX_NAME",
    "THERMOPOWER_NO_BROWSER",
    "THERMOPOWER_REPORT_OUTPUT_DIRECTORY"
)
$PreviousEnvironment = @{}
$Process = $null
try {
    foreach ($Name in $ManagedEnvironmentVariables) {
        $PreviousEnvironment[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process")
        [Environment]::SetEnvironmentVariable($Name, $null, "Process")
    }
    $env:THERMOPOWER_APP_DATA_DIR = $SmokeData
    $env:THERMOPOWER_NO_BROWSER = "1"
    $env:THERMOPOWER_ENVIRONMENT = "physical-alpha"
    $env:THERMOPOWER_MUTEX_NAME = "ThermoPowerMonitorSmoke-" + [guid]::NewGuid().ToString("N")
    $ExpectedDatabase = Join-Path $SmokeData "data\thermopower.db"
    $ExpectedPort = $null
    foreach ($Candidate in 8765..8804) {
        $Listener = [System.Net.Sockets.TcpListener]::new(
            [System.Net.IPAddress]::Loopback,
            $Candidate
        )
        try {
            $Listener.Start()
            $ExpectedPort = $Candidate
            break
        } catch {
            # Try the next local port.
        } finally {
            $Listener.Stop()
        }
    }
    if (-not $ExpectedPort) { throw "Nenhuma porta de smoke test está livre." }
    $Process = Start-Process -FilePath $Executable -WorkingDirectory $SmokeData `
        -PassThru -WindowStyle Hidden
    $Health = $null
    $Port = $null
    for ($Attempt = 0; $Attempt -lt 40 -and -not $Health; $Attempt++) {
        Start-Sleep -Milliseconds 500
        try {
            $Response = Invoke-RestMethod -Uri "http://127.0.0.1:$ExpectedPort/health" -TimeoutSec 1
            if ($Response.status -eq "ok" -and $Response.version -eq $ExpectedVersion) {
                $Health = $Response
                $Port = $ExpectedPort
            }
        } catch {
            # The launcher may still be applying migrations.
        }
        if ($Process.HasExited) { break }
    }
    if (-not $Health) {
        $LogPath = Join-Path $SmokeData "logs\thermopower.log"
        if (Test-Path -LiteralPath $LogPath) { Get-Content -LiteralPath $LogPath -Tail 80 }
        throw "O executável não respondeu ao health check."
    }
    $Spa = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/" -TimeoutSec 5
    $BuildInfo = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/build-info" -TimeoutSec 5
    if ($BuildInfo.version -ne $ExpectedVersion -or
        $BuildInfo.environment -ne "physical-alpha" -or
        $BuildInfo.demo_credentials.email -ne "homologacao@demo.thermopower.com" -or
        $BuildInfo.demo_credentials.password -ne "ThermoPower-HML@2026") {
        throw "A configuracao exibida pela UI nao corresponde ao usuario da build de engenharia."
    }
    if ($Spa.StatusCode -ne 200 -or -not $Spa.Content.Contains('id="root"')) {
        throw "A SPA empacotada nao respondeu com o root esperado."
    }
    $LoginBody = @{
        email = "homologacao@demo.thermopower.com"
        password = "ThermoPower-HML@2026"
    } | ConvertTo-Json
    $Login = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/auth/login" `
        -Method Post -ContentType "application/json" -Body $LoginBody -TimeoutSec 10
    if ($Login.user.email -ne "homologacao@demo.thermopower.com") {
        throw "O launcher nao autenticou o usuario de homologacao esperado."
    }
    $Headers = @{ Authorization = "Bearer $($Login.access_token)" }
    $Devices = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/devices" `
        -Headers $Headers -TimeoutSec 10
    $At4532 = $Devices | Where-Object { $_.protocol -eq "at4532_serial" } | Select-Object -First 1
    $Gpm8213 = $Devices | Where-Object { $_.protocol -eq "gpm8213_serial" } | Select-Object -First 1
    if (-not $At4532 -or $At4532.baud_rate -ne 19200) {
        throw "AT4532 ausente ou sem baud rate 19200."
    }
    if ($At4532.port -ne "COM5" -or
        -not $At4532.metadata.usb.manual_confirmed -or
        $At4532.metadata.usb.confirmed_port -ne "COM5") {
        throw "A associacao manual COM5 do AT4532 nao foi preservada."
    }
    if (-not $Gpm8213 -or $Gpm8213.serial_number -ne "GES913349") {
        throw "GPM-8213 ausente ou sem o serial USB confirmado."
    }
    if ($At4532.metadata.serial.parameters_source -ne "vendor_documented" -or
        $Gpm8213.metadata.serial.parameters_source -ne "vendor_documented") {
        throw "Os parametros seriais oficiais nao foram empacotados."
    }
    $OpenApi = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/openapi.json" -TimeoutSec 10
    $DiagnosticRoute = $OpenApi.paths.PSObject.Properties.Name -contains "/api/v1/hardware/serial-diagnostic/read"
    if (-not $DiagnosticRoute) { throw "A API de diagnostico serial read-only nao foi empacotada." }
    $ProtocolProbeRoute = $OpenApi.paths.PSObject.Properties.Name -contains "/api/v1/devices/{device_id}/protocol-probe"
    if (-not $ProtocolProbeRoute) { throw "A API de protocolo documentado nao foi empacotada." }
    $CombinedStatusRoute = $OpenApi.paths.PSObject.Properties.Name -contains "/api/v1/acquisition/combined-status"
    if (-not $CombinedStatusRoute) { throw "O status da aquisicao combinada nao foi empacotado." }
    $ConnectSourcesRoute = $OpenApi.paths.PSObject.Properties.Name -contains "/api/v1/devices/connect-sources"
    if (-not $ConnectSourcesRoute) { throw "A conexao independente por fonte nao foi empacotada." }
    $DiagnosticOpenSchema = $OpenApi.components.schemas.SerialDiagnosticOpenRequest
    $EngineeringConsent = $DiagnosticOpenSchema.properties.PSObject.Properties.Name -contains "use_engineering_assumption_8n1"
    if (-not $EngineeringConsent) { throw "O consentimento explicito para a hipotese 8-N-1 nao foi empacotado." }
    $ExecutableDirectory = Split-Path $Executable -Parent
    $FrontendAssets = Join-Path $ExecutableDirectory "frontend\assets"
    if (-not (Test-Path -LiteralPath $FrontendAssets)) {
        $FrontendAssets = Join-Path $ExecutableDirectory "_internal\frontend\assets"
    }
    $FrontendVersion = Get-ChildItem -LiteralPath $FrontendAssets -File |
        Select-String -SimpleMatch $ExpectedVersion -Quiet
    if (-not $FrontendVersion) { throw "O frontend empacotado nao contem a versao esperada." }
    $LogPath = Join-Path $SmokeData "logs\thermopower.log"
    if (-not (Test-Path -LiteralPath $LogPath) -or (Get-Item -LiteralPath $LogPath).Length -eq 0) {
        throw "thermopower.log nao foi criado com conteudo."
    }
    if (-not (Test-Path -LiteralPath $ExpectedDatabase -PathType Leaf) -or
        (Get-Item -LiteralPath $ExpectedDatabase).Length -eq 0) {
        throw "O banco SQLite isolado do smoke nao foi criado com conteudo."
    }
    $LogContent = Get-Content -Raw -LiteralPath $LogPath
    if (-not $LogContent.Contains("startup version=$ExpectedVersion")) {
        throw "thermopower.log nao registrou o startup posterior as migrations."
    }
    [pscustomobject]@{
        ProcessId = $Process.Id
        Port = $Port
        Health = $Health.status
        Version = $Health.version
        SpaStatus = $Spa.StatusCode
        SpaHasRoot = $Spa.Content.Contains('id="root"')
        LoginUser = $Login.user.email
        UiCredentialsMatch = $true
        At4532BaudRate = $At4532.baud_rate
        At4532ManualPort = $At4532.metadata.usb.confirmed_port
        GpmSerial = $Gpm8213.serial_number
        DocumentedProtocolProbe = $ProtocolProbeRoute
        CombinedAcquisitionStatus = $CombinedStatusRoute
        IndependentSourceConnection = $ConnectSourcesRoute
        DiagnosticReadOnlyRoute = $DiagnosticRoute
        Engineering8N1Consent = $EngineeringConsent
        FrontendVersion = $ExpectedVersion
        LogBytes = (Get-Item -LiteralPath $LogPath).Length
        DatabaseCreated = $true
        DatabaseBytes = (Get-Item -LiteralPath $ExpectedDatabase).Length
    }
} finally {
    try {
        if ($Process -and -not $Process.HasExited) {
            Stop-Process -Id $Process.Id
            Wait-Process -Id $Process.Id -ErrorAction SilentlyContinue
        }
    } finally {
        foreach ($Name in $ManagedEnvironmentVariables) {
            if ($PreviousEnvironment.ContainsKey($Name)) {
                [Environment]::SetEnvironmentVariable(
                    $Name,
                    $PreviousEnvironment[$Name],
                    "Process"
                )
            }
        }
    }
}
