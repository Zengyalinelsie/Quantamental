"""FastAPI read-only skeleton for P1 capability and governance resources."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from importlib.metadata import version
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from a_share_platform.adapters.memory.governance import InMemoryGovernanceRepository
from a_share_platform.application.permissions import Principal
from a_share_platform.domain.run_context import DataMode, DeploymentStage, RunContext

from .schemas import Envelope, ProblemDetails, ResponseContext


class RunContextOverrideDenied(ValueError):
    pass


def anonymous_principal() -> Principal:
    """P1 has no trusted identity provider; headers never create a principal."""

    return Principal.anonymous()


def fixed_read_context(
    data_mode: Annotated[str | None, Query()] = None,
    deployment_stage: Annotated[str | None, Query()] = None,
) -> RunContext:
    if data_mode is not None or deployment_stage is not None:
        raise RunContextOverrideDenied(
            "run context is fixed by the server use case and cannot be promoted by query parameters"
        )
    return RunContext(DataMode.CURRENT_RESEARCH, DeploymentStage.RESEARCH)


def response_context(context: RunContext) -> ResponseContext:
    now = datetime.now(UTC)
    return ResponseContext(
        as_of=now,
        system_as_of=now,
        data_mode=context.data_mode,
        deployment_stage=context.deployment_stage,
    )


def envelope(data: Any, context: RunContext) -> Envelope:
    return Envelope(data=jsonable_encoder(data), context=response_context(context))


def create_app(
    repository: InMemoryGovernanceRepository | None = None,
) -> FastAPI:
    app = FastAPI(
        title="A-Share Platform Next",
        summary="Read-only P1 capability and governance API",
        version=version("a-share-platform"),
    )
    governance = repository or InMemoryGovernanceRepository()
    app.state.governance_repository = governance

    @app.exception_handler(RunContextOverrideDenied)
    async def run_context_override_handler(
        request: Request,
        error: RunContextOverrideDenied,
    ) -> JSONResponse:
        problem = ProblemDetails(
            type="run_context_override_denied",
            title="Run context override denied",
            status=400,
            detail=str(error),
            instance=request.url.path,
        )
        return JSONResponse(problem.model_dump(), status_code=400)

    @app.get("/api/health", response_model=Envelope)
    def health() -> Envelope:
        context = RunContext(DataMode.CURRENT_RESEARCH, DeploymentStage.RESEARCH)
        return envelope({"status": "ok"}, context)

    @app.get("/api/version", response_model=Envelope)
    def application_version(
        context: Annotated[RunContext, Depends(fixed_read_context)],
    ) -> Envelope:
        return envelope({"version": version("a-share-platform")}, context)

    @app.get("/api/capabilities", response_model=Envelope)
    def capabilities(
        context: Annotated[RunContext, Depends(fixed_read_context)],
    ) -> Envelope:
        return envelope(
            [
                {"key": "run_context", "status": "ready"},
                {"key": "governance_ledger", "status": "ready"},
                {
                    "key": "identity_provider",
                    "status": "unavailable",
                    "reason": "no trusted identity provider is configured",
                },
                {
                    "key": "execution",
                    "status": "unavailable",
                    "reason": "P1 exposes no order endpoint or account connection",
                },
            ],
            context,
        )

    @app.get("/api/identity", response_model=Envelope)
    def identity(
        principal: Annotated[Principal, Depends(anonymous_principal)],
        context: Annotated[RunContext, Depends(fixed_read_context)],
    ) -> Envelope:
        return envelope(
            {
                "subject_id": principal.subject_id,
                "roles": sorted(role.value for role in principal.roles),
            },
            context,
        )

    @app.get("/api/datasets", response_model=Envelope)
    def datasets(
        context: Annotated[RunContext, Depends(fixed_read_context)],
    ) -> Envelope:
        return envelope([asdict(item) for item in governance.list_datasets()], context)

    @app.get("/api/runs", response_model=Envelope)
    def runs(
        context: Annotated[RunContext, Depends(fixed_read_context)],
    ) -> Envelope:
        return envelope([asdict(item) for item in governance.list_runs()], context)

    @app.get("/api/artifacts", response_model=Envelope)
    def artifacts(
        context: Annotated[RunContext, Depends(fixed_read_context)],
    ) -> Envelope:
        return envelope([asdict(item) for item in governance.list_artifacts()], context)

    return app


app = create_app()
