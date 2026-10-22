# Identidade corporativa — 0.7.1 r2

Entre como administrador e abra **Configuração → Identidade corporativa**.
Informe empresa e, opcionalmente, unidade/laboratório; clique em **Salvar identificação**.
Envie somente um logotipo cujo uso esteja autorizado. O logotipo oficial da Britânia
não foi fornecido nem incluído nesta candidata.

PNG ou JPEG estático, até 1 MB, largura de 16 a 2048 px e altura de 16 a 1024 px.
O servidor verifica o conteúdo, rejeita animações e recodifica para PNG sem metadados.
SVG, HTML, imagens inválidas e URLs externas não são aceitos.
**Remover logotipo** preserva os textos; limpar o nome da empresa retorna à apresentação neutra.

Os dados ficam na tabela `company_identity`, no banco desta instalação. Somente
administradores podem alterá-los. A marca ThermoPower continua presente.
PDFs gerados após a configuração usam a identidade atual; arquivos existentes
não são reescritos. CSV e XLSX mantêm sua estrutura e não recebem logotipos.

Em **Compartilhar resultado**, marque explicitamente **Autorizar identidade corporativa
neste resultado** para incluí-la. A opção começa desmarcada. A cópia da identidade
fica vinculada ao compartilhamento e não muda quando a configuração administrativa
é editada. Para publicar outra identidade, crie outro compartilhamento.
Não reutilize a mesma instalação/credencial de publicação entre empresas diferentes.
O portal mantém a propriedade por instalação/empresa e protege a integridade do snapshot.

O Render precisa receber a atualização de contrato e viewer da r2 para aceitar e
mostrar snapshots com identidade. Sem essa atualização, mantenha a opção desmarcada.
Não houve deploy automático nesta entrega. Revogação, senha, expiração e permissões
mantêm a implementação anterior.
