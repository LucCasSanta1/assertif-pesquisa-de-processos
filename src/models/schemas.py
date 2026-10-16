from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class EsferaJustica(str, Enum):
    TRABALHISTA = "Trabalhista"
    ESTADUAL = "Estadual"
    FEDERAL = "Federal"
    OUTROS = "Outros"


class StatusArquivamento(str, Enum):
    ARQUIVADO_DEFINITIVO = "Arquivado Definitivamente"
    ARQUIVADO_PROVISORIO = "Arquivado Provisoriamente"
    BAIXADO = "Baixado / Arquivado"
    ATIVO = "Ativo / Em Andamento"
    DESARQUIVADO = "Reativado / Desarquivado"
    INDETERMINADO = "Indeterminado"


class MovimentoProcessual(BaseModel):
    codigo: int = Field(..., description="Código TPU do CNJ para o movimento")
    nome: str = Field(..., description="Descrição do movimento processual")
    data_hora: datetime = Field(..., description="Data e hora do movimento")
    complemento: Optional[str] = Field(default=None, description="Complemento do movimento se houver")


class ProcessoJudicial(BaseModel):
    numero_processo: str = Field(..., description="Número CNJ padronizado (20 dígitos ou formatado NNNNNNN-DD.AAAA.J.TR.OOOO)")
    numero_formatado: str = Field(..., description="Número CNJ formatado com pontuação")
    tribunal: str = Field(..., description="Sigla do tribunal (ex: TRT2, TJSP, TRF3)")
    esfera: EsferaJustica = Field(..., description="Trabalhista, Estadual ou Federal")
    classe_codigo: Optional[int] = Field(default=None, description="Código da classe processual TPU")
    classe_nome: Optional[str] = Field(default=None, description="Nome da classe processual")
    orgao_julgador: Optional[str] = Field(default=None, description="Vara / Órgão julgador")
    uf: Optional[str] = Field(default=None, description="UF do tribunal / origem")
    data_ajuizamento: Optional[datetime] = Field(default=None, description="Data de ajuizamento")
    data_ultima_movimentacao: Optional[datetime] = Field(default=None, description="Data da última movimentacao")
    ultimo_movimento_relevante: Optional[str] = Field(default=None, description="Descrição do movimento que definiu o status")
    codigo_movimento_arquivamento: Optional[int] = Field(default=None, description="Código TPU do arquivamento (ex: 246, 245, 861, 22)")
    data_arquivamento: Optional[datetime] = Field(default=None, description="Data exata do arquivamento")
    arquivado: bool = Field(default=False, description="True se o processo encontra-se atualmente arquivado/baixado")
    status_detalhado: StatusArquivamento = Field(default=StatusArquivamento.INDETERMINADO)
    polo_empresa: Optional[str] = Field(default=None, description="Polo da empresa (Ativo/Passivo/Terceiro)")
    partes_resumo: Optional[str] = Field(default=None, description="Resumo das partes identificadas")
    fonte_descoberta: str = Field(default="CNJ/Comunica+DataJud", description="Fonte onde o processo foi localizado")
    movimentos: List[MovimentoProcessual] = Field(default_factory=list, description="Lista de movimentos analisados")


class DadosEmpresaCNPJ(BaseModel):
    cnpj: str = Field(..., description="CNPJ apenas números (14 dígitos)")
    cnpj_formatado: str = Field(..., description="CNPJ formatado XX.XXX.XXX/XXXX-XX")
    razao_social: str = Field(..., description="Razão Social oficial na Receita Federal")
    nome_fantasia: Optional[str] = Field(default=None)
    uf: Optional[str] = Field(default=None)
    municipio: Optional[str] = Field(default=None)
    situacao_cadastral: Optional[str] = Field(default=None)


class ResumoEsfera(BaseModel):
    total_localizados: int = 0
    arquivados: int = 0
    arquivados_definitivo: int = 0
    arquivados_provisorio: int = 0
    ativos: int = 0


class ContagemArquivadosResumo(BaseModel):
    trabalhista: int = Field(default=0, description="Quantidade de processos arquivados na Justiça do Trabalho")
    estadual: int = Field(default=0, description="Quantidade de processos arquivados na Justiça Estadual")
    federal: int = Field(default=0, description="Quantidade de processos arquivados na Justiça Federal")
    total_arquivados: int = Field(default=0, description="Soma total de processos arquivados")
    total_geral_analisados: int = Field(default=0, description="Total de processos analisados (arquivados + ativos)")


class ResultadoBuscaCNPJ(BaseModel):
    job_id: str
    empresa: DadosEmpresaCNPJ
    data_consulta: datetime
    contagem_arquivados: ContagemArquivadosResumo
    detalhamento_por_esfera: Dict[str, ResumoEsfera]
    processos_arquivados: List[ProcessoJudicial] = Field(default_factory=list)
    todos_processos: List[ProcessoJudicial] = Field(default_factory=list)
    fontes_consultadas: List[str] = Field(default_factory=list)
    observacoes: List[str] = Field(default_factory=list)
