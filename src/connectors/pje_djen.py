from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

import httpx

from src.models.schemas import (
    DadosEmpresaCNPJ,
    EsferaJustica,
    MovimentoProcessual,
    ProcessoJudicial,
    StatusArquivamento,
)

logger = logging.getLogger(__name__)

COMUNICA_PJE_URL = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"

# Regex para identificar números de processo no padrão CNJ (formatado ou 20 dígitos)
CNJ_FORMATADO_RE = re.compile(r"\b(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})\b")
CNJ_DIGITOS_RE = re.compile(r"\b(\d{20})\b")


def _limpar_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor or "")


def _formatar_cnj_local(digitos: str) -> str:
    d = _limpar_digitos(digitos)
    if len(d) != 20:
        return digitos
    return f"{d[0:7]}-{d[7:9]}.{d[9:13]}.{d[13:14]}.{d[14:16]}.{d[16:20]}"


def _inferir_esfera_e_tribunal_fallback(numero_20: str, sigla_informada: Optional[str] = None) -> Tuple[EsferaJustica, str, Optional[str]]:
    """
     Tenta usar src.logic.court_classifier (implementado pelo Claude Code) e possui fallback seguro.
    """
    try:
        from src.logic.court_classifier import classificar_esfera_e_tribunal
        return classificar_esfera_e_tribunal(numero_20, sigla_informada)
    except Exception:
        d = _limpar_digitos(numero_20)
        sigla = (sigla_informada or "").upper().strip()
        if len(d) == 20:
            j = d[13]
            tr = int(d[14:16])
            if j == "5":
                return EsferaJustica.TRABALHISTA, sigla or (f"TRT{tr}" if tr > 0 else "TST"), None
            if j == "4":
                return EsferaJustica.FEDERAL, sigla or f"TRF{tr}", None
            if j == "8":
                return EsferaJustica.ESTADUAL, sigla or f"TJ{tr:02d}", None
        if sigla.startswith("TRT") or sigla == "TST":
            return EsferaJustica.TRABALHISTA, sigla, None
        if sigla.startswith("TRF") or sigla in {"CJF", "JF"}:
            return EsferaJustica.FEDERAL, sigla, None
        if sigla.startswith("TJ"):
            return EsferaJustica.ESTADUAL, sigla, None
        return EsferaJustica.OUTROS, sigla or "DESCONHECIDO", None


def _extrair_movimentos_de_texto_comunicacao(
    texto: str,
    data_disponibilizacao: Optional[datetime],
) -> List[MovimentoProcessual]:
    """
    Analisa o teor da publicação/comunicação judicial do DJEN/Comunica PJe para detectar
    eventos de arquivamento ou desarquivamento publicados nos diários oficiais, servindo
    como fonte complementar caso o movimento ainda não esteja sincronizado no DataJud.
    """
    if not texto:
        return []
    t = texto.lower()
    dt = data_disponibilizacao or datetime.utcnow()
    movs: List[MovimentoProcessual] = []

    # Verifica reativação / desarquivamento primeiro
    if any(k in t for k in ["desarquivamento", "desarquivem-se os autos", "autos desarquivados", "reativação do processo"]):
        movs.append(
            MovimentoProcessual(
                codigo=893,
                nome="Desarquivamento (Detectado via publicação DJEN/PJe)",
                data_hora=dt,
                complemento="Extraído do teor da comunicação processual oficial",
            )
        )
    # Verifica arquivamento definitivo / baixa
    elif any(
        k in t
        for k in [
            "arquivem-se os autos",
            "arquivamento definitivo",
            "arquivado definitivamente",
            "baixa definitiva",
            "remetam-se os autos ao arquivo",
            "determino o arquivamento dos autos",
            "arquive-se o processo",
            "extinção da execução",
            "processo arquivado",
        ]
    ):
        movs.append(
            MovimentoProcessual(
                codigo=246,
                nome="Arquivamento Definitivo / Baixa (Detectado via publicação DJEN/PJe)",
                data_hora=dt,
                complemento="Extraído do teor da comunicação processual oficial",
            )
        )
    elif any(
        k in t
        for k in [
            "arquivamento provisório",
            "arquivado provisoriamente",
            "arquivo provisório",
        ]
    ):
        movs.append(
            MovimentoProcessual(
                codigo=245,
                nome="Arquivamento Provisório (Detectado via publicação DJEN/PJe)",
                data_hora=dt,
                complemento="Extraído do teor da comunicação processual oficial",
            )
        )

    return movs


def _parse_data(valor: Optional[str]) -> Optional[datetime]:
    if not valor:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(valor[:19], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(valor.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


async def _consultar_pagina_comunica_pje(
    client: httpx.AsyncClient,
    params: Dict[str, str | int],
) -> List[dict]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CNJ-Legal-Analytics/1.0",
    }
    try:
        resp = await client.get(COMUNICA_PJE_URL, params=params, headers=headers, timeout=20.0)
        if resp.status_code != 200:
            logger.warning("Comunica PJe retornou status %s para params=%s", resp.status_code, params)
            return []
        data = resp.json()
        if isinstance(data, dict):
            items = data.get("items") or data.get("content") or data.get("resultado") or []
            return items if isinstance(items, list) else []
        if isinstance(data, list):
            return data
        return []
    except Exception as exc:
        logger.warning("Erro ao consultar Comunica PJe (%s): %s", params, exc)
        return []


def _limpar_razao_social_para_busca(razao_social: str) -> str:
    """
    Remove sufixos societários genéricos ou pontuações que podem atrapalhar
    o match no Comunica PJe / DJEN quando grafados de forma abreviada nos tribunais.
    """
    nome = (razao_social or "").strip()
    # Mantém uma versão limpa sem pontuação excessiva
    nome = re.sub(r"\s+", " ", nome)
    return nome


def _extrair_nucleo_empresarial(razao_social: str) -> str:
    nome = (razao_social or "").upper().strip()
    # Remove sufixos societários no final (S.A, S/A, LTDA, EIRELI, ME, EPP, etc.)
    nucleo = re.sub(
        r"[\s\-.,/]+\b(LTDA|S\.?A\.?|S/A|EIRELI|ME|EPP|EM RECUPERACAO JUDICIAL|SRM)\b.*$",
        "",
        nome,
        flags=re.IGNORECASE,
    ).strip(" -.,/")
    return nucleo if len(nucleo) >= 4 else nome


def _validar_pertinencia_empresa(
    item: dict,
    cnpj_limpo: str,
    cnpj_formatado: str,
    razao_social: str,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Verifica se a comunicação/processo realmente pertence à empresa buscada
    (incluindo variações históricas LTDA / S.A. do mesmo grupo/núcleo empresarial).
    """
    texto = (item.get("texto") or "").upper()
    destinatarios = item.get("destinatarios") or []

    partes_nomes: List[str] = []
    polo_empresa: Optional[str] = None
    razao_upper = (razao_social or "").upper().strip()
    nucleo_upper = _extrair_nucleo_empresarial(razao_upper)

    ignorar = {"LTDA", "S/A", "S.A.", "S.A", "SA", "ME", "EPP", "EIRELI", "CIA", "COMPANHIA", "EMPRESA", "DE", "DO", "DA", "DOS", "DAS", "E", "EM", "RECUPERACAO", "JUDICIAL", "SRM"}
    tokens_relevantes = [
        t for t in re.split(r"[^A-Z0-9]+", nucleo_upper) if len(t) >= 3 and t not in ignorar
    ]

    for dest in destinatarios:
        if isinstance(dest, dict):
            nome_dest = (dest.get("nome") or "").strip()
            polo = (dest.get("polo") or "").strip()
            if nome_dest:
                partes_nomes.append(f"{nome_dest} ({polo})" if polo else nome_dest)
                nome_dest_upper = nome_dest.upper()
                if nucleo_upper and len(nucleo_upper) >= 5 and nucleo_upper in nome_dest_upper:
                    polo_empresa = polo or "Parte"
                elif razao_upper and (razao_upper in nome_dest_upper or nome_dest_upper in razao_upper):
                    polo_empresa = polo or "Parte"
                elif tokens_relevantes and len(tokens_relevantes) >= 2:
                    if all(tok in nome_dest_upper for tok in tokens_relevantes[:2]):
                        polo_empresa = polo or "Parte"

    partes_resumo = "; ".join(partes_nomes[:6]) if partes_nomes else None

    # 1. CNPJ consta diretamente no texto da publicação
    if cnpj_formatado in texto or (cnpj_limpo and cnpj_limpo in _limpar_digitos(texto)):
        return True, polo_empresa or "Identificado por CNPJ", partes_resumo

    # 2. Identificado nos destinatários oficiais da intimação
    if polo_empresa is not None:
        return True, polo_empresa, partes_resumo

    # 3. Núcleo empresarial ou razão social consta no texto da publicação
    if nucleo_upper and len(nucleo_upper) >= 5 and nucleo_upper in texto:
        return True, "Citado na publicação", partes_resumo

    return False, None, partes_resumo


async def descobrir_processos_por_cnpj(
    empresa: DadosEmpresaCNPJ,
    max_paginas_por_estrategia: int = 16,
    itens_por_pagina: int = 100,
    numeros_cnj_adicionais: Optional[List[str]] = None,
) -> Tuple[List[ProcessoJudicial], List[str]]:
    """
    Descobre processos judiciais da empresa em âmbito nacional combinando:
    1. Busca no Comunica PJe / DJEN por CNPJ formatado e numérico
    2. Busca no Comunica PJe / DJEN pelo Núcleo Empresarial (cobrindo automaticamente variações S.A. e LTDA)
    3. Paginação paralela para alta velocidade
    4. Números de processos CNJ informados diretamente na requisição ou planilha
    """
    processos_map: Dict[str, ProcessoJudicial] = {}
    fontes_consultadas: List[str] = []

    cnpj_limpo = _limpar_digitos(empresa.cnpj)
    cnpj_fmt = empresa.cnpj_formatado
    razao_limpa = _limpar_razao_social_para_busca(empresa.razao_social)
    nucleo = _extrair_nucleo_empresarial(razao_limpa)

    estrategias: List[Tuple[str, Dict[str, str | int], int]] = []

    if cnpj_fmt:
        estrategias.append(("CNJ Comunica PJe / DJEN (CNPJ Formatado)", {"texto": cnpj_fmt}, 3))

    if razao_limpa and not razao_limpa.startswith("EMPRESA "):
        # Busca pelo núcleo empresarial (ex: "SUDATI PAINEIS"), que retorna simultaneamente S.A., LTDA, etc.
        termo_principal = nucleo if len(nucleo) >= 5 else razao_limpa
        estrategias.append(
            (f"CNJ Comunica PJe / DJEN (Busca Nominal: {termo_principal})", {"nomeParte": termo_principal}, max_paginas_por_estrategia)
        )

    sem = asyncio.Semaphore(6)

    async def _buscar_pagina(client: httpx.AsyncClient, params: Dict[str, str | int]) -> List[dict]:
        async with sem:
            return await _consultar_pagina_comunica_pje(client, params)

    async with httpx.AsyncClient(verify=True, follow_redirects=True) as client:
        for nome_fonte, base_params, limite_pags in estrategias:
            fontes_consultadas.append(nome_fonte)
            # Busca a página 1 primeiro para saber se há mais páginas
            p1_items = await _buscar_pagina(client, {**base_params, "pagina": 1, "itensPorPagina": itens_por_pagina})
            todas_paginas_itens = [p1_items]

            if len(p1_items) >= itens_por_pagina and limite_pags > 1:
                tasks = [
                    _buscar_pagina(client, {**base_params, "pagina": pag, "itensPorPagina": itens_por_pagina})
                    for pag in range(2, limite_pags + 1)
                ]
                demais = await asyncio.gather(*tasks)
                todas_paginas_itens.extend(demais)

            for itens in todas_paginas_itens:
                for item in itens:
                    pertinente, polo, partes_resumo = _validar_pertinencia_empresa(
                        item, cnpj_limpo, cnpj_fmt, empresa.razao_social
                    )
                    if not pertinente:
                        continue

                    num_raw = str(item.get("numero_processo") or item.get("numeroProcesso") or "")
                    num_20 = _limpar_digitos(num_raw)
                    if len(num_20) != 20:
                        m_fmt = CNJ_FORMATADO_RE.search(str(item.get("numeroprocessocommascara") or item.get("texto") or ""))
                        if m_fmt:
                            num_20 = _limpar_digitos(m_fmt.group(1))
                        else:
                            continue

                    if len(num_20) != 20:
                        continue

                    sigla_trib = (item.get("siglaTribunal") or "").strip().upper()
                    esfera, sigla_padrao, uf_trib = _inferir_esfera_e_tribunal_fallback(num_20, sigla_trib)
                    num_formatado = item.get("numeroprocessocommascara") or _formatar_cnj_local(num_20)
                    dt_disp = _parse_data(item.get("data_disponibilizacao") or item.get("dataDisponibilizacao"))
                    texto_pub = item.get("texto") or ""
                    movs_extraidos = _extrair_movimentos_de_texto_comunicacao(texto_pub, dt_disp)

                    codigo_classe_raw = item.get("codigoClasse")
                    codigo_classe = int(codigo_classe_raw) if str(codigo_classe_raw or "").isdigit() else None
                    nome_classe = item.get("nomeClasse") or None
                    orgao = item.get("nomeOrgao") or None

                    if num_20 not in processos_map:
                        processos_map[num_20] = ProcessoJudicial(
                            numero_processo=num_20,
                            numero_formatado=num_formatado,
                            tribunal=sigla_padrao,
                            esfera=esfera,
                            classe_codigo=codigo_classe,
                            classe_nome=nome_classe,
                            orgao_julgador=orgao,
                            uf=uf_trib,
                            data_ultima_movimentacao=dt_disp,
                            polo_empresa=polo,
                            partes_resumo=partes_resumo,
                            fonte_descoberta="Comunica PJe / DJEN (CNJ)",
                            movimentos=movs_extraidos,
                        )
                    else:
                        proc_existente = processos_map[num_20]
                        if movs_extraidos:
                            proc_existente.movimentos.extend(movs_extraidos)
                        if dt_disp and (
                            not proc_existente.data_ultima_movimentacao
                            or dt_disp > proc_existente.data_ultima_movimentacao
                        ):
                            proc_existente.data_ultima_movimentacao = dt_disp
                        if not proc_existente.partes_resumo and partes_resumo:
                            proc_existente.partes_resumo = partes_resumo
                        if not proc_existente.polo_empresa and polo:
                            proc_existente.polo_empresa = polo

    # Adiciona números CNJ informados manualmente pelo usuário (se houver)
    if numeros_cnj_adicionais:
        fontes_consultadas.append("Lista de Processos CNJ Informada na Requisição")
        for n_raw in numeros_cnj_adicionais:
            num_20 = _limpar_digitos(n_raw)
            if len(num_20) == 20 and num_20 not in processos_map:
                esfera, sigla_padrao, uf_trib = _inferir_esfera_e_tribunal_fallback(num_20, None)
                processos_map[num_20] = ProcessoJudicial(
                    numero_processo=num_20,
                    numero_formatado=_formatar_cnj_local(num_20),
                    tribunal=sigla_padrao,
                    esfera=esfera,
                    uf=uf_trib,
                    polo_empresa="Informado pelo usuário",
                    fonte_descoberta="Input Direto + DataJud CNJ",
                )

    return list(processos_map.values()), fontes_consultadas
