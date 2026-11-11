from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from config.database import get_db
from models.orm import ContaGlobal, SessaoGlobal
from schemas.auth import OtpRequestResponse, RefreshRequest
from schemas.registration import ContaGlobalRead, GlobalAuthResponse, GlobalOtpRequest, GlobalOtpVerify, PasswordRegistrationRequest, PasswordRegistrationVerify, SelecionarCondominio, VinculoRead
from security import bearer_scheme, hash_token, utcnow
from services.global_auth import get_current_global_account, refresh_global_session, request_global_otp, select_membership, verify_global_otp
from services.memberships import authorized_users, membership_read

router = APIRouter(prefix="/api/v1/auth", tags=["Contas globais"])


@router.post("/register/request-otp", response_model=OtpRequestResponse, response_model_exclude_none=True)
def request_registration(data: PasswordRegistrationRequest, request: Request, db: Session = Depends(get_db)):
    return request_global_otp(str(data.email), "cadastro", request, db, data.senha.get_secret_value())


@router.post("/register/verify-otp", response_model=GlobalAuthResponse, status_code=201)
def verify_registration(data: PasswordRegistrationVerify, db: Session = Depends(get_db)):
    return verify_global_otp(str(data.email), data.codigo, "cadastro", db, data.senha.get_secret_value())


@router.post("/register/resend-otp", response_model=OtpRequestResponse, response_model_exclude_none=True)
def resend_registration(data: GlobalOtpRequest, request: Request, db: Session = Depends(get_db)):
    return request_global_otp(str(data.email), "cadastro", request, db, resend=True)


@router.post("/password/setup/request-otp", response_model=OtpRequestResponse, response_model_exclude_none=True)
def request_password_setup(data: PasswordRegistrationRequest, request: Request, db: Session = Depends(get_db)):
    return request_global_otp(str(data.email), "definicao_senha", request, db, data.senha.get_secret_value())


@router.post("/password/setup/verify-otp", response_model=GlobalAuthResponse)
def verify_password_setup(data: PasswordRegistrationVerify, db: Session = Depends(get_db)):
    return verify_global_otp(str(data.email), data.codigo, "definicao_senha", db, data.senha.get_secret_value())


@router.post("/global/request-otp", response_model=OtpRequestResponse, response_model_exclude_none=True, deprecated=True)
def request_global_login(data: GlobalOtpRequest, request: Request, db: Session = Depends(get_db)):
    return request_global_otp(str(data.email), "login_global", request, db)


@router.post("/global/verify-otp", response_model=GlobalAuthResponse, deprecated=True)
def verify_global_login(data: GlobalOtpVerify, db: Session = Depends(get_db)):
    return verify_global_otp(str(data.email), data.codigo, "login_global", db)


@router.get("/global/me", response_model=ContaGlobalRead)
def global_me(account: ContaGlobal = Depends(get_current_global_account)):
    return account


@router.get("/global/condominios", response_model=list[VinculoRead])
def list_memberships(account: ContaGlobal = Depends(get_current_global_account), db: Session = Depends(get_db)):
    return [membership_read(user) for user in authorized_users(account, db)]


@router.post("/global/select-condominio", response_model=GlobalAuthResponse)
def choose_membership(data: SelecionarCondominio, account: ContaGlobal = Depends(get_current_global_account), credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme), db: Session = Depends(get_db)):
    return select_membership(account, credentials.credentials, data.usuario_id, db)


@router.post("/global/refresh", response_model=GlobalAuthResponse)
def refresh_global(data: RefreshRequest, db: Session = Depends(get_db)):
    return refresh_global_session(data.refresh_token, db)


@router.post("/global/logout", status_code=204)
def logout_global(data: RefreshRequest, account: ContaGlobal = Depends(get_current_global_account), db: Session = Depends(get_db)):
    try:
        token = db.scalar(select(SessaoGlobal).where(SessaoGlobal.token_hash == hash_token(data.refresh_token), SessaoGlobal.conta_id == account.id).with_for_update())
        if token is not None and token.revoked_at is None:
            token.revoked_at = utcnow()
        db.commit()
    except Exception:
        db.rollback()
        raise
    return Response(status_code=204)
