# Radar Jurídico CNPJ — API de Processos Arquivados (Trabalhista, Estadual e Federal)

Projeto desenvolvido em parceria colaborativa entre **Gemini (Antigravity)** e **Claude Code**.

## Visão Geral

Esta API e Painel Web permitem consultar, a partir de um **CNPJ**, a quantidade exata de **processos judiciais arquivados** separados por esfera da Justiça:

1. **Justiça do Trabalho (`J=5`)** — `TRT1` a `TRT24` e `TST`
2. **Justiça Estadual (`J=8`)** — Todos os 27 Tribunais de Justiça (`TJAC` a `TJTO`)
3. **Justiça Federal (`J=4`)** — `TRF1` a `TRF6`

Além do resumo quantitativo por esfera (incluindo a distinção entre **Arquivamento Definitivo/Baixa** e **Arquivamento Provisório**), a API permite baixar uma planilha **Excel (`.xlsx`)** completa e estilizada com 6 abas.

---

## Arquitetura de Precisão (Sem Certificado Digital)

1. **Enriquecimento Cadastral (`src/connectors/brasilapi.py`):**
   - Consulta automática do CNPJ na Receita Federal via `BrasilAPI` (com fallback para `CNPJ.ws` e `ReceitaWS`) para obter a Razão Social oficial, Nome Fantasia, UF, Município e Situação Cadastral.
2. **Descoberta Nacional de Processos (`src/connectors/pje_djen.py`):**
   - Consulta a API nacional do **Comunica PJe / DJEN (CNJ)** combinando buscas pelo CNPJ formatado, CNPJ numérico (14 dígitos), Razão Social e núcleo empresarial, validando pertinência para evitar homônimos.
3. **Classificação de Esfera e Tribunal (`src/logic/court_classifier.py`):**
   - Analisa os 20 dígitos do Número Único Processual CNJ (`NNNNNNN-DD.AAAA.J.TR.OOOO`) para classificar com 100% de precisão a esfera (`J=5` Trabalhista, `J=8` Estadual, `J=4` Federal) e o tribunal (`TR`).
4. **Enriquecimento e Máquina de Estados TPU (`src/connectors/datajud.py` + `src/logic/archive_classifier.py`):**
   - Consulta a **API Pública Oficial do DataJud (CNJ)** para cada processo localizado.
   - Ordena todos os movimentos da Tabela Processual Unificada (TPU) cronologicamente por `data_hora` e verifica:
     - **Arquivamento Definitivo / Baixa:** Códigos TPU `246`, `22`, `861`, `472`, `473`, `10966` (Arquivamento Sumário Trabalhista - Art. 852-B CLT), `12618`, `196`.
     - **Arquivamento Provisório:** Códigos TPU `245`, `247`.
     - **Desarquivamento / Reativação:** Códigos TPU `893`, `849`, `36` (se ocorrerem *após* um arquivamento, o processo volta a ser classificado como **Ativo/Desarquivado**, garantindo máxima precisão).
5. **Exportação Excel (`.xlsx`) (`src/exporters/excel.py`):**
   - Gera planilha OpenPyXL em memória com 6 abas:
     - `Resumo Executivo`
     - `Processos Arquivados`
     - `Trabalhista (Arquivados)`
     - `Estadual (Arquivados)`
     - `Federal (Arquivados)`
     - `Todos os Processos Analisados`

---

## Como Executar

```powershell
cd C:\Users\asser\.gemini\antigravity\scratch\processos-arquivados-cnpj
python main.py
```

- **Painel Web Interativo:** `http://127.0.0.1:8000/`
- **Documentação Interativa (Swagger UI):** `http://127.0.0.1:8000/docs`

### Principais Endpoints

- `POST /api/v1/consulta-cnpj` — Retorna o JSON completo com as contagens separadas (`trabalhista`, `estadual`, `federal`, `total_arquivados`) e a lista de processos.
- `GET /api/v1/jobs/{job_id}/excel` — Baixa o arquivo `.xlsx` da consulta realizada.
- `GET /api/v1/consulta-cnpj/{cnpj}/excel` — Faz a consulta pelo CNPJ e já baixa diretamente a planilha Excel.
