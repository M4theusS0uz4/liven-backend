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
# Copie as variáveis locais e suba PostgreSQL com volume persistente
Copy-Item .env.example .env
docker compose up -d postgres

# Instale dependências e aplique as migrations
.\.venv\Scripts\Activate.ps1 # opcional, se o ambiente virtual existir
pip install -r backend\requirements.txt
Set-Location backend
alembic upgrade head
python seed.py
Set-Location ..

# Inicie a API pela raiz do repositório
python -m uvicorn main:app --reload --port 8000

# em outro terminal
Set-Location frontend
npm install
npm run dev
```

O entrypoint da raiz encaminha para `backend.main`; também é possível executar
diretamente com `Set-Location backend; python -m uvicorn main:app --reload --port 8000`.

## Login de demonstração

```powershell
$login = Invoke-RestMethod http://localhost:8000/api/v1/auth/login -Method Post -ContentType 'application/json' -Body '{"telefone":"11999999999","perfil":"portaria","codigo":"123456"}'
$token = $login.access_token
Invoke-RestMethod http://localhost:8000/api/v1/unidades -Headers @{Authorization="Bearer $token"}
```

Os perfis são `morador`, `portaria` e `sindico`. Portaria e síndico acessam
módulos administrativos; morador fica limitado aos próprios recursos. Durante
o desenvolvimento, `X-User-Profile` e `X-User-Phone` continuam aceitos como
compatibilidade temporária. O código `123456` é exclusivo da apresentação e
deve ser removido antes de qualquer ambiente real.

API de teste: `GET http://localhost:8000/api/v1/health`.

O endpoint facial demonstrativo recebe multipart no campo `image`:

```powershell
curl.exe -X POST http://localhost:8000/api/v1/facial/validate `
  -H "Authorization: Bearer <access_token>" `
  -F "image=@C:\caminho\imagem.jpg"
```

Ele aceita JPEG, PNG ou WebP de até 5 MB, processa a imagem em memória e
retorna `demo: true`. Nenhuma imagem original é persistida.

## Validação de integração

Com Docker Desktop em execução, na raiz deste repositório:

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose ps
docker compose exec backend alembic current
Invoke-RestMethod http://localhost:8000/api/v1/health
Invoke-WebRequest http://localhost:8000/api/v1/health -Headers @{Origin="http://localhost:5173"}
```

O comando do serviço `backend` executa `alembic upgrade head` antes do Uvicorn.
Para validar o frontend em outro terminal:

```powershell
Set-Location ..\liven-frontend\frontend
npm install
Get-Content .env.local # deve conter VITE_API_URL=http://localhost:8000/api/v1, se existir
npm run lint
npm run build
npm run dev
```

Os fluxos de mapa e entregas consultam a API; os endpoints usados são
`/api/v1/unidades`, `/api/v1/moradores` e `/api/v1/entregas`.

## Docker (backend e PostgreSQL)

O frontend continua sendo executado localmente em `http://localhost:5173`.

```powershell
Copy-Item .env.example .env
docker compose up --build
```

A API ficará disponível em `http://localhost:8000`, compatível com a origem
local padrão configurada em CORS. O volume nomeado `liven_postgres_data`
preserva os dados após `docker compose down`; use `docker compose down -v`
somente quando desejar removê-los.
