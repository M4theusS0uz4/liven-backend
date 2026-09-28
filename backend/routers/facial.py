from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy.orm import Session

from config.database import get_db
from models.orm import PerfilUsuario, Usuario
from security import client_ip, require_profiles
from services.audit_service import registrar_auditoria
from services.facial_service import validate_demo_image

router = APIRouter(prefix="/api/v1/facial", tags=["Validação facial"])
Staff = Annotated[Usuario, Depends(require_profiles(PerfilUsuario.PORTARIA, PerfilUsuario.SINDICO))]


@router.post("/validate")
async def validate_facial(
    request: Request,
    image: UploadFile = File(...),
    user: Staff = None,
    db: Session = Depends(get_db),
) -> dict:
    content = await image.read(5 * 1024 * 1024 + 1)
    result = validate_demo_image(content, image.content_type)
    registrar_auditoria(
        db,
        condominio_id=user.condominio_id,
        usuario_id=user.id,
        acao="facial.validar",
        recurso="facial",
        endereco_ip=client_ip(request),
        detalhes={"sucesso": result.success},
    )
    return {
        "success": result.success,
        "validated": result.validated,
        "demo": result.demo,
        "message": result.message,
        "confidence": result.confidence,
    }