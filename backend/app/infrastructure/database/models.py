"""Importa todos os modelos para registrar o metadata (Alembic e testes)."""

from app.infrastructure.database.base import Base
from app.modules.audit.models import AuditEvent
from app.modules.billing.models import Plan, Subscription, UsageRecord
from app.modules.clients.models import ClientAccount
from app.modules.comparison.models import ComparisonJob, ComparisonResult
from app.modules.files.models import FileAsset
from app.modules.organizations.models import Membership, Organization, User
from app.modules.processing.models import ProcessingJob, ValidationFinding
from app.modules.profiles.models import DatasetProfile, DatasetProfileVersion, MappingProfile
from app.modules.validation.models import ValidationRule

__all__ = [
    "AuditEvent", "Base", "ClientAccount", "ComparisonJob", "ComparisonResult", "DatasetProfile", "DatasetProfileVersion",
    "FileAsset", "MappingProfile", "Membership", "Organization", "Plan", "ProcessingJob", "Subscription", "UsageRecord",
    "User", "ValidationFinding", "ValidationRule",
]
