"""Strict, issuer-bound fixture inputs and canonical content serialization."""

from __future__ import annotations

from dataclasses import MISSING, dataclass, fields, is_dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
import hashlib
import json
import re
from types import UnionType
from typing import get_args, get_origin, get_type_hints

from turtle_quant.premise.general_fcf import GeneralFCFInputs, QualityWeights
from turtle_quant.strategy.selection import UniverseInput


SCHEMA = "synthetic-batch-hard-gates-v1"
DATA_KIND = "SYNTHETIC_FIXTURE"
_SECURITY = re.compile(r"^(sh|sz)\.\d{6}$")


def plain(value):
    if is_dataclass(value):
        return {field.name: plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("nonfinite quantity")
        return str(value)
    if type(value) is date:
        return value.isoformat()
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    return value


def canonical_bytes(value) -> bytes:
    return json.dumps(plain(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def content_hash(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_number(value):
    raise ValueError(f"use decimal strings, not floating/nonfinite JSON numbers: {value}")


def _decode(value, annotation, path):
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is UnionType:
        if value is None and type(None) in args:
            return None
        choices = [item for item in args if item is not type(None)]
        if len(choices) == 1:
            return _decode(value, choices[0], path)
    if origin is tuple and args[-1] is Ellipsis:
        if not isinstance(value, list):
            raise ValueError(f"{path} must be an array")
        return tuple(_decode(item, args[0], f"{path}[{index}]")
                     for index, item in enumerate(value))
    if annotation is date:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError(f"{path} must be an ISO date")
        return date.fromisoformat(value)
    if annotation is Decimal:
        if not isinstance(value, str) or not re.fullmatch(r"-?\d+(?:\.\d+)?", value):
            raise ValueError(f"{path} must be a finite decimal string")
        return Decimal(value)
    if annotation in (bool, int, str):
        if type(value) is not annotation:
            raise ValueError(f"{path} must be {annotation.__name__}")
        return value
    if is_dataclass(annotation):
        if not isinstance(value, dict):
            raise ValueError(f"{path} must be an object")
        model_fields = {field.name: field for field in fields(annotation)}
        # Scoring is out of scope; callers cannot introduce alternative weights.
        allowed = set(model_fields) - {"quality_weights"}
        if set(value) - allowed:
            raise ValueError(f"unexpected fields in {path}: {sorted(set(value) - allowed)}")
        hints, decoded = get_type_hints(annotation), {}
        for name, field in model_fields.items():
            if name in value:
                decoded[name] = _decode(value[name], hints[name], f"{path}.{name}")
            elif field.default is MISSING and field.default_factory is MISSING:
                raise ValueError(f"missing field: {path}.{name}")
        return annotation(**decoded)
    raise ValueError(f"unsupported fixture field: {path}")


@dataclass(frozen=True)
class SecurityFixture:
    security_id: str
    basic: UniverseInput | None
    financial: GeneralFCFInputs | None


@dataclass(frozen=True)
class BatchRequest:
    schema: str
    data_kind: str
    as_of: date
    security_ids: tuple[str, ...]
    inputs: tuple[SecurityFixture, ...]

    def __post_init__(self):
        if self.schema != SCHEMA or self.data_kind != DATA_KIND:
            raise ValueError("only the frozen SYNTHETIC_FIXTURE schema is supported")
        if type(self.as_of) is not date:
            raise ValueError("as_of must be a date")
        ids = tuple(self.security_ids)
        if any(not isinstance(item, str) or not _SECURITY.fullmatch(item) for item in ids):
            raise ValueError("invalid canonical security_id")
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate requested security_id")
        records = tuple(self.inputs)
        seen = set()
        for record in records:
            if not isinstance(record, SecurityFixture) or record.security_id not in ids:
                raise ValueError("fixture is not bound to the requested securities")
            if record.security_id in seen:
                raise ValueError("duplicate fixture security_id")
            seen.add(record.security_id)
            basic, financial = record.basic, record.financial
            if basic is not None:
                if not isinstance(basic, UniverseInput):
                    raise ValueError("basic must be UniverseInput or None")
                if basic.security_id != record.security_id or basic.as_of != self.as_of:
                    raise ValueError("basic security/as_of binding mismatch")
                share = basic.share_capital_evidence
                if share and (share.security_id != record.security_id or share.as_of != self.as_of):
                    raise ValueError("share evidence security/as_of binding mismatch")
            if financial is not None:
                if not isinstance(financial, GeneralFCFInputs) or financial.as_of != self.as_of:
                    raise ValueError("financial as_of binding mismatch")
                if financial.quality_weights != QualityWeights():
                    raise ValueError("alternative quality weights are out of scope")
                if (basic and basic.industry_profile is not None
                        and financial.industry_profile is not None
                        and basic.industry_profile != financial.industry_profile):
                    raise ValueError("basic/financial profile mismatch")
                versions = {}
                for annual in financial.annual_observations:
                    key = (annual.fiscal_year, annual.available_at)
                    if key in versions and versions[key] != annual:
                        raise ValueError("conflicting annual observations at one PIT ordering key")
                    versions[key] = annual
        object.__setattr__(self, "security_ids", tuple(sorted(ids)))
        object.__setattr__(self, "inputs", tuple(sorted(records, key=lambda item: item.security_id)))

    def normalized(self):
        result = plain(self)
        for record in result["inputs"]:
            if record["financial"]:
                record["financial"].pop("quality_weights")
                record["financial"]["annual_observations"].sort(key=canonical_bytes)
        return result


def load_request(raw: bytes) -> BatchRequest:
    payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                         parse_float=_reject_number, parse_constant=_reject_number)
    return _decode(payload, BatchRequest, "request")
