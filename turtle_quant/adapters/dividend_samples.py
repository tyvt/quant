"""Pure normalization for the fixed stage-B2 dividend evidence sample.

The module deliberately has no network client and is not connected to the
snapshot sync runner.  The original sample cannot infer ordinary status from
provider labels. A separate pinned legal-PDF pair can classify this one
annual cash distribution under RULE_SPEC v1.2.0; neither that classification
nor a later payment revision proves complete window coverage.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import math
import re

from turtle_quant.storage.snapshot import _canonical_json

from .security import normalize_security_id


DIVIDEND_SAMPLE_SCHEMA_VERSION = 1
DIVIDEND_SAMPLE_NORMALIZATION_VERSION = "dividend_sample_v1"
DIVIDEND_CLASSIFIED_SCHEMA_VERSION = 2
DIVIDEND_CLASSIFIED_NORMALIZATION_VERSION = "dividend_sample_v2_ordinary"
DIVIDEND_SAMPLE_REVISION_STATUS = "dividends:fixed_cross_source_sample"
DIVIDEND_PAYMENT_VERIFIED_STATUS = "dividends:payment_completion_verified"

_AKSHARE_INTERFACE = "stock_fhps_detail_em"
_BAOSTOCK_INTERFACE = "query_dividend_data"
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_SPDB_PLAN_SHA256 = "3304f19cd12fc66b019017756c4da6c5e12b04de5750ce2d422cb93d048d3a9d"
_SPDB_IMPLEMENTATION_SHA256 = "556db2246673babc2d6dcc996fd3d9dff308b6610b4cd61dfe78baf5c005f17b"
_SPDB_PLAN_URL = "https://static.cninfo.com.cn/finalpage/2023-04-19/1216456205.PDF"

_AKSHARE_REQUIRED_FIELDS = (
    "报告期",
    "业绩披露日期",
    "现金分红-现金分红比例",
    "现金分红-现金分红比例描述",
    "总股本",
    "预案公告日",
    "股权登记日",
    "除权除息日",
    "方案进度",
    "最新公告日期",
)
_BAOSTOCK_REQUIRED_FIELDS = (
    "code",
    "dividPreNoticeDate",
    "dividAgmPumDate",
    "dividPlanAnnounceDate",
    "dividPlanDate",
    "dividRegistDate",
    "dividOperateDate",
    "dividPayDate",
    "dividStockMarketDate",
    "dividCashPsBeforeTax",
    "dividCashPsAfterTax",
    "dividStocksPs",
    "dividCashStock",
    "dividReserveToStockPs",
)
_LEGAL_REQUIRED_FIELDS = (
    "source_name",
    "url",
    "sha256",
    "page_count",
    "announcement_number",
    "document_date",
    "security_code",
    "distribution_year",
    "share_class",
    "gross_cash_per_share",
    "currency",
    "record_date",
    "ex_date",
    "scheduled_payment_date",
    "differential_distribution",
    "basis_shares",
    "gross_cash_total",
    "evidence_pages",
)
_PAYMENT_COMPLETION_REQUIRED_FIELDS = (
    "source_name",
    "url",
    "sha256",
    "page_count",
    "announcement_id",
    "document_title",
    "announcement_date",
    "security_code",
    "completed",
    "payment_date",
    "gross_cash_per_share",
    "basis_shares",
    "gross_cash_total",
    "evidence_pages",
)
_ORDINARY_CLASSIFICATION_REQUIRED_FIELDS = (
    "source_name",
    "plan_document_url",
    "plan_document_sha256",
    "plan_document_date",
    "plan_available_on",
    "plan_evidence_pages",
    "implementation_document_sha256",
    "security_code",
    "fiscal_year",
    "annual_base_cash_distribution",
    "special_component_present",
)


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


def _normal_date(value: object, field: str) -> date:
    if value in (None, ""):
        raise ValueError(f"{field} must contain a date")
    if isinstance(value, datetime):
        return value.date()
    if type(value) is date:
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError as exc:
        raise ValueError(f"invalid {field}: {value!r}") from exc


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


def _positive_integer(value: object, field: str) -> int:
    converted = _decimal(value, field)
    if converted <= 0 or converted != converted.to_integral_value():
        raise ValueError(f"{field} must be a positive integer")
    return int(converted)


def _utc_datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("first_observed_at must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("first_observed_at must include a timezone")
    return value.astimezone(timezone.utc).replace(microsecond=0)


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


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


def _validated_ordinary_classification(
    sample: Mapping[str, object],
    *,
    security_code: str,
    fiscal_year: int,
    plan_announcement_date: date,
    implementation_document_date: date,
    implementation_available_date: date,
    implementation_sha256: str,
    next_trading_day: Callable[[date], date],
) -> str | None:
    """Validate the manually reviewed PDF pair for this fixed B2 sample.

    This is deliberately not a general dividend text classifier. Without the
    exact legal evidence, ordinary status remains UNKNOWN.
    """

    if "ordinary_classification_evidence" not in sample:
        return None
    evidence = _mapping(
        sample["ordinary_classification_evidence"],
        "ordinary_classification_evidence",
    )
    _require_fields(
        evidence,
        _ORDINARY_CLASSIFICATION_REQUIRED_FIELDS,
        "ordinary classification evidence",
    )
    if (
        evidence["source_name"] != "cninfo"
        or evidence["plan_document_url"] != _SPDB_PLAN_URL
        or str(evidence["plan_document_sha256"]).lower() != _SPDB_PLAN_SHA256
        or str(evidence["implementation_document_sha256"]).lower()
        != _SPDB_IMPLEMENTATION_SHA256
        or implementation_sha256 != _SPDB_IMPLEMENTATION_SHA256
        or evidence["security_code"] != security_code
        or type(evidence["fiscal_year"]) is not int
        or evidence["fiscal_year"] != fiscal_year
    ):
        raise ValueError("ordinary classification legal evidence identity disagrees")
    plan_document_date = _normal_date(
        evidence["plan_document_date"],
        "ordinary_classification_evidence.plan_document_date",
    )
    plan_available_on = _normal_date(
        evidence["plan_available_on"],
        "ordinary_classification_evidence.plan_available_on",
    )
    if (
        plan_document_date != date(2023, 4, 18)
        or plan_available_on != plan_announcement_date
        or plan_available_on != next_trading_day(plan_document_date)
        or plan_available_on > implementation_available_date
        or plan_document_date >= implementation_document_date
    ):
        raise ValueError("ordinary classification plan PIT dates disagree")
    if evidence["plan_evidence_pages"] != [1, 2]:
        raise ValueError("ordinary classification plan page references disagree")
    if (
        evidence["annual_base_cash_distribution"] is not True
        or evidence["special_component_present"] is not False
    ):
        raise ValueError("ordinary classification legal assessment is not supported")
    return f"cninfo:1216456205:sha256:{_SPDB_PLAN_SHA256}:pages:1-2"


def normalize_dividend_sample(
    sample: Mapping[str, object],
    *,
    first_observed_at: datetime,
    next_trading_day: Callable[[date], date],
) -> dict[str, object]:
    """Reconcile the fixed dividend sample without manufacturing ``D``.

    The implementation announcement verifies the scheduled payment date,
    share basis and cash amount. The original v1 fixture alone does not prove
    ordinary status. A v2 sidecar must pin the reviewed annual plan and the
    implementation PDFs before this fixed event can be marked ordinary.
    Scheduled payment still does not prove completion.
    """

    sample = _mapping(sample, "sample")
    _require_fields(
        sample,
        (
            "security_id",
            "fiscal_period_end",
            "event_kind",
            "akshare",
            "baostock",
            "legal_announcement",
        ),
        "dividend sample",
    )
    if sample["event_kind"] != "CASH_DIVIDEND":
        raise ValueError("event_kind must be CASH_DIVIDEND")

    normalized_security = normalize_security_id(
        str(sample["security_id"]), source="dividend_sample"
    )
    if sample["security_id"] != normalized_security.security_id:
        raise ValueError("security_id must already be normalized")
    fiscal_period_end = _normal_date(
        sample["fiscal_period_end"], "fiscal_period_end"
    )

    akshare = _mapping(sample["akshare"], "akshare")
    baostock = _mapping(sample["baostock"], "baostock")
    legal = _mapping(sample["legal_announcement"], "legal_announcement")
    _require_fields(
        akshare,
        ("source_interface", "source_endpoint", "request", "raw_row"),
        "akshare source",
    )
    _require_fields(
        baostock,
        ("source_interface", "request", "raw_row"),
        "baostock source",
    )
    _require_fields(legal, _LEGAL_REQUIRED_FIELDS, "legal announcement")
    if akshare["source_interface"] != _AKSHARE_INTERFACE:
        raise ValueError("unsupported akshare source_interface")
    if baostock["source_interface"] != _BAOSTOCK_INTERFACE:
        raise ValueError("unsupported baostock source_interface")

    ak_request = _mapping(akshare["request"], "akshare.request")
    bs_request = _mapping(baostock["request"], "baostock.request")
    ak_row = _mapping(akshare["raw_row"], "akshare.raw_row")
    bs_row = _mapping(baostock["raw_row"], "baostock.raw_row")
    _require_fields(ak_row, _AKSHARE_REQUIRED_FIELDS, "akshare raw row")
    _require_fields(bs_row, _BAOSTOCK_REQUIRED_FIELDS, "baostock raw row")

    if str(ak_request.get("symbol", "")) != normalized_security.raw_code:
        raise ValueError("akshare request and security identities disagree")
    if bs_request.get("code") != normalized_security.security_id:
        raise ValueError("baostock request and security identities disagree")
    if bs_row["code"] != normalized_security.security_id:
        raise ValueError("baostock row and security identities disagree")
    if str(legal["security_code"]) != normalized_security.raw_code:
        raise ValueError("legal announcement and security identities disagree")

    ak_period_end = _normal_date(ak_row["报告期"], "akshare.报告期")
    if ak_period_end != fiscal_period_end:
        raise ValueError("fiscal period dates disagree across sources")
    distribution_year = legal["distribution_year"]
    if (
        isinstance(distribution_year, bool)
        or not isinstance(distribution_year, int)
        or distribution_year != fiscal_period_end.year
    ):
        raise ValueError("distribution year and fiscal period disagree")

    plan_dates = {
        _normal_date(ak_row["业绩披露日期"], "akshare.业绩披露日期"),
        _normal_date(ak_row["预案公告日"], "akshare.预案公告日"),
        _normal_date(
            bs_row["dividPlanAnnounceDate"],
            "baostock.dividPlanAnnounceDate",
        ),
    }
    if len(plan_dates) != 1:
        raise ValueError("plan announcement dates disagree across sources")
    plan_announcement_date = next(iter(plan_dates))

    provider_announcement_dates = {
        _normal_date(ak_row["最新公告日期"], "akshare.最新公告日期"),
        _normal_date(bs_row["dividPlanDate"], "baostock.dividPlanDate"),
    }
    if len(provider_announcement_dates) != 1:
        raise ValueError(
            "implementation announcement dates disagree across providers"
        )
    provider_announcement_date = next(iter(provider_announcement_dates))
    legal_document_date = _normal_date(
        legal["document_date"], "legal.document_date"
    )
    available_date = next_trading_day(legal_document_date)
    if type(available_date) is not date or available_date <= legal_document_date:
        raise ValueError(
            "next trading day availability must follow legal document date"
        )
    if provider_announcement_date != available_date:
        raise ValueError(
            "provider announcement date and conservative availability disagree"
        )

    record_dates = {
        _normal_date(ak_row["股权登记日"], "akshare.股权登记日"),
        _normal_date(bs_row["dividRegistDate"], "baostock.dividRegistDate"),
        _normal_date(legal["record_date"], "legal.record_date"),
    }
    if len(record_dates) != 1:
        raise ValueError("record dates disagree across sources")
    record_date = next(iter(record_dates))

    ex_dates = {
        _normal_date(ak_row["除权除息日"], "akshare.除权除息日"),
        _normal_date(bs_row["dividOperateDate"], "baostock.dividOperateDate"),
        _normal_date(legal["ex_date"], "legal.ex_date"),
    }
    if len(ex_dates) != 1:
        raise ValueError("ex-dividend dates disagree across sources")
    ex_date = next(iter(ex_dates))

    payment_dates = {
        _normal_date(bs_row["dividPayDate"], "baostock.dividPayDate"),
        _normal_date(
            legal["scheduled_payment_date"],
            "legal.scheduled_payment_date",
        ),
    }
    if len(payment_dates) != 1:
        raise ValueError("payment dates disagree across sources")
    scheduled_payment_date = next(iter(payment_dates))
    if not (
        plan_announcement_date
        <= legal_document_date
        < record_date
        <= ex_date
        <= scheduled_payment_date
    ):
        raise ValueError("dividend event dates are not chronologically valid")

    ak_per_share = _decimal(
        ak_row["现金分红-现金分红比例"],
        "akshare.cash_dividend_per_10",
    ) / Decimal("10")
    bs_per_share = _decimal(
        bs_row["dividCashPsBeforeTax"],
        "baostock.dividCashPsBeforeTax",
    )
    legal_per_share = _decimal(
        legal["gross_cash_per_share"],
        "legal.gross_cash_per_share",
    )
    if len({ak_per_share, bs_per_share, legal_per_share}) != 1:
        raise ValueError("gross per-share amounts disagree across sources")
    if legal_per_share < 0:
        raise ValueError("gross cash per share must be non-negative")
    if _decimal(bs_row["dividStocksPs"], "baostock.dividStocksPs") != 0:
        raise ValueError("fixed cash-dividend sample unexpectedly includes stock")

    ak_basis_shares = _positive_integer(ak_row["总股本"], "akshare.总股本")
    legal_basis_shares = _positive_integer(
        legal["basis_shares"], "legal.basis_shares"
    )
    if ak_basis_shares != legal_basis_shares:
        raise ValueError("dividend share bases disagree across sources")
    calculated_total = legal_per_share * Decimal(legal_basis_shares)
    legal_total = _decimal(
        legal["gross_cash_total"], "legal.gross_cash_total"
    )
    if calculated_total != legal_total:
        raise ValueError("legal gross cash total disagrees with share basis")

    currency = str(legal["currency"]).strip().upper()
    if re.fullmatch(r"[A-Z]{3}", currency) is None:
        raise ValueError("legal currency must be three ASCII uppercase letters")
    if legal["share_class"] != "COMMON":
        raise ValueError("fixed dividend sample share_class must be COMMON")
    if not isinstance(legal["differential_distribution"], bool):
        raise ValueError("differential_distribution must be boolean")

    legal_hash = str(legal["sha256"])
    if _SHA256_PATTERN.fullmatch(legal_hash) is None:
        raise ValueError("legal announcement sha256 must be a SHA-256 digest")
    legal_hash = legal_hash.lower()
    page_count = legal["page_count"]
    evidence_pages = legal["evidence_pages"]
    if (
        isinstance(page_count, bool)
        or not isinstance(page_count, int)
        or page_count <= 0
    ):
        raise ValueError("legal page_count must be a positive integer")
    if (
        not isinstance(evidence_pages, list)
        or not evidence_pages
        or any(
            isinstance(page, bool)
            or not isinstance(page, int)
            or not 1 <= page <= page_count
            for page in evidence_pages
        )
    ):
        raise ValueError("legal evidence_pages must fall within the PDF")

    observed_at = _utc_datetime(first_observed_at)
    if observed_at.date() < scheduled_payment_date:
        raise ValueError("first_observed_at cannot precede source event dates")
    available_at = datetime.combine(
        available_date, time.min, tzinfo=timezone.utc
    )
    ak_hash = _raw_row_hash(ak_row)
    bs_hash = _raw_row_hash(bs_row)
    ordinary_evidence_ref = _validated_ordinary_classification(
        sample,
        security_code=normalized_security.raw_code,
        fiscal_year=fiscal_period_end.year,
        plan_announcement_date=plan_announcement_date,
        implementation_document_date=legal_document_date,
        implementation_available_date=available_date,
        implementation_sha256=legal_hash,
        next_trading_day=next_trading_day,
    )

    row = {
        "schema_version": (
            DIVIDEND_CLASSIFIED_SCHEMA_VERSION
            if ordinary_evidence_ref is not None
            else DIVIDEND_SAMPLE_SCHEMA_VERSION
        ),
        "normalization_version": (
            DIVIDEND_CLASSIFIED_NORMALIZATION_VERSION
            if ordinary_evidence_ref is not None
            else DIVIDEND_SAMPLE_NORMALIZATION_VERSION
        ),
        "security_id": normalized_security.security_id,
        "raw_code": normalized_security.raw_code,
        "fiscal_period_end": fiscal_period_end.isoformat(),
        "event_kind": "CASH_DIVIDEND",
        "share_class": "COMMON",
        "plan_announcement_date": plan_announcement_date.isoformat(),
        "legal_document_date": legal_document_date.isoformat(),
        "provider_implementation_announcement_date": (
            provider_announcement_date.isoformat()
        ),
        "record_date": record_date.isoformat(),
        "ex_date": ex_date.isoformat(),
        "scheduled_payment_date": scheduled_payment_date.isoformat(),
        "available_at": _utc_text(available_at),
        "available_at_basis": (
            "next_trading_day_after_legal_document_date"
        ),
        "first_observed_at": _utc_text(observed_at),
        "gross_cash_per_share": legal_per_share,
        "basis_shares": legal_basis_shares,
        "gross_cash_total": legal_total,
        "calculated_gross_cash_total": calculated_total,
        "currency": currency,
        "differential_distribution": legal["differential_distribution"],
        "is_ordinary": "TRUE" if ordinary_evidence_ref is not None else "UNKNOWN",
        "ordinary_status_basis": (
            "rule_spec_v1.2_annual_base_cash_legal_pdf_pair"
            if ordinary_evidence_ref is not None
            else "legal_classification_evidence_missing"
        ),
        "is_paid": "UNKNOWN",
        "payment_status_basis": (
            "scheduled_payment_date_without_completion_evidence"
        ),
        "d_eligible_amount": None,
        "window_event_coverage_complete": False,
        "provider_revision_sequence": None,
        "revision_status": DIVIDEND_SAMPLE_REVISION_STATUS,
        "source_row_hashes": {
            "akshare": ak_hash,
            "baostock": bs_hash,
        },
        "legal_document_sha256": legal_hash,
        "evidence_refs": [
            (
                f"eastmoney:{_AKSHARE_INTERFACE}:"
                f"{normalized_security.security_id}:"
                f"{fiscal_period_end.isoformat()}:{ak_hash}"
            ),
            (
                f"baostock:{_BAOSTOCK_INTERFACE}:"
                f"{normalized_security.security_id}:"
                f"{fiscal_period_end.isoformat()}:{bs_hash}"
            ),
            (
                f"spdb:{legal['announcement_number']}:"
                f"sha256:{legal_hash}"
            ),
        ],
        "research_eligible": False,
        "blocking_reasons": [
            *([] if ordinary_evidence_ref is not None else ["ordinary_classification_unknown"]),
            "payment_completion_unverified",
            "window_event_coverage_unverified",
        ],
        "provider_scheme_progress": str(ak_row["方案进度"]),
        "provider_cash_description": str(
            ak_row["现金分红-现金分红比例描述"]
        ),
        "provider_after_tax_text": str(bs_row["dividCashPsAfterTax"]),
    }
    if ordinary_evidence_ref is not None:
        row["ordinary_classification_evidence_ref"] = ordinary_evidence_ref
        row["evidence_refs"].append(ordinary_evidence_ref)
    return row


def _validated_payment_completion(
    sample: Mapping[str, object],
    initial: Mapping[str, object],
    *,
    first_observed_at: datetime,
    next_trading_day: Callable[[date], date],
) -> dict[str, object]:
    if "payment_completion_evidence" not in sample:
        raise ValueError("dividend sample is missing payment_completion_evidence")
    evidence = _mapping(
        sample["payment_completion_evidence"],
        "payment_completion_evidence",
    )
    _require_fields(
        evidence,
        _PAYMENT_COMPLETION_REQUIRED_FIELDS,
        "payment completion evidence",
    )
    if evidence["source_name"] != "cninfo":
        raise ValueError("unsupported payment completion source_name")
    if str(evidence["security_code"]) != initial["raw_code"]:
        raise ValueError("payment completion security identity disagrees")
    if evidence["completed"] is not True:
        raise ValueError("payment completion evidence must explicitly state completed")

    payment_date = _normal_date(
        evidence["payment_date"],
        "payment_completion_evidence.payment_date",
    )
    if payment_date.isoformat() != initial["scheduled_payment_date"]:
        raise ValueError("payment completion date disagrees with scheduled payment")
    per_share = _decimal(
        evidence["gross_cash_per_share"],
        "payment_completion_evidence.gross_cash_per_share",
    )
    if per_share != initial["gross_cash_per_share"]:
        raise ValueError("payment completion per-share amount disagrees")
    basis_shares = _positive_integer(
        evidence["basis_shares"],
        "payment_completion_evidence.basis_shares",
    )
    if basis_shares != initial["basis_shares"]:
        raise ValueError("payment completion share basis disagrees")
    gross_total = _decimal(
        evidence["gross_cash_total"],
        "payment_completion_evidence.gross_cash_total",
    )
    if gross_total != initial["gross_cash_total"]:
        raise ValueError("payment completion total amount disagrees")

    announcement_date = _normal_date(
        evidence["announcement_date"],
        "payment_completion_evidence.announcement_date",
    )
    if announcement_date <= payment_date:
        raise ValueError("payment completion announcement must follow payment date")
    available_date = next_trading_day(announcement_date)
    if type(available_date) is not date or available_date <= announcement_date:
        raise ValueError(
            "next trading day availability must follow completion announcement date"
        )
    observed_at = _utc_datetime(first_observed_at)
    if observed_at.date() < available_date:
        raise ValueError("first_observed_at cannot precede completion evidence")

    document_hash = str(evidence["sha256"])
    if _SHA256_PATTERN.fullmatch(document_hash) is None:
        raise ValueError("payment completion sha256 must be a SHA-256 digest")
    page_count = evidence["page_count"]
    evidence_pages = evidence["evidence_pages"]
    if (
        isinstance(page_count, bool)
        or not isinstance(page_count, int)
        or page_count <= 0
    ):
        raise ValueError("payment completion page_count must be a positive integer")
    if (
        not isinstance(evidence_pages, list)
        or not evidence_pages
        or any(
            isinstance(page, bool)
            or not isinstance(page, int)
            or not 1 <= page <= page_count
            for page in evidence_pages
        )
    ):
        raise ValueError(
            "payment completion evidence_pages must fall within the PDF"
        )
    announcement_id = str(evidence["announcement_id"]).strip()
    document_title = str(evidence["document_title"]).strip()
    url = str(evidence["url"]).strip()
    if not announcement_id or not document_title or not url.startswith("https://"):
        raise ValueError("payment completion evidence metadata is incomplete")

    available_at = datetime.combine(
        available_date,
        time.min,
        tzinfo=timezone.utc,
    )
    return {
        "available_at": _utc_text(available_at),
        "announcement_date": announcement_date.isoformat(),
        "document_sha256": document_hash.lower(),
        "evidence_ref": (
            f"cninfo:{announcement_id}:page:{evidence_pages[0]}"
        ),
        "source_url": url,
        "document_title": document_title,
    }


def normalize_dividend_sample_revisions(
    sample: Mapping[str, object],
    *,
    first_observed_at: datetime,
    next_trading_day: Callable[[date], date],
) -> tuple[dict[str, object], dict[str, object]]:
    """Return the initial UNKNOWN payment state and later verified state.

    The later issuer report explicitly states that the distribution completed.
    Its evidence becomes visible only after that report's announcement, so the
    verified state is a separate PIT revision and is never backdated to the
    implementation announcement or scheduled payment date.
    """

    sample = _mapping(sample, "sample")
    initial = normalize_dividend_sample(
        sample,
        first_observed_at=first_observed_at,
        next_trading_day=next_trading_day,
    )
    completion = _validated_payment_completion(
        sample,
        initial,
        first_observed_at=first_observed_at,
        next_trading_day=next_trading_day,
    )
    verified = dict(initial)
    verified.update(
        {
            "available_at": completion["available_at"],
            "available_at_basis": (
                "next_trading_day_after_payment_completion_announcement"
            ),
            "is_paid": "TRUE",
            "payment_status_basis": (
                "issuer_periodic_report_explicitly_states_completed"
            ),
            "payment_completion_announcement_date": completion[
                "announcement_date"
            ],
            "payment_completion_document_sha256": completion[
                "document_sha256"
            ],
            "payment_completion_evidence_ref": completion["evidence_ref"],
            "payment_completion_source_url": completion["source_url"],
            "payment_completion_document_title": completion["document_title"],
            "revision_status": DIVIDEND_PAYMENT_VERIFIED_STATUS,
            "evidence_refs": [
                *initial["evidence_refs"],
                completion["evidence_ref"],
            ],
            "blocking_reasons": [
                *(
                    []
                    if initial["is_ordinary"] == "TRUE"
                    else ["ordinary_classification_unknown"]
                ),
                "window_event_coverage_unverified",
            ],
        }
    )
    return initial, verified
