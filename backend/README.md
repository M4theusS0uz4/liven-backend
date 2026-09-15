# Backend Liven

API FastAPI local conectada ao PostgreSQL via SQLAlchemy.

```powershell
Copy-Item .env.example .env
pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --reload --port 8000
```

A migração inicial cria `unidades`, `moradores`, `entregas` e `registros_acesso`.

## Execução com Docker

O Docker Compose está na raiz do repositório. Copie `../.env.example` para
`../.env`, inicie os serviços com `docker compose up --build` e aplique as
migrações manualmente com `docker compose exec backend alembic upgrade head`.

No Docker, `DATABASE_URL` é fornecida pelo Compose e usa o hostname interno
`postgres`; não utilize `localhost` para a comunicação entre os containers.
