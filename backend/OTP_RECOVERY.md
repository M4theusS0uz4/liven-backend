# Recuperação do cadastro após falha de e-mail

## Contratos preservados

- Solicitação: `POST /api/v1/auth/register/request-otp`, com e-mail e senha de 8–128 caracteres.
- Reenvio: `POST /api/v1/auth/register/resend-otp`, somente e-mail. Campos extras são rejeitados.
- Confirmação: `POST /api/v1/auth/register/verify-otp`, com e-mail, a mesma senha e código de seis dígitos.
- Login: `POST /api/v1/auth/login`, somente e-mail e senha, sem entrega de OTP.

As respostas públicas continuam genéricas para evitar enumeração. Não inferir envio
a partir de HTTP 200. Cadastro duplicado continua sem emissão, reativação ou troca de senha.
Login OTP legado permanece desativado por padrão. Nenhum perfil ou vínculo novo é criado.

## Persistência antes do transporte

O hash do OTP e a senha pendente são confirmados no PostgreSQL antes de chamar o provedor.
Uma conexão dedicada fica presa ao pedido e mantém um advisory lock por finalidade/e-mail
entre as transações. O lock de linha é retomado antes do envio. Isso preserva a serialização
entre solicitações e mantém o consumo único protegido pelo lock da confirmação.

Não há nova migration, fila ou armazenamento do OTP em texto claro. O serviço usa apenas
as tabelas existentes. Um código aceito pelo SMTP já está durável, sem commit de negócio
pendente após o aceite.

| Resultado do transporte | Estado do cadastro pendente |
| --- | --- |
| Aceito, inclusive com erro de QUIT | Novo desafio permanece válido; mantém cooldown e cota |
| Rejeição comprovada antes de aceite | Restaura desafio anterior, tentativas, cota e cooldown; retém a senha da primeira solicitação se ainda não havia uma |
| Conexão perdida durante envio, sem resposta conclusiva | Mantém novo desafio válido e cota reservada; registra resultado indeterminado |

Reenvio nunca recebe ou substitui a senha. Repetir uma solicitação com a mesma senha
reutiliza seu hash pendente. Uma solicitação completa com outra senha pode reiniciar
o cadastro, como antes; a confirmação continua exigindo a senha correspondente ao OTP.
Se essa nova tentativa for rejeitada pelo transporte, o estado anterior é restaurado.

As cotas originais de envio por e-mail/IP são devolvidas somente após rejeição comprovada
e restauração bem-sucedida no banco. A cota persistida de envios e o cooldown após sucesso
continuam iguais. Um orçamento separado limita tentativas a `2 * OTP_RATE_LIMIT` por e-mail
e `4 * OTP_RATE_LIMIT` por IP na janela OTP. Esse orçamento não é devolvido em falhas e é
persistido em `limites_login` com namespace `otp_attempt:`, separado do login por senha.

## Eventos internos sanitizados

Os eventos do serviço incluem finalidade, provedor, resultado, motivo e `request_id`
aleatório para correlação. Não contêm e-mail, senha, código, hash ou tokens.

- `challenge_prepared`: commit do desafio concluído antes do transporte.
- `delivery_started`: chamada ao provedor iniciada.
- `delivery_accepted`: provedor confirmou aceite; não comprova entrega ao destinatário.
- `delivery_failed`: rejeição comprovada, com estado anterior restaurado.
- `delivery_indeterminate`: envio pode ter sido aceito; resultado desconhecido.
- `skipped`: motivo como cooldown, limite persistido, conta existente ou ausência de pendência.
- `blocked`: limite de requisições/tentativas, com HTTP 429 genérico.
- `recovery_failed`: o banco não confirmou a restauração após rejeição.
- `lock_cleanup_failed`: conexão invalidada para não devolver advisory lock ao pool.

O transporte SMTP registra apenas etapa, classe da exceção e código numérico quando
disponível. Não habilitar debug SMTP. SMTP 235 prova autenticação; aceite da mensagem
não prova entrega ou presença na caixa principal/spam.

## Limites da solução síncrona

SMTP e PostgreSQL não têm transação distribuída. Uma interrupção do processo depois
do commit e antes do envio deixa um desafio persistido que talvez não tenha sido enviado.
Uma falha no banco durante restauração também pode manter a reserva conservadora.
Nesses casos, aguardar o cooldown e reenviar; não limpar registros ou contornar limites.
Não há retry automático, pois uma resposta perdida pode ocultar um envio já aceito.
Uma indisponibilidade do banco pode impedir confirmação até a recuperação do serviço.

## Reinício sem migrations automáticas

Confirmar primeiro que a revisão aplicada é `20261111_0011` (consulta somente leitura):

```sh
cd /Users/mateus/Downloads/liven-backend-main
docker compose exec -T backend alembic current
```

Se a revisão divergir, não aplicar migrations automaticamente: revisar o estado do banco.
Com a revisão correta, recriar somente o backend usando o override que omite Alembic:

```sh
docker compose -f docker-compose.yml -f docker-compose.no-migrations.yml up -d --no-deps --force-recreate backend
```

Esse procedimento não foi executado durante a implementação. Não altera `.env`, não
recria PostgreSQL nem executa seed. A configuração existente monta o código do backend;
esta correção não acrescenta dependências de execução.

## Uma tentativa real controlada pelo operador

1. Após o reinício, usar a tela de cadastro com um endereço controlado ainda não cadastrado
   e uma senha nova com pelo menos oito caracteres. Enviar uma única solicitação.
2. Não repetir nem clicar em reenvio durante essa tentativa. Consultar eventos sanitizados:
   `docker compose logs --since 5m backend | rg 'otp_request|otp_smtp'`.
3. Conferir `challenge_prepared`, `delivery_started` e o resultado do transporte. Se houver
   falha ou resultado indeterminado, registrar etapa/request_id e encerrar a tentativa.
4. Se a mensagem chegar, inserir o código somente na interface e confirmar com a senha
   inicial. Conferir autenticação automática. Não copiar OTP, senha ou tokens para logs.
5. Sair e entrar uma vez por e-mail/senha; isso não deve produzir outro envio SMTP.

Conta nova sem autorização de condomínio fica no escopo global. Acesso aos dados do
condomínio exige vínculo previamente autorizado. Aceite SMTP sem recebimento exige
evidências de entrega/rejeição do provedor ou cabeçalhos sanitizados do destinatário.

## Testes

`tests/test_registration_recovery.py` usa PostgreSQL descartável e SMTP simulado. Inclui
falha inicial, recuperação, reenvio, proteção da senha, cotas, concorrência, QUIT, envio
indeterminado, falhas de banco antes/depois do aceite, confirmação, sessão e login.
Nunca executar a suíte com banco principal; a fixture exige `liven_test_*` e recria tabelas.


## Resultado da validação desta correção

- Suíte completa: **198 aprovados e 1 falha preexistente**, em 173,24 segundos.
- Os **20 novos testes de recuperação** passaram, cobrindo os 12 cenários solicitados,
  concorrência, tentativa persistida entre workers e limpeza após aceite.
- A falha `test_api.py::test_mapa_persistido_sem_dados_sensiveis_e_posicoes` também foi
  reproduzida com os três serviços originais de HEAD, sem esta correção. O módulo de
  mapas e seu teste não foram alterados.
- Upgrade 0008 → 0011 validado em PostgreSQL novo e descartável: conta antiga sem senha,
  usuários e vínculos da fixture preservados; cadastro e autenticação no schema migrado.
- Sintaxe Python, `git diff --check` e Compose com override sem Alembic aprovados.
- A primeira execução integral, com tmpfs de 256 MiB, teve erros de preparação de testes;
  a execução final com 1 GiB não apresentou erros de preparação. Não foram observados
  disco cheio, crash, limite de conexões ou deadlock nos logs sanitizados da rodada final.
- Avisos de depreciação de Starlette/httpx e HTTP 422; sem alterações de dependências do projeto.
- Containers de teste sem portas publicadas, PostgreSQL em tmpfs e rede Docker interna
  separada dos serviços existentes. SMTP e HTTP de e-mail bloqueados pela fixture.
- Nenhum e-mail real, alteração de `.env`, migration no banco principal ou reinício
  explícito dos containers existentes foi executado.
