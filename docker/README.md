# Contêineres

O `docker-compose.yml` na raiz sobe PostgreSQL, FastAPI e o frontend servido pelo Nginx. A serial física requer configuração específica do host e não é mapeada automaticamente, pois o caminho varia por sistema operacional e equipamento.

Use um `.env` derivado de `.env.example` antes de qualquer exposição em rede.
