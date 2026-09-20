import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import Base, engine
from .routers import auth, events, orgs, public


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)  # use Alembic migrations for production schemas
    yield


app = FastAPI(title="EventForge API", version="1.0.0", lifespan=lifespan,
              description="Multi-tenant event hosting: organizations, RBAC, ticketing, check-in, payments.")

origins = [o.strip() for o in settings.cors_origins.split(",")]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])

app.include_router(auth.router)
app.include_router(orgs.router)
app.include_router(events.router)
app.include_router(public.router)


@app.get("/api/health", tags=["meta"])
def health():
    return {"status": "ok"}


_default = Path(__file__).resolve().parents[2] / "frontend"
FRONTEND_DIR = Path(os.getenv("FRONTEND_DIR", _default))
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
