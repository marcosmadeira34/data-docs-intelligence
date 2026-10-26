# Arquitetura

## Visão geral

Monólito modular em Python (FastAPI) + frontend Next.js, PostgreSQL e armazenamento de objetos privado.
Sem microsserviços, sem fila externa: o processamento assíncrono usa uma fila persistida no próprio PostgreSQL.

```
Navegador ──► web (Next.js, :3000) ──proxy /api/*──► api (FastAPI, :8000) ──► PostgreSQL
                                                         │                      ▲
                                                         ▼                      │
                                                Armazenamento de objetos ◄── worker (python -m app.worker)
                                                (local em dev / S3 em prod)
```

- **web**: interface em pt-BR. Chama a API pela mesma origem (rewrite `/api/*`), o que permite cookies
  `SameSite=Strict` e dispensa CORS.
- **api**: autenticação, autorização, ingestão, inspeção, perfis, regras, criação de execuções, relatórios.
  Arquivos pequenos (`DDI_JOB_INLINE_MAX_BYTES`, padrão 2 MB) são processados de forma síncrona na própria requisição.
- **worker**: processa execuções e comparações enfileiradas, recupera jobs travados e aplica a retenção de arquivos.
  Pode ter várias réplicas (`SELECT … FOR UPDATE SKIP LOCKED`).
- **migrate**: aplica as migrations Alembic e o bootstrap (planos e regras globais) antes de api/worker subirem.

## Organização do código

```
backend/app/
  core/            config (variáveis de ambiente), errors (erros HTTP padronizados), logging (JSON), security (argon2, JWT)
  domain/          regras de negócio PURAS, sem banco/HTTP — testáveis isoladamente
    values.py        interpretação de números BR/US, datas, CPF/CNPJ, mascaramento
    canonical_fields.py  catálogo de campos padronizados (+ campos x_ personalizados)
    ingestion/       detecção do formato real, leitores em streaming (CSV/XLSX), inspeção estrutural
    mapping/         sugestão heurística, entradas de mapeamento/transformações, compatibilidade estrutural
    validation/      condições declarativas, 14 tipos de regra, motor de validação
    comparison/      motor de comparação por chave explícita
  infrastructure/
    database/        Base declarativa, sessão, registro de todos os modelos
    storage/         LocalStorage / S3Storage (mesma interface)
    ai/              abstração de provedores; heurística (padrão) e Anthropic (opcional)
  modules/         casos de uso com persistência + rotas HTTP, um por contexto
    organizations/   auth, sessão, organização, membros, consumo
    clients/ files/ profiles/ validation/ processing/ comparison/ reports/ audit/ billing/
  api/deps.py      autenticação, escopo da organização, papéis, paginação, get_owned (anti-IDOR)
  main.py          app FastAPI, middlewares (request id, cabeçalhos, limite de upload), handlers de erro, health
  worker.py        loop do worker
  cli.py           bootstrap, seed-demo, purge-retention
  demo/synthetic.py  gerador determinístico de arquivos sintéticos
frontend/src/
  app/             rotas (login, cadastro e grupo autenticado `(app)`)
  components/      UI base, painéis de arquivo (estrutura, mapeamento, execução), formulário de regras
  lib/             cliente de API (CSRF, upload com progresso), sessão, formatação, tipos
```

## Pipeline de um arquivo

1. **Recebimento** (`POST /files`): limite de tamanho (cabeçalho `Content-Length` e contagem em streaming),
   cota do plano, SHA-256, **formato real pelo conteúdo** (assinaturas binárias, contêiner ZIP do XLSX, macros,
   taxa de compressão), nome interno aleatório, armazenamento privado. Arquivos rejeitados não são armazenados
   e geram evento de auditoria.
2. **Inspeção** (síncrona no upload): codificação (BOM, UTF-8 estrito, cp1252/latin-1 presumidos com alerta),
   delimitador por consistência de colunas, abas, células mescladas, linha de cabeçalho por pontuação
   (texto, preenchimento, unicidade, nomes conhecidos, tipos nas linhas abaixo), tipos por coluna, formato numérico
   BR/US, formato de data, % de vazios, linhas malformadas, prévia limitada e **mascarada**.
   Ambiguidades (delimitador, cabeçalho, várias abas) são **relatadas**, não decididas em silêncio.
3. **Confirmação** (`POST /files/{id}/structure`): o usuário fixa aba, cabeçalho, delimitador e codificação.
4. **Mapeamento** (`POST /files/{id}/mapping`): sugestões com confiança, justificativa, alertas e
   `requires_confirmation`; perfis aprovados são comparados estruturalmente com o arquivo.
5. **Perfil** (`POST /profiles` ou `/profiles/{id}/versions`): versão imutável da estrutura + mapeamento.
   Aprovar exige que nenhuma coluna esteja "pendente".
6. **Execução** (`POST /jobs`): recusada com `409 structure_review_required` se a estrutura mudou
   (colunas mapeadas ausentes ou tipos incompatíveis). Congela no job o snapshot das regras (versão e parâmetros)
   e do arquivo/perfil, para reprodutibilidade.
7. **Validação**: leitura em streaming → `RecordBuilder` (transformações autorizadas + tipagem) →
   `ValidationEngine` → achados gravados em lotes. Limite de achados armazenados por regra; contagens são completas.
8. **Resultados**: filtros, revisão de achados, exportação CSV protegida contra fórmulas, relatório de evidências.

## Fila e execução

- Estados: `queued → running → succeeded | failed | cancelled`.
- Classificação de falhas: `file_error` e `config_error` (não retentadas), `timeout`, `infrastructure_error`
  (retentada com backoff exponencial até `job_max_attempts`).
- Idempotência: cada tentativa apaga os achados da anterior; falha definitiva remove resultados parciais.
  `Idempotency-Key` em `POST /jobs` e `POST /comparisons` evita duplicar execuções em reenvios.
- Recuperação: jobs `running` cujo lock expirou são reenfileirados (ou falham se esgotaram tentativas).
- Concorrência: limite de execuções simultâneas por organização (`DDI_MAX_CONCURRENT_JOBS_PER_ORG`).

## IA

`infrastructure/ai` define `MappingSuggester`. O padrão é heurístico e local. Com `DDI_AI_PROVIDER=anthropic`
e uma chave, `AssistedSuggester` chama o modelo **apenas para colunas sem sugestão confiável**, enviando nomes,
tipos inferidos e % de vazios (amostras só com `DDI_AI_SEND_SAMPLE_VALUES=true`, e mascaradas). A saída é
restringida por JSON Schema (destinos enumerados) e revalidada; destinos desconhecidos são descartados e toda
sugestão da IA exige confirmação humana. Falha do provedor nunca bloqueia o fluxo.

## Decisões

| Decisão | Motivo |
|---|---|
| Fila no PostgreSQL em vez de Celery/Redis | Um serviço a menos; jobs persistidos e consultáveis; suficiente para o volume do MVP. Trocar por Celery depois não afeta o domínio (`execute_job` é independente da fila). |
| Leitura com `csv` + `openpyxl` read-only, sem pandas | Memória limitada por linha; controle fino sobre tipos e números BR. |
| Regras sobre campos canônicos | Uma regra serve para qualquer layout mapeado; perfis isolam a variação de layout. |
| Regras versionadas por linha (`rule_key` + `version`) | Execuções guardam exatamente a versão usada; histórico completo. |
| Regras globais somente leitura | Organizações duplicam para personalizar; ninguém altera o catálogo silenciosamente. |
| Cookie httpOnly + CSRF double-submit; Bearer para clientes de API | Token fora do alcance de JavaScript no navegador; integrações continuam simples. |
| 404 para recurso de outra organização | Não revela a existência do recurso (anti-enumeração). |
