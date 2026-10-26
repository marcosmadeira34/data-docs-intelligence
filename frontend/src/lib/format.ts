export const fmtDateTime = (v?: string | null) =>
  v ? new Date(v.endsWith("Z") || v.includes("+") ? v : `${v}Z`).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "—";

export const fmtNumber = (v?: number | null) => (v === null || v === undefined ? "—" : v.toLocaleString("pt-BR"));

export const fmtBytes = (n: number) => {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
};

export const fmtPct = (v?: number | null) => (v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`);

export const JOB_STATUS: Record<string, string> = {
  queued: "Na fila",
  running: "Processando",
  succeeded: "Concluída",
  failed: "Falhou",
  cancelled: "Cancelada",
};

export const ERROR_KIND: Record<string, string> = {
  file_error: "Erro no arquivo",
  config_error: "Erro de configuração",
  infrastructure_error: "Falha técnica",
  timeout: "Tempo excedido",
};

export const SEVERITY: Record<string, string> = { error: "Erro", warning: "Alerta", info: "Informação" };

export const ROLES: Record<string, string> = {
  owner: "Proprietário",
  admin: "Administrador",
  analyst: "Analista",
  viewer: "Leitura",
};

export const REVIEW: Record<string, string> = {
  open: "Aberta",
  acknowledged: "Ciente",
  resolved: "Resolvida",
  false_positive: "Falso positivo",
};

export const COMPAT: Record<string, string> = {
  identical: "Idêntica",
  compatible: "Compatível",
  review_required: "Revisão necessária",
  incompatible: "Incompatível",
};

export const CATEGORY: Record<string, string> = {
  match: "Correspondente sem divergência",
  mismatch: "Correspondente com divergência",
  only_a: "Somente no arquivo A",
  only_b: "Somente no arquivo B",
  duplicate_key_a: "Chave duplicada em A",
  duplicate_key_b: "Chave duplicada em B",
  missing_key_a: "Sem chave em A",
  missing_key_b: "Sem chave em B",
};

export const INFERRED_TYPE: Record<string, string> = {
  text: "texto",
  code: "código",
  integer: "inteiro",
  decimal: "número",
  date: "data",
  boolean: "sim/não",
  tax_id: "CPF/CNPJ",
  empty: "vazia",
};

export const AUDIT_ACTION: Record<string, string> = {
  "organization.created": "Organização criada",
  "auth.login": "Login",
  "client.created": "Empresa cadastrada",
  "client.updated": "Empresa alterada",
  "file.uploaded": "Arquivo enviado",
  "file.rejected": "Arquivo rejeitado",
  "file.structure_confirmed": "Estrutura confirmada",
  "file.downloaded": "Arquivo baixado",
  "file.deleted": "Arquivo excluído",
  "file.retention_purged": "Arquivo expurgado (retenção)",
  "profile.created": "Perfil criado",
  "profile.updated": "Perfil alterado",
  "profile.version_created": "Nova versão de perfil",
  "mapping.approved": "Mapeamento aprovado",
  "rule.created": "Regra criada",
  "rule.updated": "Regra alterada",
  "rule.cloned": "Regra duplicada",
  "job.created": "Execução iniciada",
  "job.reprocessed": "Reprocessamento",
  "job.cancelled": "Execução cancelada",
  "finding.reviewed": "Inconsistência revisada",
  "comparison.created": "Comparação iniciada",
  "report.exported": "Relatório exportado",
  "member.added": "Membro adicionado",
  "member.updated": "Membro alterado",
  "member.password_reset": "Senha redefinida",
  "user.password_changed": "Senha alterada",
  "organization.updated": "Organização alterada",
};
