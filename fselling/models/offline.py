"""ORM mappings for the I09 offline receipt tables.

The schema is owned by migration 0004.  These classes only map the released
tables so service code can persist and verify legacy-v0 receipt evidence.
Lease behaviour belongs to later I09 slices.
"""

from sqlalchemy import Column, ForeignKey, Integer, String, text

from ..core.database import Base


class OfflineLease(Base):
    __tablename__ = "offline_leases"

    lease_id = Column(String, primary_key=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    device_id = Column(String, nullable=False)
    contract_version = Column(Integer, nullable=False)
    catalog_version = Column(Integer, nullable=False)
    catalog_snapshot_digest = Column(String, nullable=False)
    secret_sha256 = Column(String, nullable=False)
    server_anchor_id = Column(String, nullable=False)
    anchor_server_time_utc = Column(String(26), nullable=False)
    issued_at = Column(String(26), nullable=False)
    expires_at = Column(String(26), nullable=False)
    state_version = Column(Integer, nullable=False, server_default=text("0"))
    revoked_at = Column(String(26), nullable=True)
    revoke_reason = Column(String, nullable=True)
    revoked_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)


class OfflineReceiptRegistry(Base):
    __tablename__ = "offline_receipt_registry"

    offline_uuid = Column(String, primary_key=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    server_fingerprint = Column(String, nullable=False)
    contract_version = Column(Integer, nullable=False)
    state = Column(String, nullable=False)
    superseded_by_offline_uuid = Column(
        String,
        ForeignKey("offline_receipt_registry.offline_uuid"),
        nullable=True,
    )
    created_at = Column(String(26), nullable=False)
    updated_at = Column(String(26), nullable=False)
    state_version = Column(Integer, nullable=False, server_default=text("0"))


class OfflineReceipt(Base):
    __tablename__ = "offline_receipts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    offline_uuid = Column(
        String,
        ForeignKey("offline_receipt_registry.offline_uuid"),
        nullable=False,
    )
    contract_version = Column(Integer, nullable=False)
    lease_id = Column(String, ForeignKey("offline_leases.lease_id"), nullable=True)
    device_id = Column(String, nullable=True)
    offline_session_id = Column(String, nullable=True)
    sequence = Column(Integer, nullable=True)
    server_fingerprint = Column(String, nullable=False)
    client_fingerprint = Column(String, nullable=True)
    client_fingerprint_mismatch = Column(Integer, nullable=False)
    sold_by_claimed_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    synced_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    attribution_kind = Column(String, nullable=False)
    sold_at_effective = Column(String(26), nullable=False)
    sold_at_client_utc = Column(String(26), nullable=False)
    sold_at_upper_bound = Column(String(26), nullable=True)
    time_confidence = Column(String, nullable=False)
    client_monotonic_ms = Column(Integer, nullable=True)
    server_anchor_id = Column(String, nullable=True)
    ingested_at = Column(String(26), nullable=False)
