# Desenvolvimento e operação

## Requisitos

Python 3.12 (com [uv](https://docs.astral.sh/uv/) ou pip), Node.js 18.18+ (20 recomendado), Docker para PostgreSQL.

## Ambiente local

```bash
docker compose up -d db                                   # PostgreSQL em localhost:5442

cd backend
uv venv -p 3.12 .venv && uv pip install -p .venv/bin/python -e ".[dev]"   # extras opcionais: s3, ai
export DDI_DATABASE_URL=postgresql+psycopg://ddi:ddi@localhost:5442/ddi
.venv/bin/alembic upgrade head
.venv/bin/python -m app.cli bootstrap                     # planos + regras globais
.venv/bin/python -m app.cli seed-demo                     # opcional
.venv/bin/uvicorn app.main:app --port 8010 --reload
.venv/bin/python -m app.worker                            # outro terminal

cd ../frontend
npm install
npm run dev                                               # http://localhost:3010 (proxy /api → localhost:8010)
```

`API_INTERNAL_URL` define o destino do proxy do frontend (padrão `http://localhost:8010`; no Docker, `http://api:8000`).

## Variáveis de ambiente (backend, prefixo `DDI_`)

| Variável | Padrão | Descrição |
|---|---|---|
| `ENVIRONMENT` | development | `production` exige `SECRET_KEY` próprio |
| `DATABASE_URL` | postgresql+psycopg://ddi:ddi@localhost:5442/ddi | conexão SQLAlchemy |
| `SECRET_KEY` | (dev) | chave de assinatura dos tokens (≥ 32 caracteres) |
| `ACCESS_TOKEN_TTL_MINUTES` | 480 | validade da sessão |
| `COOKIE_SECURE` | false | cookies apenas em HTTPS |
| `ALLOW_SIGNUP` | true | cadastro público de organizações |
| `CORS_ORIGINS` | vazio | lista separada por vírgulas (desnecessário com o proxy do Next) |
| `LOGIN_MAX_ATTEMPTS` / `LOGIN_LOCKOUT_SECONDS` | 8 / 300 | bloqueio de força bruta |
| `STORAGE_BACKEND` | local | `local` ou `s3` |
| `STORAGE_LOCAL_ROOT` | ./var/storage | diretório privado (dev) |
| `S3_BUCKET` / `S3_ENDPOINT_URL` / `S3_REGION` | — | armazenamento S3 compatível (credenciais AWS padrão) |
| `MAX_UPLOAD_BYTES` | 52428800 | tamanho máximo por arquivo (também limitado pelo plano) |
| `MAX_XLSX_UNCOMPRESSED_BYTES` | 419430400 | limite de descompressão de XLSX |
| `MAX_RECORDS_PER_FILE` | 1000000 | registros por arquivo |
| `FILE_RETENTION_DAYS` | 180 | retenção do conteúdo |
| `PREVIEW_ROWS` / `INSPECTION_SAMPLE_ROWS` | 20 / 1000 | prévia e amostra para inferência |
| `MASK_SENSITIVE_PREVIEWS` | true | mascaramento em prévias e achados |
| `JOB_INLINE_MAX_BYTES` | 2097152 | até este tamanho, processa na requisição |
| `JOB_MAX_ATTEMPTS` / `JOB_TIMEOUT_SECONDS` / `JOB_LOCK_TIMEOUT_SECONDS` | 3 / 900 / 1800 | retentativas e tempos |
| `MAX_CONCURRENT_JOBS_PER_ORG` | 5 | execuções simultâneas por organização |
| `MAX_FINDINGS_PER_RULE` / `MAX_COMPARISON_ROWS_STORED` | 5000 / 20000 | limites de armazenamento de resultados |
| `WORKER_POLL_SECONDS` | 2 | intervalo de consulta da fila |
| `AI_PROVIDER` | none | `none` ou `anthropic` |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | — / claude-opus-5-5 | provedor de IA opcional (extra `ai`) |
| `AI_SERVER_FALLBACK` | true | fallback do lado do servidor em caso de recusa do modelo |
| `AI_SEND_SAMPLE_VALUES` | false | envia até 3 amostras mascaradas por coluna |
| `MAPPING_CONFIRMATION_THRESHOLD` | 0.85 | abaixo disso, sugestão exige confirmação |
| `LOG_LEVEL` | INFO | nível de log |

## Testes

```bash
cd backend
.venv/bin/pytest                                    # SQLite temporário
docker exec ddi-db-1 psql -U ddi -c "create database ddi_test"   # uma vez
DDI_TEST_DATABASE_URL=postgresql+psycopg://ddi:ddi@localhost:5442/ddi_test .venv/bin/pytest
```

| Arquivo | Cobertura |
|---|---|
| `test_values.py` | números BR/US, datas, CPF/CNPJ, mascaramento |
| `test_ingestion.py` | CSV válido, delimitadores, codificação, XLSX com várias abas/títulos/mesclas, vazio, corrompido, extensão incompatível, macro, bomba de descompressão, cabeçalho ambíguo, colunas duplicadas, linhas malformadas |
| `test_mapping.py` | sinônimos, desconhecidas, conflitos, ambiguidade, validação de entradas, transformações, compatibilidade estrutural |
| `test_rules.py` | cada um dos 14 tipos de regra, condições, severidades, limite de achados, regex perigosa |
| `test_comparison.py` | correspondências, só em A/B, tolerâncias, chaves duplicadas, nulos, chaves ausentes, valores inseguros |
| `test_export_and_ai.py` | injeção de fórmulas, contrato da IA, fallback sem IA, minimização de dados |
| `test_api_flow.py` | fluxo completo do MVP (critérios 1–16), idempotência, reprocessamento, versionamento de regras |
| `test_security.py` | isolamento entre organizações, papéis, CSRF, tokens, logs, erros, cotas, uploads |
| `test_jobs_queue.py` | worker, retentativas, classificação de falhas, recuperação, cancelamento, concorrência, retenção |
| `test_migrations.py` | upgrade/downgrade e ausência de divergência modelo × migration (PostgreSQL) |
| `test_entrypoints.py` | API, worker e CLI registram todas as tabelas quando iniciados isoladamente |

## Operação

- **Logs**: JSON em stdout com `request_id` (e `job_id` dentro do worker). Ex.: `docker compose logs -f api worker`.
- **Reprocessamento**: `POST /api/v1/jobs/{id}/reprocess` (ou botão "Reprocessar") cria uma nova execução com o
  mesmo arquivo, perfil e seleção de regras (versões atuais), vinculada por `reprocess_of_id`.
- **Jobs travados**: o worker reenfileira automaticamente após `JOB_LOCK_TIMEOUT_SECONDS`.
- **Retenção manual**: `python -m app.cli purge-retention`.
- **Novas migrations**: altere os modelos → `alembic revision --autogenerate -m "..."` → revise → `alembic upgrade head`;
  `test_migrations.py` falha se houver divergência.
