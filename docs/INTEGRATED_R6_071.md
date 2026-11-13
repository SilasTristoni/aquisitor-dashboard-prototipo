# ThermoPower Monitor 0.7.1 r6 — distribuição Windows

Pacote integrado para testes na Britânia, com recuperação de ensaios e melhorias
para sessões prolongadas consolidadas na master. Base funcional: `bbbd4dc`.
A revisão r6 identifica o novo empacotamento; a versão permanece
`0.7.1-engineering`. Consulte `build-info.json` para o commit exato do pacote.

## Instalação e uso

1. Extraia todo o ZIP para uma nova pasta local. Preserve as pastas e builds anteriores.
2. Mantenha `ThermoPowerMonitor.exe` e `_internal` juntos; não execute dentro do ZIP.
3. Abra `ThermoPowerMonitor.exe`. Python, Node e o repositório de desenvolvimento
   não são necessários. O navegador acessa o serviço local iniciado pelo executável.
4. Consulte `Manual do Usuario.pdf`, também disponível na ajuda da aplicação.

O primeiro acesso é gerado localmente em uma instalação nova; não há senha de
produção incorporada. O pacote não contém credenciais predefinidas do Render.
Configurações anteriores podem ser reutilizadas quando presentes no cofre do
mesmo usuário Windows. O portal exige configuração válida; `portal-viewer/` é o
viewer preparado para publicação, sem deploy automático.

## Atualização e recuperação

Encerre ensaios e faça backup antes de atualizar. A migration aditiva
`0015_session_recovery` cria os registros de instância e recuperação, preservando
medições. O launcher mantém o mecanismo existente de backup e atualização segura.
Não execute versões anteriores sobre o banco atualizado. Para voltar, restaure
um backup anterior em outra pasta, mantendo intacto o banco novo.

As medições confirmadas no banco são preservadas após interrupção do processo.
Ao reiniciar, a aplicação apresenta o ensaio interrompido e permite ao operador
retomar com o mesmo identificador ou encerrar como interrompido, mantendo o histórico.
Nenhuma aquisição física é reiniciada pela recuperação sem confirmação do operador.
As fontes elétrica e térmica continuam independentes.

**Dados ainda somente em memória podem ser perdidos em uma queda de energia.**
Não há promessa de perda zero. SQLite usa sincronização durável explícita, mas a
persistência também depende do sistema operacional e do armazenamento. Morte de
processo foi testada; queda elétrica real e estabilidade física contínua de
20–24 horas permanecem pendentes de homologação em bancada.

Consulte `SESSION_RECOVERY_071.md` para operação, limites, armazenamento e rollback.
As simulações de 20/24 horas representam volume e timestamps acelerados, não
operação física ininterrupta por esse período.

## Funcionalidades preservadas

Aquisição AT4532/GPM, correções físicas, identidade corporativa, ambiente DEMO,
portal/permissões, relatórios, exportações e layouts permanecem integrados.
Não houve mudança de protocolos, parsers, cadência ou política de conexão neste
empacotamento. Drivers USB do fabricante, quando exigidos pelo equipamento,
continuam sendo uma dependência do Windows e não são instalados por este ZIP.

Os traços visuais de 0 W são exclusivos de indisponibilidade GPM confirmada;
não são amostras físicas nem entram nos cálculos. Interrupção do processo e
lacunas desconhecidas não geram zeros presumidos. Históricos antigos sem eventos
confiáveis não podem ser reconstruídos. Detalhes em `INTEGRATED_R5_071.md`.

## Validação e suporte

`VALIDATION.json` registra os gates utilizados; `SOURCE-SHA256.json` identifica
os fontes e `SHA256SUMS.txt` permite verificar os arquivos distribuídos. O pacote
inclui runtime e bibliotecas, manual PDF, viewer e ferramentas de diagnóstico.
Não inclui banco, medições de clientes, credenciais, logs ou ambientes de desenvolvimento.
Ferramentas de caracterização física somente devem ser usadas em bancada controlada.

Esta é uma candidata para validação, não uma declaração de homologação física.
