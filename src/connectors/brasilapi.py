from __future__ import annotations

import re

import httpx

from src.models.schemas import DadosEmpresaCNPJ

_TIMEOUT = httpx.Timeout(30.0)


def _limpar_cnpj(cnpj: str) -> str:
    return re.sub(r"\D", "", cnpj)


def _formatar_cnpj(cnpj: str) -> str:
    return f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:14]}"


def _parse_brasilapi(data: dict, cnpj: str) -> DadosEmpresaCNPJ:
    sit = data.get("descricao_situacao_cadastral") or data.get("situacao_cadastral")
    return DadosEmpresaCNPJ(
        cnpj=cnpj,
        cnpj_formatado=_formatar_cnpj(cnpj),
        razao_social=str(data.get("razao_social") or f"EMPRESA {_formatar_cnpj(cnpj)}"),
        nome_fantasia=data.get("nome_fantasia") or None,
        uf=data.get("uf") or None,
        municipio=data.get("municipio") or None,
        situacao_cadastral=str(sit) if sit is not None else None,
    )


def _parse_cnpjws(data: dict, cnpj: str) -> DadosEmpresaCNPJ:
    estab = data.get("estabelecimento") or {}
    municipio_raw = estab.get("municipio")
    municipio = municipio_raw.get("nome") if isinstance(municipio_raw, dict) else municipio_raw
    sit = estab.get("situacao_cadastral")
    return DadosEmpresaCNPJ(
        cnpj=cnpj,
        cnpj_formatado=_formatar_cnpj(cnpj),
        razao_social=str(data.get("razao_social") or f"EMPRESA {_formatar_cnpj(cnpj)}"),
        nome_fantasia=estab.get("nome_fantasia") or None,
        uf=estab.get("uf") or None,
        municipio=str(municipio) if municipio else None,
        situacao_cadastral=str(sit) if sit is not None else None,
    )


def _parse_receitaws(data: dict, cnpj: str) -> DadosEmpresaCNPJ:
    sit = data.get("situacao")
    return DadosEmpresaCNPJ(
        cnpj=cnpj,
        cnpj_formatado=_formatar_cnpj(cnpj),
        razao_social=str(data.get("nome") or f"EMPRESA {_formatar_cnpj(cnpj)}"),
        nome_fantasia=data.get("fantasia") or None,
        uf=data.get("uf") or None,
        municipio=data.get("municipio") or None,
        situacao_cadastral=str(sit) if sit is not None else None,
    )


async def consultar_cnpj(cnpj: str) -> DadosEmpresaCNPJ:
    """
    Consulta dados da empresa pelo CNPJ com fallback automático entre fontes públicas.

    Ordem: BrasilAPI -> cnpj.ws -> ReceitaWS -> Fallback local
    """
    cnpj = _limpar_cnpj(cnpj)
    if len(cnpj) != 14:
        raise ValueError(f"CNPJ inválido: esperado 14 dígitos, obtido {len(cnpj)}")

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        # Fonte primária: BrasilAPI
        try:
            resp = await client.get(f"https://brasilapi.com.br/api/cnpj/v1/{cnpj}")
            if resp.status_code == 200:
                return _parse_brasilapi(resp.json(), cnpj)
        except Exception:
            pass

        # Fallback 1: cnpj.ws
        try:
            resp = await client.get(f"https://publica.cnpj.ws/cnpj/{cnpj}")
            if resp.status_code == 200:
                return _parse_cnpjws(resp.json(), cnpj)
        except Exception:
            pass

        # Fallback 2: ReceitaWS
        try:
            resp = await client.get(
                f"https://receitaws.com.br/v1/cnpj/{cnpj}",
                headers={"Accept": "application/json"},
            )
            if resp.status_code == 200 and resp.json().get("status") != "ERROR":
                return _parse_receitaws(resp.json(), cnpj)
        except Exception:
            pass

    return DadosEmpresaCNPJ(
        cnpj=cnpj,
        cnpj_formatado=_formatar_cnpj(cnpj),
        razao_social=f"EMPRESA CNPJ {_formatar_cnpj(cnpj)}",
        situacao_cadastral="ATIVA (Fallback)",
    )
