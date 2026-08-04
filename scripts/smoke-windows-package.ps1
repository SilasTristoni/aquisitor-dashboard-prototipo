$ErrorActionPreference = "Stop"
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$SmokeData = Join-Path $RepositoryRoot "build\smoke-runtime"
$Executable = Join-Path $RepositoryRoot "dist\ThermoPowerMonitor\ThermoPowerMonitor.exe"

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
            if ($Response.version -eq "0.4.0-beta") {
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
    $LoginBody = @{
        email = "homologacao@demo.thermopower.com"
        password = "ThermoPower-HML@2026"
    } | ConvertTo-Json
    $Login = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/auth/login" `
        -Method Post -ContentType "application/json" -Body $LoginBody -TimeoutSec 10
    [pscustomobject]@{
        ProcessId = $Process.Id
        Port = $Port
        Health = $Health.status
        Version = $Health.version
        SpaStatus = $Spa.StatusCode
        SpaHasRoot = $Spa.Content.Contains('id="root"')
        LoginUser = $Login.user.email
        DatabaseCreated = Test-Path -LiteralPath (Join-Path $SmokeData "data\thermopower.db")
    }
} finally {
    if (-not $Process.HasExited) { Stop-Process -Id $Process.Id }
}
