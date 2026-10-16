from __future__ import annotations

from datetime import datetime

from src.models.schemas import MovimentoProcessual, StatusArquivamento

# Códigos TPU de arquivamento/baixa definitiva
_CODIGOS_BAIXA_DEFINITIVA: frozenset[int] = frozenset({22})
_CODIGOS_DEFINITIVOS: frozenset[int] = frozenset({246, 861, 472, 473, 10966, 12618, 196})

# Códigos de arquivamento provisório/sobrestamento
_CODIGOS_PROVISORIOS: frozenset[int] = frozenset({245, 247})

# Códigos de reativação/desarquivamento/redistribuição
_CODIGOS_REATIVACAO: frozenset[int] = frozenset({893, 849, 36})

_KW_REATIVACAO = (
    "desarquivamento",
    "desarquivado",
    "reativação",
    "reativado",
)
_KW_DEFINITIVO = (
    "arquivado definitivamente",
    "arquivamento definitivo",
    "baixa definitiva",
)
_KW_PROVISORIO = (
    "arquivamento provisório",
    "arquivado provisoriamente",
    "processo arquivado",
)


def _status_por_palavras_chave(texto: str) -> StatusArquivamento | None:
    t = texto.lower()
    # Reativação tem precedência sobre os demais para evitar falso positivo
    if any(kw in t for kw in _KW_REATIVACAO):
        return StatusArquivamento.DESARQUIVADO
    if any(kw in t for kw in _KW_DEFINITIVO):
        return StatusArquivamento.ARQUIVADO_DEFINITIVO
    if any(kw in t for kw in _KW_PROVISORIO):
        return StatusArquivamento.ARQUIVADO_PROVISORIO
    return None


def classificar_arquivamento(
    movimentos: list[MovimentoProcessual],
    texto_status_fallback: str | None = None,
) -> tuple[bool, StatusArquivamento, int | None, str | None, datetime | None]:
    """
    Avalia a máquina de estados temporal dos movimentos e retorna o status atual.

    Returns:
        (arquivado, status_detalhado, codigo_movimento, descricao_movimento, data_arquivamento)
    """
    status = StatusArquivamento.ATIVO
    last_code: int | None = None
    last_desc: str | None = None
    last_date: datetime | None = None

    for mov in sorted(movimentos, key=lambda m: m.data_hora):
        if mov.codigo in _CODIGOS_BAIXA_DEFINITIVA:
            status = StatusArquivamento.BAIXADO
            last_code, last_desc, last_date = mov.codigo, mov.nome, mov.data_hora

        elif mov.codigo in _CODIGOS_DEFINITIVOS:
            status = StatusArquivamento.ARQUIVADO_DEFINITIVO
            last_code, last_desc, last_date = mov.codigo, mov.nome, mov.data_hora

        elif mov.codigo in _CODIGOS_PROVISORIOS:
            status = StatusArquivamento.ARQUIVADO_PROVISORIO
            last_code, last_desc, last_date = mov.codigo, mov.nome, mov.data_hora

        elif mov.codigo in _CODIGOS_REATIVACAO:
            status = StatusArquivamento.DESARQUIVADO
            last_code, last_desc, last_date = None, None, None

        else:
            # Fallback por palavras-chave no nome do movimento
            kw_status = _status_por_palavras_chave(mov.nome)
            if kw_status == StatusArquivamento.DESARQUIVADO:
                status = StatusArquivamento.DESARQUIVADO
                last_code, last_desc, last_date = None, None, None
            elif kw_status in (
                StatusArquivamento.ARQUIVADO_DEFINITIVO,
                StatusArquivamento.ARQUIVADO_PROVISORIO,
            ):
                status = kw_status
                last_code, last_desc, last_date = mov.codigo, mov.nome, mov.data_hora

    # Último recurso: verificar texto de status externo quando nenhum evento foi detectado
    if status == StatusArquivamento.ATIVO and texto_status_fallback:
        fb_status = _status_por_palavras_chave(texto_status_fallback)
        if fb_status is not None:
            status = fb_status

    arquivado = status in (
        StatusArquivamento.ARQUIVADO_DEFINITIVO,
        StatusArquivamento.ARQUIVADO_PROVISORIO,
        StatusArquivamento.BAIXADO,
    )

    return arquivado, status, last_code, last_desc, last_date
