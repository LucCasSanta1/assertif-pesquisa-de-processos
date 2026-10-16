from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Optional

import httpx

from src.logic.archive_classifier import classificar_arquivamento
from src.logic.court_classifier import normalizar_numero_cnj, obter_endpoint_datajud
from src.models.schemas import MovimentoProcessual, ProcessoJudicial

# Chave pública oficial CNJ DataJud (sobrescrevível via env DATAJUD_API_KEY)
_DEFAULT_API_KEY = "cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw=="
_TIMEOUT = httpx.Timeout(30.0)


def _get_api_key() -> str:
    return os.environ.get("DATAJUD_API_KEY", _DEFAULT_API_KEY)


def _parse_date(date_val: str | int | None) -> datetime | None:
    if date_val is None:
        return None
    date_str = str(date_val).strip()
    if not date_str:
        return None
    # Formato compacto DataJud: YYYYMMDDHHMMSS ou YYYYMMDD
    if date_str.isdigit():
        try:
            if len(date_str) >= 14:
                return datetime.strptime(date_str[:14], "%Y%m%d%H%M%S")
            if len(date_str) >= 8:
                return datetime.strptime(date_str[:8], "%Y%m%d")
        except ValueError:
            pass
    try:
        clean = date_str.rstrip("Z").split(".")[0]
        return datetime.fromisoformat(clean)
    except (ValueError, AttributeError):
        return None


def _parse_movimentos(raw_movs: list[dict]) -> list[MovimentoProcessual]:
    result: list[MovimentoProcessual] = []
    for mov in raw_movs:
        data_hora = _parse_date(
            mov.get("dataHora") or mov.get("data") or mov.get("data_hora")
        )
        if data_hora is None:
            continue

        complemento_raw = mov.get("complementosTabelados") or []
        if isinstance(complemento_raw, list) and complemento_raw:
            partes = []
            for c in complemento_raw:
                if isinstance(c, dict):
                    partes.append(str(c.get("valor") or c.get("descricao") or ""))
                else:
                    partes.append(str(c))
            complemento: str | None = "; ".join(filter(None, partes)) or None
        else:
            complemento = None

        result.append(
            MovimentoProcessual(
                codigo=int(mov.get("codigo") or 0),
                nome=mov.get("nome") or "",
                data_hora=data_hora,
                complemento=complemento,
            )
        )
    return result


async def enriquecer_processo_datajud(
    processo: ProcessoJudicial,
    client: Optional[httpx.AsyncClient] = None,
) -> ProcessoJudicial:
    """
    Consulta o DataJud e enriquece o ProcessoJudicial com classe, órgão julgador,
    data de ajuizamento, movimentos e status de arquivamento.
    """
    endpoint = obter_endpoint_datajud(processo.tribunal)
    numero_limpo = normalizar_numero_cnj(processo.numero_processo)
    headers = {
        "Authorization": f"APIKey {_get_api_key()}",
        "Content-Type": "application/json",
    }
    query = {
        "query": {"match": {"numeroProcesso": numero_limpo}},
        "size": 1,
    }

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=_TIMEOUT)

    try:
        resp = await client.post(endpoint, json=query, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return processo
    finally:
        if own_client:
            await client.aclose()

    hits = data.get("hits", {}).get("hits", [])
    if not hits:
        return processo

    source: dict = hits[0].get("_source", {})

    classe = source.get("classe") or {}
    orgao = source.get("orgaoJulgador") or {}
    movimentos_dj = _parse_movimentos(source.get("movimentos") or [])
    movimentos = (processo.movimentos or []) + movimentos_dj
    data_ajuizamento = _parse_date(source.get("dataAjuizamento"))

    arquivado, status, cod_mov, desc_mov, data_arq = classificar_arquivamento(movimentos)

    ultima_movimentacao = (
        max((m.data_hora for m in movimentos), default=processo.data_ultima_movimentacao)
        if movimentos
        else processo.data_ultima_movimentacao
    )

    return processo.model_copy(
        update={
            "classe_codigo": classe.get("codigo") or processo.classe_codigo,
            "classe_nome": classe.get("nome") or processo.classe_nome,
            "orgao_julgador": orgao.get("nome") or processo.orgao_julgador,
            "data_ajuizamento": data_ajuizamento or processo.data_ajuizamento,
            "data_ultima_movimentacao": ultima_movimentacao,
            "movimentos": movimentos,
            "arquivado": arquivado,
            "status_detalhado": status,
            "codigo_movimento_arquivamento": cod_mov,
            "ultimo_movimento_relevante": desc_mov,
            "data_arquivamento": data_arq,
            "fonte_descoberta": f"{processo.fonte_descoberta} + DataJud TPU",
        }
    )


def _aplicar_source_datajud(processo: ProcessoJudicial, source: dict) -> ProcessoJudicial:
    classe = source.get("classe") or {}
    orgao = source.get("orgaoJulgador") or {}
    movimentos_dj = _parse_movimentos(source.get("movimentos") or [])
    movimentos = (processo.movimentos or []) + movimentos_dj
    data_ajuizamento = _parse_date(source.get("dataAjuizamento"))

    arquivado, status, cod_mov, desc_mov, data_arq = classificar_arquivamento(movimentos)

    movs_ordenados = sorted(movimentos, key=lambda m: m.data_hora) if movimentos else []
    ultima_movimentacao = (
        movs_ordenados[-1].data_hora
        if movs_ordenados
        else processo.data_ultima_movimentacao
    )
    if not desc_mov and movs_ordenados:
        ult = movs_ordenados[-1]
        desc_mov = f"{ult.nome} (Cód. {ult.codigo})" if ult.nome else f"Movimento TPU {ult.codigo}"

    return processo.model_copy(
        update={
            "classe_codigo": classe.get("codigo") or processo.classe_codigo,
            "classe_nome": classe.get("nome") or processo.classe_nome,
            "orgao_julgador": orgao.get("nome") or processo.orgao_julgador,
            "data_ajuizamento": data_ajuizamento or processo.data_ajuizamento,
            "data_ultima_movimentacao": ultima_movimentacao,
            "movimentos": movimentos,
            "arquivado": arquivado,
            "status_detalhado": status,
            "codigo_movimento_arquivamento": cod_mov,
            "ultimo_movimento_relevante": desc_mov,
            "data_arquivamento": data_arq,
            "fonte_descoberta": f"{processo.fonte_descoberta} + DataJud TPU",
        }
    )


async def _enriquecer_chunk_tribunal(
    tribunal: str,
    chunk: list[ProcessoJudicial],
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
) -> list[ProcessoJudicial]:
    endpoint = obter_endpoint_datajud(tribunal)
    mapa_num: dict[str, ProcessoJudicial] = {}
    for p in chunk:
        try:
            mapa_num[normalizar_numero_cnj(p.numero_processo)] = p
        except ValueError:
            pass

    if not mapa_num:
        return chunk

    headers = {
        "Authorization": f"APIKey {_get_api_key()}",
        "Content-Type": "application/json",
    }
    numeros_lista = list(mapa_num.keys())
    es_size = max(100, len(numeros_lista) * 4)
    query = {
        "size": es_size,
        "query": {
            "bool": {
                "should": [
                    {"match": {"numeroProcesso": n}} for n in numeros_lista
                ],
                "minimum_should_match": 1,
            }
        },
    }

    async with semaphore:
        try:
            resp = await client.post(endpoint, json=query, headers=headers)
            hits = []
            if resp.status_code == 200:
                hits = resp.json().get("hits", {}).get("hits", [])

            # Agrupa múltiplos hits do mesmo processo (ex: G1 e G2 no mesmo tribunal)
            sources_por_num: dict[str, list[dict]] = {}
            for h in hits:
                src = h.get("_source") or {}
                num_hit = str(src.get("numeroProcesso") or "").strip()
                if num_hit in mapa_num:
                    sources_por_num.setdefault(num_hit, []).append(src)

            for num_hit, lista_src in sources_por_num.items():
                proc_atual = mapa_num[num_hit]
                for src in lista_src:
                    proc_atual = _aplicar_source_datajud(proc_atual, src)
                mapa_num[num_hit] = proc_atual
        except Exception:
            pass

    return [mapa_num.get(normalizar_numero_cnj(p.numero_processo), p) for p in chunk]


async def enriquecer_lote_datajud(
    processos: list[ProcessoJudicial],
    max_concurrency: int = 10,
    batch_size: int = 20,
) -> list[ProcessoJudicial]:
    """
    Enriquece uma lista de processos via DataJud agrupando por tribunal em lotes
    Elasticsearch (muito mais rápido que 1 requisição por processo).
    """
    if not processos:
        return []

    por_tribunal: dict[str, list[ProcessoJudicial]] = {}
    for p in processos:
        por_tribunal.setdefault(p.tribunal, []).append(p)

    semaphore = asyncio.Semaphore(max_concurrency)
    tasks = []

    async with httpx.AsyncClient(timeout=_TIMEOUT) as shared_client:
        for trib, lista_trib in por_tribunal.items():
            for i in range(0, len(lista_trib), batch_size):
                chunk = lista_trib[i : i + batch_size]
                tasks.append(_enriquecer_chunk_tribunal(trib, chunk, shared_client, semaphore))

        resultados_chunks = await asyncio.gather(*tasks)

    # Recompõe na ordem original
    mapa_final: dict[str, ProcessoJudicial] = {}
    for chunk_res in resultados_chunks:
        for p in chunk_res:
            mapa_final[p.numero_processo] = p

    return [mapa_final.get(p.numero_processo, p) for p in processos]

