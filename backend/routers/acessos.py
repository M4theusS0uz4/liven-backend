import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from config.database import get_db
from models.orm import Acesso, AutorizacaoAcesso, Morador, PerfilUsuario, QrCode, StatusAutorizacao, Usuario, Visitante
from schemas.plataforma import AcessoCreate, AcessoHistoricoRead, AcessoRead, FacialValidation, QrValidation, VisitanteCreate, VisitanteRead, VisitanteUpdate
from security import as_utc, get_current_user, hash_token, require_profiles, utcnow

router = APIRouter(tags=["Visitantes e acessos"])
DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[Usuario, Depends(get_current_user)]
Staff = Annotated[Usuario, Depends(require_profiles(PerfilUsuario.PORTARIA, PerfilUsuario.SINDICO))]


def _morador_do_usuario(db: Session, user: Usuario) -> Morador | None:
    return db.scalar(select(Morador).where(Morador.usuario_id == user.id, Morador.unidade.has(condominio_id=user.condominio_id)))


def _visitante(visitante_id: int, db: Session, user: Usuario) -> Visitante:
    visitante = db.scalar(select(Visitante).where(Visitante.id == visitante_id, Visitante.condominio_id == user.condominio_id))
    if visitante is None:
        raise HTTPException(status_code=404, detail="Visitante não encontrado.")
    return visitante


@router.get("/api/v1/visitantes", response_model=list[VisitanteRead])
def listar_visitantes(db: DbSession, user: CurrentUser) -> list[Visitante]:
    query = select(Visitante).where(Visitante.condominio_id == user.condominio_id)
    if user.perfil == PerfilUsuario.MORADOR:
        morador = _morador_do_usuario(db, user)
        if morador is None:
            return []
        query = query.where(Visitante.id.in_(select(AutorizacaoAcesso.visitante_id).where(AutorizacaoAcesso.morador_id == morador.id)))
    return list(db.scalars(query.order_by(desc(Visitante.id))).all())


@router.post("/api/v1/visitantes", response_model=VisitanteRead, status_code=status.HTTP_201_CREATED)
def criar_visitante(dados: VisitanteCreate, db: DbSession, user: CurrentUser) -> Visitante:
    visitante = Visitante(condominio_id=user.condominio_id, criado_por_id=user.id, **dados.model_dump())
    db.add(visitante)
    db.commit()
    db.refresh(visitante)
    return visitante


@router.get("/api/v1/visitantes/{visitante_id}", response_model=VisitanteRead)
def consultar_visitante(visitante_id: int, db: DbSession, user: CurrentUser) -> Visitante:
    visitante = _visitante(visitante_id, db, user)
    if user.perfil == PerfilUsuario.MORADOR and not db.scalar(select(AutorizacaoAcesso.id).where(AutorizacaoAcesso.visitante_id == visitante_id, AutorizacaoAcesso.morador_id == _morador_do_usuario(db, user).id)):
        raise HTTPException(status_code=404, detail="Visitante não encontrado.")
    return visitante


@router.put("/api/v1/visitantes/{visitante_id}", response_model=VisitanteRead)
def atualizar_visitante(visitante_id: int, dados: VisitanteUpdate, db: DbSession, user: CurrentUser) -> Visitante:
    visitante = consultar_visitante(visitante_id, db, user)
    for campo, valor in dados.model_dump().items():
        setattr(visitante, campo, valor)
    db.commit()
    db.refresh(visitante)
    return visitante


@router.delete("/api/v1/visitantes/{visitante_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir_visitante(visitante_id: int, db: DbSession, user: CurrentUser) -> None:
    visitante = consultar_visitante(visitante_id, db, user)
    visitante.ativo = False
    db.commit()


@router.get("/api/v1/visitantes/{visitante_id}/acessos", response_model=list[AcessoRead])
def listar_autorizacoes(visitante_id: int, db: DbSession, user: CurrentUser) -> list[AutorizacaoAcesso]:
    _visitante(visitante_id, db, user)
    query = select(AutorizacaoAcesso).where(AutorizacaoAcesso.visitante_id == visitante_id, AutorizacaoAcesso.condominio_id == user.condominio_id)
    if user.perfil == PerfilUsuario.MORADOR:
        morador = _morador_do_usuario(db, user)
        query = query.where(AutorizacaoAcesso.morador_id == (morador.id if morador else -1))
    return list(db.scalars(query.order_by(desc(AutorizacaoAcesso.id))).all())


@router.post("/api/v1/visitantes/{visitante_id}/acessos", response_model=AcessoRead, status_code=status.HTTP_201_CREATED)
def criar_autorizacao(visitante_id: int, dados: AcessoCreate, db: DbSession, user: CurrentUser) -> dict:
    if dados.fim <= dados.inicio or dados.fim <= utcnow():
        raise HTTPException(status_code=422, detail="Período de acesso inválido.")
    visitante = _visitante(visitante_id, db, user)
    morador = _morador_do_usuario(db, user) if user.perfil == PerfilUsuario.MORADOR else db.get(Morador, dados.morador_id)
    if morador is None or morador.unidade.condominio_id != user.condominio_id:
        raise HTTPException(status_code=403, detail="Acesso não autorizado.")
    if user.perfil == PerfilUsuario.MORADOR and not db.scalar(select(AutorizacaoAcesso.id).where(AutorizacaoAcesso.visitante_id == visitante.id, AutorizacaoAcesso.morador_id == morador.id)):
        if visitante.criado_por_id != user.id:
            raise HTTPException(status_code=403, detail="Acesso não autorizado.")
    autorizacao = AutorizacaoAcesso(
        condominio_id=user.condominio_id,
        visitante_id=visitante.id,
        morador_id=morador.id,
        unidade_id=morador.unidade_id,
        criado_por_id=user.id,
        inicio=dados.inicio,
        fim=dados.fim,
        limite_usos=dados.limite_usos,
    )
    raw_token = secrets.token_urlsafe(32)
    db.add(autorizacao)
    db.flush()
    db.add(QrCode(autorizacao_id=autorizacao.id, token_hash=hash_token(raw_token), expira_em=dados.fim, limite_usos=dados.limite_usos))
    db.commit()
    db.refresh(autorizacao)
    return {**AcessoRead.model_validate(autorizacao, from_attributes=True).model_dump(), "qr_token": raw_token}


@router.post("/api/v1/acessos/{acesso_id}/revogar", response_model=AcessoRead)
def revogar_acesso(acesso_id: int, db: DbSession, user: CurrentUser) -> AutorizacaoAcesso:
    acesso = db.scalar(select(AutorizacaoAcesso).where(AutorizacaoAcesso.id == acesso_id, AutorizacaoAcesso.condominio_id == user.condominio_id))
    if acesso is None:
        raise HTTPException(status_code=404, detail="Acesso não encontrado.")
    if user.perfil == PerfilUsuario.MORADOR:
        morador = _morador_do_usuario(db, user)
        if morador is None or acesso.morador_id != morador.id:
            raise HTTPException(status_code=403, detail="Acesso não autorizado.")
    acesso.status = StatusAutorizacao.REVOGADA
    acesso.revogada_em = utcnow()
    db.query(QrCode).filter(QrCode.autorizacao_id == acesso.id).update({QrCode.ativo: False})
    db.commit()
    return acesso


@router.post("/api/v1/acessos/validar-qr")
def validar_qr(dados: QrValidation, db: DbSession, user: Staff) -> dict:
    qr = db.scalar(select(QrCode).where(QrCode.token_hash == hash_token(dados.token), QrCode.ativo.is_(True)))
    if qr is None:
        raise HTTPException(status_code=401, detail="QR Code inválido ou expirado.")
    acesso = db.get(AutorizacaoAcesso, qr.autorizacao_id)
    if acesso is None or acesso.condominio_id != user.condominio_id or acesso.status != StatusAutorizacao.ATIVA or as_utc(acesso.fim) <= utcnow() or as_utc(qr.expira_em) <= utcnow() or qr.usos >= qr.limite_usos:
        raise HTTPException(status_code=401, detail="QR Code inválido ou expirado.")
    qr.usos += 1
    acesso.usos += 1
    if qr.usos >= qr.limite_usos:
        qr.ativo = False
    db.add(Acesso(condominio_id=user.condominio_id, visitante_id=acesso.visitante_id, autorizacao_id=acesso.id, morador_id=acesso.morador_id, unidade_id=acesso.unidade_id, visitante_nome=db.get(Visitante, acesso.visitante_id).nome, metodo="qr_code", permitido=True))
    db.commit()
    return {"permitido": True, "visitante_id": acesso.visitante_id, "unidade_id": acesso.unidade_id}


@router.post("/api/v1/acessos/validar-facial")
def validar_facial(_dados: FacialValidation, _user: Staff) -> dict:
    raise HTTPException(status_code=503, detail="Validação facial indisponível.")


@router.get("/api/v1/acessos/historico", response_model=list[AcessoHistoricoRead])
def historico_acessos(db: DbSession, user: Staff) -> list[Acesso]:
    return list(db.scalars(select(Acesso).where(Acesso.condominio_id == user.condominio_id).order_by(desc(Acesso.ocorrido_em)).limit(200)).all())