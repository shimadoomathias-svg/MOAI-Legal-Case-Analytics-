from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pathlib import Path
from .database import Base, engine
from .seed import seed_database
from .routes import cases, dashboard, analytics, predictions, ai, metadata

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    seed_database()
    yield

app = FastAPI(title="MOAI Legal Case Analytics API",
    description="Multi-jurisdiction legal case research and sentencing analytics.",
    version="0.1.0", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"])

app.include_router(cases.router)
app.include_router(dashboard.router)
app.include_router(analytics.router)
app.include_router(predictions.router)
app.include_router(ai.router)
app.include_router(metadata.router)

@app.get("/health")
def health():
    return {"status": "ok", "application": "MOAI Legal Case Analytics"}

@app.get("/")
def home():
    return FileResponse(Path(__file__).resolve().parent / "static" / "index.html")
