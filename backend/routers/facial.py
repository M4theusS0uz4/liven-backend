from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from models.orm import PerfilUsuario, Usuario
from security import require_profiles
from services.facial_service import validate_demo_image

router = APIRouter(prefix="/api/v1/facial", tags=["Validação facial"])
Staff = Annotated[Usuario, Depends(require_profiles(PerfilUsuario.PORTARIA, PerfilUsuario.SINDICO))]


@router.post("/validate")
async def validate_facial(image: UploadFile = File(...), _user: Staff = None) -> dict:
    content = await image.read(5 * 1024 * 1024 + 1)
    result = validate_demo_image(content, image.content_type)
    return {
        "success": result.success,
        "validated": result.validated,
        "demo": result.demo,
        "message": result.message,
        "confidence": result.confidence,
    }