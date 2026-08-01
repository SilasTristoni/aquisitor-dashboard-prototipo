# Implantação

## Compose

1. Copie `.env.example` para `.env`.
2. Gere segredo JWT aleatório e senhas fortes.
3. Execute `docker compose up --build -d`.
4. Verifique `http://localhost:8080/health` e `docker compose ps`.

O Nginx serve a SPA e encaminha REST/WebSocket para o FastAPI. O backend espera o PostgreSQL saudável e executa `alembic upgrade head`.

## Produção

- termine TLS em proxy reverso confiável;
- restrinja CORS e firewall;
- use secret manager, backup com teste de restauração e observabilidade externa;
- execute aquisição em um worker único por dispositivo;
- monte portas seriais explicitamente somente após homologação;
- monitore disco, crescimento de tabelas, latência e perda de amostras;
- troque/remova a conta de demonstração.

## Limite validado

Os arquivos foram criados para Compose, mas o host de desenvolvimento desta entrega não possui Docker instalado. Portanto, build e comunicação local foram validados pelos runtimes Python/Node; a subida dos contêineres deve ser confirmada em host com Docker.
