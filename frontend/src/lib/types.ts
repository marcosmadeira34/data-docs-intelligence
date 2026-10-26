export type Column = {
  index: number; name: string; normalized: string; inferred_type: string; null_ratio: number; filled: number;
  distinct_sample: number; number_style: string | null; date_format: string | null; samples: string[];
};

export type Inspection = {
  format: string;
  options: { sheet: string | null; header_row: number; delimiter: string | null; encoding: string | null };
  sheets: { name: string; dimension: string | null; visible: boolean; merged_ranges: string[] | null }[];
  header_candidates: { row: number; score: number; values: string[]; is_title: boolean }[];
  delimiter_candidates: { delimiter: string; fields: number; consistency: number }[];
  columns: Column[];
  row_count: number;
  blank_rows: number;
  malformed_rows: { count: number; examples: { row: number; fields: number; expected: number }[] };
  preview: string[][];
  warnings: { code: string; message: string }[];
  ambiguities: { code: string; message: string; options: (string | number)[] }[];
};

export type FileAsset = {
  id: string; client_account_id: string; original_filename: string; detected_format: string; size_bytes: number;
  content_hash: string; status: string; created_at: string; retention_until: string | null; deleted_at: string | null;
  duplicate_of_id: string | null; read_options: Inspection["options"] | null; structure_confirmed: boolean;
  inspection?: Inspection | null;
};

export type Suggestion = {
  source_column: string; target_field: string | null; confidence: number; rationale: string; warnings: string[];
  requires_confirmation: boolean; alternatives: string[]; source: string; inferred_type: string | null;
  number_style: string | null; date_format: string | null;
};

export type Compatibility = {
  status: "identical" | "compatible" | "review_required" | "incompatible"; requires_review: boolean;
  missing_mapped_columns: string[]; added_columns: string[]; type_changes: { column: string; expected: string; found: string }[];
  messages: string[];
};

export type ProfileMatch = { profile_id: string; profile_name: string; version_id: string; version: number; compatibility: Compatibility };

export type MappingEntry = {
  source_column: string; target_field: string | null; status: "approved" | "suggested" | "ignored"; confidence?: number | null;
  rationale?: string | null; transforms: string[]; required: boolean; number_style: string; date_format?: string | null; source?: string;
};

export type CanonicalField = { key: string; label: string; data_type: string };

export type RuleType = { type: string; label: string; description: string; category: string; scope: string; params_schema: any };

export type Rule = {
  id: string; rule_key: string; version: number; name: string; description: string | null; rule_type: string; category: string;
  params: Record<string, any>; severity: string; applies_when: any; message: string | null; status: string; is_current: boolean;
  is_global: boolean; client_account_id: string | null; profile_id: string | null; created_at: string;
};

export type Profile = {
  id: string; name: string; description: string | null; client_account_id: string | null; client_name: string | null; status: string;
  created_at: string; updated_at: string; version_count: number;
  current_version: ProfileVersion | null; versions?: ProfileVersion[];
};

export type ProfileVersion = {
  id: string; version: number; source_format: string; sheet_name: string | null; header_row: number; delimiter: string | null;
  encoding: string | null; columns: { name: string; inferred_type: string }[]; approval_status: string; approved_at: string | null;
  created_at: string; change_note: string | null; source_file_id: string | null; mapping: MappingEntry[]; suggestion_source: string | null;
};

export type Job = {
  id: string; client_account_id: string; file_asset_id: string; profile_version_id: string; reprocess_of_id: string | null;
  status: string; error_kind: string | null; failure_reason: string | null; attempts: number; max_attempts: number; records_read: number;
  error_count: number; warning_count: number; info_count: number; findings_stored: number; created_at: string;
  started_at: string | null; finished_at: string | null; parameters: any; input_snapshot: any; summary: any;
};
