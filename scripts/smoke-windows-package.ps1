$ErrorActionPreference = "Stop"
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ReleaseConfiguration = Get-Content -Raw -LiteralPath (Join-Path $RepositoryRoot "release-config.json") | ConvertFrom-Json
$ExpectedVersion = [string]$ReleaseConfiguration.version
$ExpectedEmail = [string]$ReleaseConfiguration.homologation.email
$ExpectedPassword = [string]$ReleaseConfiguration.homologation.password
$SmokeData = Join-Path $RepositoryRoot "build\smoke-runtime"
$Executable = Join-Path $RepositoryRoot "dist\ThermoPowerMonitor\ThermoPowerMonitor.exe"
$PreviousAppData = $env:THERMOPOWER_APP_DATA_DIR
$PreviousNoBrowser = $env:THERMOPOWER_NO_BROWSER

if (-not (Test-Path -LiteralPath $Executable)) {
    throw "Pacote portátil ausente. Execute scripts\build-windows.ps1 -SkipInstaller."
}
New-Item -ItemType Directory -Path $SmokeData -Force | Out-Null
$env:THERMOPOWER_APP_DATA_DIR = $SmokeData
$env:THERMOPOWER_NO_BROWSER = "1"
$ExpectedPort = $null
foreach ($Candidate in 8765..8804) {
    $Listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Candidate)
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
$Process = Start-Process -FilePath $Executable -PassThru -WindowStyle Hidden

try {
    $Health = $null
    $Port = $null
    for ($Attempt = 0; $Attempt -lt 40 -and -not $Health; $Attempt++) {
        Start-Sleep -Milliseconds 500
        try {
            $Response = Invoke-RestMethod -Uri "http://127.0.0.1:$ExpectedPort/health" -TimeoutSec 1
            if ($Response.version -eq $ExpectedVersion) {
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
    $PublicConfig = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/public-config" -TimeoutSec 5
    if ($PublicConfig.version -ne $ExpectedVersion) { throw "Frontend e health expõem versões diferentes." }
    if (-not $PublicConfig.login_prefill.enabled) { throw "Preenchimento de homologação não foi ativado." }
    if ($PublicConfig.login_prefill.email -ne $ExpectedEmail -or $PublicConfig.login_prefill.password -ne $ExpectedPassword) {
        throw "As credenciais apresentadas pela UI divergem de release-config.json."
    }
    $LoginBody = @{
        email = $PublicConfig.login_prefill.email
        password = $PublicConfig.login_prefill.password
    } | ConvertTo-Json
    $Login = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/auth/login" `
        -Method Post -ContentType "application/json" -Body $LoginBody -TimeoutSec 10
    $Headers = @{ Authorization = "Bearer $($Login.access_token)" }
    $Devices = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/devices" -Headers $Headers
    $Simulator = $Devices | Where-Object protocol -eq "simulator" | Select-Object -First 1
    $SessionBody = @{ device_id=$Simulator.id; name="Smoke pacote Windows"; sample_interval_ms=1000; sync_grid_ms=1000; sync_tolerance_ms=1500 } | ConvertTo-Json
    $Session = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/sessions" -Method Post -Headers $Headers -ContentType "application/json" -Body $SessionBody
    Start-Sleep -Seconds 3
    Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/sessions/$($Session.id)/finish" -Method Post -Headers $Headers | Out-Null
    $Report = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/api/v1/reports/sessions/$($Session.id).pdf" -Headers $Headers
    if ($Report.RawContentLength -lt 1000) { throw "Relatório PDF do smoke é inválido." }
    [pscustomobject]@{
        ProcessId = $Process.Id
        Port = $Port
        Health = $Health.status
        Version = $Health.version
        SpaStatus = $Spa.StatusCode
        SpaHasRoot = $Spa.Content.Contains('id="root"')
        LoginUser = $Login.user.email
        UiCredentialsMatch = $Login.user.email -eq $ExpectedEmail
        DatabaseCreated = Test-Path -LiteralPath (Join-Path $SmokeData "data\thermopower.db")
        SessionId = $Session.id
        ReportBytes = $Report.RawContentLength
        CleanShutdown = $true
    }
} finally {
    if (-not $Process.HasExited) { Stop-Process -Id $Process.Id }
    if ($null -eq $PreviousAppData) { Remove-Item Env:THERMOPOWER_APP_DATA_DIR -ErrorAction SilentlyContinue } else { $env:THERMOPOWER_APP_DATA_DIR = $PreviousAppData }
    if ($null -eq $PreviousNoBrowser) { Remove-Item Env:THERMOPOWER_NO_BROWSER -ErrorAction SilentlyContinue } else { $env:THERMOPOWER_NO_BROWSER = $PreviousNoBrowser }
}
