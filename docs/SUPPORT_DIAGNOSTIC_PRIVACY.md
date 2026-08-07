# Privacidade do diagnóstico de suporte

O pacote exporta somente informações técnicas do aplicativo, Windows e dispositivos COM/PnP relacionados. Antes da exportação, a mesma representação sanitizada é mostrada na tela.

Não entram no ZIP: senhas, tokens, JWT, segredo local, banco SQLite, medições completas, arquivos pessoais, conteúdo de Documentos, inventário de rede ou nome de usuário quando desnecessário. Caminhos do perfil são substituídos por `%USERPROFILE%` e chaves sensíveis viram `[REMOVIDO]`.

Consentimento apresentado: “Este pacote contém apenas informações técnicas dos dispositivos e do aplicativo.”
