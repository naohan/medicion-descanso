"""
Punto de entrada de la API FastAPI.

Inicia el servidor con:
    uvicorn main:app --reload --host 0.0.0.0 --port 8000

Documentación interactiva en:
    http://localhost:8000/docs      (Swagger UI)
    http://localhost:8000/redoc     (ReDoc)
"""
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

from auth import require_api_key
from routers import ingest, query

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Serenity Fatiga — API",
    description="Backend para monitoreo de sueño y fatiga desde Xiaomi Watch 2",
    version="1.0.0",
)

# ---------------------------------------------------------------------------
# CORS: permite que el dashboard HTML abra los endpoints desde cualquier
# origen local. En producción restringe origins a tu dominio.
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(ingest.router, dependencies=[Depends(require_api_key)])
app.include_router(query.router, dependencies=[Depends(require_api_key)])

# ---------------------------------------------------------------------------
# Sirve el dashboard estático desde ../dashboard/
# ---------------------------------------------------------------------------
DASHBOARD_DIR = os.path.join(os.path.dirname(__file__), "..", "dashboard")
if os.path.isdir(DASHBOARD_DIR):
    app.mount("/dashboard", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")

    @app.get("/", include_in_schema=False)
    def root():
        return FileResponse(os.path.join(DASHBOARD_DIR, "index.html"))


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}
