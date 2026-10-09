param([string]$Port = "COM5")
$ErrorActionPreference = "Stop"
$Executable = Join-Path $PSScriptRoot "ThermoPowerMonitor.exe"
if (-not (Test-Path -LiteralPath $Executable)) { throw "Execute dentro do pacote de engenharia integrado." }
$Arguments = @("--characterize-at4532-repeated-celsius", "--port", $Port)
Write-Host "Feche o ThermoPower e outros programas que usam $Port. Passivo 5 s + Celsius 3 vezes, 5 s cada."
$Process = Start-Process -FilePath $Executable -ArgumentList $Arguments -PassThru -Wait -WindowStyle Hidden
if ($Process.ExitCode -ne 0) { throw "Experimento interrompido. Abra o ThermoPower e exporte o diagnostico fisico completo." }
Write-Host "Observacao concluida. Abra o ThermoPower, execute os testes e use Exportar diagnostico fisico completo."
Write-Host "A evidencia Celsius sera incluida automaticamente no mesmo ZIP final. Homologacao pendente."
