# Backend Liven

API FastAPI local conectada ao PostgreSQL via SQLAlchemy.

```powershell
Copy-Item .env.example .env
pip install -r requirements.txt
alembic upgrade head
python seed.py
python -m uvicorn main:app --app-dir . --reload --port 8000
```

A partir da raiz do repositório, use `python -m uvicorn main:app --reload
--port 8000`; o `main.py` da raiz encaminha para `backend.main`.

A migração inicial cria `unidades`, `moradores`, `entregas` e `registros_acesso`.
A migração `20260916_0003` cria condomínios, usuários, OTP, sessões, porteiros,
visitantes, autorizações, QR Codes, comunicados, ocorrências e auditoria.

## Execução com Docker

O Docker Compose está na raiz do repositório. Copie `.env.example` para `.env`
e inicie os serviços com `docker compose up --build`. O comando do backend
aplica automaticamente `alembic upgrade head` antes de iniciar o Uvicorn.

No Docker, `DATABASE_URL` é fornecida pelo Compose e usa o hostname interno
`postgres`; não utilize `localhost` para a comunicação entre os containers.

API de teste: `GET http://localhost:8000/api/v1/health`.

Para executar os testes automatizados:

```powershell
pip install -r requirements.txt
LIVEN_TEST_DATABASE_URL=<URL_POSTGRES_DESCARTAVEL_LIVEN_TEST> pytest -q
```

Teste facial demonstrativo:

```powershell
curl.exe -X POST http://localhost:8000/api/v1/facial/validate `
	-H "Authorization: Bearer <access_token>" `
	-F "image=@C:\caminho\imagem.jpg"
```

O endpoint aceita JPEG, PNG ou WebP de até 5 MB, processa a imagem somente em
memória e não armazena o arquivo nem dados biométricos. O resultado é
explicitamente marcado com `demo: true`.

Para simular a criação dos dados locais depois das migrações (sem alterar dados):

```powershell
python seed.py
```

O login usa `POST /api/v1/auth/request-otp` e `POST /api/v1/auth/verify-otp`.
Somente `APP_ENV=development` com `MOCK_OTP=true` devolve `codigo_mock`.
O Resend é configurável para e-mail; sem provedor válido a solicitação retorna 503.
A migration `20261110_0008` permanece pendente. OTP usa e-mail e condomínio.
`/auth/login` retorna 410 e headers de perfil não autenticam.

Veja [o guia completo de OTP](docs/OTP.md), incluindo seed com aprovação,
contratos, migração incremental e testes PostgreSQL isolados.

Todas as rotas de domínio exigem `Authorization: Bearer <access_token>`.
Defina `JWT_SECRET` com um valor aleatório de pelo menos 32 caracteres e nunca
commite o arquivo `.env`.

O mapa usa coordenadas normalizadas entre `0` e `1`. As posições são
persistidas em `mapa_unidades` e podem ser cadastradas em
`POST /api/v1/condominio/mapa/unidades` ou alteradas em
`PATCH /api/v1/condominio/mapa/unidades/{id}`. O endpoint de leitura é
`GET /api/v1/condominio/mapa` e não retorna dados pessoais dos moradores.

## Gmail SMTP

O provedor opcional `OTP_EMAIL_PROVIDER=smtp` utiliza STARTTLS na porta 587 e senha
de app por variáveis de ambiente. Veja [configuração e testes SMTP](docs/SMTP.md).
O Resend e os contratos OTP existentes permanecem disponíveis.

## Cadastro e login globais

Cadastro com e-mail, senha e confirmação OTP; login normal por e-mail e senha.
Sem dados fictícios ou vínculo automático de condomínio. Veja [contratos, migration e transição de contas antigas](docs/PASSWORD_AUTH.md).
O login recupera perfis já autorizados e mantém a seleção explícita quando há vários
condomínios. Veja [integração com usuários e permissões](docs/AUTHORIZATION.md).
