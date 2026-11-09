from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pathlib import Path
from .database import Base, engine
from .seed import seed_database
from .routes import cases, dashboard, analytics, predictions, ai

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    seed_database()
    yield

app = FastAPI(
    title="MOAI Legal Case Analytics API",
    description="Multi-jurisdiction legal case research and sentencing analytics.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict to the deployed frontend origin before public production use.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(cases.router)
app.include_router(dashboard.router)
app.include_router(analytics.router)
app.include_router(predictions.router)
app.include_router(ai.router)

@app.get("/health")
def health():
    return {"status": "ok", "application": "MOAI Legal Case Analytics"}

@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <html><head><title>MOAI Legal Case Analytics</title></head>
    <body style="font-family:Arial,sans-serif;max-width:760px;margin:60px auto;padding:0 20px">
    <h1>MOAI Legal Case Analytics</h1>
    <p>Backend foundation is running.</p>
    <ul>
      <li><a href="/docs">API documentation</a></li>
      <li><a href="/health">Health check</a></li>
      <li><a href="/api/dashboard/overview">Dashboard overview API</a></li>
      <li><a href="/api/ai/status">OpenRouter configuration status</a></li>
    </ul>
    <p>Research estimates are not legal advice and are not guaranteed outcomes.</p>
    </body></html>
    """
