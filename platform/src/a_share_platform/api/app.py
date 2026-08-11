"""FastAPI API for governed research data and append-only review decisions."""

from __future__ import annotations

import os
from dataclasses import asdict
from datetime import UTC, date, datetime, time
from importlib.metadata import version
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from a_share_platform.adapters.memory.experiments import (
    UnavailableExperimentRunRepository,
)
from a_share_platform.adapters.memory.factor_reviews import (
    UnavailableFactorReviewRepository,
)
from a_share_platform.adapters.memory.financial_evidence import StaticFinancialEvidenceReader
from a_share_platform.adapters.memory.governance import InMemoryGovernanceRepository
from a_share_platform.adapters.memory.system_catalog import StaticSystemCatalogReader
from a_share_platform.adapters.postgres.experiments import (
    PostgresExperimentRunRepository,
)
from a_share_platform.adapters.postgres.factor_reviews import (
    PostgresFactorReviewRepository,
)
from a_share_platform.adapters.postgres.financial_evidence import PostgresFinancialEvidenceReader
from a_share_platform.adapters.postgres.system_catalog import PostgresSystemCatalogReader
from a_share_platform.application.experiments import ExperimentRunService
from a_share_platform.application.factor_reviews import (
    FactorReviewDenied,
    FactorReviewService,
    InvalidFactorReview,
)
from a_share_platform.application.financial_evidence import (
    FactComparisonQuery,
    FactIdentityQuery,
)
from a_share_platform.application.permissions import (
    Permission,
    PermissionPolicy,
    Principal,
)
from a_share_platform.domain.experiments import ExperimentRunConflict
from a_share_platform.domain.factor_reviews import FactorReviewConflict
from a_share_platform.domain.market_data import (
    MarketDataCatalog,
    MarketDataConflict,
    MarketDataUnavailable,
)
from a_share_platform.domain.metrics import StatementType
from a_share_platform.domain.pit import FinancialPeriodType
from a_share_platform.domain.run_context import DataMode, DeploymentStage, RunContext
from a_share_platform.domain.security_master import Exchange, SecurityMaster
from a_share_platform.domain.universe import UniverseCatalog
from a_share_platform.ports.experiments import (
    ExperimentRunRepository,
    ExperimentStoreUnavailable,
)
from a_share_platform.ports.factor_reviews import (
    FactorReviewRepository,
    FactorReviewStoreUnavailable,
)
from a_share_platform.ports.financial_evidence import FinancialEvidenceReader
from a_share_platform.ports.system_catalog import SystemCatalogReader

from .schemas import (
    Envelope,
    ExperimentRunInput,
    FactorReviewInput,
    ProblemDetails,
    ResponseContext,
)


class RunContextOverrideDenied(ValueError):
    pass


class ResourceNotFound(LookupError):
    pass


class PermissionDenied(PermissionError):
    pass


class InvalidExperimentRequest(ValueError):
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


def response_context(
    context: RunContext,
    *,
    as_of: datetime | None = None,
    trust_state: str | None = None,
    dataset_version_ids: tuple[str, ...] = (),
    run_id: str | None = None,
    warnings: tuple[str, ...] = (),
) -> ResponseContext:
    now = datetime.now(UTC)
    return ResponseContext(
        as_of=as_of or now,
        system_as_of=now,
        data_mode=context.data_mode,
        deployment_stage=context.deployment_stage,
        trust_state=trust_state,
        dataset_version_ids=list(dataset_version_ids),
        run_id=run_id,
        warnings=list(warnings),
    )


def envelope(
    data: Any,
    context: RunContext,
    *,
    as_of: datetime | None = None,
    trust_state: str | None = None,
    dataset_version_ids: tuple[str, ...] = (),
    run_id: str | None = None,
    warnings: tuple[str, ...] = (),
) -> Envelope:
    return Envelope(
        data=jsonable_encoder(data),
        context=response_context(
            context,
            as_of=as_of,
            trust_state=trust_state,
            dataset_version_ids=dataset_version_ids,
            run_id=run_id,
            warnings=warnings,
        ),
    )


def create_app(
    repository: InMemoryGovernanceRepository | None = None,
    security_master: SecurityMaster | None = None,
    universe_catalog: UniverseCatalog | None = None,
    market_data_catalog: MarketDataCatalog | None = None,
    system_catalog: SystemCatalogReader | None = None,
    financial_evidence: FinancialEvidenceReader | None = None,
    experiment_repository: ExperimentRunRepository | None = None,
    factor_review_repository: FactorReviewRepository | None = None,
) -> FastAPI:
    app = FastAPI(
        title="A-Share Platform Next",
        summary="Governed research data, experiments, and review API",
        version=version("a-share-platform"),
    )
    governance = repository or InMemoryGovernanceRepository()
    master = security_master or SecurityMaster.empty()
    universes = universe_catalog or UniverseCatalog.empty()
    market_data = market_data_catalog or MarketDataCatalog.empty()
    database_url = os.environ.get("ASP_DATABASE_URL", "").strip()
    system = system_catalog or (
        PostgresSystemCatalogReader.from_dsn(database_url)
        if database_url
        else StaticSystemCatalogReader()
    )
    financial = financial_evidence or (
        PostgresFinancialEvidenceReader.from_dsn(database_url)
        if database_url
        else StaticFinancialEvidenceReader()
    )
    experiments = experiment_repository or (
        PostgresExperimentRunRepository.from_dsn(database_url)
        if database_url
        else UnavailableExperimentRunRepository(
            "ASP_DATABASE_URL is not configured for experiment persistence"
        )
    )
    experiment_service = ExperimentRunService(experiments)
    factor_reviews = factor_review_repository or (
        PostgresFactorReviewRepository.from_dsn(database_url)
        if database_url
        else UnavailableFactorReviewRepository(
            "ASP_DATABASE_URL is not configured for factor review persistence"
        )
    )
    permission_policy = PermissionPolicy.default()
    factor_review_service = FactorReviewService(factor_reviews, permission_policy)
    app.state.governance_repository = governance
    app.state.security_master = master
    app.state.universe_catalog = universes
    app.state.market_data_catalog = market_data
    app.state.system_catalog = system
    app.state.financial_evidence = financial
    app.state.experiment_repository = experiments
    app.state.experiment_service = experiment_service
    app.state.factor_review_repository = factor_reviews
    app.state.factor_review_service = factor_review_service
    app.state.permission_policy = permission_policy

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

    @app.exception_handler(ResourceNotFound)
    async def resource_not_found_handler(
        request: Request,
        error: ResourceNotFound,
    ) -> JSONResponse:
        problem = ProblemDetails(
            type="resource_not_found",
            title="Resource not found",
            status=404,
            detail=str(error),
            instance=request.url.path,
        )
        return JSONResponse(problem.model_dump(), status_code=404)

    @app.exception_handler(PermissionDenied)
    async def permission_denied_handler(
        request: Request,
        error: PermissionDenied,
    ) -> JSONResponse:
        problem = ProblemDetails(
            type="permission_denied",
            title="Permission denied",
            status=403,
            detail=str(error),
            instance=request.url.path,
        )
        return JSONResponse(problem.model_dump(), status_code=403)

    @app.exception_handler(InvalidExperimentRequest)
    async def invalid_experiment_request_handler(
        request: Request,
        error: InvalidExperimentRequest,
    ) -> JSONResponse:
        problem = ProblemDetails(
            type="invalid_experiment_request",
            title="Invalid experiment request",
            status=422,
            detail=str(error),
            instance=request.url.path,
        )
        return JSONResponse(problem.model_dump(), status_code=422)

    @app.exception_handler(ExperimentRunConflict)
    async def experiment_run_conflict_handler(
        request: Request,
        error: ExperimentRunConflict,
    ) -> JSONResponse:
        problem = ProblemDetails(
            type="experiment_run_conflict",
            title="Experiment run conflict",
            status=409,
            detail=str(error),
            instance=request.url.path,
        )
        return JSONResponse(problem.model_dump(), status_code=409)

    @app.exception_handler(ExperimentStoreUnavailable)
    async def experiment_store_unavailable_handler(
        request: Request,
        error: ExperimentStoreUnavailable,
    ) -> JSONResponse:
        problem = ProblemDetails(
            type="experiment_store_unavailable",
            title="Experiment store unavailable",
            status=503,
            detail=str(error),
            instance=request.url.path,
        )
        return JSONResponse(problem.model_dump(), status_code=503)

    @app.exception_handler(InvalidFactorReview)
    async def invalid_factor_review_handler(
        request: Request,
        error: InvalidFactorReview,
    ) -> JSONResponse:
        problem = ProblemDetails(
            type="invalid_factor_review",
            title="Invalid factor review",
            status=422,
            detail=str(error),
            instance=request.url.path,
        )
        return JSONResponse(problem.model_dump(), status_code=422)

    @app.exception_handler(FactorReviewConflict)
    async def factor_review_conflict_handler(
        request: Request,
        error: FactorReviewConflict,
    ) -> JSONResponse:
        problem = ProblemDetails(
            type="factor_review_conflict",
            title="Factor review conflict",
            status=409,
            detail=str(error),
            instance=request.url.path,
        )
        return JSONResponse(problem.model_dump(), status_code=409)

    @app.exception_handler(FactorReviewStoreUnavailable)
    async def factor_review_store_unavailable_handler(
        request: Request,
        error: FactorReviewStoreUnavailable,
    ) -> JSONResponse:
        problem = ProblemDetails(
            type="factor_review_store_unavailable",
            title="Factor review store unavailable",
            status=503,
            detail=str(error),
            instance=request.url.path,
        )
        return JSONResponse(problem.model_dump(), status_code=503)

    @app.exception_handler(MarketDataUnavailable)
    async def market_data_unavailable_handler(
        request: Request,
        error: MarketDataUnavailable,
    ) -> JSONResponse:
        problem = ProblemDetails(
            type="market_data_unavailable",
            title="Market data unavailable",
            status=404,
            detail=str(error),
            instance=request.url.path,
        )
        return JSONResponse(problem.model_dump(), status_code=404)

    @app.exception_handler(MarketDataConflict)
    async def market_data_conflict_handler(
        request: Request,
        error: MarketDataConflict,
    ) -> JSONResponse:
        problem = ProblemDetails(
            type="market_data_conflict",
            title="Market data conflict",
            status=409,
            detail=str(error),
            instance=request.url.path,
        )
        return JSONResponse(problem.model_dump(), status_code=409)

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
                {"key": "security_master", "status": "ready"},
                {"key": "historical_universe", "status": "ready"},
                {"key": "market_data_contract", "status": "ready"},
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

    @app.get("/api/experiments/runs", response_model=Envelope)
    def experiment_runs(
        context: Annotated[RunContext, Depends(fixed_read_context)],
    ) -> Envelope:
        return envelope(
            [asdict(item) for item in experiment_service.list_runs()],
            context,
        )

    @app.get("/api/experiments/runs/{run_id}", response_model=Envelope)
    def experiment_run(
        run_id: str,
        _context: Annotated[RunContext, Depends(fixed_read_context)],
    ) -> Envelope:
        value = experiment_service.get_run(run_id)
        if value is None:
            raise ResourceNotFound(f"experiment run not found: {run_id}")
        return envelope(
            asdict(value),
            value.spec.run_context,
            dataset_version_ids=value.spec.dataset_version_ids,
            run_id=value.run_id,
        )

    @app.post("/api/experiments/runs", response_model=Envelope, status_code=201)
    def create_experiment_run(
        request: ExperimentRunInput,
        principal: Annotated[Principal, Depends(anonymous_principal)],
        _context: Annotated[RunContext, Depends(fixed_read_context)],
    ) -> Envelope:
        if not permission_policy.allows(principal, Permission.CREATE_EXPERIMENT):
            raise PermissionDenied(
                f"subject {principal.subject_id} cannot create experiment runs"
            )
        try:
            value = request.to_domain()
        except (TypeError, ValueError) as error:
            raise InvalidExperimentRequest(str(error)) from error
        stored = experiment_service.create_run(value)
        return envelope(
            asdict(stored),
            stored.spec.run_context,
            dataset_version_ids=stored.spec.dataset_version_ids,
            run_id=stored.run_id,
        )

    @app.get("/api/factors/reviews", response_model=Envelope)
    def factor_promotion_reviews(
        context: Annotated[RunContext, Depends(fixed_read_context)],
    ) -> Envelope:
        return envelope(
            [asdict(item) for item in factor_review_service.list_reviews()],
            context,
        )

    @app.get("/api/factors/reviews/{review_id}", response_model=Envelope)
    def factor_promotion_review(
        review_id: str,
        _context: Annotated[RunContext, Depends(fixed_read_context)],
    ) -> Envelope:
        value = factor_review_service.get_review(review_id)
        if value is None:
            raise ResourceNotFound(f"factor promotion review not found: {review_id}")
        return envelope(asdict(value), _context)

    @app.post("/api/factors/reviews", response_model=Envelope, status_code=201)
    def create_factor_promotion_review(
        review: FactorReviewInput,
        principal: Annotated[Principal, Depends(anonymous_principal)],
        _context: Annotated[RunContext, Depends(fixed_read_context)],
    ) -> Envelope:
        try:
            factor_version = review.factor_version.to_domain()
            validation_report = review.validation_report.to_domain()
            stored = factor_review_service.record_review(
                factor_version=factor_version,
                validation_report=validation_report,
                approval_id=review.approval_id,
                scope=review.scope,
                decision=review.decision,
                principal=principal,
                decided_at=review.decided_at,
                reason=review.reason,
                evidence_hashes=review.evidence_hashes,
            )
        except FactorReviewDenied as error:
            raise PermissionDenied(str(error)) from error
        except (TypeError, ValueError) as error:
            if isinstance(error, InvalidFactorReview):
                raise
            raise InvalidFactorReview(str(error)) from error
        return envelope(
            asdict(stored),
            validation_report.run_context,
            dataset_version_ids=validation_report.dataset_version_ids,
            run_id=validation_report.experiment_run_id,
        )

    @app.get("/api/securities", response_model=Envelope)
    def securities(
        as_of: Annotated[date, Query()],
        context: Annotated[RunContext, Depends(fixed_read_context)],
    ) -> Envelope:
        decision_time = datetime.combine(as_of, time.min, tzinfo=ZoneInfo("Asia/Shanghai"))
        return envelope(
            [asdict(item) for item in master.snapshots(as_of)],
            context,
            as_of=decision_time,
        )

    @app.get("/api/listings/resolve", response_model=Envelope)
    def resolve_listing(
        exchange: Annotated[Exchange, Query()],
        code: Annotated[str, Query(min_length=1)],
        as_of: Annotated[date, Query()],
        context: Annotated[RunContext, Depends(fixed_read_context)],
    ) -> Envelope:
        decision_time = datetime.combine(as_of, time.min, tzinfo=ZoneInfo("Asia/Shanghai"))
        snapshot = master.resolve_listing(exchange, code, as_of)
        return envelope(
            None if snapshot is None else asdict(snapshot),
            context,
            as_of=decision_time,
        )

    @app.get("/api/companies/{company_id}", response_model=Envelope)
    def company_mapping(
        company_id: str,
        context: Annotated[RunContext, Depends(fixed_read_context)],
    ) -> Envelope:
        try:
            company = master.company(company_id)
        except KeyError as error:
            raise ResourceNotFound(str(error)) from error
        securities = master.securities_for_company(company_id)
        return envelope(
            {
                "company": asdict(company),
                "securities": [
                    {
                        "security": asdict(security),
                        "listings": [
                            asdict(listing)
                            for listing in master.listings_for_security(security.security_id)
                        ],
                    }
                    for security in securities
                ],
            },
            context,
        )

    @app.get("/api/universes", response_model=Envelope)
    def universe_versions(
        context: Annotated[RunContext, Depends(fixed_read_context)],
    ) -> Envelope:
        return envelope(
            [asdict(version) for version in universes.versions],
            context,
            dataset_version_ids=tuple(
                sorted({version.dataset_version_id for version in universes.versions})
            ),
        )

    @app.get("/api/universes/{universe_version_id}/snapshot", response_model=Envelope)
    def universe_snapshot(
        universe_version_id: str,
        as_of: Annotated[date, Query()],
        context: Annotated[RunContext, Depends(fixed_read_context)],
    ) -> Envelope:
        try:
            snapshot = universes.snapshot(universe_version_id, as_of, master)
        except KeyError as error:
            raise ResourceNotFound(str(error)) from error
        decision_time = datetime.combine(as_of, time.min, tzinfo=ZoneInfo("Asia/Shanghai"))
        return envelope(
            asdict(snapshot),
            context,
            as_of=decision_time,
            dataset_version_ids=(snapshot.dataset_version_id,),
        )

    @app.get("/api/universes/{universe_version_id}/diff", response_model=Envelope)
    def universe_diff(
        universe_version_id: str,
        from_date: Annotated[date, Query()],
        to_date: Annotated[date, Query()],
        context: Annotated[RunContext, Depends(fixed_read_context)],
    ) -> Envelope:
        try:
            result = universes.diff(universe_version_id, from_date, to_date, master)
        except KeyError as error:
            raise ResourceNotFound(str(error)) from error
        decision_time = datetime.combine(to_date, time.min, tzinfo=ZoneInfo("Asia/Shanghai"))
        return envelope(
            asdict(result),
            context,
            as_of=decision_time,
            dataset_version_ids=(universes.version(universe_version_id).dataset_version_id,),
        )

    @app.get("/api/universes/{universe_version_id}/coverage", response_model=Envelope)
    def universe_coverage(
        universe_version_id: str,
        as_of: Annotated[date, Query()],
        context: Annotated[RunContext, Depends(fixed_read_context)],
    ) -> Envelope:
        try:
            result = universes.coverage(universe_version_id, as_of, master)
        except KeyError as error:
            raise ResourceNotFound(str(error)) from error
        decision_time = datetime.combine(as_of, time.min, tzinfo=ZoneInfo("Asia/Shanghai"))
        return envelope(
            asdict(result),
            context,
            as_of=decision_time,
            dataset_version_ids=(universes.version(universe_version_id).dataset_version_id,),
        )

    @app.get("/api/market-data/bars", response_model=Envelope)
    def daily_bars(
        listing_id: Annotated[str, Query(min_length=1)],
        session_date: Annotated[date, Query()],
        context: Annotated[RunContext, Depends(fixed_read_context)],
    ) -> Envelope:
        rows = market_data.bars_for(listing_id, session_date)
        decision_time = datetime.combine(
            session_date,
            time.min,
            tzinfo=ZoneInfo("Asia/Shanghai"),
        )
        dataset_ids = tuple(sorted({row.dataset_version_id for row in rows}))
        trust_states = {row.trust_state.value for row in rows}
        trust_state = next(iter(trust_states)) if len(trust_states) == 1 else None
        warnings = (
            ("multiple trust states are present",)
            if len(trust_states) > 1
            else ()
        )
        return envelope(
            [asdict(item) for item in rows],
            context,
            as_of=decision_time,
            trust_state=trust_state,
            dataset_version_ids=dataset_ids,
            warnings=warnings,
        )

    @app.get("/api/market-data/summary", response_model=Envelope)
    def market_summary(
        listing_id: Annotated[str, Query(min_length=1)],
        session_date: Annotated[date, Query()],
        context: Annotated[RunContext, Depends(fixed_read_context)],
    ) -> Envelope:
        bar = market_data.select_bar(listing_id, session_date)
        state = next(
            (
                item
                for item in market_data.states
                if item.listing_id == listing_id and item.session_date == session_date
            ),
            None,
        )
        warnings: list[str] = []

        def optional_decimal(name: str, operation: Any) -> str | None:
            try:
                return str(operation())
            except MarketDataUnavailable:
                warnings.append(f"{name} unavailable")
                return None

        try:
            price_limit_status = market_data.price_limit_status(
                listing_id,
                session_date,
            ).value
        except MarketDataUnavailable:
            price_limit_status = None
            warnings.append("price_limit_status unavailable")
        decision_time = datetime.combine(
            session_date,
            time.min,
            tzinfo=ZoneInfo("Asia/Shanghai"),
        )
        return envelope(
            {
                "bar": asdict(bar),
                "state": None if state is None else asdict(state),
                "adjusted_close": optional_decimal(
                    "adjusted_close",
                    lambda: market_data.adjusted_close(listing_id, session_date),
                ),
                "market_cap": optional_decimal(
                    "market_cap",
                    lambda: market_data.market_cap(listing_id, session_date),
                ),
                "price_limit_status": price_limit_status,
            },
            context,
            as_of=decision_time,
            trust_state=bar.trust_state.value,
            dataset_version_ids=(bar.dataset_version_id,),
            warnings=tuple(warnings),
        )

    @app.get("/api/market-data/corporate-actions", response_model=Envelope)
    def corporate_actions(
        listing_id: Annotated[str, Query(min_length=1)],
        context: Annotated[RunContext, Depends(fixed_read_context)],
    ) -> Envelope:
        rows = tuple(
            item for item in market_data.corporate_actions if item.listing_id == listing_id
        )
        return envelope([asdict(item) for item in rows], context)

    @app.get("/api/market-data/quality", response_model=Envelope)
    def market_data_quality(
        context: Annotated[RunContext, Depends(fixed_read_context)],
    ) -> Envelope:
        return envelope(asdict(market_data.quality_report()), context)

    @app.get("/api/system/catalog", response_model=Envelope)
    def system_datasets(
        context: Annotated[RunContext, Depends(fixed_read_context)],
    ) -> Envelope:
        return envelope([asdict(item) for item in system.list_datasets()], context)

    @app.get("/api/system/quality", response_model=Envelope)
    def system_quality(
        context: Annotated[RunContext, Depends(fixed_read_context)],
    ) -> Envelope:
        return envelope([asdict(item) for item in system.list_quality_reports()], context)

    @app.get("/api/system/lineage", response_model=Envelope)
    def system_lineage(
        context: Annotated[RunContext, Depends(fixed_read_context)],
    ) -> Envelope:
        return envelope([asdict(item) for item in system.list_lineage()], context)

    @app.get("/api/system/jobs", response_model=Envelope)
    def system_jobs(
        context: Annotated[RunContext, Depends(fixed_read_context)],
    ) -> Envelope:
        return envelope([asdict(item) for item in system.list_jobs()], context)

    @app.get("/api/system/disclosures", response_model=Envelope)
    def system_disclosures(
        context: Annotated[RunContext, Depends(fixed_read_context)],
        company_id: Annotated[str | None, Query()] = None,
    ) -> Envelope:
        return envelope(
            [asdict(item) for item in financial.list_disclosures(company_id)],
            context,
        )

    @app.get("/api/system/facts/revisions", response_model=Envelope)
    def system_fact_revisions(
        context: Annotated[RunContext, Depends(fixed_read_context)],
        company_id: Annotated[str | None, Query()] = None,
        security_id: Annotated[str | None, Query()] = None,
        metric_code: Annotated[str | None, Query()] = None,
        report_period_end: Annotated[date | None, Query()] = None,
        period_type: Annotated[FinancialPeriodType | None, Query()] = None,
        statement_type: Annotated[StatementType | None, Query()] = None,
    ) -> Envelope:
        query = FactIdentityQuery(
            company_id=company_id,
            security_id=security_id,
            metric_code=metric_code,
            report_period_end=report_period_end,
            period_type=None if period_type is None else period_type.value,
            statement_type=None if statement_type is None else statement_type.value,
        )
        return envelope(
            [asdict(item) for item in financial.list_fact_revisions(query)],
            context,
        )

    @app.get("/api/system/facts/compare", response_model=Envelope)
    def system_fact_comparison(
        company_id: Annotated[str, Query(min_length=1)],
        security_id: Annotated[str, Query(min_length=1)],
        metric_code: Annotated[str, Query(min_length=1)],
        report_period_end: Annotated[date, Query()],
        period_type: Annotated[FinancialPeriodType, Query()],
        statement_type: Annotated[StatementType, Query()],
        decision_time: Annotated[datetime, Query()],
        system_time: Annotated[datetime, Query()],
        authority_rule_version: Annotated[str, Query(min_length=1)],
        context: Annotated[RunContext, Depends(fixed_read_context)],
    ) -> Envelope:
        result = financial.compare_fact(
            FactComparisonQuery(
                company_id=company_id,
                security_id=security_id,
                metric_code=metric_code,
                report_period_end=report_period_end,
                period_type=period_type.value,
                statement_type=statement_type.value,
                decision_time=decision_time,
                system_time=system_time,
                authority_rule_version=authority_rule_version,
            )
        )
        if result is None:
            raise ResourceNotFound("financial fact comparison inputs are unavailable")
        return envelope(asdict(result), context, as_of=decision_time)

    @app.get("/api/system/mismatches", response_model=Envelope)
    def system_financial_mismatches(
        context: Annotated[RunContext, Depends(fixed_read_context)],
    ) -> Envelope:
        return envelope(
            [asdict(item) for item in financial.list_mismatches()],
            context,
        )

    @app.get("/api/system/evidence/{raw_object_id}", response_model=Envelope)
    def system_raw_evidence(
        raw_object_id: str,
        context: Annotated[RunContext, Depends(fixed_read_context)],
    ) -> Envelope:
        result = financial.get_evidence(raw_object_id)
        if result is None:
            raise ResourceNotFound(f"raw evidence not found: {raw_object_id}")
        return envelope(asdict(result), context, as_of=result.retrieved_at)

    @app.get("/api/calendars/{exchange}/next-session", response_model=Envelope)
    def next_session(
        exchange: Exchange,
        after: Annotated[date, Query()],
        context: Annotated[RunContext, Depends(fixed_read_context)],
    ) -> Envelope:
        selected = market_data.calendar(exchange).next_session(after)
        decision_time = datetime.combine(
            after,
            time.min,
            tzinfo=ZoneInfo("Asia/Shanghai"),
        )
        return envelope(
            {"exchange": exchange, "after": after, "next_session": selected},
            context,
            as_of=decision_time,
        )

    return app


app = create_app()
