# Laboratório USB virtual

O executável `ThermoPowerVirtualLab.exe` usa banco e logs em `%LOCALAPPDATA%\ThermoPower Virtual Lab` e apresenta uma faixa roxa permanente. Ele oferece perfis sintéticos de 32 temperaturas AT4532 e grandezas elétricas GPM-8213, com plug/unplug, troca de COM, porta ocupada, driver ausente, metadados ausentes, falha e reconexão.

O laboratório percorre descoberta, associação, `DeviceAdapter`, aquisição, WebSocket, sessão, persistência e relatórios. Seus itens usam `source=virtual` e `simulated=true`; todos os estados físicos de validação permanecem falsos. O laboratório não enumera nem abre portas reais.

Perfis aceitam opções de intervalo, jitter, atraso, drift, sensores/canais ausentes, picos, valores elétricos ausentes e falha durante aquisição. Os endpoints `/api/v1/lab/usb/*` são recusados fora de desenvolvimento/teste ou habilitação explícita.

Uma porta virtual e `loop://` validam somente software. Não comprovam cabo, driver, VID/PID, firmware, framing, precisão ou protocolo do fabricante.
