"""Authenticated, public-only offline contract rollout capability."""

from fastapi import APIRouter, Depends

from .. import models
from ..core import config
from ..dependencies import get_current_user

router = APIRouter(prefix="/api/offline", tags=["offline-contract"])


@router.get("/capability")
def offline_contract_capability(
    _current_user: models.User = Depends(get_current_user),
):
    """Return policy metadata only; no credential, digest, or user data."""
    return {
        "supported_versions": list(config.OFFLINE_CONTRACT_SUPPORTED_VERSIONS),
        "minimum_accepted_version": config.OFFLINE_CONTRACT_MIN_VERSION,
        "phase": config.OFFLINE_CONTRACT_PHASE,
        "cutoff_at_utc": config.OFFLINE_CONTRACT_CUTOFF_AT,
        "policy_code": config.OFFLINE_CONTRACT_POLICY_CODE,
    }
