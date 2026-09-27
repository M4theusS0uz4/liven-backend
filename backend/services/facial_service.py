from dataclasses import dataclass

import cv2
import numpy as np


MAX_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}


@dataclass(frozen=True)
class FacialValidationResult:
    success: bool
    validated: bool
    demo: bool
    message: str
    confidence: float | None = None


def validate_demo_image(content: bytes, content_type: str | None) -> FacialValidationResult:
    """Valida e decodifica a imagem localmente sem armazená-la.

    A decisão de reconhecimento é deliberadamente demonstrativa e isolada
    para permitir substituição futura por um modelo local real.
    """
    if not content or len(content) > MAX_IMAGE_BYTES or content_type not in ALLOWED_CONTENT_TYPES:
        return FacialValidationResult(False, False, True, "Não foi possível processar a imagem.")

    image = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        return FacialValidationResult(False, False, True, "Não foi possível processar a imagem.")

    return FacialValidationResult(True, True, True, "Validação facial demonstrativa concluída.", 0.98)