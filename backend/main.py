import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from config.config import env
from config.database import engine
from routers.moradores import router as moradores_router
from routers.unidades import router as unidades_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        logger.info("PostgreSQL conectado.")
    except Exception as exc:
        logger.warning("PostgreSQL indisponível na inicialização: %s", exc)
    yield
    engine.dispose()


app = FastAPI(title="Liven — Portaria Inteligente", description="API local para controle de acesso condominial.", version="2.0.0", lifespan=lifespan)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Erro não tratado em %s: %s", request.url.path, exc, exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Ocorreu um erro interno no servidor."})


app.add_middleware(CORSMiddleware, allow_origins=env["CORS_ORIGINS"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])
app.include_router(unidades_router)
app.include_router(moradores_router)


@app.get("/api/v1/health", tags=["Status"])
async def health():
    return {"status": "ok", "app": "Liven", "database": "postgresql", "version": "2.0.0"}
