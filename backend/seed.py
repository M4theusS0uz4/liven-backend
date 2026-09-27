from sqlalchemy import select

from config.database import SessionLocal
from models.orm import Condominio, Morador, PerfilUsuario, Unidade, Usuario
from security import normalize_phone


def run() -> None:
    with SessionLocal.begin() as db:
        condominio = db.scalar(select(Condominio).where(Condominio.nome == "Condomínio Demo"))
        if condominio is None:
            condominio = Condominio(nome="Condomínio Demo")
            db.add(condominio)
            db.flush()

        sindico = db.scalar(select(Usuario).where(Usuario.condominio_id == condominio.id, Usuario.telefone == "5511999999900"))
        if sindico is None:
            db.add(Usuario(condominio_id=condominio.id, nome="Síndico Demo", telefone="5511999999900", perfil=PerfilUsuario.SINDICO))

        unidade = db.scalar(select(Unidade).where(Unidade.condominio_id == condominio.id, Unidade.bloco == "A", Unidade.numero == "101"))
        if unidade is None:
            unidade = Unidade(condominio_id=condominio.id, bloco="A", numero="101", andar=1)
            db.add(unidade)
            db.flush()

        morador_user = db.scalar(select(Usuario).where(Usuario.condominio_id == condominio.id, Usuario.telefone == "5511999999901"))
        if morador_user is None:
            morador_user = Usuario(condominio_id=condominio.id, nome="Morador Demo", telefone=normalize_phone("5511999999901"), perfil=PerfilUsuario.MORADOR)
            db.add(morador_user)
            db.flush()
        if db.scalar(select(Morador).where(Morador.usuario_id == morador_user.id)) is None:
            db.add(Morador(unidade_id=unidade.id, usuario_id=morador_user.id, nome=morador_user.nome, telefone=morador_user.telefone))
    print("Seed concluído. Síndico: 5511999999900 | Morador: 5511999999901")


if __name__ == "__main__":
    run()