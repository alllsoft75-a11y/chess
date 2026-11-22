from pathlib import Path

from fastapi.staticfiles import StaticFiles

from .main import app

app.mount("/", StaticFiles(directory=Path(__file__).resolve().parents[1] / "web", html=True))
