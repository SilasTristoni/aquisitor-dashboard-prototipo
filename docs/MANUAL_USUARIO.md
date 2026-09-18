# Manual do Usuário — ThermoPower Monitor

Guia para operadores de laboratório · edição 0.6.4-client-preview

## 1. O que é o ThermoPower Monitor

O ThermoPower Monitor acompanha ensaios elétricos e térmicos, guarda as leituras por sessão e gera documentos para análise. É possível trabalhar somente com potência e demais grandezas elétricas, somente com temperaturas ou com as duas fontes em conjunto. Os valores representam as leituras recebidas dos instrumentos; uma ausência de leitura não é convertida em zero.

## 2. Primeiro acesso

Extraia todo o pacote em uma pasta própria e abra ThermoPowerMonitor.exe. Mantenha a pasta de arquivos que acompanha o executável. Na primeira utilização, siga as orientações do arquivo PRIMEIRO-ACESSO.txt gerado na pasta de dados do usuário. Use o acesso disponibilizado pelo responsável pelo laboratório; não compartilhe sua senha. Se já existe uma instalação configurada, utilize o acesso habitual. O perfil de acesso determina quais ações aparecem na interface.

## 3. Tela principal

Em Tempo real você seleciona as fontes, conecta os instrumentos e inicia o ensaio. O botão principal acompanha a etapa atual. Durante a coleta, observe os indicadores, as curvas e os avisos. O menu separa Operação, Configuração e Avançado. Em Ajuda estão o guia, a versão do programa e o diagnóstico. A orientação inicial em quatro passos pode ser fechada com “Entendi, não mostrar novamente”.

## 4. Conectar equipamentos

Ligue os instrumentos, conecte os cabos e confirme com o responsável que a bancada está pronta. Selecione a fonte elétrica, a térmica ou ambas. Clique em Conectar e aguarde a confirmação. Em Equipamentos, confira o modelo e a porta identificada. Se houver dúvida sobre qual porta corresponde ao instrumento, solicite auxílio ao responsável; não altere configurações de comunicação por tentativa.

## 5. Status dos equipamentos

Conectado indica comunicação estabelecida. Desconectado indica ausência de conexão ativa. Uma mensagem de erro ou frequência reduzida pede atenção: observe qual fonte foi afetada e consulte o diagnóstico. A indicação de intervalo configurado é uma expectativa; o intervalo observado descreve as leituras efetivamente recebidas. Uma fonte pode continuar funcionando enquanto a outra apresenta falha.

## 6. Criar/iniciar ensaio

Informe um nome que identifique produto, amostra e data. Confira as fontes escolhidas e clique em Iniciar ensaio. Quando as duas fontes são solicitadas, o programa aguarda novas leituras compatíveis antes de confirmar o início; “Sincronizando fontes” é uma etapa de preparação. Se não for possível iniciar, confira as conexões e tente novamente. Para um ensaio de uma única fonte, selecione explicitamente apenas essa fonte.

## 7. Acompanhar potência e temperatura

Observe os valores atuais e a evolução ao longo do tempo. No gráfico combinado, temperaturas e potência têm escalas próprias. O instante zero corresponde ao início do ensaio. Clique na legenda para ocultar uma série e use Mostrar todos para restaurar a visualização. Ocultar uma curva não apaga medições nem altera os cálculos. Ao passar o cursor, consulte os valores disponíveis naquele instante.

## 8. Pausar/finalizar

Pausar interrompe a gravação de novas leituras na sessão; a comunicação pode permanecer ativa. Retomar continua o mesmo ensaio. Finalizar encerra a sessão e disponibiliza seus resultados. Aguarde a confirmação antes de fechar o programa ou desligar a bancada. Se aparecer erro ao finalizar, não presuma que o encerramento ocorreu: consulte o estado mostrado e tente novamente. Cancelar e excluir são ações diferentes e dependem das permissões do usuário.

## 9. Sessões

Abra Sessões para consultar o histórico. Selecione o ensaio para revisar identificação, instrumentos, indicadores, curvas e integridade. A comparação e as exportações ficam acessíveis nessa tela. Editar informações permite complementar a identificação do ensaio; não substitui uma nova coleta. Excluir uma sessão remove seus dados associados: use somente quando autorizado pelo laboratório.

## 10. Período de análise

Os indicadores e arquivos exportados correspondem ao período aplicado. Alterar datas nos campos é apenas preparar uma seleção: aplique o período e aguarde a atualização antes de analisar. Verifique início e fim mostrados na tela. A central de relatórios também permite consultar um intervalo que abrange diferentes sessões, mantendo a identificação de cada ensaio.

## 11. Sessão completa

Selecione Sessão completa para analisar desde o início até o fim registrado, incluindo os segundos exatos. Essa é a escolha indicada para conferir contagens, comportamento inicial e resultado global. Ao exportar, confira se esse período está aplicado.

## 12. Após estabilização

Quando houver uma sugestão de estabilização, examine a janela proposta e confirme em Usar este período. A sugestão precisa ser avaliada segundo o procedimento do laboratório; não é uma aprovação automática do produto. Ela não altera nem exclui o trecho inicial do ensaio. Se não houver informação suficiente, use a sessão completa ou um período personalizado.

## 13. Período personalizado

Escolha Personalizado, informe início e fim e aplique a seleção. O fim deve ser posterior ao início. Uma janela sem leituras não produz um relatório válido: ajuste as datas. Os arquivos usam a última janela aplicada com sucesso, mesmo se houver datas diferentes ainda em edição.

## 14. Pico de potência

O pico é a maior potência registrada no período aplicado. O marcador mostra valor e instante; ele não é uma média. Um pico fora da janela selecionada não aparecerá nessa análise. Para investigar a partida de um equipamento, confira também a sessão completa.

## 15. Energia

A energia, em Wh, estima o consumo pela potência medida ao longo do tempo. Ela depende tanto dos valores quanto da duração do ensaio. Lacunas extensas são excluídas para evitar atribuir consumo a trechos sem medições. Por isso, confira a integridade junto com a energia e não compare períodos diferentes sem considerar sua duração.

## 16. Temperatura máxima

É a maior temperatura válida registrada entre os canais considerados no período. Confira o canal e o instante associados. Quando não há leituras térmicas, o indicador mostra “—”; isso significa ausência de informação, não temperatura zero.

## 17. Canal crítico

Identifica o canal que apresentou a maior temperatura no período analisado. O nome configurado ajuda a localizar o ponto físico na amostra. “Crítico” identifica o destaque térmico do ensaio e, isoladamente, não significa reprovação. Avalie o resultado conforme os limites do procedimento.

## 18. ΔT

O ΔT máximo resume a maior diferença térmica entre os canais comparados em uma leitura válida. Confira quais canais participaram do cálculo nos detalhes. Ele não deve ser confundido com a temperatura máxima ou com a variação de um único canal ao longo de todo o ensaio. Sem dados suficientes para comparação, aparece “—”.

## 19. Integridade

Os avisos de integridade ajudam a identificar início sem amostras, lacunas, frequência reduzida e canais sem leitura. Abra os detalhes para ver contagens e intervalos por fonte. Um sensor aberto não fornece temperatura válida. A ausência de uma fonte que não foi selecionada é diferente de uma falha em uma fonte esperada. Confira as fontes e os detalhes antes de interpretar um aviso; não esconda períodos incompletos apenas para melhorar a aparência do relatório.

## 20. Exportar PDF

Na sessão, abra Exportar e escolha PDF técnico. Aguarde a preparação e salve o documento. Confira identificação, intervalo e fontes no arquivo. O relatório inclui indicadores, gráficos e detalhes conforme o conteúdo selecionado. O número de páginas depende do ensaio e das opções.

## 21. Resumo executivo

Escolha Resumo executivo · PDF para um documento compacto, ou Resumo executivo · PNG para uma imagem que pode ser compartilhada. Ambos usam a janela aplicada. Em sessão somente elétrica, temperatura máxima, canal crítico e ΔT aparecem como “—”. Essa condição permite gerar o resumo normalmente. Se ocorrer erro, use Tentar novamente e guarde o código exibido.

## 22. XLSX

XLSX técnico reúne resumo, curvas, estatísticas, leituras reais, dados sincronizados e metadados em abas. As leituras reais elétricas e térmicas ficam separadas. Contagens diferentes entre fontes podem refletir frequências distintas ou falhas; consulte a integridade. Trabalhe em uma cópia se precisar acrescentar cálculos na planilha.

## 23. CSV

O CSV permite levar os dados para outras ferramentas de análise. Confirme a janela antes de exportar. Ao abrir em uma planilha, confira interpretação de datas, separadores e unidades. Campos vazios representam valores indisponíveis e não devem ser substituídos automaticamente por zero.

## 24. Imagem do gráfico

Escolha Imagem do gráfico para salvar as curvas do período. Use o resumo executivo em PNG quando precisar também dos principais indicadores. A imagem é uma apresentação dos dados; preserve o relatório técnico ou a planilha para rastreabilidade e análise detalhada.

## 25. Comparar sessões

Em Comparar sessões, selecione de duas a oito sessões e execute a comparação. Verifique se produto, condições e duração permitem uma comparação adequada. Os indicadores auxiliam a investigação; não substituem os critérios de aprovação do laboratório.

## 26. Configuração de termopares

Em Termopares, identifique os canais pela posição física, habilite os usados no ensaio e revise limites e correções autorizadas. Confira a correspondência entre o sensor e o canal antes de iniciar. O ensaio registra sua configuração inicial para manter a identificação histórica. Não altere correções para forçar um resultado esperado.

## 27. Sessão somente elétrica

Selecione apenas o GPM-8213. Após conectar, inicie o ensaio e acompanhe potência e demais grandezas elétricas. Zero leituras térmicas é esperado nesse tipo de sessão. PDF técnico, resumo executivo, XLSX, CSV e imagens continuam disponíveis. Os indicadores térmicos mostram “—”, sem criar temperaturas fictícias.

## 28. Sessão combinada

Selecione GPM-8213 e AT4532, conecte as fontes e inicie o ensaio. Aguarde a sincronização inicial. As leituras de cada fonte mantêm seus próprios instantes e contagens. Se uma fonte falhar, observe o aviso e siga o procedimento do laboratório para continuar ou encerrar. Não execute testes de comunicação invasivos durante uma aquisição saudável.

## 29. Mensagens de erro

Leia primeiro a mensagem e a ação sugerida. Erros inesperados mostram um código semelhante a TP-EXP-A82F31. Anote esse código, o horário e a ação realizada. Uma falha na geração de um arquivo não apaga os dados da sessão. Tente novamente; se persistir, exporte o diagnóstico. Em Avançado → Eventos e logs, filtre por período, nível, categoria, sessão, equipamento ou código. “Mostrar detalhes técnicos” contém informações para o suporte.

## 30. Gerar pacote de diagnóstico

Em Avançado → Diagnóstico, clique em Exportar pacote de suporte. A mesma ação está em Ajuda e junto de erros relevantes. O arquivo ZIP pode ser gerado sem uma sessão ativa. Ele reúne versão, informações do sistema, estado dos equipamentos, contadores e logs sanitizados; não inclui a base de medições nem suas credenciais. Gerar esse pacote consulta o estado disponível e não inicia um teste de comunicação. Envie o ZIP ao canal de suporte acordado, junto do código do erro. Prefira exportá-lo antes de desconectar para conservar os contadores da conexão.

## 31. Perguntas frequentes

**Posso medir somente temperaturas?** Sim. Selecione somente a fonte térmica e confira os canais. Não haverá potência medida; consulte os indicadores disponíveis e os detalhes de integridade.

**O gráfico ao vivo voltou vazio ao retornar à tela?** A tela ao vivo mantém uma janela limitada de mensagens. Consulte a sessão e os relatórios para analisar as leituras persistidas.

**A porta está ocupada pelo ThermoPower?** A aquisição já está usando essa porta. Consulte o diagnóstico de estado. Para realizar um teste de comunicação, encerre o ensaio e desconecte a fonte antes.

**A porta está ocupada por outro programa?** Confira se outro programa de instrumentos mantém a conexão aberta. Feche-o conforme o procedimento do laboratório e tente conectar novamente.

**Um canal mostra sensor aberto?** Verifique a conexão e o termopar com a bancada em condição segura. Não interprete esse estado como zero grau.

**Por que a exportação difere do intervalo digitado?** Confirme se a janela foi aplicada. Campos ainda em edição não substituem o período analisado.

**Como informo a versão ao suporte?** Abra Ajuda → Sobre o ThermoPower. A tela informa versão, build, ambiente e data da build.

**Preciso reinstalar ao ocorrer um erro de relatório?** Não como primeira medida. Tente novamente, anote o código e gere o pacote de diagnóstico. Preserve seus dados e aguarde a orientação do suporte.
