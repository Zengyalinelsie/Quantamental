"""Deny-by-default role and permission policy for application use cases."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Role(str, Enum):
    VIEWER = "viewer"
    RESEARCHER = "researcher"
    DATA_OPERATOR = "data_operator"
    REVIEWER = "reviewer"
    PORTFOLIO_MANAGER = "portfolio_manager"
    TRADER = "trader"
    ADMINISTRATOR = "administrator"
    AGENT = "agent"


class Permission(str, Enum):
    READ_PUBLIC = "read_public"
    READ_ARTIFACT = "read_artifact"
    CREATE_EXPERIMENT = "create_experiment"
    MANAGE_DATA = "manage_data"
    APPROVE_RESEARCH = "approve_research"
    APPROVE_PORTFOLIO = "approve_portfolio"
    SEND_ORDER = "send_order"
    ADMINISTER = "administer"


@dataclass(frozen=True)
class Principal:
    subject_id: str
    roles: frozenset[Role]

    def __post_init__(self) -> None:
        if not isinstance(self.subject_id, str) or not self.subject_id.strip():
            raise ValueError("subject_id must not be empty")
        object.__setattr__(self, "roles", frozenset(Role(role) for role in self.roles))

    @classmethod
    def anonymous(cls) -> Principal:
        return cls("anonymous", frozenset())


@dataclass(frozen=True)
class PermissionPolicy:
    grants: dict[Role, frozenset[Permission]]

    @classmethod
    def default(cls) -> PermissionPolicy:
        read = frozenset({Permission.READ_PUBLIC})
        artifact_read = frozenset({Permission.READ_ARTIFACT})
        return cls(
            {
                Role.VIEWER: read,
                Role.RESEARCHER: read | artifact_read | {Permission.CREATE_EXPERIMENT},
                Role.DATA_OPERATOR: read | artifact_read | {Permission.MANAGE_DATA},
                Role.REVIEWER: read | artifact_read | {Permission.APPROVE_RESEARCH},
                Role.PORTFOLIO_MANAGER: read
                | artifact_read
                | {Permission.APPROVE_PORTFOLIO},
                Role.TRADER: read | {Permission.SEND_ORDER},
                Role.ADMINISTRATOR: frozenset(Permission),
                Role.AGENT: read,
            }
        )

    def allows(self, principal: Principal, permission: Permission | str) -> bool:
        try:
            requested = Permission(permission)
        except ValueError:
            return False
        if principal.subject_id == "anonymous":
            return requested is Permission.READ_PUBLIC
        return any(requested in self.grants.get(role, ()) for role in principal.roles)
