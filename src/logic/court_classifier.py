from __future__ import annotations

import re

from src.models.schemas import EsferaJustica

# J=5 (Trabalhista): TR -> (sigla, uf)
_TRT_MAP: dict[int, tuple[str, str | None]] = {
    0:  ("TST",   None),
    1:  ("TRT1",  "RJ"),
    2:  ("TRT2",  "SP"),
    3:  ("TRT3",  "MG"),
    4:  ("TRT4",  "RS"),
    5:  ("TRT5",  "BA"),
    6:  ("TRT6",  "PE"),
    7:  ("TRT7",  "CE"),
    8:  ("TRT8",  "PA"),
    9:  ("TRT9",  "PR"),
    10: ("TRT10", "DF"),
    11: ("TRT11", "AM"),
    12: ("TRT12", "SC"),
    13: ("TRT13", "PB"),
    14: ("TRT14", "RO"),
    15: ("TRT15", "SP"),
    16: ("TRT16", "MA"),
    17: ("TRT17", "ES"),
    18: ("TRT18", "GO"),
    19: ("TRT19", "AL"),
    20: ("TRT20", "SE"),
    21: ("TRT21", "RN"),
    22: ("TRT22", "PI"),
    23: ("TRT23", "MT"),
    24: ("TRT24", "MS"),
}

# J=4 (Federal): TR -> (sigla, uf_sede)
_TRF_MAP: dict[int, tuple[str, str]] = {
    1: ("TRF1", "DF"),
    2: ("TRF2", "RJ"),
    3: ("TRF3", "SP"),
    4: ("TRF4", "RS"),
    5: ("TRF5", "PE"),
    6: ("TRF6", "MG"),
}

# J=8 (Estadual): TR (01-27) -> (sigla, uf) — tabela oficial CNJ
_TJXX_MAP: dict[int, tuple[str, str]] = {
    1:  ("TJAC",  "AC"),
    2:  ("TJAL",  "AL"),
    3:  ("TJAP",  "AP"),
    4:  ("TJAM",  "AM"),
    5:  ("TJBA",  "BA"),
    6:  ("TJCE",  "CE"),
    7:  ("TJDFT", "DF"),
    8:  ("TJES",  "ES"),
    9:  ("TJGO",  "GO"),
    10: ("TJMA",  "MA"),
    11: ("TJMT",  "MT"),
    12: ("TJMS",  "MS"),
    13: ("TJMG",  "MG"),
    14: ("TJPA",  "PA"),
    15: ("TJPB",  "PB"),
    16: ("TJPR",  "PR"),
    17: ("TJPE",  "PE"),
    18: ("TJPI",  "PI"),
    19: ("TJRJ",  "RJ"),
    20: ("TJRN",  "RN"),
    21: ("TJRS",  "RS"),
    22: ("TJRO",  "RO"),
    23: ("TJRR",  "RR"),
    24: ("TJSC",  "SC"),
    25: ("TJSE",  "SE"),
    26: ("TJSP",  "SP"),
    27: ("TJTO",  "TO"),
}

_DATAJUD_BASE = "https://api-publica.datajud.cnj.jus.br"


def normalizar_numero_cnj(numero: str) -> str:
    """Retorna os 20 dígitos limpos do número CNJ."""
    digits = re.sub(r"\D", "", numero)
    if len(digits) != 20:
        raise ValueError(
            f"Número CNJ inválido (esperado 20 dígitos, obtido {len(digits)}): {numero!r}"
        )
    return digits


def formatar_numero_cnj(numero: str) -> str:
    """Retorna o número CNJ no formato NNNNNNN-DD.AAAA.J.TR.OOOO."""
    d = normalizar_numero_cnj(numero)
    return f"{d[0:7]}-{d[7:9]}.{d[9:13]}.{d[13]}.{d[14:16]}.{d[16:20]}"


def classificar_esfera_e_tribunal(
    numero_cnj: str,
    sigla_tribunal: str | None = None,
) -> tuple[EsferaJustica, str, str | None]:
    """
    Deriva esfera, sigla padronizada do tribunal e UF a partir do número CNJ.

    O dígito J (índice 13 nos 20 dígitos) define a esfera; TR (índices 14-15)
    identifica o tribunal específico dentro da esfera.

    Returns:
        (esfera, sigla_tribunal_padronizada, uf)
    """
    d = normalizar_numero_cnj(numero_cnj)
    j = int(d[13])
    tr = int(d[14:16])

    if j == 5:
        esfera = EsferaJustica.TRABALHISTA
        sigla_derivada, uf = _TRT_MAP.get(tr, (f"TRT{tr}", None))
    elif j == 4:
        esfera = EsferaJustica.FEDERAL
        sigla_derivada, uf = _TRF_MAP.get(tr, (f"TRF{tr}", None))
    elif j == 8:
        esfera = EsferaJustica.ESTADUAL
        sigla_derivada, uf = _TJXX_MAP.get(tr, (f"TJ{tr:02d}", None))
    else:
        esfera = EsferaJustica.OUTROS
        sigla_derivada = f"J{j}TR{tr:02d}"
        uf = None

    # Sigla informada externamente prevalece sobre a derivada; UF mantida
    sigla_final = sigla_tribunal if sigla_tribunal else sigla_derivada
    return esfera, sigla_final, uf


def obter_endpoint_datajud(sigla_tribunal: str) -> str:
    """Retorna a URL do endpoint público DataJud para o tribunal informado."""
    return f"{_DATAJUD_BASE}/api_publica_{sigla_tribunal.lower()}/_search"
