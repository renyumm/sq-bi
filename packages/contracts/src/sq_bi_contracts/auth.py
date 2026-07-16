from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .common import ContractModel
from .enums import AuthBackendType


class TokenClaims(ContractModel):
    """JWT / session token payload extracted at auth boundaries."""

    sub: str  # user_id
    org_id: str
    role_ids: list[str] = Field(default_factory=list)
    iat: datetime | None = None
    exp: datetime | None = None
    iss: str = "sq-bi"
    session_id: str | None = None


class SessionInfo(ContractModel):
    """Server-side session state (local auth backend)."""

    session_id: str
    user_id: str
    org_id: str
    display_name: str
    role_ids: list[str] = Field(default_factory=list)
    locale: str = "zh-CN"
    timezone: str = "Asia/Shanghai"
    expires_at: datetime
    created_at: datetime


class LoginRequest(ContractModel):
    username: str
    password: str
    backend: AuthBackendType = AuthBackendType.LOCAL


class LoginResponse(ContractModel):
    session_id: str
    token: str
    user_id: str
    display_name: str
    org_id: str
    role_ids: list[str] = Field(default_factory=list)
    expires_at: datetime


class AuthBackendConfig(ContractModel):
    """Pluggable backend descriptor — subclasses implement the actual protocol."""

    backend_type: AuthBackendType
    enabled: bool = True
    config: dict[str, str] = Field(default_factory=dict)
