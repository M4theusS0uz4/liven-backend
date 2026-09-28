import hashlib
import hmac
import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from config.config import env
from models.orm import Auditoria, Condominio

HASH_GENESIS = "0" * 64
_CHAVE = hmac.new(env["JWT_SECRET"].encode(), b"liven-auditoria-v1", hashlib.sha256).digest()


def _calcular_hash(hash_anterior: str, r: Auditoria) -> str:
    criado_em = r.criado_em.astimezone(timezone.utc).isoformat()
    conteudo = json.dumps(
        [hash_anterior, r.condominio_id, r.usuario_id, r.acao, r.recurso,
         r.recurso_id, r.endereco_ip, r.detalhes, criado_em],
        ensure_ascii=False,
    )
    return hmac.new(_CHAVE, conteudo.encode(), hashlib.sha256).hexdigest()


def registrar_auditoria(
    db: Session,
    *,
    condominio_id: int,
    acao: str,
    recurso: str,
    usuario_id: int | None = None,
    recurso_id: int | None = None,
    endereco_ip: str | None = None,
    detalhes: dict | None = None,
) -> Auditoria:
    # trava a linha do condomínio: um registro por vez na corrente
    db.execute(select(Condominio.id).where(Condominio.id == condominio_id).with_for_update())
    hash_anterior = db.scalar(
        select(Auditoria.hash_atual)
        .where(Auditoria.condominio_id == condominio_id, Auditoria.hash_atual.is_not(None))
        .order_by(Auditoria.id.desc())
        .limit(1)
    ) or HASH_GENESIS

    registro = Auditoria(
        condominio_id=condominio_id,
        usuario_id=usuario_id,
        acao=acao,
        recurso=recurso,
        recurso_id=recurso_id,
        endereco_ip=endereco_ip,
        detalhes=json.dumps(detalhes, ensure_ascii=False, sort_keys=True) if detalhes else None,
        criado_em=datetime.now(timezone.utc),
        hash_anterior=hash_anterior,
    )
    registro.hash_atual = _calcular_hash(hash_anterior, registro)
    db.add(registro)
    db.commit()
    db.refresh(registro)
    return registro


def verificar_integridade(db: Session, condominio_id: int) -> tuple[bool, int | None]:
    esperado = HASH_GENESIS
    registros = db.scalars(
        select(Auditoria)
        .where(Auditoria.condominio_id == condominio_id, Auditoria.hash_atual.is_not(None))
        .order_by(Auditoria.id)
    )
    for r in registros:
        calculado = _calcular_hash(esperado, r)
        if r.hash_anterior != esperado or not hmac.compare_digest(calculado, r.hash_atual):
            return False, r.id
        esperado = r.hash_atual
    return True, None