from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional
from pydantic import BaseModel

from src.models.schemas import ResultadoBuscaCNPJ


class EstadoJob(BaseModel):
    job_id: str
    cnpj: str
    status: str  # "PROCESSANDO" | "CONCLUIDO" | "ERRO"
    criado_em: datetime
    concluido_em: Optional[datetime] = None
    erro: Optional[str] = None
    resultado: Optional[ResultadoBuscaCNPJ] = None


class GerenciadorJobs:
    def __init__(self) -> None:
        self._jobs: Dict[str, EstadoJob] = {}

    def criar_job(self, job_id: str, cnpj: str) -> EstadoJob:
        job = EstadoJob(
            job_id=job_id,
            cnpj=cnpj,
            status="PROCESSANDO",
            criado_em=datetime.now(),
        )
        self._jobs[job_id] = job
        return job

    def concluir_job(self, job_id: str, resultado: ResultadoBuscaCNPJ) -> EstadoJob:
        job = self._jobs.get(job_id)
        if not job:
            job = EstadoJob(
                job_id=job_id,
                cnpj=resultado.empresa.cnpj,
                status="CONCLUIDO",
                criado_em=datetime.now(),
            )
            self._jobs[job_id] = job
        job.status = "CONCLUIDO"
        job.concluido_em = datetime.now()
        job.resultado = resultado
        return job

    def registrar_erro(self, job_id: str, erro: str) -> None:
        job = self._jobs.get(job_id)
        if job:
            job.status = "ERRO"
            job.concluido_em = datetime.now()
            job.erro = erro

    def obter_job(self, job_id: str) -> Optional[EstadoJob]:
        return self._jobs.get(job_id)

    def listar_jobs(self) -> list[EstadoJob]:
        return sorted(self._jobs.values(), key=lambda j: j.criado_em, reverse=True)


gerenciador_jobs = GerenciadorJobs()
