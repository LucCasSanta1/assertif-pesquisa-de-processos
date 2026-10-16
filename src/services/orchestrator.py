from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from src.connectors.brasilapi import consultar_cnpj
from src.connectors.datajud import enriquecer_lote_datajud
from src.connectors.pje_djen import descobrir_processos_por_cnpj
from src.logic.archive_classifier import classificar_arquivamento
from src.logic.court_classifier import classificar_esfera_e_tribunal, formatar_numero_cnj, normalizar_numero_cnj
from src.models.schemas import (
    ContagemArquivadosResumo,
    DadosEmpresaCNPJ,
    EsferaJustica,
    MovimentoProcessual,
    ProcessoJudicial,
    ResultadoBuscaCNPJ,
    ResumoEsfera,
    StatusArquivamento,
)

logger = logging.getLogger(__name__)


def _gerar_processos_demonstracao(empresa: DadosEmpresaCNPJ) -> List[ProcessoJudicial]:
    """
    Gera um conjunto de processos exemplares (Trabalhista, Estadual e Federal)
    com movimentos reais da Tabela Processual Unificada (TPU/CNJ) quando o usuário
    ativa o modo de demonstração para validar relatórios e exportação Excel.
    """
    exemplos = [
        # Trabalhista - Arquivados (TRT2, TRT15, TRT1)
        (
            "10012345620225020001",
            "TRT2",
            1125,
            "Ação Trabalhista - Rito Ordinário",
            "1ª Vara do Trabalho de São Paulo",
            [
                MovimentoProcessual(codigo=26, nome="Distribuição", data_hora=datetime(2022, 3, 10, 14, 0)),
                MovimentoProcessual(codigo=219, nome="Procedência em Parte", data_hora=datetime(2023, 1, 18, 16, 30)),
                MovimentoProcessual(codigo=848, nome="Trânsito em Julgado", data_hora=datetime(2023, 6, 5, 10, 0)),
                MovimentoProcessual(codigo=246, nome="Arquivamento Definitivo", data_hora=datetime(2024, 2, 14, 11, 20)),
            ],
        ),
        (
            "00108921120215150092",
            "TRT15",
            1126,
            "Ação Trabalhista - Rito Sumaríssimo",
            "5ª Vara do Trabalho de Campinas",
            [
                MovimentoProcessual(codigo=26, nome="Distribuição", data_hora=datetime(2021, 7, 12, 9, 15)),
                MovimentoProcessual(codigo=10966, nome="Arquivamento Sumário (Art. 852-B CLT)", data_hora=datetime(2021, 11, 22, 15, 0)),
            ],
        ),
        (
            "01005438820205010015",
            "TRT1",
            1125,
            "Ação Trabalhista - Rito Ordinário",
            "15ª Vara do Trabalho do Rio de Janeiro",
            [
                MovimentoProcessual(codigo=26, nome="Distribuição", data_hora=datetime(2020, 5, 4, 13, 0)),
                MovimentoProcessual(codigo=245, nome="Arquivamento Provisório", data_hora=datetime(2023, 9, 10, 17, 45)),
            ],
        ),
        # Trabalhista - Desarquivado / Ativo (não deve somar como arquivado!)
        (
            "10029876520235020030",
            "TRT2",
            1125,
            "Ação Trabalhista - Rito Ordinário",
            "30ª Vara do Trabalho de São Paulo",
            [
                MovimentoProcessual(codigo=26, nome="Distribuição", data_hora=datetime(2023, 2, 1, 10, 0)),
                MovimentoProcessual(codigo=245, nome="Arquivamento Provisório", data_hora=datetime(2023, 8, 12, 14, 0)),
                MovimentoProcessual(codigo=893, nome="Desarquivamento", data_hora=datetime(2024, 1, 19, 11, 0)),
            ],
        ),
        # Estadual - Arquivados (TJSP, TJRJ, TJMG)
        (
            "10456781220218260100",
            "TJSP",
            7,
            "Procedimento Comum Cível",
            "12ª Vara Cível - Foro Central Cível",
            [
                MovimentoProcessual(codigo=26, nome="Distribuição", data_hora=datetime(2021, 4, 20, 11, 10)),
                MovimentoProcessual(codigo=22, nome="Baixa Definitiva", data_hora=datetime(2023, 10, 30, 18, 0)),
            ],
        ),
        (
            "00876543220198190001",
            "TJRJ",
            12154,
            "Execução de Título Extrajudicial",
            "4ª Vara Empresarial da Capital",
            [
                MovimentoProcessual(codigo=26, nome="Distribuição", data_hora=datetime(2019, 8, 14, 15, 30)),
                MovimentoProcessual(codigo=246, nome="Arquivamento Definitivo", data_hora=datetime(2022, 12, 5, 16, 10)),
            ],
        ),
        (
            "50123456720228130024",
            "TJMG",
            436,
            "Procedimento do Juizado Especial Cível",
            "2ª Unidade Jurisdicional Cível de Belo Horizonte",
            [
                MovimentoProcessual(codigo=26, nome="Distribuição", data_hora=datetime(2022, 9, 1, 12, 0)),
                MovimentoProcessual(codigo=861, nome="Arquivamento", data_hora=datetime(2023, 7, 19, 14, 25)),
            ],
        ),
        # Federal - Arquivados (TRF3, TRF1)
        (
            "50098765420204036100",
            "TRF3",
            1116,
            "Execução Fiscal",
            "3ª Vara de Execuções Fiscais Federais de São Paulo",
            [
                MovimentoProcessual(codigo=26, nome="Distribuição", data_hora=datetime(2020, 1, 15, 9, 0)),
                MovimentoProcessual(codigo=245, nome="Arquivamento Provisório (Art. 40 LEF)", data_hora=datetime(2023, 4, 11, 16, 0)),
            ],
        ),
        (
            "10112233420214013400",
            "TRF1",
            120,
            "Mandado de Segurança Cível",
            "7ª Vara Federal Cível da SJDF",
            [
                MovimentoProcessual(codigo=26, nome="Distribuição", data_hora=datetime(2021, 6, 3, 14, 20)),
                MovimentoProcessual(codigo=246, nome="Arquivamento Definitivo", data_hora=datetime(2023, 11, 28, 17, 10)),
            ],
        ),
    ]

    processos: List[ProcessoJudicial] = []
    for num_20, sigla, cod_classe, nome_classe, orgao, movs in exemplos:
        esfera, sigla_padrao, uf_trib = classificar_esfera_e_tribunal(num_20, sigla)
        arq, status_det, cod_mov, desc_mov, dt_arq = classificar_arquivamento(movs)
        processos.append(
            ProcessoJudicial(
                numero_processo=num_20,
                numero_formatado=formatar_numero_cnj(num_20),
                tribunal=sigla_padrao,
                esfera=esfera,
                classe_codigo=cod_classe,
                classe_nome=nome_classe,
                orgao_julgador=orgao,
                uf=uf_trib,
                data_ajuizamento=movs[0].data_hora if movs else None,
                data_ultima_movimentacao=movs[-1].data_hora if movs else None,
                ultimo_movimento_relevante=desc_mov,
                codigo_movimento_arquivamento=cod_mov,
                data_arquivamento=dt_arq,
                arquivado=arq,
                status_detalhado=status_det,
                polo_empresa="Passivo (Réu/Reclamado)",
                partes_resumo=f"{empresa.razao_social} ({empresa.cnpj_formatado})",
                fonte_descoberta="Simulação TPU/DataJud (Modo Demonstração)",
                movimentos=movs,
            )
        )
    return processos


def consolidar_resultado_busca(
    job_id: str,
    empresa: DadosEmpresaCNPJ,
    processos: List[ProcessoJudicial],
    fontes_consultadas: List[str],
    observacoes: Optional[List[str]] = None,
) -> ResultadoBuscaCNPJ:
    """
    Garante que todos os processos estejam com esfera e status de arquivamento
    calculados e consolida as contagens exatas por esfera (Trabalhista, Estadual, Federal).
    """
    detalhamento: Dict[str, ResumoEsfera] = {
        EsferaJustica.TRABALHISTA.value: ResumoEsfera(),
        EsferaJustica.ESTADUAL.value: ResumoEsfera(),
        EsferaJustica.FEDERAL.value: ResumoEsfera(),
        EsferaJustica.OUTROS.value: ResumoEsfera(),
    }

    processos_arquivados: List[ProcessoJudicial] = []

    for proc in processos:
        # Garante classificação de esfera e tribunal pelo número CNJ
        esfera, sigla_padrao, uf_trib = classificar_esfera_e_tribunal(proc.numero_processo, proc.tribunal)
        proc.esfera = esfera
        proc.tribunal = sigla_padrao
        if not proc.uf and uf_trib:
            proc.uf = uf_trib

        # Caso ainda esteja indeterminado e possua movimentos, roda o classificador TPU
        if proc.status_detalhado == StatusArquivamento.INDETERMINADO and proc.movimentos:
            arq, status_det, cod_mov, desc_mov, dt_arq = classificar_arquivamento(
                proc.movimentos, proc.ultimo_movimento_relevante
            )
            proc.arquivado = arq
            proc.status_detalhado = status_det
            proc.codigo_movimento_arquivamento = cod_mov
            proc.ultimo_movimento_relevante = desc_mov
            proc.data_arquivamento = dt_arq

        chave_esfera = proc.esfera.value
        if chave_esfera not in detalhamento:
            detalhamento[chave_esfera] = ResumoEsfera()

        resumo_esf = detalhamento[chave_esfera]
        resumo_esf.total_localizados += 1

        if proc.arquivado:
            resumo_esf.arquivados += 1
            if proc.status_detalhado == StatusArquivamento.ARQUIVADO_PROVISORIO:
                resumo_esf.arquivados_provisorio += 1
            else:
                resumo_esf.arquivados_definitivo += 1
            processos_arquivados.append(proc)
        else:
            resumo_esf.ativos += 1

    # Remove a chave "Outros" do detalhamento se estiver zerada
    if detalhamento[EsferaJustica.OUTROS.value].total_localizados == 0:
        detalhamento.pop(EsferaJustica.OUTROS.value, None)

    trab_arq = detalhamento[EsferaJustica.TRABALHISTA.value].arquivados
    est_arq = detalhamento[EsferaJustica.ESTADUAL.value].arquivados
    fed_arq = detalhamento[EsferaJustica.FEDERAL.value].arquivados
    outros_arq = detalhamento.get(EsferaJustica.OUTROS.value, ResumoEsfera()).arquivados

    contagem = ContagemArquivadosResumo(
        trabalhista=trab_arq,
        estadual=est_arq,
        federal=fed_arq,
        total_arquivados=trab_arq + est_arq + fed_arq + outros_arq,
        total_geral_analisados=len(processos),
    )

    return ResultadoBuscaCNPJ(
        job_id=job_id,
        empresa=empresa,
        data_consulta=datetime.now(),
        contagem_arquivados=contagem,
        detalhamento_por_esfera=detalhamento,
        processos_arquivados=processos_arquivados,
        todos_processos=processos,
        fontes_consultadas=fontes_consultadas,
        observacoes=observacoes or [],
    )


async def executar_busca_completa_cnpj(
    cnpj: str,
    razao_social_override: Optional[str] = None,
    max_paginas_por_estrategia: int = 8,
    numeros_cnj_adicionais: Optional[List[str]] = None,
    modo_demonstracao: bool = False,
    job_id: Optional[str] = None,
) -> ResultadoBuscaCNPJ:
    """
    Pipeline principal de consulta de processos arquivados por CNPJ:
    1. Consulta dados cadastrais do CNPJ na Receita Federal (via BrasilAPI / CNPJ.ws / ReceitaWS).
    2. Carrega processos históricos da Base de Acervo (ex: Grupo Sudati 2.0.xlsx ou planilhas importadas).
    3. Descobre processos judiciais em todo o país via Comunica PJe / DJEN (por CNPJ e Núcleo Empresarial S.A./LTDA).
    4. Consulta a API Pública do DataJud (CNJ) para enriquecer os movimentos TPU (Tabelas Processuais Unificadas).
    5. Classifica cronologicamente cada processo como Arquivado (Definitivo/Provisório/Baixado) ou Ativo/Reativado.
    6. Separa as contagens exatas entre Justiça do Trabalho, Justiça Estadual e Justiça Federal.
    """
    from src.connectors.planilha_base import buscar_processos_na_planilha_base

    jid = job_id or str(uuid.uuid4())
    observacoes: List[str] = []

    # 1. Enriquecimento cadastral do CNPJ
    empresa = await consultar_cnpj(cnpj)
    if razao_social_override and razao_social_override.strip():
        empresa.razao_social = razao_social_override.strip().upper()

    if modo_demonstracao:
        processos_demo = _gerar_processos_demonstracao(empresa)
        observacoes.append(
            "Modo demonstração ativado: dados simulados com movimentos reais da Tabela Processual Unificada (TPU/CNJ)."
        )
        return consolidar_resultado_busca(
            job_id=jid,
            empresa=empresa,
            processos=processos_demo,
            fontes_consultadas=["BrasilAPI / Receita Federal", "Simulador Oficial TPU/DataJud (Demonstração)"],
            observacoes=observacoes,
        )

    fontes_totais = ["BrasilAPI / Receita Federal (Cadastro CNPJ)"]
    mapa_processos: Dict[str, ProcessoJudicial] = {}

    # 2. Base histórica (planilhas acervo / Grupo Sudati 2.0.xlsx / uploads)
    processos_acervo = buscar_processos_na_planilha_base(empresa.cnpj)
    if processos_acervo:
        fontes_totais.append(f"Base Histórica de Acervo ({len(processos_acervo)} processos 2008-2026)")
        for p in processos_acervo:
            mapa_processos[p.numero_processo] = p

    # 3. Descoberta nacional ao vivo (Comunica PJe / DJEN + Números adicionais)
    processos_descobertos, fontes_comunica = await descobrir_processos_por_cnpj(
        empresa=empresa,
        max_paginas_por_estrategia=max_paginas_por_estrategia,
        numeros_cnj_adicionais=numeros_cnj_adicionais,
    )
    fontes_totais.extend(fontes_comunica)

    novos_ou_pendentes: List[ProcessoJudicial] = []
    for p_desc in processos_descobertos:
        if p_desc.numero_processo not in mapa_processos:
            mapa_processos[p_desc.numero_processo] = p_desc
            novos_ou_pendentes.append(p_desc)
        else:
            # Mescla informações complementares (ex: classe ou órgão julgador vindo do Comunica PJe)
            p_atual = mapa_processos[p_desc.numero_processo]
            if not p_atual.classe_nome and p_desc.classe_nome:
                p_atual.classe_nome = p_desc.classe_nome
            if not p_atual.orgao_julgador and p_desc.orgao_julgador:
                p_atual.orgao_julgador = p_desc.orgao_julgador
            if p_desc.movimentos:
                p_atual.movimentos.extend(p_desc.movimentos)

    # 4. Enriquecimento de movimentos TPU via API Pública do DataJud (CNJ)
    # Enriquece prioritariamente os processos descobertos ao vivo ou com status indeterminado
    para_enriquecer = [
        p for p in mapa_processos.values()
        if p.status_detalhado == StatusArquivamento.INDETERMINADO or p in novos_ou_pendentes
    ]
    if para_enriquecer:
        fontes_totais.append("API Pública DataJud (CNJ - Tabelas Processuais Unificadas TPU)")
        enriquecidos = await enriquecer_lote_datajud(para_enriquecer, max_concurrency=10, batch_size=25)
        for p_enr in enriquecidos:
            mapa_processos[p_enr.numero_processo] = p_enr

    todos_processos = list(mapa_processos.values())
    if not todos_processos:
        observacoes.append(
            "Nenhum processo público localizado no Comunica PJe/DJEN para este CNPJ/Razão Social. "
            "Você também pode importar uma planilha de acervo (.xlsx) ou informar números CNJ adicionais."
        )

    return consolidar_resultado_busca(
        job_id=jid,
        empresa=empresa,
        processos=todos_processos,
        fontes_consultadas=fontes_totais,
        observacoes=observacoes,
    )
