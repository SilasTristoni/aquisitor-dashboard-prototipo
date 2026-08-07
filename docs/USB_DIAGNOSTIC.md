# Diagnóstico USB físico

O diagnóstico enumera COM via pySerial e, no Windows, tenta complementar o inventário com CIM/PowerShell. Bloqueio do PowerShell não interrompe a captura. A verificação de disponibilidade abre e fecha a porta com timeout zero e nunca chama `write`.

Cada `UsbSnapshot` registra versão, Windows/arquitetura, portas, metadados fornecidos pelo sistema, associação, sugestão e estado. `UsbSnapshotDiff` informa adições, remoções, alterações e mudança de COM mantendo o mesmo serial.

O ZIP contém HTML/PDF, JSONs, versão, log recente sanitizado, README e hashes internos. Uma lista positiva exclui banco, medições completas, credenciais, JWT, segredo, rede e arquivos pessoais. A usuária revisa a prévia e confirma o consentimento antes de exportar.

Aviso obrigatório: a detecção confirma somente que o Windows enumerou um dispositivo. Não confirma leitura ou homologação do instrumento.
