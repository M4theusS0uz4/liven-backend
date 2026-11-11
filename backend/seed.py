"""Dados acadêmicos: simulação por padrão; --apply exige autorização do operador."""
import argparse

from sqlalchemy import select

from config.config import env
from config.database import SessionLocal
from models.orm import Condominio, Morador, PerfilUsuario, Unidade, Usuario

DEMO_USERS = (
    ("5511999999900", "Síndico Demo", PerfilUsuario.SINDICO),
    ("5511999999901", "Morador Demo", PerfilUsuario.MORADOR),
)


def run(*, condominio_id: int | None = None, apply: bool = False) -> None:
    if env["APP_ENV"] != "development":
        raise RuntimeError("O seed demonstrativo é permitido somente em development.")
    with SessionLocal.begin() as db:
        if condominio_id is not None:
            condo = db.get(Condominio, condominio_id)
            if condo is None or not condo.ativo:
                raise RuntimeError("Condomínio inexistente ou inativo.")
        else:
            condo = db.scalar(select(Condominio).where(Condominio.nome == "Condomínio Demo", Condominio.ativo.is_(True)).order_by(Condominio.id))
            if condo is None:
                condo = db.scalar(select(Condominio).where(Condominio.ativo.is_(True)).order_by(Condominio.id))
        if condo is None:
            if not apply:
                print("SIMULAÇÃO: criar Condomínio Demo, unidade DEMO-OTP/101 e dois usuários demonstrativos.")
                return
            condo = Condominio(nome="Condomínio Demo")
            db.add(condo)
            db.flush()
        print(f"condominio_id={condo.id} | {condo.nome}")
        if not apply:
            for phone, _, profile in DEMO_USERS:
                user = db.scalar(select(Usuario).where(Usuario.condominio_id == condo.id, Usuario.telefone == phone))
                print(f"{phone}: {'já cadastrado' if user else 'será criado'} | perfil esperado={profile.value}")
            print(f"SIMULAÇÃO: nenhuma alteração. Após aprovação: python seed.py --condominio-id {condo.id} --apply")
            return
        # Serializa duas execuções do seed no mesmo condomínio.
        db.scalar(select(Condominio.id).where(Condominio.id == condo.id).with_for_update())
        users = {}
        for phone, name, profile in DEMO_USERS:
            user = db.scalar(select(Usuario).where(Usuario.condominio_id == condo.id, Usuario.telefone == phone))
            if user is None:
                user = Usuario(condominio_id=condo.id, nome=name, telefone=phone, perfil=profile)
                db.add(user)
                db.flush()
            elif user.perfil != profile or not user.ativo:
                raise RuntimeError("Usuário demonstrativo existente tem perfil/estado diferente; nenhuma alteração aplicada.")
            users[phone] = user
        resident = users["5511999999901"]
        if db.scalar(select(Morador).where(Morador.usuario_id == resident.id)) is None:
            unit = db.scalar(select(Unidade).where(Unidade.bloco == "DEMO-OTP", Unidade.numero == "101"))
            if unit is not None and unit.condominio_id != condo.id:
                raise RuntimeError("Unidade DEMO-OTP/101 pertence a outro condomínio; nenhuma alteração aplicada.")
            if unit is None:
                unit = Unidade(condominio_id=condo.id, bloco="DEMO-OTP", numero="101", andar=1)
                db.add(unit)
                db.flush()
            db.add(Morador(unidade_id=unit.id, usuario_id=resident.id, nome=resident.nome, telefone=resident.telefone))
    print("Seed concluído sem alterar perfis ou reativar usuários existentes.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--condominio-id", type=int)
    parser.add_argument("--apply", action="store_true", help="Executar somente após aprovação para criar os dados demo.")
    args = parser.parse_args()
    run(condominio_id=args.condominio_id, apply=args.apply)
