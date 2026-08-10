"""Pydantic response contracts for the read-only P1 API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from a_share_platform.domain.run_context import DataMode, DeploymentStage


class ResponseContext(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    as_of: datetime
    system_as_of: datetime
    data_mode: DataMode
    deployment_stage: DeploymentStage
    trust_state: str | None = None
    dataset_version_ids: list[str] = Field(default_factory=list)
    model_version_ids: list[str] = Field(default_factory=list)
    run_id: str | None = None
    coverage: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class Envelope(BaseModel):
    data: Any
    context: ResponseContext


class ProblemDetails(BaseModel):
    type: str
    title: str
    status: int
    detail: str
    instance: str
