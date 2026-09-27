from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PontoMapa(BaseModel):
    x: float
    y: float


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
    tipo_residencia: Literal["casa", "apartamento"]
    status: str

    model_config = ConfigDict(from_attributes=True)


class MapaBlocoRead(BaseModel):
    id: int
    nome: str
    x: float
    y: float
    largura: float
    altura: float
    andares: int

    model_config = ConfigDict(from_attributes=True)


class MapaRuaRead(BaseModel):
    id: int
    nome: str
    largura: float
    pontos: list[PontoMapa]


class MapaAreaComumRead(BaseModel):
    id: int
    nome: str
    tipo: str
    x: float
    y: float
    largura: float
    altura: float

    model_config = ConfigDict(from_attributes=True)


class MapaPortariaRead(BaseModel):
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
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    largura: float = Field(gt=0)
    altura: float = Field(gt=0)
    rotacao: float = Field(ge=-360, le=360)


class MapaUnidadeUpdate(BaseModel):
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    largura: float = Field(gt=0)
    altura: float = Field(gt=0)
    rotacao: float = Field(ge=-360, le=360)


class MapaUnidadeInput(MapaUnidadeCreate):
    pass


class MapaBlocoInput(BaseModel):
    nome: str = Field(min_length=1, max_length=100)
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    largura: float = Field(gt=0)
    altura: float = Field(gt=0)
    andares: int = Field(default=1, ge=1, le=999)


class MapaRuaInput(BaseModel):
    nome: str = Field(min_length=1, max_length=150)
    largura: float = Field(gt=0)
    pontos: list[PontoMapa] = Field(min_length=2)


class MapaAreaComumInput(BaseModel):
    nome: str = Field(min_length=1, max_length=150)
    tipo: Literal["lazer", "quadra", "piscina", "playground", "churrasqueira", "salao", "academia", "jardim"]
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    largura: float = Field(gt=0)
    altura: float = Field(gt=0)

    @field_validator("tipo", mode="before")
    @classmethod
    def normalizar_tipo(cls, value: str) -> str:
        return "salao" if value == "salão" else value


class MapaPortariaInput(BaseModel):
    nome: str = Field(min_length=1, max_length=150)
    x: float = Field(ge=0)
    y: float = Field(ge=0)


class MapaUpdate(BaseModel):
    nome: str = Field(min_length=1, max_length=150)
    tipo_condominio: Literal["vertical", "horizontal", "misto"] = "vertical"
    largura: float = Field(gt=0)
    altura: float = Field(gt=0)
    unidades: list[MapaUnidadeInput] = Field(default_factory=list)
    blocos: list[MapaBlocoInput] = Field(default_factory=list)
    ruas: list[MapaRuaInput] = Field(default_factory=list)
    areas_comuns: list[MapaAreaComumInput] = Field(default_factory=list)
    portarias: list[MapaPortariaInput] = Field(default_factory=list)
