$ErrorActionPreference = "Stop"
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ReleaseConfiguration = Get-Content -Raw -LiteralPath (Join-Path $RepositoryRoot "release-config.json") | ConvertFrom-Json
$ExpectedVersion = [string]$ReleaseConfiguration.version
$SmokeData = Join-Path $RepositoryRoot "build\smoke-virtual-lab"
$Executable = Join-Path $RepositoryRoot "dist\ThermoPowerVirtualLab\ThermoPowerVirtualLab.exe"
$PreviousAppData = $env:THERMOPOWER_APP_DATA_DIR
$PreviousNoBrowser = $env:THERMOPOWER_NO_BROWSER
if (-not (Test-Path -LiteralPath $Executable)) { throw "Executável do Virtual Lab ausente." }
New-Item -ItemType Directory -Path $SmokeData -Force | Out-Null
$env:THERMOPOWER_APP_DATA_DIR = $SmokeData
$env:THERMOPOWER_NO_BROWSER = "1"
$Port = $null
foreach ($Candidate in 8765..8804) {
    $Listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Candidate)
    try { $Listener.Start(); $Port = $Candidate; break } catch {} finally { $Listener.Stop() }
}
if (-not $Port) { throw "Nenhuma porta local livre." }
$Process = Start-Process -FilePath $Executable -PassThru -WindowStyle Hidden
try {
    $Health = $null
    for ($Attempt = 0; $Attempt -lt 60 -and -not $Health; $Attempt++) {
        Start-Sleep -Milliseconds 500
        try { $Health = Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 1 } catch {}
        if ($Process.HasExited) { break }
    }
    if (-not $Health) { throw "Virtual Lab não respondeu ao health check." }
    $PublicConfig = Invoke-RestMethod "http://127.0.0.1:$Port/api/v1/public-config"
    if ($Health.version -ne $ExpectedVersion -or $PublicConfig.version -ne $ExpectedVersion) { throw "Versão incoerente no Virtual Lab." }
    if (-not $PublicConfig.virtual_lab -or -not $PublicConfig.login_prefill.enabled) { throw "Configuração pública do Virtual Lab inválida." }
    $LoginBody = @{ email=$PublicConfig.login_prefill.email; password=$PublicConfig.login_prefill.password } | ConvertTo-Json
    $Login = Invoke-RestMethod "http://127.0.0.1:$Port/api/v1/auth/login" -Method Post -ContentType "application/json" -Body $LoginBody
    $Headers = @{ Authorization = "Bearer $($Login.access_token)" }
    $Runtime = Invoke-RestMethod "http://127.0.0.1:$Port/api/v1/runtime" -Headers $Headers
    if (-not $Runtime.virtual_lab) { throw "O executável não iniciou em modo Virtual Lab." }
    if ($Runtime.version -ne $ExpectedVersion) { throw "Runtime e health do Virtual Lab divergem." }
    $Initial = Invoke-RestMethod "http://127.0.0.1:$Port/api/v1/lab/usb/state" -Headers $Headers
    if ($Initial.devices.Count -ne 0) { throw "O laboratório não iniciou vazio." }
    foreach ($Item in @(@{profile="at4532";port="COM90"}, @{profile="gpm8213";port="COM91"})) {
        Invoke-RestMethod "http://127.0.0.1:$Port/api/v1/lab/usb/plug" -Method Post -Headers $Headers -ContentType "application/json" -Body ($Item | ConvertTo-Json) | Out-Null
    }
    $Discovery = Invoke-RestMethod "http://127.0.0.1:$Port/api/v1/hardware/discovery" -Headers $Headers
    if ($Discovery.Count -ne 2 -or ($Discovery | Where-Object { -not $_.simulated })) { throw "Descoberta virtual inválida." }
    $Devices = Invoke-RestMethod "http://127.0.0.1:$Port/api/v1/devices" -Headers $Headers
    $At = $Devices | Where-Object protocol -eq "virtual_at4532" | Select-Object -First 1
    $Gpm = $Devices | Where-Object protocol -eq "virtual_gpm8213" | Select-Object -First 1
    foreach ($Link in @(@{port="COM90";device_id=$At.id}, @{port="COM91";device_id=$Gpm.id})) {
        Invoke-RestMethod "http://127.0.0.1:$Port/api/v1/hardware/discovery/associate" -Method Post -Headers $Headers -ContentType "application/json" -Body ($Link | ConvertTo-Json) | Out-Null
    }
    $SessionBody = @{ name="Smoke Virtual Lab"; temperature_device_id=$At.id; electrical_device_id=$Gpm.id; sample_interval_ms=1000; sync_grid_ms=1000; sync_tolerance_ms=1500 } | ConvertTo-Json
    $Session = Invoke-RestMethod "http://127.0.0.1:$Port/api/v1/sessions" -Method Post -Headers $Headers -ContentType "application/json" -Body $SessionBody
    Start-Sleep -Seconds 4
    Invoke-RestMethod "http://127.0.0.1:$Port/api/v1/lab/usb/unplug" -Method Post -Headers $Headers -ContentType "application/json" -Body (@{port="COM90"}|ConvertTo-Json) | Out-Null
    Invoke-RestMethod "http://127.0.0.1:$Port/api/v1/lab/usb/plug" -Method Post -Headers $Headers -ContentType "application/json" -Body (@{profile="at4532";port="COM90"}|ConvertTo-Json) | Out-Null
    Invoke-RestMethod "http://127.0.0.1:$Port/api/v1/sessions/$($Session.id)/finish" -Method Post -Headers $Headers | Out-Null
    $Pdf = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/api/v1/reports/sessions/$($Session.id).pdf" -Headers $Headers
    $Jpeg = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/api/v1/reports/sessions/$($Session.id).jpeg" -Headers $Headers
    if ($Pdf.RawContentLength -lt 1000 -or $Jpeg.RawContentLength -lt 1000) { throw "Relatórios virtuais inválidos." }
    [pscustomobject]@{ Health=$Health.status; Version=$Runtime.version; UiCredentialsMatch=($Login.user.email -eq $PublicConfig.login_prefill.email); Devices=$Discovery.Count; Session=$Session.id; PdfBytes=$Pdf.RawContentLength; JpegBytes=$Jpeg.RawContentLength; CleanShutdown=$true }
} finally {
    if (-not $Process.HasExited) { Stop-Process -Id $Process.Id }
    if ($null -eq $PreviousAppData) { Remove-Item Env:THERMOPOWER_APP_DATA_DIR -ErrorAction SilentlyContinue } else { $env:THERMOPOWER_APP_DATA_DIR = $PreviousAppData }
    if ($null -eq $PreviousNoBrowser) { Remove-Item Env:THERMOPOWER_NO_BROWSER -ErrorAction SilentlyContinue } else { $env:THERMOPOWER_NO_BROWSER = $PreviousNoBrowser }
}
