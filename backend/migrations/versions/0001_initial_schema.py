"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-10-23 14:34:02.335535
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('organizations',
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status in ('active','suspended')", name=op.f('ck_organizations_status')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_organizations'))
    )
    op.create_table('plans',
    sa.Column('code', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('limits', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('price_cents', sa.Integer(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('code', name=op.f('pk_plans'))
    )
    op.create_table('users',
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status in ('active','disabled')", name=op.f('ck_users_status')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('email', name=op.f('uq_users_email'))
    )
    op.create_table('audit_events',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=True),
    sa.Column('actor_user_id', sa.Uuid(), nullable=True),
    sa.Column('action', sa.String(length=60), nullable=False),
    sa.Column('entity_type', sa.String(length=40), nullable=False),
    sa.Column('entity_id', sa.String(length=64), nullable=True),
    sa.Column('details', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('request_id', sa.String(length=64), nullable=True),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], name=op.f('fk_audit_events_actor_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_audit_events_organization_id_organizations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_events'))
    )
    op.create_index('ix_audit_events_org_created', 'audit_events', ['organization_id', 'created_at'], unique=False)
    op.create_table('client_accounts',
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('external_reference', sa.String(length=100), nullable=True),
    sa.Column('tax_id', sa.String(length=20), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status in ('active','inactive')", name=op.f('ck_client_accounts_status')),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_client_accounts_organization_id_organizations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_client_accounts')),
    sa.UniqueConstraint('organization_id', 'name', name=op.f('uq_client_accounts_organization_id'))
    )
    op.create_index('ix_client_accounts_org_status', 'client_accounts', ['organization_id', 'status'], unique=False)
    op.create_table('memberships',
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("role in ('owner','admin','analyst','viewer')", name=op.f('ck_memberships_role')),
    sa.CheckConstraint("status in ('active','disabled')", name=op.f('ck_memberships_status')),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_memberships_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_memberships_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_memberships')),
    sa.UniqueConstraint('organization_id', 'user_id', name=op.f('uq_memberships_organization_id'))
    )
    op.create_index(op.f('ix_memberships_organization_id'), 'memberships', ['organization_id'], unique=False)
    op.create_index(op.f('ix_memberships_user_id'), 'memberships', ['user_id'], unique=False)
    op.create_table('subscriptions',
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('plan_code', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('overage_policy', sa.String(length=10), nullable=False),
    sa.Column('current_period_start', sa.DateTime(timezone=True), nullable=True),
    sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('external_reference', sa.String(length=100), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("overage_policy in ('block','allow')", name=op.f('ck_subscriptions_overage_policy')),
    sa.CheckConstraint("status in ('trialing','active','past_due','canceled')", name=op.f('ck_subscriptions_status')),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_subscriptions_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['plan_code'], ['plans.code'], name=op.f('fk_subscriptions_plan_code_plans')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_subscriptions')),
    sa.UniqueConstraint('organization_id', name=op.f('uq_subscriptions_organization_id'))
    )
    op.create_table('usage_records',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('metric', sa.String(length=30), nullable=False),
    sa.Column('quantity', sa.BigInteger(), nullable=False),
    sa.Column('period', sa.String(length=7), nullable=False),
    sa.Column('entity_type', sa.String(length=40), nullable=True),
    sa.Column('entity_id', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_usage_records_organization_id_organizations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_usage_records'))
    )
    op.create_index('ix_usage_records_org_metric_period', 'usage_records', ['organization_id', 'metric', 'period'], unique=False)
    op.create_table('dataset_profiles',
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('client_account_id', sa.Uuid(), nullable=True),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('current_version_id', sa.Uuid(), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status in ('active','archived')", name=op.f('ck_dataset_profiles_status')),
    sa.ForeignKeyConstraint(['client_account_id'], ['client_accounts.id'], name=op.f('fk_dataset_profiles_client_account_id_client_accounts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_dataset_profiles_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_dataset_profiles_organization_id_organizations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_dataset_profiles')),
    sa.UniqueConstraint('organization_id', 'name', name=op.f('uq_dataset_profiles_organization_id'))
    )
    op.create_index('ix_dataset_profiles_org_client', 'dataset_profiles', ['organization_id', 'client_account_id'], unique=False)
    op.create_table('file_assets',
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('client_account_id', sa.Uuid(), nullable=False),
    sa.Column('original_filename', sa.String(length=255), nullable=False),
    sa.Column('detected_format', sa.String(length=10), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('storage_key', sa.String(length=300), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('uploaded_by', sa.Uuid(), nullable=True),
    sa.Column('retention_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('duplicate_of_id', sa.Uuid(), nullable=True),
    sa.Column('read_options', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('structure_confirmed', sa.Boolean(), nullable=False),
    sa.Column('inspection', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("detected_format in ('csv','xlsx')", name=op.f('ck_file_assets_format')),
    sa.CheckConstraint("status in ('uploaded','inspected','deleted')", name=op.f('ck_file_assets_status')),
    sa.ForeignKeyConstraint(['client_account_id'], ['client_accounts.id'], name=op.f('fk_file_assets_client_account_id_client_accounts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['duplicate_of_id'], ['file_assets.id'], name=op.f('fk_file_assets_duplicate_of_id_file_assets'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_file_assets_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], name=op.f('fk_file_assets_uploaded_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_file_assets'))
    )
    op.create_index('ix_file_assets_org_client_created', 'file_assets', ['organization_id', 'client_account_id', 'created_at'], unique=False)
    op.create_index('ix_file_assets_org_hash', 'file_assets', ['organization_id', 'content_hash'], unique=False)
    op.create_table('comparison_jobs',
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('client_account_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=True),
    sa.Column('file_a_id', sa.Uuid(), nullable=False),
    sa.Column('file_b_id', sa.Uuid(), nullable=False),
    sa.Column('config', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('input_snapshot', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('summary', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('results_stored', sa.Integer(), nullable=False),
    sa.Column('results_truncated', sa.Boolean(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('error_kind', sa.String(length=30), nullable=True),
    sa.Column('failure_reason', sa.Text(), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('max_attempts', sa.Integer(), nullable=False),
    sa.Column('idempotency_key', sa.String(length=100), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('locked_by', sa.String(length=100), nullable=True),
    sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('run_after', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status in ('queued','running','succeeded','failed','cancelled')", name=op.f('ck_comparison_jobs_status')),
    sa.ForeignKeyConstraint(['client_account_id'], ['client_accounts.id'], name=op.f('fk_comparison_jobs_client_account_id_client_accounts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_comparison_jobs_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['file_a_id'], ['file_assets.id'], name=op.f('fk_comparison_jobs_file_a_id_file_assets'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['file_b_id'], ['file_assets.id'], name=op.f('fk_comparison_jobs_file_b_id_file_assets'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_comparison_jobs_organization_id_organizations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_comparison_jobs')),
    sa.UniqueConstraint('organization_id', 'idempotency_key', name=op.f('uq_comparison_jobs_organization_id'))
    )
    op.create_index('ix_comparison_jobs_org_created', 'comparison_jobs', ['organization_id', 'created_at'], unique=False)
    op.create_index('ix_comparison_jobs_status', 'comparison_jobs', ['status'], unique=False)
    op.create_table('dataset_profile_versions',
    sa.Column('profile_id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('source_format', sa.String(length=10), nullable=False),
    sa.Column('sheet_name', sa.String(length=255), nullable=True),
    sa.Column('header_row', sa.Integer(), nullable=False),
    sa.Column('delimiter', sa.String(length=4), nullable=True),
    sa.Column('encoding', sa.String(length=30), nullable=True),
    sa.Column('columns', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('structure_signature', sa.String(length=64), nullable=False),
    sa.Column('structural_rules', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('approval_status', sa.String(length=20), nullable=False),
    sa.Column('approved_by', sa.Uuid(), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('change_note', sa.Text(), nullable=True),
    sa.Column('source_file_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("approval_status in ('draft','approved','superseded')", name=op.f('ck_dataset_profile_versions_approval_status')),
    sa.ForeignKeyConstraint(['approved_by'], ['users.id'], name=op.f('fk_dataset_profile_versions_approved_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_dataset_profile_versions_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_dataset_profile_versions_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['profile_id'], ['dataset_profiles.id'], name=op.f('fk_dataset_profile_versions_profile_id_dataset_profiles'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_file_id'], ['file_assets.id'], name=op.f('fk_dataset_profile_versions_source_file_id_file_assets'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_dataset_profile_versions')),
    sa.UniqueConstraint('profile_id', 'version', name=op.f('uq_dataset_profile_versions_profile_id'))
    )
    op.create_index(op.f('ix_dataset_profile_versions_organization_id'), 'dataset_profile_versions', ['organization_id'], unique=False)
    op.create_index(op.f('ix_dataset_profile_versions_structure_signature'), 'dataset_profile_versions', ['structure_signature'], unique=False)
    # FK circular (perfil -> versão atual) criada após as duas tabelas existirem
    op.create_foreign_key(op.f('fk_dataset_profiles_current_version_id_dataset_profile_versions'), 'dataset_profiles',
                          'dataset_profile_versions', ['current_version_id'], ['id'], ondelete='SET NULL')
    op.create_table('validation_rules',
    sa.Column('organization_id', sa.Uuid(), nullable=True),
    sa.Column('client_account_id', sa.Uuid(), nullable=True),
    sa.Column('profile_id', sa.Uuid(), nullable=True),
    sa.Column('rule_key', sa.String(length=80), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('rule_type', sa.String(length=40), nullable=False),
    sa.Column('category', sa.String(length=40), nullable=False),
    sa.Column('params', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('severity', sa.String(length=10), nullable=False),
    sa.Column('applies_when', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('message', sa.String(length=300), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('is_current', sa.Boolean(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("severity in ('error','warning','info')", name=op.f('ck_validation_rules_severity')),
    sa.CheckConstraint("status in ('active','inactive')", name=op.f('ck_validation_rules_status')),
    sa.ForeignKeyConstraint(['client_account_id'], ['client_accounts.id'], name=op.f('fk_validation_rules_client_account_id_client_accounts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_validation_rules_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_validation_rules_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['profile_id'], ['dataset_profiles.id'], name=op.f('fk_validation_rules_profile_id_dataset_profiles'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_validation_rules')),
    sa.UniqueConstraint('rule_key', 'version', name=op.f('uq_validation_rules_rule_key'))
    )
    op.create_index('ix_validation_rules_org_current', 'validation_rules', ['organization_id', 'is_current'], unique=False)
    op.create_table('comparison_results',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('comparison_id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('category', sa.String(length=20), nullable=False),
    sa.Column('key_value', sa.String(length=250), nullable=True),
    sa.Column('row_a', sa.BigInteger(), nullable=True),
    sa.Column('row_b', sa.BigInteger(), nullable=True),
    sa.Column('differences', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('note', sa.String(length=300), nullable=True),
    sa.ForeignKeyConstraint(['comparison_id'], ['comparison_jobs.id'], name=op.f('fk_comparison_results_comparison_id_comparison_jobs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_comparison_results_organization_id_organizations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_comparison_results'))
    )
    op.create_index('ix_comparison_results_cmp_category', 'comparison_results', ['comparison_id', 'category'], unique=False)
    op.create_table('mapping_profiles',
    sa.Column('profile_version_id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('entries', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('suggestion_source', sa.String(length=20), nullable=False),
    sa.Column('confirmation_threshold', sa.Float(), nullable=False),
    sa.Column('approved_by', sa.Uuid(), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['approved_by'], ['users.id'], name=op.f('fk_mapping_profiles_approved_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_mapping_profiles_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['profile_version_id'], ['dataset_profile_versions.id'], name=op.f('fk_mapping_profiles_profile_version_id_dataset_profile_versions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_mapping_profiles')),
    sa.UniqueConstraint('profile_version_id', name=op.f('uq_mapping_profiles_profile_version_id'))
    )
    op.create_index(op.f('ix_mapping_profiles_organization_id'), 'mapping_profiles', ['organization_id'], unique=False)
    op.create_table('processing_jobs',
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('client_account_id', sa.Uuid(), nullable=False),
    sa.Column('file_asset_id', sa.Uuid(), nullable=False),
    sa.Column('profile_version_id', sa.Uuid(), nullable=False),
    sa.Column('reprocess_of_id', sa.Uuid(), nullable=True),
    sa.Column('parameters', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('rules_snapshot', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('input_snapshot', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('summary', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('records_read', sa.Integer(), nullable=False),
    sa.Column('error_count', sa.Integer(), nullable=False),
    sa.Column('warning_count', sa.Integer(), nullable=False),
    sa.Column('info_count', sa.Integer(), nullable=False),
    sa.Column('findings_stored', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('error_kind', sa.String(length=30), nullable=True),
    sa.Column('failure_reason', sa.Text(), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('max_attempts', sa.Integer(), nullable=False),
    sa.Column('idempotency_key', sa.String(length=100), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('locked_by', sa.String(length=100), nullable=True),
    sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('run_after', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status in ('queued','running','succeeded','failed','cancelled')", name=op.f('ck_processing_jobs_status')),
    sa.ForeignKeyConstraint(['client_account_id'], ['client_accounts.id'], name=op.f('fk_processing_jobs_client_account_id_client_accounts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_processing_jobs_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['file_asset_id'], ['file_assets.id'], name=op.f('fk_processing_jobs_file_asset_id_file_assets'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_processing_jobs_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['profile_version_id'], ['dataset_profile_versions.id'], name=op.f('fk_processing_jobs_profile_version_id_dataset_profile_versions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['reprocess_of_id'], ['processing_jobs.id'], name=op.f('fk_processing_jobs_reprocess_of_id_processing_jobs'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_processing_jobs')),
    sa.UniqueConstraint('organization_id', 'idempotency_key', name=op.f('uq_processing_jobs_organization_id'))
    )
    op.create_index('ix_processing_jobs_org_created', 'processing_jobs', ['organization_id', 'created_at'], unique=False)
    op.create_index('ix_processing_jobs_status', 'processing_jobs', ['status'], unique=False)
    op.create_table('validation_findings',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('job_id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('rule_id', sa.Uuid(), nullable=True),
    sa.Column('rule_key', sa.String(length=80), nullable=False),
    sa.Column('rule_version', sa.Integer(), nullable=False),
    sa.Column('rule_type', sa.String(length=40), nullable=False),
    sa.Column('rule_name', sa.String(length=200), nullable=True),
    sa.Column('severity', sa.String(length=10), nullable=False),
    sa.Column('row_number', sa.BigInteger(), nullable=True),
    sa.Column('record_key', sa.String(length=120), nullable=True),
    sa.Column('field', sa.String(length=64), nullable=True),
    sa.Column('observed_value', sa.String(length=130), nullable=True),
    sa.Column('message', sa.String(length=500), nullable=False),
    sa.Column('evidence', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('review_status', sa.String(length=20), nullable=False),
    sa.Column('review_note', sa.String(length=500), nullable=True),
    sa.Column('reviewed_by', sa.Uuid(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("review_status in ('open','acknowledged','resolved','false_positive')", name=op.f('ck_validation_findings_review_status')),
    sa.ForeignKeyConstraint(['job_id'], ['processing_jobs.id'], name=op.f('fk_validation_findings_job_id_processing_jobs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_validation_findings_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], name=op.f('fk_validation_findings_reviewed_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['rule_id'], ['validation_rules.id'], name=op.f('fk_validation_findings_rule_id_validation_rules'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_validation_findings'))
    )
    op.create_index('ix_validation_findings_job_field', 'validation_findings', ['job_id', 'field'], unique=False)
    op.create_index('ix_validation_findings_job_rule', 'validation_findings', ['job_id', 'rule_key'], unique=False)
    op.create_index('ix_validation_findings_job_severity', 'validation_findings', ['job_id', 'severity'], unique=False)


def downgrade() -> None:
    op.drop_constraint(op.f('fk_dataset_profiles_current_version_id_dataset_profile_versions'), 'dataset_profiles', type_='foreignkey')
    op.drop_index('ix_validation_findings_job_severity', table_name='validation_findings')
    op.drop_index('ix_validation_findings_job_rule', table_name='validation_findings')
    op.drop_index('ix_validation_findings_job_field', table_name='validation_findings')
    op.drop_table('validation_findings')
    op.drop_index('ix_processing_jobs_status', table_name='processing_jobs')
    op.drop_index('ix_processing_jobs_org_created', table_name='processing_jobs')
    op.drop_table('processing_jobs')
    op.drop_index(op.f('ix_mapping_profiles_organization_id'), table_name='mapping_profiles')
    op.drop_table('mapping_profiles')
    op.drop_index('ix_comparison_results_cmp_category', table_name='comparison_results')
    op.drop_table('comparison_results')
    op.drop_index('ix_validation_rules_org_current', table_name='validation_rules')
    op.drop_table('validation_rules')
    op.drop_index(op.f('ix_dataset_profile_versions_structure_signature'), table_name='dataset_profile_versions')
    op.drop_index(op.f('ix_dataset_profile_versions_organization_id'), table_name='dataset_profile_versions')
    op.drop_table('dataset_profile_versions')
    op.drop_index('ix_comparison_jobs_status', table_name='comparison_jobs')
    op.drop_index('ix_comparison_jobs_org_created', table_name='comparison_jobs')
    op.drop_table('comparison_jobs')
    op.drop_index('ix_file_assets_org_hash', table_name='file_assets')
    op.drop_index('ix_file_assets_org_client_created', table_name='file_assets')
    op.drop_table('file_assets')
    op.drop_index('ix_dataset_profiles_org_client', table_name='dataset_profiles')
    op.drop_table('dataset_profiles')
    op.drop_index('ix_usage_records_org_metric_period', table_name='usage_records')
    op.drop_table('usage_records')
    op.drop_table('subscriptions')
    op.drop_index(op.f('ix_memberships_user_id'), table_name='memberships')
    op.drop_index(op.f('ix_memberships_organization_id'), table_name='memberships')
    op.drop_table('memberships')
    op.drop_index('ix_client_accounts_org_status', table_name='client_accounts')
    op.drop_table('client_accounts')
    op.drop_index('ix_audit_events_org_created', table_name='audit_events')
    op.drop_table('audit_events')
    op.drop_table('users')
    op.drop_table('plans')
    op.drop_table('organizations')
