from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

from src.api.routes import router as api_router

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_INDEX = BASE_DIR / "frontend" / "index.html"

app = FastAPI(
    title="API de Consulta de Processos Arquivados por CNPJ",
    description=(
        "API para auditoria nacional de processos judiciais arquivados por CNPJ, "
        "separando com precisão as quantidades das esferas Trabalhista (TRTs/TST), "
        "Estadual (TJs) e Federal (TRFs) via Tabelas Processuais Unificadas (TPU/DataJud CNJ) "
        "e permitindo exportação completa em Excel (.xlsx)."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def pagina_inicial() -> FileResponse:
    return FileResponse(FRONTEND_INDEX)


@app.get("/health", tags=["Sistema"])
async def health_check() -> dict:
    return {"status": "ok", "service": "processos-arquivados-cnpj"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
