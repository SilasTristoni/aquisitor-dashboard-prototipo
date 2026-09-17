# ThermoPower 0.6.3-client-preview

Esta rodada melhora a recuperação térmica e a operação da interface. A [auditoria completa](UX_AUDIT_CLIENT_PREVIEW.md) registra os problemas, as soluções, as evidências e os limites da investigação.

## Recuperação do AT4532

A recuperação anterior reabria a COM após qualquer timeout. Uma fixture reproduziu intervalos de seis segundos ao repetir o timeout de identidade e o FETCH de fallback em cada reconexão. Agora, um timeout isolado com porta aberta é repetido na mesma conexão, respeitando a guarda serial. Três timeouts consecutivos ou uma falha real do transporte iniciam reconexão controlada.

Os testes saudáveis de 100 e 300 FETCH resultaram em intervalo de 1.000 ms e zero reconexões. O cenário de timeout isolado também terminou com zero reconexões e retomou 1 Hz; o cenário de três timeouts consecutivos fez uma reconexão antes da próxima leitura válida. O teste de persistência manteve a sessão e as sequências únicas durante duas recuperações.

O mecanismo de amplificação foi comprovado no software. Os anexos físicos mostram a cadência reduzida, mas não incluem os logs de transação necessários para confirmar o gatilho exato da sessão 14. A taxa física esperada continua próxima de uma leitura por segundo quando a fonte responde normalmente; não há garantia artificial de frequência nem preenchimento de dados.

## Operação

- Botão principal acompanha conexão, início, pausa e finalização; resultados ficam acessíveis ao concluir.
- Navegação agrupada, informações secundárias recolhidas e controles maiores.
- Sessão completa usa os horários exatos; estabilização precisa de confirmação e exportações seguem o período aplicado.
- Integridade explica contagens, frequência reduzida, ausências e canais Open.
- Legenda permite ocultar/restaurar séries; eixos, cores, cálculos e marcadores permanecem preservados.
- Diagnóstico consultivo mostra cadência e recuperação sem abrir a serial novamente.
- Relatório técnico usa texto legível para qualidade e layout mais compacto; resumo executivo permanece em uma página na fixture.

## Uso na bancada

1. Extraia o novo ZIP em uma pasta própria e execute `ThermoPowerMonitor.exe`.
2. Use o acesso local já configurado. Em uma instalação nova, siga o primeiro acesso gerado localmente; o pacote não incorpora senha fixa de cliente.
3. Conecte as fontes e inicie um ensaio de pelo menos cinco minutos.
4. Em Avançado → Diagnóstico, confira intervalo configurado/observado e os contadores do AT. Consultar essa tela não interrompe a aquisição.
5. Finalize, abra os resultados e exporte usando “Sessão completa”. Capture os contadores/logs antes de desconectar.

Não execute probe de comunicação durante uma aquisição saudável. A aplicação informa quando a COM pertence ao próprio ThermoPower. O ensaio físico final com GPM + AT4532 permanece pendente.

## Limites preservados

O painel ao vivo mantém o limite existente de 3.600 mensagens e não recarrega todo o histórico ao voltar à tela. Relatórios usam os dados persistidos. O simulador permanece disponível no desenvolvimento; a client-preview mantém a configuração de operação física já adotada.

## Entrega validada

Build e testes concluídos em 16/09/2026; publicação preparada em 17/09/2026.

| Verificação | Resultado |
| --- | --- |
| Regressões com fixtures físicas | 64 testes aprovados (subconjunto do backend) |
| Backend completo | 162 testes aprovados; 14 avisos de depreciação de dependências |
| Frontend | 35 testes em 11 arquivos aprovados |
| Ruff, ESLint e TypeScript | Aprovados |
| Alembic upgrade/check e pip check | Aprovados; nenhuma migration nova necessária |
| Compose | Configuração aprovada com binário oficial standalone; containers não executados |
| Vite e PyInstaller | Aprovados |
| Smoke isolado do executável | Saúde, autenticação, SPA, versão, aquisição e rotas de relatórios aprovadas |
| Revisão visual | 88 combinações de 22 telas/estados; zero erros JavaScript ou transbordamentos horizontais |
| Documentos sintéticos | PDF técnico, executivo, imagens e XLSX conferidos; executivo com uma página |
| Integridade do pacote | ZIP extraído e arquivos comparados ao manifesto SHA-256 pelo empacotador |

- Versão: **0.6.3-client-preview**.
- Commit do código usado no executável: `7edca141a9341d401c89201d03f2d8440e880de3`.
- ZIP: `engineering/ThermoPower-0.6.3-client-preview.zip`.
- Tamanho: **56.185.372 bytes**.
- SHA-256: `17165038B828DDBB5CBF5E278845979D8F1830B19A68E295CE413F97DE6862F7`.
- Evidências embarcadas: `TEST-RESULTS.txt` e `SHA256SUMS.txt`.
- Auditoria local: `build/ux-review/visual-results.json` e capturas no mesmo diretório.

A atualização final desta documentação é posterior ao empacotamento e não altera o código executável. O checksum do ZIP da 0.6.2 permanece idêntico ao registrado anteriormente; as builds anteriores foram preservadas. Nenhum anexo ou série real da sessão 14 foi incluído no Git ou no ZIP.

**Homologação física final pendente**, conforme o roteiro acima. Os resultados automatizados não substituem um novo ensaio com os dois equipamentos reais.
