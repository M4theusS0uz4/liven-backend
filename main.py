"""Entry point conveniente para executar a API a partir da raiz do repositório."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from backend.main import app

__all__ = ["app"]