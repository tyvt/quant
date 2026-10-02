"""Stage-B1 financial-statement sample normalization.

This module deliberately has no network client and is not wired into the
snapshot sync runner.  It proves a deterministic mapping for nine fixed
Eastmoney/AKShare samples while preserving unresolved facts which block
production use, including unverified statement scope and provider revision
order.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import math
import re
from types import MappingProxyType

from turtle_quant.storage.snapshot import _canonical_json

from .security import normalize_security_id


FINANCIAL_SAMPLE_SCHEMA_VERSION = 1
FINANCIAL_SAMPLE_NORMALIZATION_VERSION = "financial_statement_sample_v1"
LATEST_RESTATED_ONLY = "financials:latest_restated_only"


@dataclass(frozen=True)
class _InterfaceDescriptor:
    source_variant: str
    statement_type: str
    endpoint: str


_INTERFACES = MappingProxyType(
    {
        "stock_balance_sheet_by_report_em": _InterfaceDescriptor(
            source_variant="listed",
            statement_type="balance_sheet",
            endpoint=(
                "https://emweb.securities.eastmoney.com/PC_HSF10/"
                "NewFinanceAnalysis/zcfzbAjaxNew"
            ),
        ),
        "stock_profit_sheet_by_report_em": _InterfaceDescriptor(
            source_variant="listed",
            statement_type="income_statement",
            endpoint=(
                "https://emweb.securities.eastmoney.com/PC_HSF10/"
                "NewFinanceAnalysis/lrbAjaxNew"
            ),
        ),
        "stock_cash_flow_sheet_by_report_em": _InterfaceDescriptor(
            source_variant="listed",
            statement_type="cash_flow_statement",
            endpoint=(
                "https://emweb.securities.eastmoney.com/PC_HSF10/"
                "NewFinanceAnalysis/xjllbAjaxNew"
            ),
        ),
        "stock_balance_sheet_by_report_delisted_em": _InterfaceDescriptor(
            source_variant="delisted",
            statement_type="balance_sheet",
            endpoint=(
                "https://datacenter.eastmoney.com/securities/api/data/get"
                "?type=RPT_F10_FINANCE_GBALANCE"
            ),
        ),
        "stock_profit_sheet_by_report_delisted_em": _InterfaceDescriptor(
            source_variant="delisted",
            statement_type="income_statement",
            endpoint=(
                "https://datacenter.eastmoney.com/securities/api/data/get"
                "?type=RPT_F10_FINANCE_GINCOME"
            ),
        ),
        "stock_cash_flow_sheet_by_report_delisted_em": _InterfaceDescriptor(
            source_variant="delisted",
            statement_type="cash_flow_statement",
            endpoint=(
                "https://datacenter.eastmoney.com/securities/api/data/get"
                "?type=RPT_F10_FINANCE_GCASHFLOW"
            ),
        ),
    }
)

_ORGANIZATION_TYPES = MappingProxyType(
    {
        "银行": "bank",
        "通用": "general",
    }
)

_BALANCE_ITEMS = MappingProxyType(
    {
        "TOTAL_ASSETS": "currency",
        "TOTAL_LIABILITIES": "currency",
        "TOTAL_PARENT_EQUITY": "currency",
        "MINORITY_EQUITY": "currency",
        "TOTAL_EQUITY": "currency",
    }
)
_LISTED_GENERAL_BALANCE_ITEMS = MappingProxyType(
    {
        "MONETARYFUNDS": "currency",
        "TRADE_FINASSET": "currency",
        "OTHER_CURRENT_ASSET": "currency",
        "NONCURRENT_ASSET_1YEAR": "currency",
        "SHORT_LOAN": "currency",
        "NONCURRENT_LIAB_1YEAR": "currency",
        "SHORT_BOND_PAYABLE": "currency",
        "LONG_LOAN": "currency",
        "BOND_PAYABLE": "currency",
        "LEASE_LIAB": "currency",
        "TOTAL_ASSETS": "currency",
        "TOTAL_LIABILITIES": "currency",
        "TOTAL_PARENT_EQUITY": "currency",
        "MINORITY_EQUITY": "currency",
        "TOTAL_EQUITY": "currency",
    }
)
_LISTED_BANK_INCOME_ITEMS = MappingProxyType(
    {
        "OPERATE_INCOME": "currency",
        "PARENT_NETPROFIT": "currency",
        "NETPROFIT": "currency",
        "BASIC_EPS": "currency_per_share",
    }
)
_DELISTED_GENERAL_INCOME_ITEMS = MappingProxyType(
    {
        "TOTAL_OPERATE_INCOME": "currency",
        "OPERATE_INCOME": "currency",
        "PARENT_NETPROFIT": "currency",
        "NETPROFIT": "currency",
        "BASIC_EPS": "currency_per_share",
    }
)
_CASH_FLOW_ITEMS = MappingProxyType(
    {
        "NETCASH_OPERATE": "currency",
        "NETCASH_INVEST": "currency",
        "NETCASH_FINANCE": "currency",
        "CCE_ADD": "currency",
    }
)
_LISTED_GENERAL_CASH_FLOW_ITEMS = MappingProxyType(
    {
        "NETCASH_OPERATE": "currency",
        "CONSTRUCT_LONG_ASSET": "currency",
        "NETCASH_INVEST": "currency",
        "NETCASH_FINANCE": "currency",
        "CCE_ADD": "currency",
    }
)

# These are intentionally sample-specific matrices.  Adding another company
# type or endpoint requires real evidence and a new matrix instead of silently
# accepting whatever columns happen to be returned.
FINANCIAL_SAMPLE_FIELD_MATRICES = MappingProxyType(
    {
        ("listed", "bank", "balance_sheet"): _BALANCE_ITEMS,
        ("listed", "bank", "income_statement"): (
            _LISTED_BANK_INCOME_ITEMS
        ),
        ("listed", "bank", "cash_flow_statement"): _CASH_FLOW_ITEMS,
        ("listed", "general", "balance_sheet"): (
            _LISTED_GENERAL_BALANCE_ITEMS
        ),
        ("listed", "general", "income_statement"): (
            _DELISTED_GENERAL_INCOME_ITEMS
        ),
        ("listed", "general", "cash_flow_statement"): (
            _LISTED_GENERAL_CASH_FLOW_ITEMS
        ),
        ("delisted", "general", "balance_sheet"): _BALANCE_ITEMS,
        ("delisted", "general", "income_statement"): (
            _DELISTED_GENERAL_INCOME_ITEMS
        ),
        ("delisted", "general", "cash_flow_statement"): _CASH_FLOW_ITEMS,
    }
)

_REQUIRED_METADATA_FIELDS = (
    "SECUCODE",
    "SECURITY_CODE",
    "SECURITY_NAME_ABBR",
    "ORG_CODE",
    "ORG_TYPE",
    "REPORT_DATE",
    "REPORT_TYPE",
    "REPORT_DATE_NAME",
    "NOTICE_DATE",
    "UPDATE_DATE",
    "CURRENCY",
)

_REPORT_TYPES = MappingProxyType(
    {
        "年报": ("ANNUAL", (12, 31)),
        "一季报": ("Q1", (3, 31)),
        "中报": ("INTERIM", (6, 30)),
        "三季报": ("Q3", (9, 30)),
    }
)

_STATEMENT_SCOPES = frozenset({"UNKNOWN", "CONSOLIDATED", "PARENT"})
_PROVIDER_REVISION_BLOCKER = "provider_revision_sequence_unavailable"

_OBSERVED_FORWARD_ONLY = "financials:observed_forward_only"
_SNAPSHOT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


def _utc_datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("first_observed_at must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("first_observed_at must include a timezone")
    return value.astimezone(timezone.utc).replace(microsecond=0)


@dataclass(frozen=True)
class FinancialStatementObservation:
    """One statement-row content observation from one immutable snapshot."""

    source_interface: str
    security_id: str
    statement_type: str
    period_end: date
    observed_at: datetime
    source_row_hash: str
    snapshot_id: str
    statement_scope: str = "UNKNOWN"

    def __post_init__(self) -> None:
        descriptor = _INTERFACES.get(self.source_interface)
        if descriptor is None:
            raise ValueError(
                f"unsupported financial sample interface: {self.source_interface}"
            )
        if self.statement_type != descriptor.statement_type:
            raise ValueError(
                "statement_type disagrees with the selected source interface"
            )
        if self.statement_scope not in _STATEMENT_SCOPES:
            raise ValueError(f"unsupported statement_scope: {self.statement_scope!r}")
        normalized = normalize_security_id(
            self.security_id, source="financial_observation"
        )
        if self.security_id != normalized.security_id:
            raise ValueError("security_id must already be normalized")
        if type(self.period_end) is not date:
            raise ValueError("period_end must be a date")
        observed_at = _utc_datetime(self.observed_at)
        if _SHA256_PATTERN.fullmatch(self.source_row_hash) is None:
            raise ValueError("source_row_hash must be a SHA-256 hex digest")
        if _SNAPSHOT_ID_PATTERN.fullmatch(self.snapshot_id) is None:
            raise ValueError("snapshot_id must be a safe non-empty identifier")
        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "source_row_hash", self.source_row_hash.lower())

    @property
    def economic_key(self) -> tuple[str, str, str, date, str]:
        return (
            self.source_interface,
            self.security_id,
            self.statement_type,
            self.period_end,
            self.statement_scope,
        )


@dataclass(frozen=True)
class ObservedFinancialRevision:
    """One forward-only content episode; not a provider revision claim."""

    source_interface: str
    security_id: str
    statement_type: str
    period_end: date
    observation_revision_sequence: int
    available_at: datetime
    last_observed_at: datetime
    source_row_hash: str
    snapshot_ids: tuple[str, ...]
    statement_scope: str = "UNKNOWN"
    provider_revision_sequence: None = None
    revision_status: str = _OBSERVED_FORWARD_ONLY


def build_sample_observation_revision_chain(
    observations: Iterable[FinancialStatementObservation],
) -> tuple[ObservedFinancialRevision, ...]:
    """Build deterministic forward-only episodes from repeated observations.

    Consecutive observations with identical content are one episode.  A later
    return to an older hash is a new episode because it is a new observable
    provider state.  Different content at the same normalized observation
    timestamp is rejected as ambiguous.  The resulting sequence is explicitly
    local and never populated into ``provider_revision_sequence``.
    """

    grouped: dict[
        tuple[str, str, str, date, str],
        list[FinancialStatementObservation],
    ] = {}
    for observation in observations:
        if not isinstance(observation, FinancialStatementObservation):
            raise TypeError(
                "observations must contain FinancialStatementObservation"
            )
        grouped.setdefault(observation.economic_key, []).append(observation)

    result: list[ObservedFinancialRevision] = []
    for economic_key in sorted(grouped):
        by_time: dict[datetime, list[FinancialStatementObservation]] = {}
        for observation in grouped[economic_key]:
            by_time.setdefault(observation.observed_at, []).append(observation)

        episodes: list[ObservedFinancialRevision] = []
        for observed_at in sorted(by_time):
            same_time = by_time[observed_at]
            hashes = {item.source_row_hash for item in same_time}
            if len(hashes) != 1:
                raise ValueError(
                    "ambiguous observed revision: different content at the "
                    "same observation time"
                )
            source_row_hash = next(iter(hashes))
            snapshot_ids = tuple(
                sorted({item.snapshot_id for item in same_time})
            )
            if episodes and episodes[-1].source_row_hash == source_row_hash:
                previous = episodes[-1]
                episodes[-1] = replace(
                    previous,
                    last_observed_at=observed_at,
                    snapshot_ids=tuple(
                        sorted(set(previous.snapshot_ids).union(snapshot_ids))
                    ),
                )
                continue

            (
                source_interface,
                security_id,
                statement_type,
                period_end,
                statement_scope,
            ) = economic_key
            episodes.append(
                ObservedFinancialRevision(
                    source_interface=source_interface,
                    security_id=security_id,
                    statement_type=statement_type,
                    period_end=period_end,
                    observation_revision_sequence=len(episodes) + 1,
                    available_at=observed_at,
                    last_observed_at=observed_at,
                    source_row_hash=source_row_hash,
                    snapshot_ids=snapshot_ids,
                    statement_scope=statement_scope,
                )
            )
        result.extend(episodes)
    return tuple(result)


def _provider_date(
    value: object,
    field: str,
    *,
    optional: bool = False,
) -> date | None:
    if value in (None, ""):
        if optional:
            return None
        raise ValueError(f"{field} must contain a provider date")
    if isinstance(value, datetime):
        return value.date()
    if type(value) is date:
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError as exc:
        raise ValueError(f"invalid {field}: {value!r}") from exc


def _decimal_or_none(value: object, field: str) -> Decimal | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a Decimal value or null")
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if not math.isfinite(value):
            raise ValueError(f"{field} must be finite")
    try:
        converted = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(
            f"invalid financial value for {field}: {value!r}"
        ) from exc
    if not converted.is_finite():
        raise ValueError(f"{field} must be finite")
    return converted


def _utc_text(value: datetime) -> str:
    return (
        _utc_datetime(value)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _hashable_raw_row(raw_row: Mapping[str, object]) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for key, value in raw_row.items():
        if isinstance(value, float) and math.isnan(value):
            normalized[str(key)] = None
        else:
            normalized[str(key)] = value
    return normalized


def _report_period(
    raw_report_type: object,
    period_end: date,
    statement_type: str,
) -> tuple[str, str]:
    definition = _REPORT_TYPES.get(str(raw_report_type))
    if definition is None:
        raise ValueError(f"unsupported REPORT_TYPE: {raw_report_type!r}")
    report_type, expected_month_day = definition
    if (period_end.month, period_end.day) != expected_month_day:
        raise ValueError(
            f"REPORT_TYPE {raw_report_type!r} disagrees with REPORT_DATE"
        )
    if statement_type == "balance_sheet":
        return report_type, "INSTANT"
    if report_type == "ANNUAL":
        return report_type, "CUMULATIVE_FY"
    return report_type, "CUMULATIVE_YTD"


def normalize_financial_statement_sample(
    raw_row: Mapping[str, object],
    *,
    source_interface: str,
    statement_type: str,
    first_observed_at: datetime,
    next_trading_day: Callable[[date], date],
    statement_scope: str = "UNKNOWN",
    scope_evidence_ref: str | None = None,
) -> tuple[dict[str, object], ...]:
    """Map one fixed probe row to long-form, non-research storage rows.

    ``available_at`` is deliberately the first observation timestamp rather
    than the announcement date.  The free endpoint exposes only its latest
    restated value and no trustworthy revision sequence, so backdating that
    value to the original notice date would create look-ahead bias.
    """

    if not isinstance(raw_row, Mapping):
        raise TypeError("raw_row must be a mapping")
    descriptor = _INTERFACES.get(source_interface)
    if descriptor is None:
        raise ValueError(
            f"unsupported financial sample interface: {source_interface}"
        )
    if statement_type != descriptor.statement_type:
        raise ValueError(
            "statement_type disagrees with the selected source interface"
        )
    if statement_scope not in _STATEMENT_SCOPES:
        raise ValueError(f"unsupported statement_scope: {statement_scope!r}")
    if statement_scope == "UNKNOWN":
        if scope_evidence_ref is not None:
            raise ValueError(
                "scope_evidence_ref requires a non-UNKNOWN statement_scope"
            )
        normalized_scope_evidence_ref = None
    else:
        if not isinstance(scope_evidence_ref, str) or not scope_evidence_ref.strip():
            raise ValueError(
                "scope_evidence_ref is required for a verified statement_scope"
            )
        normalized_scope_evidence_ref = scope_evidence_ref.strip()

    missing_metadata = [
        field for field in _REQUIRED_METADATA_FIELDS if field not in raw_row
    ]
    if missing_metadata:
        raise ValueError(
            "financial sample is missing metadata fields: "
            + ", ".join(missing_metadata)
        )

    normalized_security = normalize_security_id(
        str(raw_row["SECUCODE"]), source="eastmoney"
    )
    if str(raw_row["SECURITY_CODE"]) != normalized_security.raw_code:
        raise ValueError("SECURITY_CODE disagrees with SECUCODE")

    raw_organization_type = str(raw_row["ORG_TYPE"])
    organization_type = _ORGANIZATION_TYPES.get(raw_organization_type)
    if organization_type is None:
        raise ValueError(
            f"unsupported sample ORG_TYPE: {raw_organization_type!r}"
        )
    matrix_key = (
        descriptor.source_variant,
        organization_type,
        statement_type,
    )
    field_matrix = FINANCIAL_SAMPLE_FIELD_MATRICES.get(matrix_key)
    if field_matrix is None:
        raise ValueError(
            f"no frozen financial sample field matrix for {matrix_key}"
        )
    missing_items = [field for field in field_matrix if field not in raw_row]
    if missing_items:
        raise ValueError(
            "raw row does not satisfy frozen financial sample field matrix: "
            + ", ".join(missing_items)
        )

    period_end = _provider_date(raw_row["REPORT_DATE"], "REPORT_DATE")
    announcement_date = _provider_date(raw_row["NOTICE_DATE"], "NOTICE_DATE")
    assert period_end is not None
    assert announcement_date is not None
    source_update_date = _provider_date(
        raw_row["UPDATE_DATE"], "UPDATE_DATE", optional=True
    )
    if announcement_date < period_end:
        raise ValueError("NOTICE_DATE cannot precede REPORT_DATE")
    if (
        source_update_date is not None
        and source_update_date < announcement_date
    ):
        raise ValueError("UPDATE_DATE cannot precede NOTICE_DATE")
    candidate_available_date = next_trading_day(announcement_date)
    if type(candidate_available_date) is not date:
        raise ValueError("next_trading_day must return a date")
    if candidate_available_date <= announcement_date:
        raise ValueError(
            "next trading day availability must be after NOTICE_DATE"
        )

    first_observed_text = _utc_text(first_observed_at)
    first_observed_date = first_observed_at.astimezone(timezone.utc).date()
    latest_provider_date = source_update_date or announcement_date
    if first_observed_date < max(candidate_available_date, latest_provider_date):
        raise ValueError(
            "first_observed_at cannot precede provider dates or conservative "
            "announcement availability"
        )
    report_type, report_period_kind = _report_period(
        raw_row["REPORT_TYPE"], period_end, statement_type
    )
    currency = str(raw_row["CURRENCY"]).strip().upper()
    if re.fullmatch(r"[A-Z]{3}", currency) is None:
        raise ValueError(f"invalid CURRENCY: {raw_row['CURRENCY']!r}")

    converted_items = {
        item_code: _decimal_or_none(raw_row[item_code], item_code)
        for item_code in field_matrix
    }

    source_row_hash = hashlib.sha256(
        _canonical_json(_hashable_raw_row(raw_row)).encode("utf-8")
    ).hexdigest()
    evidence_ref = (
        f"eastmoney:{source_interface}:{normalized_security.security_id}:"
        f"{period_end.isoformat()}:{source_row_hash}"
    )
    blocking_reasons = [_PROVIDER_REVISION_BLOCKER]
    if statement_scope == "UNKNOWN":
        blocking_reasons.insert(0, "statement_scope_unknown")

    common: dict[str, object] = {
        "security_id": normalized_security.security_id,
        "raw_code": normalized_security.raw_code,
        "display_name": str(raw_row["SECURITY_NAME_ABBR"]),
        "organization_code": str(raw_row["ORG_CODE"]),
        "organization_type": organization_type,
        "source_variant": descriptor.source_variant,
        "statement_type": statement_type,
        "statement_scope": statement_scope,
        "statement_scope_evidence_ref": normalized_scope_evidence_ref,
        "period_end": period_end.isoformat(),
        "report_type": report_type,
        "raw_report_type": str(raw_row["REPORT_TYPE"]),
        "report_date_name": str(raw_row["REPORT_DATE_NAME"]),
        "report_period_kind": report_period_kind,
        "announcement_date": announcement_date.isoformat(),
        "candidate_announcement_available_date": (
            candidate_available_date.isoformat()
        ),
        "available_at": first_observed_text,
        "available_at_basis": "first_observed_at_latest_restated_only",
        "first_observed_at": first_observed_text,
        "source_update_date": (
            source_update_date.isoformat()
            if source_update_date is not None
            else None
        ),
        "provider_revision_sequence": None,
        "revision_status": LATEST_RESTATED_ONLY,
        "currency": currency,
        "source_unit_scale": Decimal("1"),
        "schema_version": FINANCIAL_SAMPLE_SCHEMA_VERSION,
        "normalization_version": FINANCIAL_SAMPLE_NORMALIZATION_VERSION,
        "source_name": "eastmoney_via_akshare",
        "source_interface": source_interface,
        "source_endpoint": descriptor.endpoint,
        "source_row_hash": source_row_hash,
        "evidence_ref": evidence_ref,
        "research_eligible": False,
        "blocking_reasons": blocking_reasons,
    }

    rows: list[dict[str, object]] = []
    for item_code, value_unit in field_matrix.items():
        value = converted_items[item_code]
        rows.append(
            {
                **common,
                "item_code": item_code,
                "value": value,
                "value_status": "KNOWN" if value is not None else "UNKNOWN",
                "value_unit": value_unit,
            }
        )
    return tuple(rows)
