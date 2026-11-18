from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PontoMapa(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)


class MapaUnidadeRead(BaseModel):
    id: int
    unidade_id: int
    bloco: str
    numero: str
    x: float
    y: float
    largura: float
    altura: float
    rotacao: float
    oculta: bool = False
    tipo_residencia: Literal["casa", "apartamento"]
    status: str

    model_config = ConfigDict(from_attributes=True)


class MapaBlocoRead(BaseModel):
    rotacao: float = 0
    id: int
    nome: str
    x: float
    y: float
    largura: float
    altura: float
    andares: int

    model_config = ConfigDict(from_attributes=True)


class MapaRuaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nome: str
    largura: float
    pontos: list[PontoMapa]


class MapaAreaComumRead(BaseModel):
    rotacao: float = 0
    id: int
    nome: str
    tipo: str
    x: float
    y: float
    largura: float
    altura: float

    model_config = ConfigDict(from_attributes=True)


class MapaPortariaRead(BaseModel):
    rotacao: float = 0
    id: int
    nome: str
    x: float
    y: float

    model_config = ConfigDict(from_attributes=True)


class MapaRead(BaseModel):
    id: int
    nome: str
    tipo_condominio: Literal["vertical", "horizontal", "misto"]
    largura: float
    altura: float
    unidades: list[MapaUnidadeRead]
    blocos: list[MapaBlocoRead]
    ruas: list[MapaRuaRead]
    areas_comuns: list[MapaAreaComumRead]
    portarias: list[MapaPortariaRead]


class MapaUnidadeCreate(BaseModel):
    unidade_id: int = Field(gt=0)
    x: float = Field(ge=0, allow_inf_nan=False)
    y: float = Field(ge=0, allow_inf_nan=False)
    largura: float = Field(gt=0, allow_inf_nan=False)
    altura: float = Field(gt=0, allow_inf_nan=False)
    rotacao: float = Field(ge=-360, le=360)


class MapaUnidadeUpdate(BaseModel):
    x: float = Field(ge=0, allow_inf_nan=False)
    y: float = Field(ge=0, allow_inf_nan=False)
    largura: float = Field(gt=0, allow_inf_nan=False)
    altura: float = Field(gt=0, allow_inf_nan=False)
    rotacao: float = Field(ge=-360, le=360)


class MapaUnidadeInput(MapaUnidadeCreate):
    oculta: bool = False


class MapaBlocoInput(BaseModel):
    id: int | None = Field(default=None, gt=0)
    rotacao: float = Field(default=0, ge=-360, le=360)
    nome: str = Field(min_length=1, max_length=100)
    x: float = Field(ge=0, allow_inf_nan=False)
    y: float = Field(ge=0, allow_inf_nan=False)
    largura: float = Field(gt=0, allow_inf_nan=False)
    altura: float = Field(gt=0, allow_inf_nan=False)
    andares: int = Field(default=1, ge=1, le=999)


class MapaRuaInput(BaseModel):
    id: int | None = Field(default=None, gt=0)
    nome: str = Field(min_length=1, max_length=150)
    largura: float = Field(gt=0, allow_inf_nan=False)
    pontos: list[PontoMapa] = Field(min_length=2, max_length=1024)


class MapaAreaComumInput(BaseModel):
    id: int | None = Field(default=None, gt=0)
    rotacao: float = Field(default=0, ge=-360, le=360)
    nome: str = Field(min_length=1, max_length=150)
    tipo: Literal["lazer", "quadra", "piscina", "playground", "churrasqueira", "salao", "academia", "jardim"]
    x: float = Field(ge=0, allow_inf_nan=False)
    y: float = Field(ge=0, allow_inf_nan=False)
    largura: float = Field(gt=0, allow_inf_nan=False)
    altura: float = Field(gt=0, allow_inf_nan=False)

    @field_validator("tipo", mode="before")
    @classmethod
    def normalizar_tipo(cls, value: str) -> str:
        return "salao" if value == "salão" else value


class MapaPortariaInput(BaseModel):
    id: int | None = Field(default=None, gt=0)
    rotacao: float = Field(default=0, ge=-360, le=360)
    nome: str = Field(min_length=1, max_length=150)
    x: float = Field(ge=0, allow_inf_nan=False)
    y: float = Field(ge=0, allow_inf_nan=False)


class MapaUpdate(BaseModel):
    nome: str = Field(min_length=1, max_length=150)
    tipo_condominio: Literal["vertical", "horizontal", "misto"] = "vertical"
    largura: float = Field(gt=0, allow_inf_nan=False)
    altura: float = Field(gt=0, allow_inf_nan=False)
    unidades: list[MapaUnidadeInput] = Field(default_factory=list, max_length=500)
    blocos: list[MapaBlocoInput] = Field(default_factory=list, max_length=500)
    ruas: list[MapaRuaInput] = Field(default_factory=list, max_length=500)
    areas_comuns: list[MapaAreaComumInput] = Field(default_factory=list, max_length=500)
    portarias: list[MapaPortariaInput] = Field(default_factory=list, max_length=500)
