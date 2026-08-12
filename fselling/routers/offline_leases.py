"""JWT endpoints cho lifecycle offline lease I09-D."""

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import get_current_user, get_db
from ..schemas.offline_lease import (
    OfflineLeaseCredentialResponse,
    OfflineLeaseIssue,
    OfflineLeaseReclaim,
    OfflineLeaseRevoke,
    OfflineLeaseStateResponse,
)
from ..services import offline_lease_service

router = APIRouter(prefix="/api/offline/leases", tags=["offline-leases"])


@router.post("", response_model=OfflineLeaseCredentialResponse)
def issue_offline_lease(
    payload: OfflineLeaseIssue,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return offline_lease_service.issue_lease(
        db,
        current_user,
        shop_id=payload.shop_id,
        device_id=payload.device_id,
    )


@router.post("/{lease_id}/heartbeat", response_model=OfflineLeaseStateResponse)
def heartbeat_offline_lease(
    lease_id: str,
    lease_token: str = Header(..., alias="X-Offline-Lease-Token"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return offline_lease_service.heartbeat(
        db,
        current_user,
        lease_id=lease_id,
        lease_token=lease_token,
    )


@router.post("/{lease_id}/reclaim", response_model=OfflineLeaseCredentialResponse)
def reclaim_offline_lease(
    lease_id: str,
    payload: OfflineLeaseReclaim,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return offline_lease_service.reclaim(
        db,
        current_user,
        lease_id=lease_id,
        expected_state_version=payload.expected_state_version,
    )


@router.delete("/{lease_id}", response_model=OfflineLeaseStateResponse)
def revoke_offline_lease(
    lease_id: str,
    payload: OfflineLeaseRevoke,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return offline_lease_service.revoke(
        db,
        current_user,
        lease_id=lease_id,
        reason=payload.reason,
    )


__all__ = ["router"]
