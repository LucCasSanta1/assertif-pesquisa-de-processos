from __future__ import annotations

import re
import uuid
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from src.api.jobs import EstadoJob, gerenciador_jobs
from src.connectors.planilha_base import carregar_bytes_planilha_para_cache
from src.exporters.excel import gerar_excel_processos
from src.models.schemas import ResultadoBuscaCNPJ
from src.services.orchestrator import executar_busca_completa_cnpj

router = APIRouter(prefix="/api/v1", tags=["Consulta Processos Arquivados por CNPJ"])


class RequisicaoConsultaCNPJ(BaseModel):
    cnpj: str = Field(..., description="CNPJ da empresa (com ou sem formatação)", examples=["08.803.452/0001-13"])
    razao_social: Optional[str] = Field(
        default=None,
        description="Opcional: Razão Social para forçar ou refinar a busca nominal nos tribunais",
    )
    max_paginas: int = Field(
        default=8,
        ge=1,
        le=25,
        description="Quantidade máxima de páginas de publicações consultadas por estratégia",
    )
    numeros_cnj_adicionais: Optional[List[str]] = Field(
        default=None,
        description="Opcional: Lista de números de processos CNJ para enriquecer/validar arquivamento diretamente no DataJud",
    )
    modo_demonstracao: bool = Field(
        default=False,
        description="Se True, utiliza dados demonstrativos com movimentos reais TPU/CNJ nas 3 esferas (Trabalhista, Estadual e Federal)",
    )


def _validar_cnpj_basico(cnpj: str) -> str:
    digitos = re.sub(r"\D", "", cnpj or "")
    if len(digitos) != 14:
        raise HTTPException(
            status_code=400,
            detail=f"CNPJ inválido ('{cnpj}'). Informe exatamente 14 dígitos numéricos.",
        )
    return digitos


@router.post(
    "/importar-planilha",
    summary="Importa uma planilha base Excel (.xlsx) de processos para enriquecimento e auditoria por CNPJ",
)
async def importar_planilha_acervo(arquivo: UploadFile = File(...)) -> dict:
    conteudo = await arquivo.read()
    if not conteudo:
        raise HTTPException(status_code=400, detail="Arquivo vazio.")
    try:
        total = carregar_bytes_planilha_para_cache(conteudo, arquivo.filename or "Upload.xlsx")
        return {
            "status": "ok",
            "arquivo": arquivo.filename,
            "processos_indexados": total,
            "mensagem": f"{total} processos indexados com sucesso e prontos para consulta por CNPJ.",
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Falha ao ler planilha Excel: {exc}") from exc


@router.post(
    "/consulta-cnpj",
    response_model=ResultadoBuscaCNPJ,
    summary="Consulta processos arquivados por CNPJ (Trabalhista, Estadual e Federal)",
)
async def consultar_processos_por_cnpj(req: RequisicaoConsultaCNPJ) -> ResultadoBuscaCNPJ:
    cnpj_limpo = _validar_cnpj_basico(req.cnpj)
    job_id = str(uuid.uuid4())
    gerenciador_jobs.criar_job(job_id, cnpj_limpo)

    try:
        resultado = await executar_busca_completa_cnpj(
            cnpj=cnpj_limpo,
            razao_social_override=req.razao_social,
            max_paginas_por_estrategia=req.max_paginas,
            numeros_cnj_adicionais=req.numeros_cnj_adicionais,
            modo_demonstracao=req.modo_demonstracao,
            job_id=job_id,
        )
        gerenciador_jobs.concluir_job(job_id, resultado)
        return resultado
    except Exception as exc:
        gerenciador_jobs.registrar_erro(job_id, str(exc))
        raise HTTPException(status_code=500, detail=f"Erro ao processar consulta do CNPJ: {exc}") from exc


@router.get(
    "/consulta-cnpj/{cnpj}",
    response_model=ResultadoBuscaCNPJ,
    summary="Consulta rápida via GET por CNPJ",
)
async def consultar_processos_por_cnpj_get(
    cnpj: str,
    razao_social: Optional[str] = Query(default=None),
    max_paginas: int = Query(default=8, ge=1, le=25),
    modo_demonstracao: bool = Query(default=False),
) -> ResultadoBuscaCNPJ:
    req = RequisicaoConsultaCNPJ(
        cnpj=cnpj,
        razao_social=razao_social,
        max_paginas=max_paginas,
        modo_demonstracao=modo_demonstracao,
    )
    return await consultar_processos_por_cnpj(req)


@router.post(
    "/jobs",
    response_model=EstadoJob,
    summary="Inicia uma consulta em segundo plano (assíncrona) e retorna o job_id",
)
async def iniciar_job_assincrono(
    req: RequisicaoConsultaCNPJ,
    background_tasks: BackgroundTasks,
) -> EstadoJob:
    cnpj_limpo = _validar_cnpj_basico(req.cnpj)
    job_id = str(uuid.uuid4())
    job = gerenciador_jobs.criar_job(job_id, cnpj_limpo)

    async def _tarefa_bg() -> None:
        try:
            res = await executar_busca_completa_cnpj(
                cnpj=cnpj_limpo,
                razao_social_override=req.razao_social,
                max_paginas_por_estrategia=req.max_paginas,
                numeros_cnj_adicionais=req.numeros_cnj_adicionais,
                modo_demonstracao=req.modo_demonstracao,
                job_id=job_id,
            )
            gerenciador_jobs.concluir_job(job_id, res)
        except Exception as e:
            gerenciador_jobs.registrar_erro(job_id, str(e))

    background_tasks.add_task(_tarefa_bg)
    return job


@router.get(
    "/jobs/{job_id}",
    response_model=EstadoJob,
    summary="Consulta o status e resultado de um job pelo ID",
)
async def obter_status_job(job_id: str) -> EstadoJob:
    job = gerenciador_jobs.obter_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado.")
    return job


@router.get(
    "/jobs/{job_id}/excel",
    summary="Baixa a planilha Excel (.xlsx) com todos os processos da consulta",
)
async def baixar_excel_por_job(job_id: str) -> Response:
    job = gerenciador_jobs.obter_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado.")
    if job.status != "CONCLUIDO" or not job.resultado:
        raise HTTPException(status_code=400, detail=f"Job ainda não concluído (status atual: {job.status}).")

    excel_bytes = gerar_excel_processos(job.resultado)
    cnpj_num = job.resultado.empresa.cnpj
    filename = f"processos_arquivados_{cnpj_num}_{job_id[:8]}.xlsx"

    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/consulta-cnpj/{cnpj}/excel",
    summary="Executa a consulta por CNPJ e já retorna diretamente o arquivo Excel (.xlsx)",
)
async def consultar_e_baixar_excel_direto(
    cnpj: str,
    razao_social: Optional[str] = Query(default=None),
    max_paginas: int = Query(default=8, ge=1, le=25),
    modo_demonstracao: bool = Query(default=False),
) -> Response:
    resultado = await consultar_processos_por_cnpj_get(
        cnpj=cnpj,
        razao_social=razao_social,
        max_paginas=max_paginas,
        modo_demonstracao=modo_demonstracao,
    )
    excel_bytes = gerar_excel_processos(resultado)
    filename = f"processos_arquivados_{resultado.empresa.cnpj}.xlsx"

    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
