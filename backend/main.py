import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy import text

from config.config import env
from config.database import engine
from routers.moradores import router as moradores_router
from routers.entregas import router as entregas_router
from routers.mapa import router as mapa_router
from routers.unidades import router as unidades_router
from routers.auth import me_router, router as auth_router
from routers.acessos import router as acessos_router
from routers.porteiros import router as porteiros_router
from routers.comunicados import router as comunicados_router
from routers.ocorrencias import router as ocorrencias_router
from routers.dashboard import router as dashboard_router
from routers.facial import router as facial_router
from routers.veiculos import router as veiculos_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.database_status = "unavailable"
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        app.state.database_status = "connected"
        logger.info("PostgreSQL conectado.")
    except Exception as exc:
        logger.warning("PostgreSQL indisponível na inicialização: %s", exc)
    yield
    engine.dispose()


is_production = env["APP_ENV"] == "production"
if is_production and (env["JWT_SECRET"].startswith("dev-only") or len(env["JWT_SECRET"]) < 32):
    raise RuntimeError("JWT_SECRET deve ser definido com um segredo forte em produção.")
app = FastAPI(
    title="Liven — Portaria Inteligente",
    description="API local para controle de acesso condominial.",
    version="2.0.0",
    lifespan=lifespan,
    docs_url=None if is_production else "/docs",
    redoc_url=None if is_production else "/redoc",
    openapi_url=None if is_production else "/openapi.json",
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Erro não tratado em %s: %s", request.url.path, exc, exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Ocorreu um erro interno no servidor."})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.info("Requisição inválida em %s", request.url.path)
    return JSONResponse(status_code=422, content={"detail": "Os dados enviados são inválidos."})


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


app.add_middleware(TrustedHostMiddleware, allowed_hosts=env["ALLOWED_HOSTS"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=env["CORS_ORIGINS"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Accept", "Authorization", "Content-Type"],
)
app.include_router(unidades_router)
app.include_router(moradores_router)
app.include_router(entregas_router)
app.include_router(mapa_router)
app.include_router(auth_router)
app.include_router(me_router)
app.include_router(acessos_router)
app.include_router(porteiros_router)
app.include_router(comunicados_router)
app.include_router(ocorrencias_router)
app.include_router(dashboard_router)
app.include_router(facial_router)
app.include_router(veiculos_router)


@app.get("/api/v1/health", tags=["Status"])
async def health():
    database_status = getattr(app.state, "database_status", "unknown")
    return {
        "status": "ok" if database_status == "connected" else "degraded",
        "app": "Liven",
        "database": database_status,
        "version": app.version,
    }
