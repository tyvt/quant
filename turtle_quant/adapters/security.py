"""A single, versioned A-share security identifier normalization boundary."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


NORMALIZATION_VERSION = "cn_equity_v1"
_NORMALIZED_PATTERN = re.compile(r"^(sh|sz)\.(\d{6})$")


@dataclass(frozen=True)
class NormalizedSecurityId:
    security_id: str
    exchange: str
    raw_code: str
    vendor_symbol: str
    normalization_version: str = NORMALIZATION_VERSION


def _split_vendor_symbol(raw: str) -> tuple[str | None, str]:
    lowered = raw.lower()
    match = _NORMALIZED_PATTERN.fullmatch(lowered)
    if match:
        return match.group(1), match.group(2)
    if re.fullmatch(r"(sh|sz)\d{6}", lowered):
        return lowered[:2], lowered[2:]
    suffix = re.fullmatch(r"(\d{6})\.(sh|sz)", lowered)
    if suffix:
        return suffix.group(2), suffix.group(1)
    if re.fullmatch(r"\d{6}", lowered):
        return None, lowered
    raise ValueError(f"unsupported security code format: {raw!r}")


def _infer_exchange(code: str) -> str:
    if code.startswith(("6", "9")):
        return "sh"
    if code.startswith(("00", "20", "30")):
        return "sz"
    raise ValueError(f"cannot infer exchange for security code: {code}")


def normalize_security_id(
    raw_code: str,
    *,
    source: str,
) -> NormalizedSecurityId:
    if not isinstance(raw_code, str) or not raw_code.strip():
        raise ValueError("raw_code must be a non-empty string")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("source must be a non-empty string")
    vendor_symbol = unicodedata.normalize("NFC", raw_code.strip())
    explicit_exchange, code = _split_vendor_symbol(vendor_symbol)
    exchange = explicit_exchange or _infer_exchange(code)
    if explicit_exchange is not None and explicit_exchange != _infer_exchange(code):
        raise ValueError(
            f"security code and exchange disagree: {vendor_symbol!r}"
        )
    return NormalizedSecurityId(
        security_id=f"{exchange}.{code}",
        exchange=exchange,
        raw_code=code,
        vendor_symbol=vendor_symbol,
    )


def is_main_board_security(security_id: str) -> bool:
    match = _NORMALIZED_PATTERN.fullmatch(security_id.lower())
    if not match:
        raise ValueError(f"security_id is not normalized: {security_id!r}")
    exchange, code = match.groups()
    if exchange == "sh":
        return code.startswith("60")
    return code.startswith(("000", "001", "002", "003"))
