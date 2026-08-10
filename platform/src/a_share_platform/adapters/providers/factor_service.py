"""Typed, provider-edge client for the internal Factor Service HTTP contracts.

The adapter supports both documented v1 and v2 APIs without importing them
into the domain core.  Query methods are fail-closed because Factor Service can
call an upstream THS/iFinD API and populate its read-through cache.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


class FactorServiceError(RuntimeError):
    """Base error for Factor Service access."""


class FactorServicePermissionError(FactorServiceError, PermissionError):
    """The caller did not acknowledge a provider-side effect."""


class FactorServiceTransportError(FactorServiceError):
    """The HTTP exchange did not produce a usable response."""


class FactorServicePayloadError(FactorServiceError, ValueError):
    """The HTTP or business payload violates the documented contract."""


@dataclass(frozen=True)
class FactorServiceHttpRequest:
    method: str
    url: str
    headers: tuple[tuple[str, str], ...]
    json_body: Mapping[str, object] | None
    timeout_seconds: float
    bearer_token: str | None = field(repr=False)

    def __post_init__(self) -> None:
        method = self.method.upper()
        if method not in {"GET", "POST"}:
            raise ValueError("Factor Service method must be GET or POST")
        object.__setattr__(self, "method", method)
        parsed = urlparse(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Factor Service request URL must be http(s)")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    @property
    def path(self) -> str:
        return urlparse(self.url).path


@dataclass(frozen=True)
class FactorServiceHttpResponse:
    status_code: int
    body: bytes

    def __post_init__(self) -> None:
        if type(self.status_code) is not int or not 100 <= self.status_code <= 599:
            raise ValueError("status_code must be a valid HTTP status")
        if not isinstance(self.body, bytes):
            raise TypeError("response body must be bytes")


class FactorServiceTransport(Protocol):
    def send(self, request: FactorServiceHttpRequest) -> FactorServiceHttpResponse: ...


class UrllibFactorServiceTransport:
    """Small stdlib transport; secrets remain outside request repr/log fields."""

    def send(self, request: FactorServiceHttpRequest) -> FactorServiceHttpResponse:
        body = None
        if request.json_body is not None:
            body = json.dumps(
                request.json_body,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        headers = dict(request.headers)
        if request.bearer_token is not None:
            headers["Authorization"] = f"Bearer {request.bearer_token}"
        outbound = Request(
            request.url,
            data=body,
            headers=headers,
            method=request.method,
        )
        try:
            with urlopen(outbound, timeout=request.timeout_seconds) as response:
                return FactorServiceHttpResponse(
                    status_code=response.status,
                    body=response.read(),
                )
        except HTTPError as error:
            return FactorServiceHttpResponse(
                status_code=error.code,
                body=error.read(),
            )
        except (URLError, TimeoutError, OSError) as error:
            raise FactorServiceTransportError("Factor Service transport failed") from error


_SUCCESS_CODES = frozenset({0, 20000})
_BEARER = re.compile(r"(?i)authorization\s*:\s*bearer\s+\S+|bearer\s+\S+")


def _reject_non_finite_json_number(value: str) -> object:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


class FactorServiceClient:
    """v1/v2 Factor Service client with explicit query-side-effect gates."""

    def __init__(
        self,
        *,
        base_url: str,
        bearer_token: str | None,
        transport: FactorServiceTransport | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        parsed = urlparse(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("base_url must be an http(s) origin without credentials or query")
        if parsed.path not in {"", "/"}:
            raise ValueError("base_url must not include an API path")
        if bearer_token is not None and not bearer_token.strip():
            raise ValueError("bearer_token must be None or non-empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._base_url = base_url.rstrip("/")
        self._bearer_token = bearer_token
        self._transport = transport or UrllibFactorServiceTransport()
        self._timeout_seconds = timeout_seconds

    def __repr__(self) -> str:
        return (
            f"FactorServiceClient(base_url={self._base_url!r}, "
            f"bearer_token={'<configured>' if self._bearer_token else None!r})"
        )

    @classmethod
    def from_environment(
        cls,
        *,
        require_token: bool = True,
        transport: FactorServiceTransport | None = None,
    ) -> FactorServiceClient:
        base_url = os.environ.get("FACTOR_SERVICE_BASE_URL", "").strip()
        token = os.environ.get("FACTOR_SERVICE_BEARER_TOKEN")
        if not base_url:
            raise FactorServicePermissionError("FACTOR_SERVICE_BASE_URL is required")
        if require_token and (token is None or not token.strip()):
            raise FactorServicePermissionError("FACTOR_SERVICE_BEARER_TOKEN is required")
        return cls(base_url=base_url, bearer_token=token, transport=transport)

    def v1_health(self) -> Mapping[str, object]:
        return self._health("/factor/service/api/v1/health")

    def v1_factor_list(
        self,
        *,
        table_name: str | None = None,
        time_type: str | None = None,
        factor_name: str | None = None,
        factor_cn_name: str | None = None,
        keyword: str | None = None,
    ) -> tuple[Mapping[str, object], ...]:
        data = self._call(
            "GET",
            "/factor/service/api/v1/factor/list",
            query=self._optional_query(
                table_name=table_name,
                time_type=time_type,
                factor_name=factor_name,
                factor_cn_name=factor_cn_name,
                keyword=keyword,
            ),
        )
        return self._object_rows(data, "v1 factor list")

    def v1_table_list(self) -> tuple[Mapping[str, object], ...]:
        return self._object_rows(
            self._call("GET", "/factor/service/api/v1/table/list"),
            "v1 table list",
        )

    def v1_factor_query(
        self,
        *,
        scodes: Sequence[str],
        factors: Sequence[str] = (),
        tables: Sequence[str] = (),
        report_period_end: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        allow_read_through_cache: bool,
    ) -> tuple[Mapping[str, object], ...]:
        self._require_read_through_ack(allow_read_through_cache)
        symbols = self._texts(scodes, "scodes")
        factor_names = self._optional_texts(factors, "factors")
        table_names = self._optional_texts(tables, "tables")
        if not factor_names and not table_names:
            raise ValueError("v1 query requires factors or tables")
        body: dict[str, object] = {"scode": list(symbols)}
        if factor_names:
            if any("." not in value for value in factor_names):
                raise ValueError("v1 factors must use table_name.factor_name")
            body["factors"] = list(factor_names)
        if table_names:
            body["tables"] = list(table_names)
        if report_period_end is not None:
            body["report_period_end"] = self._iso_date(
                report_period_end,
                "report_period_end",
            )
        if start_date is not None or end_date is not None:
            if start_date is None or end_date is None:
                raise ValueError("v1 date query requires both start_date and end_date")
            body["date"] = self._date_range(start_date, end_date)
        if "report_period_end" not in body and "date" not in body:
            raise ValueError("v1 query requires report_period_end or date range")
        data = self._call(
            "POST",
            "/factor/service/api/v1/factor/query",
            json_body=body,
        )
        return self._object_rows(data, "v1 factor query")

    def v2_health(self) -> Mapping[str, object]:
        return self._health("/factor/service/api/v2/health")

    def v2_meta_schema(self) -> Mapping[str, object]:
        return self._object(
            self._call("GET", "/factor/service/api/v2/meta/schema"),
            "v2 meta schema",
        )

    def v2_metadata(
        self,
        *,
        prompt_version: str | None = None,
        keyword: str | None = None,
        time_type: str | None = None,
        filter_date: str | None = None,
        shape: str | None = None,
        enabled: bool | None = None,
    ) -> Mapping[str, object]:
        body = self._optional_body(
            prompt_version=prompt_version,
            keyword=keyword,
            time_type=time_type,
            filter_date=filter_date,
            shape=shape,
            enabled=enabled,
        )
        return self._object(
            self._call(
                "POST",
                "/factor/service/api/v2/metadata",
                json_body=body,
            ),
            "v2 metadata",
        )

    def v2_tables(
        self,
        *,
        keyword: str | None = None,
        time_type: str | None = None,
        filter_date: str | None = None,
        shape: str | None = None,
        enabled: bool | None = None,
    ) -> tuple[Mapping[str, object], ...]:
        query = self._optional_query(
            keyword=keyword,
            time_type=time_type,
            filter_date=filter_date,
            shape=shape,
            enabled=enabled,
        )
        return self._object_rows(
            self._call("GET", "/factor/service/api/v2/tables", query=query),
            "v2 tables",
        )

    def v2_table_detail(self, table_name: str) -> Mapping[str, object]:
        return self._object(
            self._call(
                "GET",
                "/factor/service/api/v2/table/detail",
                query={"table_name": self._text(table_name, "table_name")},
            ),
            "v2 table detail",
        )

    def v2_columns_search(
        self,
        *,
        keyword: str | None = None,
        table_name: str | None = None,
        enabled: bool | None = None,
    ) -> tuple[Mapping[str, object], ...]:
        query = self._optional_query(
            keyword=keyword,
            table_name=table_name,
            enabled=enabled,
        )
        return self._object_rows(
            self._call(
                "GET",
                "/factor/service/api/v2/columns/search",
                query=query,
            ),
            "v2 columns search",
        )

    def v2_table_count(
        self,
        *,
        table_name: str,
        primary_key_name: str | None,
        primary_key_values: Sequence[str],
        filter_date: str,
        start_date: str,
        end_date: str,
        allow_date_only_query: bool,
    ) -> int:
        body = self._v2_filter_body(
            table_name=table_name,
            primary_key_name=primary_key_name,
            primary_key_values=primary_key_values,
            filter_date=filter_date,
            start_date=start_date,
            end_date=end_date,
            allow_date_only_query=allow_date_only_query,
        )
        data = self._object(
            self._call(
                "POST",
                "/factor/service/api/v2/table/count",
                json_body=body,
            ),
            "v2 table count",
        )
        count = data.get("count")
        if type(count) is not int or count < 0:
            raise FactorServicePayloadError("v2 table count must be a non-negative integer")
        return count

    def v2_table_query(
        self,
        *,
        table_name: str,
        primary_key_name: str | None,
        primary_key_values: Sequence[str],
        columns: Sequence[str],
        filter_date: str,
        start_date: str,
        end_date: str,
        limit: int,
        offset: int,
        allow_date_only_query: bool = False,
        allow_read_through_cache: bool,
    ) -> Mapping[str, object]:
        self._require_read_through_ack(allow_read_through_cache)
        if type(limit) is not int or not 1 <= limit <= 5000:
            raise ValueError("v2 query limit must be between 1 and 5000")
        if type(offset) is not int or offset < 0:
            raise ValueError("v2 query offset must be a non-negative integer")
        body = self._v2_filter_body(
            table_name=table_name,
            primary_key_name=primary_key_name,
            primary_key_values=primary_key_values,
            filter_date=filter_date,
            start_date=start_date,
            end_date=end_date,
            allow_date_only_query=allow_date_only_query,
        )
        body["columns"] = list(self._optional_texts(columns, "columns"))
        body["limit"] = limit
        body["offset"] = offset
        data = self._object(
            self._call(
                "POST",
                "/factor/service/api/v2/table/query",
                json_body=body,
            ),
            "v2 table query",
        )
        self._object_rows(data.get("rows"), "v2 table query rows")
        return data

    def iter_v2_table_rows(
        self,
        *,
        table_name: str,
        primary_key_name: str | None,
        primary_key_values: Sequence[str],
        columns: Sequence[str],
        filter_date: str,
        start_date: str,
        end_date: str,
        page_size: int,
        allow_date_only_query: bool,
        allow_read_through_cache: bool,
    ) -> Iterator[Mapping[str, object]]:
        if type(page_size) is not int or not 1 <= page_size <= 5000:
            raise ValueError("page_size must be between 1 and 5000")
        count = self.v2_table_count(
            table_name=table_name,
            primary_key_name=primary_key_name,
            primary_key_values=primary_key_values,
            filter_date=filter_date,
            start_date=start_date,
            end_date=end_date,
            allow_date_only_query=allow_date_only_query,
        )
        offset = 0
        while offset < count:
            page = self.v2_table_query(
                table_name=table_name,
                primary_key_name=primary_key_name,
                primary_key_values=primary_key_values,
                columns=columns,
                filter_date=filter_date,
                start_date=start_date,
                end_date=end_date,
                limit=min(page_size, count - offset),
                offset=offset,
                allow_date_only_query=allow_date_only_query,
                allow_read_through_cache=allow_read_through_cache,
            )
            rows = self._object_rows(page.get("rows"), "v2 table query rows")
            if not rows:
                raise FactorServicePayloadError(
                    "v2 pagination returned an empty page before the reported count"
                )
            yield from rows
            offset += len(rows)
            if offset > count:
                raise FactorServicePayloadError(
                    "v2 pagination returned more rows than the reported count"
                )

    def _health(self, path: str) -> Mapping[str, object]:
        data = self._call("GET", path, allow_plain_health=True)
        payload = self._object(data, "health")
        if payload.get("status") != "ok":
            raise FactorServicePayloadError("Factor Service health status is not ok")
        return payload

    def _call(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        json_body: Mapping[str, object] | None = None,
        allow_plain_health: bool = False,
    ) -> object:
        url = f"{self._base_url}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        headers: list[tuple[str, str]] = [("Accept", "application/json")]
        if json_body is not None:
            headers.append(("Content-Type", "application/json"))
        request = FactorServiceHttpRequest(
            method=method,
            url=url,
            headers=tuple(headers),
            json_body=json_body,
            timeout_seconds=self._timeout_seconds,
            bearer_token=self._bearer_token,
        )
        try:
            response = self._transport.send(request)
        except FactorServiceTransportError:
            raise
        except Exception as error:
            detail = self._safe_text(str(error))
            raise FactorServiceTransportError(
                f"Factor Service transport failed: {detail}"
            ) from error
        if not 200 <= response.status_code < 300:
            detail = self._safe_text(response.body.decode("utf-8", errors="replace"))
            raise FactorServicePayloadError(
                f"Factor Service HTTP {response.status_code}: {detail[:500]}"
            )
        try:
            payload = json.loads(
                response.body,
                parse_float=Decimal,
                parse_constant=_reject_non_finite_json_number,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise FactorServicePayloadError("Factor Service response is not valid JSON") from error
        if not isinstance(payload, dict):
            raise FactorServicePayloadError("Factor Service response must be a JSON object")
        if allow_plain_health and "code" not in payload:
            return cast(Mapping[str, object], payload)
        code = payload.get("code")
        if type(code) is not int or code not in _SUCCESS_CODES:
            message = self._safe_text(str(payload.get("message", "unknown provider error")))
            raise FactorServicePayloadError(
                f"Factor Service business error {code!r}: {message[:500]}"
            )
        return payload.get("data")

    def _v2_filter_body(
        self,
        *,
        table_name: str,
        primary_key_name: str | None,
        primary_key_values: Sequence[str],
        filter_date: str,
        start_date: str,
        end_date: str,
        allow_date_only_query: bool,
    ) -> dict[str, object]:
        if type(allow_date_only_query) is not bool:
            raise TypeError("allow_date_only_query must be a boolean")
        body: dict[str, object] = {
            "table_name": self._text(table_name, "table_name"),
            "filter_date": self._text(filter_date, "filter_date"),
            "filter_date_range": self._date_range(start_date, end_date),
        }
        if primary_key_name is None:
            if primary_key_values:
                raise ValueError("primary key values require primary_key_name")
            if not allow_date_only_query:
                raise ValueError(
                    "primary key is required unless live metadata allows date-only query"
                )
        else:
            values = self._texts(primary_key_values, "primary_key_values")
            body["primary_key"] = {
                "name": self._text(primary_key_name, "primary_key_name"),
                "values": list(values),
            }
        return body

    def _safe_text(self, value: str) -> str:
        safe = value
        if self._bearer_token:
            safe = safe.replace(self._bearer_token, "<redacted>")
        return _BEARER.sub("<redacted>", safe)

    @staticmethod
    def _require_read_through_ack(value: bool) -> None:
        if type(value) is not bool:
            raise TypeError("allow_read_through_cache must be a boolean")
        if not value:
            raise FactorServicePermissionError(
                "Factor Service query requires explicit read-through cache acknowledgement"
            )

    @staticmethod
    def _text(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must not be empty")
        return value

    @classmethod
    def _texts(cls, values: Sequence[str], field_name: str) -> tuple[str, ...]:
        normalized = cls._optional_texts(values, field_name)
        if not normalized:
            raise ValueError(f"{field_name} must not be empty")
        return normalized

    @classmethod
    def _optional_texts(cls, values: Sequence[str], field_name: str) -> tuple[str, ...]:
        if isinstance(values, str):
            raise TypeError(f"{field_name} must be a sequence of strings")
        return tuple(cls._text(value, field_name) for value in values)

    @staticmethod
    def _iso_date(value: str, field_name: str) -> str:
        try:
            date.fromisoformat(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{field_name} must be an ISO date") from error
        return value

    @classmethod
    def _date_range(cls, start_date: str, end_date: str) -> dict[str, str]:
        start = cls._iso_date(start_date, "start_date")
        end = cls._iso_date(end_date, "end_date")
        if end < start:
            raise ValueError("end_date cannot precede start_date")
        return {"start": start, "end": end}

    @classmethod
    def _optional_query(cls, **values: object) -> dict[str, str]:
        query: dict[str, str] = {}
        for name, value in values.items():
            if value is None:
                continue
            if isinstance(value, bool):
                query[name] = "true" if value else "false"
            elif isinstance(value, str):
                query[name] = cls._text(value, name)
            else:
                raise TypeError(f"{name} must be a string, boolean, or None")
        return query

    @classmethod
    def _optional_body(cls, **values: object) -> dict[str, object]:
        body: dict[str, object] = {}
        for name, value in values.items():
            if value is None:
                continue
            if isinstance(value, bool):
                body[name] = value
            elif isinstance(value, str):
                body[name] = cls._text(value, name)
            else:
                raise TypeError(f"{name} must be a string, boolean, or None")
        return body

    @staticmethod
    def _object(value: object, context: str) -> Mapping[str, object]:
        if not isinstance(value, dict):
            raise FactorServicePayloadError(f"{context} must be a JSON object")
        return cast(Mapping[str, object], value)

    @classmethod
    def _object_rows(cls, value: object, context: str) -> tuple[Mapping[str, object], ...]:
        if not isinstance(value, list):
            raise FactorServicePayloadError(f"{context} must be a JSON array")
        return tuple(cls._object(row, context) for row in value)


__all__ = [
    "FactorServiceClient",
    "FactorServiceError",
    "FactorServiceHttpRequest",
    "FactorServiceHttpResponse",
    "FactorServicePayloadError",
    "FactorServicePermissionError",
    "FactorServiceTransport",
    "FactorServiceTransportError",
    "UrllibFactorServiceTransport",
]
