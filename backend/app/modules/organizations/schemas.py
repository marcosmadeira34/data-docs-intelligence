from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

Role = Literal["owner", "admin", "analyst", "viewer"]


def _password_rules(v: str) -> str:
    if len(v) < 10:
        raise ValueError("a senha deve ter pelo menos 10 caracteres")
    if v.isdigit() or v.isalpha():
        raise ValueError("a senha deve combinar letras e números ou símbolos")
    return v


class SignupIn(BaseModel):
    organization_name: str = Field(min_length=2, max_length=200)
    name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    password: str = Field(max_length=200)

    _pw = field_validator("password")(_password_rules)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)
    organization_id: uuid.UUID | None = None


class SwitchOrgIn(BaseModel):
    organization_id: uuid.UUID


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)

    _pw = field_validator("new_password")(_password_rules)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    email: str


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    status: str
    created_at: datetime


class MembershipSummary(BaseModel):
    organization_id: uuid.UUID
    organization_name: str
    role: Role


class SessionOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    csrf_token: str
    user: UserOut
    organization: OrganizationOut
    role: Role
    memberships: list[MembershipSummary]


class MeOut(BaseModel):
    user: UserOut
    organization: OrganizationOut
    role: Role
    memberships: list[MembershipSummary]


class OrgUpdateIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)


class MemberOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    email: str
    role: Role
    status: str
    created_at: datetime
    last_login_at: datetime | None


class MemberCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    role: Role


class MemberCreatedOut(BaseModel):
    member: MemberOut
    temporary_password: str | None = Field(
        None, description="Exibida apenas uma vez quando um novo usuário é criado.")


class MemberUpdateIn(BaseModel):
    role: Role | None = None
    status: Literal["active", "disabled"] | None = None


class TemporaryPasswordOut(BaseModel):
    temporary_password: str


class UsageOut(BaseModel):
    plan_code: str
    plan_name: str
    subscription_status: str
    overage_policy: str
    period: str
    usage: dict[str, int]
    limits: dict[str, int | None]
