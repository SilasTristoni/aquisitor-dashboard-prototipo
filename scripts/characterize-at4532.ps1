param([string]$Port = "COM5", [ValidateRange(5,10)][int]$PassiveSeconds = 10)
$ErrorActionPreference = "Stop"
$Executable = Join-Path $PSScriptRoot "ThermoPowerMonitor.exe"
if (-not (Test-Path -LiteralPath $Executable)) { throw "Execute dentro do pacote de engenharia." }
$Output = Join-Path $PSScriptRoot ("AT4532-observation-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff"))
$Arguments = @("--characterize-at4532", "--port", $Port, "--passive-seconds", $PassiveSeconds,
               "--output", ('"{0}"' -f $Output))
Write-Host "Feche o ThermoPower e outros programas que utilizem a porta $Port antes desta observacao."
Write-Host "Observando quatro janelas; resultado em $Output"
$Process = Start-Process -FilePath $Executable -ArgumentList $Arguments -PassThru -Wait -WindowStyle Hidden
if ($Process.ExitCode -ne 0) { throw "Caracterizacao interrompida. Consulte events.jsonl em $Output" }
Compress-Archive -LiteralPath $Output -DestinationPath "$Output.zip"
Get-FileHash -LiteralPath "$Output.zip" -Algorithm SHA256
Write-Host "Envie o ZIP de observacao. Nao representa homologacao fisica."
