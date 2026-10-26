# Data Docs Intelligence

Plataforma SaaS multiempresa para escritórios contábeis e BPOs financeiros: recebe planilhas de layouts diferentes,
identifica a estrutura, mapeia colunas para campos padronizados, valida com regras configuráveis, compara arquivos
e gera relatórios de inconsistências — com rastreabilidade de cada execução.

A IA é opcional e auxiliar (sugestão de mapeamento). O núcleo é um motor **determinístico e auditável**.

## Início rápido (Docker)

Pré-requisitos: Docker com Compose v2.

```bash
cp .env.example .env            # ajuste DDI_SECRET_KEY e POSTGRES_PASSWORD
docker compose up -d --build    # db, migrate (alembic + bootstrap), api, worker, web
docker compose exec api python -m app.cli seed-demo   # opcional: dados sintéticos de demonstração
```

| Serviço | Endereço |
|---|---|
| Interface web | http://localhost:3010 |
| Documentação da API (Swagger) | http://localhost:3010/api/docs (ou http://localhost:8010/api/docs) |
| Health check | http://localhost:8010/health/ready |

Usuários criados por `seed-demo` (senha padrão `Demo-2024-segura`, ou o valor de `DDI_DEMO_PASSWORD`):

| E-mail | Papel |
|---|---|
| demo@exemplo.com.br | Proprietário — Escritório Demonstração |
| analista@exemplo.com.br | Analista |
| leitura@exemplo.com.br | Leitura |
| outra@exemplo.com.br | Proprietário de **outra** organização (para verificar o isolamento) |

As portas podem ser alteradas com `DDI_WEB_PORT`, `DDI_API_PORT` e `DDI_DB_PORT`.

## Fluxo demonstrável

1. Entre como `demo@exemplo.com.br` → **Arquivos** → abra `contas_pagar_2024_09.csv`.
2. **Estrutura**: delimitador, codificação, cabeçalho, tipos inferidos e prévia mascarada.
3. **Mapeamento e perfil**: o perfil "Contas a pagar — layout padrão" já está aprovado.
4. **Executar validação** → resultados com filtros por severidade/regra/campo → **Exportar CSV**.
5. Abra `contas_pagar_2024_10.csv` → o perfil aparece como **Idêntica** → reutilize.
6. Abra `contas_pagar_2024_11_layout_alterado.csv` → o perfil aparece como **Incompatível** → crie nova versão.
7. **Comparações** → "ERP x Banco": correspondências, divergências, só em A/B, chaves duplicadas e sem chave.
8. Entre como `outra@exemplo.com.br`: nenhum dado do Escritório Demonstração fica visível.

Os arquivos sintéticos estão em [backend/demo_data/](backend/demo_data/) (gerados por `python -m app.demo.synthetic`)
e são os mesmos usados nos testes automatizados.

## Desenvolvimento local sem Docker

Ver [docs/development.md](docs/development.md). Em resumo:

```bash
cd backend && uv venv -p 3.12 .venv && uv pip install -p .venv/bin/python -e ".[dev]"
.venv/bin/alembic upgrade head && .venv/bin/python -m app.cli bootstrap
.venv/bin/uvicorn app.main:app --port 8010 --reload        # API
.venv/bin/python -m app.worker                              # worker (outro terminal)
cd ../frontend && npm install && npm run dev                # web em http://localhost:3010
```

## Testes

```bash
cd backend
.venv/bin/pytest                                             # SQLite (rápido)
DDI_TEST_DATABASE_URL=postgresql+psycopg://ddi:ddi@localhost:5442/ddi_test .venv/bin/pytest   # PostgreSQL + migrations
cd ../frontend && npm run typecheck && npm run build
```

## Documentação

| Documento | Conteúdo |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Arquitetura, módulos, fluxo de processamento, decisões |
| [docs/data-model.md](docs/data-model.md) | Entidades, relacionamentos, índices e estratégias de exclusão |
| [docs/api.md](docs/api.md) | Endpoints, autenticação, erros, paginação, idempotência |
| [docs/security.md](docs/security.md) | Segurança, isolamento, LGPD, backup e checklist de implantação |
| [docs/development.md](docs/development.md) | Ambiente local, variáveis de ambiente, testes, operação |
| [docs/roadmap.md](docs/roadmap.md) | Funcionalidades, limitações conhecidas, pendências e estimativas |
