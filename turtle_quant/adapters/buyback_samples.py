"""Pure stage-B3 mapping for fixed cumulative buyback evidence.

Provider rows expose cumulative progress rather than individual executions.
This module therefore differences issuer-announced cumulative observations
into interval-censored deltas.  It never substitutes an announcement date or
plan start date for an exact trade date.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import math
import re

from turtle_quant.storage.snapshot import _canonical_json

from .security import normalize_security_id


BUYBACK_SAMPLE_SCHEMA_VERSION = 1
BUYBACK_SAMPLE_NORMALIZATION_VERSION = "buyback_sample_v1"
BUYBACK_INTERVAL_CENSORED = "buybacks:interval_censored_cumulative_delta"

_AKSHARE_INTERFACE = "stock_repurchase_em"
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_PLAN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]+$")

_AKSHARE_REQUIRED_FIELDS = (
    "股票代码",
    "股票简称",
    "计划回购金额区间-下限",
    "计划回购金额区间-上限",
    "回购起始时间",
    "实施进度",
    "已回购股份数量",
    "已回购金额",
    "最新公告日期",
)
_LEGAL_OBSERVATION_FIELDS = (
    "announcement_number",
    "document_date",
    "cumulative_through",
    "cumulative_shares",
    "cumulative_amount",
    "url",
    "sha256",
    "evidence_page",
    "kind",
)
_CANCELLATION_FIELDS = (
    "source_name",
    "document_date",
    "url",
    "sha256",
    "evidence_page",
    "cancelled_shares",
    "pre_cancellation_shares",
    "post_cancellation_shares",
    "cancellation_date",
    "status",
)


def _utc_datetime(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return value.astimezone(timezone.utc).replace(microsecond=0)


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _date_at_utc_start(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _decimal(value: object, field: str) -> Decimal:
    if value in (None, "") or isinstance(value, bool):
        raise ValueError(f"{field} must contain a decimal value")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{field} must be finite")
    try:
        converted = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid decimal value for {field}: {value!r}") from exc
    if not converted.is_finite():
        raise ValueError(f"{field} must be finite")
    return converted


def _nonnegative_integer(value: object, field: str) -> int:
    converted = _decimal(value, field)
    if converted < 0 or converted != converted.to_integral_value():
        raise ValueError(f"{field} must be a non-negative integer")
    return int(converted)


def _positive_integer(value: object, field: str) -> int:
    converted = _nonnegative_integer(value, field)
    if converted <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return converted


def _normal_date(
    value: object,
    field: str,
    *,
    optional: bool = False,
) -> date | None:
    if value in (None, ""):
        if optional:
            return None
        raise ValueError(f"{field} must contain a date")
    if isinstance(value, datetime):
        return value.date()
    if type(value) is date:
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError as exc:
        raise ValueError(f"invalid {field}: {value!r}") from exc


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    return value


def _require_fields(
    row: Mapping[str, object], fields: tuple[str, ...], label: str
) -> None:
    missing = [field for field in fields if field not in row]
    if missing:
        raise ValueError(f"{label} is missing fields: {', '.join(missing)}")


def _sha256(value: object, field: str) -> str:
    normalized = str(value)
    if _SHA256_PATTERN.fullmatch(normalized) is None:
        raise ValueError(f"{field} must be a SHA-256 digest")
    return normalized.lower()


def _raw_row_hash(row: Mapping[str, object]) -> str:
    normalized = {
        str(key): None
        if isinstance(value, float) and math.isnan(value)
        else value
        for key, value in row.items()
    }
    return hashlib.sha256(
        _canonical_json(normalized).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class CumulativeBuybackObservation:
    """One issuer-announced cumulative state for a single buyback plan."""

    security_id: str
    plan_id: str
    cumulative_through: date
    available_at: datetime
    cumulative_shares: int
    cumulative_amount: Decimal
    evidence_ref: str

    def __post_init__(self) -> None:
        normalized = normalize_security_id(
            self.security_id, source="buyback_observation"
        )
        if self.security_id != normalized.security_id:
            raise ValueError("security_id must already be normalized")
        if not isinstance(self.plan_id, str) or _PLAN_ID_PATTERN.fullmatch(
            self.plan_id
        ) is None:
            raise ValueError("plan_id must be a safe non-empty identifier")
        if type(self.cumulative_through) is not date:
            raise ValueError("cumulative_through must be a date")
        available_at = _utc_datetime(self.available_at, "available_at")
        if available_at.date() <= self.cumulative_through:
            raise ValueError(
                "available_at must follow the cumulative execution cutoff"
            )
        if (
            isinstance(self.cumulative_shares, bool)
            or not isinstance(self.cumulative_shares, int)
            or self.cumulative_shares < 0
        ):
            raise ValueError("cumulative_shares must be a non-negative integer")
        amount = _decimal(self.cumulative_amount, "cumulative_amount")
        if amount < 0:
            raise ValueError("cumulative_amount must be non-negative")
        if not isinstance(self.evidence_ref, str) or not self.evidence_ref.strip():
            raise ValueError("evidence_ref must be non-empty")
        object.__setattr__(self, "available_at", available_at)
        object.__setattr__(self, "cumulative_amount", amount)
        object.__setattr__(self, "evidence_ref", self.evidence_ref.strip())


@dataclass(frozen=True)
class BuybackIntervalDelta:
    """A cumulative difference known only within an execution-date interval."""

    security_id: str
    plan_id: str
    interval_sequence: int
    execution_window_start: date
    execution_window_start_inclusive: bool
    execution_window_end: date
    delta_shares: int
    delta_amount: Decimal
    cumulative_shares: int
    cumulative_amount: Decimal
    event_available_at: datetime
    evidence_refs: tuple[str, ...]


def eventize_cumulative_buyback_observations(
    observations: Iterable[CumulativeBuybackObservation],
    *,
    first_execution_date: date,
) -> tuple[BuybackIntervalDelta, ...]:
    """Difference monotone cumulative states without inventing trade dates."""

    if type(first_execution_date) is not date:
        raise ValueError("first_execution_date must be a date")
    materialized = tuple(observations)
    if not materialized:
        return ()
    if any(
        not isinstance(item, CumulativeBuybackObservation)
        for item in materialized
    ):
        raise TypeError(
            "observations must contain CumulativeBuybackObservation"
        )
    identities = {
        (item.security_id, item.plan_id) for item in materialized
    }
    if len(identities) != 1:
        raise ValueError("all cumulative observations must share one plan identity")

    by_cutoff: dict[date, list[CumulativeBuybackObservation]] = {}
    for item in materialized:
        by_cutoff.setdefault(item.cumulative_through, []).append(item)

    collapsed: list[CumulativeBuybackObservation] = []
    evidence_by_cutoff: dict[date, tuple[str, ...]] = {}
    for cutoff in sorted(by_cutoff):
        same_cutoff = by_cutoff[cutoff]
        states = {
            (item.cumulative_shares, item.cumulative_amount)
            for item in same_cutoff
        }
        if len(states) != 1:
            raise ValueError(
                "conflicting cumulative buyback states at the same cutoff"
            )
        earliest = min(same_cutoff, key=lambda item: item.available_at)
        collapsed.append(earliest)
        evidence_by_cutoff[cutoff] = tuple(
            sorted({item.evidence_ref for item in same_cutoff})
        )

    if first_execution_date > collapsed[0].cumulative_through:
        raise ValueError("first_execution_date follows first cumulative cutoff")

    security_id, plan_id = next(iter(identities))
    previous_cutoff = first_execution_date
    previous_shares = 0
    previous_amount = Decimal("0")
    result: list[BuybackIntervalDelta] = []
    for sequence, item in enumerate(collapsed, start=1):
        if (
            item.cumulative_shares < previous_shares
            or item.cumulative_amount < previous_amount
        ):
            raise ValueError("cumulative buyback state must not regress")
        delta_shares = item.cumulative_shares - previous_shares
        delta_amount = item.cumulative_amount - previous_amount
        if (delta_shares == 0) != (delta_amount == 0):
            raise ValueError(
                "cumulative share and amount changes must be jointly zero"
            )
        result.append(
            BuybackIntervalDelta(
                security_id=security_id,
                plan_id=plan_id,
                interval_sequence=sequence,
                execution_window_start=previous_cutoff,
                execution_window_start_inclusive=sequence == 1,
                execution_window_end=item.cumulative_through,
                delta_shares=delta_shares,
                delta_amount=delta_amount,
                cumulative_shares=item.cumulative_shares,
                cumulative_amount=item.cumulative_amount,
                event_available_at=item.available_at,
                evidence_refs=evidence_by_cutoff[item.cumulative_through],
            )
        )
        previous_cutoff = item.cumulative_through
        previous_shares = item.cumulative_shares
        previous_amount = item.cumulative_amount
    return tuple(result)


def normalize_buyback_sample(
    sample: Mapping[str, object],
    *,
    first_observed_at: datetime,
    next_trading_day: Callable[[date], date],
) -> tuple[dict[str, object], ...]:
    """Normalize the fixed Moutai plan to non-research interval deltas."""

    sample = _mapping(sample, "sample")
    _require_fields(
        sample,
        (
            "security_id",
            "plan_id",
            "currency",
            "plan_first_disclosed_on",
            "plan_amount_min",
            "plan_amount_max",
            "intended_use",
            "first_execution_date",
            "last_execution_date",
            "akshare_final_row",
            "legal_cumulative_observations",
            "cancellation_confirmation",
        ),
        "buyback sample",
    )
    normalized_security = normalize_security_id(
        str(sample["security_id"]), source="buyback_sample"
    )
    if sample["security_id"] != normalized_security.security_id:
        raise ValueError("security_id must already be normalized")
    plan_id = str(sample["plan_id"])
    if _PLAN_ID_PATTERN.fullmatch(plan_id) is None:
        raise ValueError("plan_id must be a safe non-empty identifier")
    currency = str(sample["currency"]).strip().upper()
    if re.fullmatch(r"[A-Z]{3}", currency) is None:
        raise ValueError("currency must be three ASCII uppercase letters")
    if sample["intended_use"] != "CANCEL_AND_REDUCE_CAPITAL":
        raise ValueError("unsupported intended_use for fixed buyback sample")

    plan_first_disclosed_on = _normal_date(
        sample["plan_first_disclosed_on"], "plan_first_disclosed_on"
    )
    first_execution_date = _normal_date(
        sample["first_execution_date"], "first_execution_date"
    )
    # Legacy fixture key: the final cumulative cutoff/completion date, NOT
    # evidence that the last repurchase trade executed on this exact day.
    final_cumulative_cutoff = _normal_date(
        sample["last_execution_date"], "last_execution_date"
    )
    assert plan_first_disclosed_on is not None
    assert first_execution_date is not None
    assert final_cumulative_cutoff is not None
    if not plan_first_disclosed_on < first_execution_date <= final_cumulative_cutoff:
        raise ValueError("buyback plan, first execution and final cutoff are not chronological")
    plan_amount_min = _decimal(sample["plan_amount_min"], "plan_amount_min")
    plan_amount_max = _decimal(sample["plan_amount_max"], "plan_amount_max")
    if not Decimal("0") <= plan_amount_min <= plan_amount_max:
        raise ValueError("buyback plan amount range is invalid")

    raw_observations = sample["legal_cumulative_observations"]
    if not isinstance(raw_observations, list) or not raw_observations:
        raise ValueError("legal_cumulative_observations must be a non-empty list")
    observations: list[CumulativeBuybackObservation] = []
    metadata_by_cutoff: dict[date, dict[str, object]] = {}
    for index, raw in enumerate(raw_observations):
        item = _mapping(raw, f"legal_cumulative_observations[{index}]")
        _require_fields(
            item,
            _LEGAL_OBSERVATION_FIELDS,
            f"legal cumulative observation {index}",
        )
        document_date = _normal_date(
            item["document_date"], f"observation[{index}].document_date"
        )
        cumulative_through = _normal_date(
            item["cumulative_through"],
            f"observation[{index}].cumulative_through",
        )
        assert document_date is not None
        assert cumulative_through is not None
        if document_date <= cumulative_through:
            raise ValueError(
                "legal buyback document date must follow its cumulative cutoff"
            )
        available_date = next_trading_day(document_date)
        if type(available_date) is not date or available_date <= document_date:
            raise ValueError(
                "next trading day availability must follow document date"
            )
        document_hash = _sha256(
            item["sha256"], f"observation[{index}].sha256"
        )
        evidence_page = _positive_integer(
            item["evidence_page"], f"observation[{index}].evidence_page"
        )
        kind = str(item["kind"])
        if kind not in {"PROGRESS", "FINAL"}:
            raise ValueError("buyback observation kind must be PROGRESS or FINAL")
        evidence_ref = (
            f"moutai:{item['announcement_number']}:page:{evidence_page}:"
            f"sha256:{document_hash}"
        )
        observations.append(
            CumulativeBuybackObservation(
                security_id=normalized_security.security_id,
                plan_id=plan_id,
                cumulative_through=cumulative_through,
                available_at=_date_at_utc_start(available_date),
                cumulative_shares=_nonnegative_integer(
                    item["cumulative_shares"],
                    f"observation[{index}].cumulative_shares",
                ),
                cumulative_amount=_decimal(
                    item["cumulative_amount"],
                    f"observation[{index}].cumulative_amount",
                ),
                evidence_ref=evidence_ref,
            )
        )
        metadata_by_cutoff[cumulative_through] = {
            "announcement_number": str(item["announcement_number"]),
            "document_date": document_date,
            "document_hash": document_hash,
            "source_url": str(item["url"]),
            "kind": kind,
        }

    interval_deltas = eventize_cumulative_buyback_observations(
        observations,
        first_execution_date=first_execution_date,
    )
    final_delta = interval_deltas[-1]
    final_metadata = metadata_by_cutoff[final_delta.execution_window_end]
    if final_delta.execution_window_end != final_cumulative_cutoff:
        raise ValueError("final cumulative cutoff and legacy date field disagree")
    if final_metadata["kind"] != "FINAL":
        raise ValueError("last legal cumulative observation must be FINAL")
    if not plan_amount_min <= final_delta.cumulative_amount <= plan_amount_max:
        raise ValueError("final cumulative amount falls outside the legal plan")

    provider = _mapping(sample["akshare_final_row"], "akshare_final_row")
    _require_fields(
        provider,
        ("source_interface", "observed_shape", "raw_row"),
        "akshare final row source",
    )
    if provider["source_interface"] != _AKSHARE_INTERFACE:
        raise ValueError("unsupported buyback provider interface")
    provider_row = _mapping(provider["raw_row"], "akshare_final_row.raw_row")
    _require_fields(
        provider_row,
        _AKSHARE_REQUIRED_FIELDS,
        "akshare final row",
    )
    if str(provider_row["股票代码"]) != normalized_security.raw_code:
        raise ValueError("provider and sample security identities disagree")
    provider_final_shares = _positive_integer(
        provider_row["已回购股份数量"], "provider.已回购股份数量"
    )
    provider_final_amount = _decimal(
        provider_row["已回购金额"], "provider.已回购金额"
    )
    provider_latest_date = _normal_date(
        provider_row["最新公告日期"], "provider.最新公告日期"
    )
    provider_start_date = _normal_date(
        provider_row["回购起始时间"], "provider.回购起始时间"
    )
    assert provider_latest_date is not None
    assert provider_start_date is not None
    if provider_final_shares != final_delta.cumulative_shares:
        raise ValueError("provider final cumulative shares disagree with legal evidence")
    if provider_final_amount != final_delta.cumulative_amount:
        raise ValueError("provider final cumulative amount disagrees with legal evidence")
    if provider_latest_date != final_metadata["document_date"]:
        raise ValueError("provider final announcement date disagrees with legal evidence")
    provider_row_hash = _raw_row_hash(provider_row)

    cancellation = _mapping(
        sample["cancellation_confirmation"], "cancellation_confirmation"
    )
    _require_fields(
        cancellation,
        _CANCELLATION_FIELDS,
        "cancellation confirmation",
    )
    if cancellation["status"] != "VERIFIED_TRUE":
        raise ValueError("fixed cancellation status must be VERIFIED_TRUE")
    cancellation_document_date = _normal_date(
        cancellation["document_date"], "cancellation.document_date"
    )
    assert cancellation_document_date is not None
    cancellation_available_date = next_trading_day(
        cancellation_document_date
    )
    if (
        type(cancellation_available_date) is not date
        or cancellation_available_date <= cancellation_document_date
    ):
        raise ValueError(
            "next trading day availability must follow cancellation document"
        )
    cancellation_available_at = _date_at_utc_start(
        cancellation_available_date
    )
    cancellation_hash = _sha256(
        cancellation["sha256"], "cancellation.sha256"
    )
    cancellation_page = _positive_integer(
        cancellation["evidence_page"], "cancellation.evidence_page"
    )
    cancelled_shares = _positive_integer(
        cancellation["cancelled_shares"], "cancellation.cancelled_shares"
    )
    pre_cancellation_shares = _positive_integer(
        cancellation["pre_cancellation_shares"],
        "cancellation.pre_cancellation_shares",
    )
    post_cancellation_shares = _positive_integer(
        cancellation["post_cancellation_shares"],
        "cancellation.post_cancellation_shares",
    )
    if pre_cancellation_shares - post_cancellation_shares != cancelled_shares:
        raise ValueError("cancellation share-count bridge does not reconcile")
    if cancelled_shares != final_delta.cumulative_shares:
        raise ValueError("cancelled shares disagree with final legal cumulative shares")
    cancellation_date = _normal_date(
        cancellation["cancellation_date"],
        "cancellation.cancellation_date",
        optional=True,
    )
    if (
        cancellation_date is not None
        and cancellation_date < final_cumulative_cutoff
    ):
        raise ValueError("cancellation date cannot precede final cumulative cutoff")

    observed_at = _utc_datetime(first_observed_at, "first_observed_at")
    if observed_at < cancellation_available_at:
        raise ValueError("first_observed_at cannot precede source evidence")
    cancellation_evidence_ref = (
        f"cninfo:annual-report:page:{cancellation_page}:"
        f"sha256:{cancellation_hash}"
    )

    rows: list[dict[str, object]] = []
    for delta in interval_deltas:
        metadata = metadata_by_cutoff[delta.execution_window_end]
        fully_qualified_available_at = max(
            delta.event_available_at, cancellation_available_at
        )
        rows.append(
            {
                "schema_version": BUYBACK_SAMPLE_SCHEMA_VERSION,
                "normalization_version": (
                    BUYBACK_SAMPLE_NORMALIZATION_VERSION
                ),
                "security_id": normalized_security.security_id,
                "raw_code": normalized_security.raw_code,
                "plan_id": plan_id,
                "currency": currency,
                "plan_first_disclosed_on": (
                    plan_first_disclosed_on.isoformat()
                ),
                "plan_amount_min": plan_amount_min,
                "plan_amount_max": plan_amount_max,
                "intended_use": "CANCEL_AND_REDUCE_CAPITAL",
                "interval_sequence": delta.interval_sequence,
                "execution_window_start": (
                    delta.execution_window_start.isoformat()
                ),
                "execution_window_start_inclusive": (
                    delta.execution_window_start_inclusive
                ),
                "execution_window_end": delta.execution_window_end.isoformat(),
                "exact_execution_date": None,
                "delta_shares": delta.delta_shares,
                "delta_amount": delta.delta_amount,
                "cumulative_shares": delta.cumulative_shares,
                "cumulative_amount": delta.cumulative_amount,
                "amount_excludes_transaction_fees": True,
                "event_available_at": _utc_text(delta.event_available_at),
                "event_available_at_basis": (
                    "next_trading_day_after_legal_announcement"
                ),
                "legal_announcement_number": metadata[
                    "announcement_number"
                ],
                "legal_document_date": metadata["document_date"].isoformat(),
                "legal_document_sha256": metadata["document_hash"],
                "cancellation_status": "VERIFIED_TRUE",
                "cancellation_status_before_verified_at": "UNKNOWN",
                "cancellation_verified_at": _utc_text(
                    cancellation_available_at
                ),
                "cancellation_date": (
                    cancellation_date.isoformat()
                    if cancellation_date is not None
                    else None
                ),
                "cancelled_shares": cancelled_shares,
                "pre_cancellation_shares": pre_cancellation_shares,
                "post_cancellation_shares": post_cancellation_shares,
                "fully_qualified_available_at": _utc_text(
                    fully_qualified_available_at
                ),
                "first_observed_at": _utc_text(observed_at),
                "provider_buyback_start_date": (
                    provider_start_date.isoformat()
                ),
                "provider_latest_announcement_date": (
                    provider_latest_date.isoformat()
                ),
                "provider_scheme_progress": str(provider_row["实施进度"]),
                "provider_final_row_hash": provider_row_hash,
                "provider_revision_sequence": None,
                "eventization_status": BUYBACK_INTERVAL_CENSORED,
                "source_evidence_refs": [
                    *delta.evidence_refs,
                    cancellation_evidence_ref,
                ],
                "latest_calendar_year_coverage_complete": False,
                "research_eligible": False,
                "blocking_reasons": [
                    "exact_execution_date_unavailable",
                    "calendar_year_coverage_unverified",
                ],
            }
        )
    return tuple(rows)
