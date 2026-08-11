"""Explicit domain routing for backfill sinks with disjoint persistence contracts."""

from __future__ import annotations

from collections.abc import Mapping

from a_share_platform.domain.backfill import BackfillBatch, BackfillDataDomain
from a_share_platform.ports.backfill import BackfillSink


class DomainRoutingBackfillSink:
    def __init__(
        self,
        *,
        default_sink: BackfillSink,
        routes: Mapping[BackfillDataDomain, BackfillSink],
    ) -> None:
        self._default = default_sink
        self._routes = {
            BackfillDataDomain(domain): sink for domain, sink in routes.items()
        }

    def persist(
        self,
        batch: BackfillBatch,
        *,
        dataset_version_id: str,
    ) -> tuple[str, ...]:
        sink = self._routes.get(batch.work_unit.domain, self._default)
        return sink.persist(batch, dataset_version_id=dataset_version_id)
