param([string]$Port = "COM5")
$ErrorActionPreference = "Stop"
$Executable = Join-Path $PSScriptRoot "AT4532RepeatedCelsius.exe"
if (-not (Test-Path -LiteralPath $Executable)) { throw "Execute dentro do pacote de engenharia." }
$Capture = Join-Path $PSScriptRoot ("AT4532-repeated-celsius-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff"))
$Arguments = @("--port", $Port, "--output", ('"{0}"' -f $Capture))
Write-Host "Feche os programas que usam $Port. Sequencia: passiva 5 s + 3 comandos Celsius, 5 s cada."
$Process = Start-Process -FilePath $Executable -ArgumentList $Arguments -PassThru -Wait -WindowStyle Hidden
if (Test-Path -LiteralPath $Capture) {
    Compress-Archive -LiteralPath $Capture -DestinationPath "$Capture.zip"
    Get-FileHash -LiteralPath "$Capture.zip" -Algorithm SHA256
}
if ($Process.ExitCode -ne 0) { throw "Experimento interrompido; preserve o ZIP e consulte events.jsonl." }
Write-Host "Observacao concluida: $Capture.zip. Resultado pendente de analise de engenharia."
