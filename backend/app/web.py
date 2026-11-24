"""CLOMORI production web entrypoint."""

from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from app.main import app as api_app

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


async def homepage(request: Request):
    return FileResponse(
        FRONTEND / "index.html",
        media_type="text/html",
        headers={"Cache-Control": "no-store"},
    )


app = Starlette(
    routes=[
        Route("/", homepage),
        Route("/index.html", homepage),
        Mount("/css", StaticFiles(directory=FRONTEND / "css")),
        Mount("/js", StaticFiles(directory=FRONTEND / "js")),
        Mount("/assets", StaticFiles(directory=FRONTEND / "assets")),
        Mount("/", app=api_app),
    ]
)
