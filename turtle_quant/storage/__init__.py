"""Immutable local snapshot infrastructure.

This package stores raw, auditable data only.  It is not a PIT reader and must
not be imported by the pure valuation domain.
"""

from .snapshot import IngestConfig, SnapshotSession
from .verification import (
    DomainRevokedError,
    SnapshotVerificationError,
    VerifiedSnapshotDomain,
    verify_published_domain,
)

__all__ = [
    "DomainRevokedError",
    "IngestConfig",
    "SnapshotSession",
    "SnapshotVerificationError",
    "VerifiedSnapshotDomain",
    "verify_published_domain",
]
