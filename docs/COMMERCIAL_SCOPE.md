# Escopo comercial

## Implementado

Aplicação web full-stack; autenticação/RBAC; equipamentos; 16 canais; simulador e cenários; sessões; persistência; WebSocket; alertas/cooldown; eventos; dashboards; paginação; estatísticas; comparação; diagnóstico; CSV/XLSX/PDF; API documentada; migrations; Docker; testes e layout responsivo.

## Dependente do equipamento

Driver, descoberta automática de porta, protocolo definitivo, comandos de configuração, firmware, checksum, frequência sustentada, reconexão específica, sinais de sensor aberto e precisão. Os adaptadores e parsers estão prontos para homologação, não certificados.

## Riscos de integração

- USB pode não ser serial/CDC;
- protocolo pode ser proprietário ou exigir SDK/licença;
- timestamp pode vir do hardware ou depender do relógio do computador;
- alta frequência pode exigir processo nativo, buffering e storage especializados;
- precisão e calibração podem exigir rastreabilidade metrológica.

## Fora do escopo atual

Certificação regulatória, assinatura digital, aplicativo desktop/instalador, alta disponibilidade multi-site, suporte offline sincronizado, SSO corporativo, notificações externas, backup gerenciado e manutenção de drivers de terceiros.

## Módulos adicionais possíveis

Modbus RTU/TCP, USB HID, SDK proprietário, ingestão de arquivos, API HTTP, alarmes por e-mail/Teams/WhatsApp, trilha 21 CFR Part 11, manutenção preditiva e multi-tenant.

## Orçamento e implantação

Separe comercialmente: licença do software, homologação por modelo/firmware, instalação, treinamento, infraestrutura, migração, SLA/suporte e evolução. Faça prova de conceito paga com o aquisitor antes de fechar prazo fixo da integração física. Reserve contingência para driver/protocolo e estabeleça critérios de precisão, frequência, perda e recuperação.
