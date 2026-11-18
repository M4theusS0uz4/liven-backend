from base64 import b64decode, b64encode
from binascii import Error
from io import BytesIO

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

MAX_BASE64 = 400_000
MAX_PIXELS = 16_000_000
FORMATOS = {"jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}


class FotoInput(BaseModel):
    foto: str | None = Field(default=None, max_length=MAX_BASE64 + 32)

    def dados_foto(self) -> dict[str, bytes | None]:
        if "foto" not in self.model_fields_set:
            return {}
        if self.foto is None:
            return {"foto_jpeg": None}

        cabecalho, _, texto = self.foto.partition(",")
        formato = FORMATOS.get(cabecalho.removeprefix("data:image/").removesuffix(";base64"))
        if not formato or not cabecalho.startswith("data:image/") or not cabecalho.endswith(";base64") or len(texto) > MAX_BASE64:
            raise HTTPException(status_code=422, detail="Envie uma foto em JPEG, PNG ou WebP.")
        try:
            with Image.open(BytesIO(b64decode(texto, validate=True)), formats=[formato]) as imagem:
                if imagem.width * imagem.height > MAX_PIXELS or getattr(imagem, "is_animated", False):
                    raise ValueError("Dimensões ou animação inválidas.")
                imagem.thumbnail((640, 640))
                retrato = ImageOps.exif_transpose(imagem).convert("RGBA")
                fundo = Image.new("RGB", retrato.size, "white")
                fundo.paste(retrato, mask=retrato.getchannel("A"))
                resultado = BytesIO()
                fundo.save(resultado, format="JPEG", quality=86, optimize=True)
        except (Error, ValueError, UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise HTTPException(status_code=422, detail="A imagem é inválida ou excede os limites de tamanho.") from exc
        return {"foto_jpeg": resultado.getvalue()}


def responder_foto(foto_jpeg: bytes | None) -> dict[str, str]:
    if foto_jpeg is None:
        raise HTTPException(status_code=404, detail="Foto não encontrada.")
    return {"foto": "data:image/jpeg;base64," + b64encode(foto_jpeg).decode("ascii")}
