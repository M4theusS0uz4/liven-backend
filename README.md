# Liven — Arquitetura Local

Sistema web local para controle de acesso condominial e automação residencial.

## Arquitetura

- **Frontend:** React, Vite e Tailwind CSS (`frontend/`).
- **Backend:** FastAPI e SQLAlchemy (`backend/`).
- **Dados:** PostgreSQL local, versionado com Alembic.
- **Visão computacional:** módulos Python locais com OpenCV/DeepFace, a serem conectados aos endpoints de acesso.

Não há Supabase, serviços cloud, Gemini ou proxy Express nesta base.

## Estrutura

```text
backend/
  alembic/             # migrações PostgreSQL
  config/              # ambiente e conexão de banco
  models/              # entidades SQLAlchemy
  main.py              # aplicação FastAPI
frontend/
  src/components/      # componentes reutilizáveis e SVG
  src/pages/           # painel, mapa e entregas
  src/lib/api.ts       # cliente HTTP da API local
```

## Execução

```powershell
# PostgreSQL: crie o banco e o usuário localmente conforme backend/.env.example
cd backend
Copy-Item .env.example .env
pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --reload --port 8000

# em outro terminal
cd frontend
npm install
npm run dev
```

API de teste: `GET http://localhost:8000/api/v1/health`.

## Docker (backend e PostgreSQL)

O frontend continua sendo executado localmente em `http://localhost:5173`.

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Em outro terminal, aplique a migração inicial manualmente:

```powershell
docker compose exec backend alembic upgrade head
```

A API ficará disponível em `http://localhost:8000`, compatível com a origem
local padrão configurada em CORS. O volume nomeado `liven_postgres_data`
preserva os dados após `docker compose down`; use `docker compose down -v`
somente quando desejar removê-los.
