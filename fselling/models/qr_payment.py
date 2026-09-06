"""Read/write mappings for the I10-A QR-payment evidence schema.

Migration 0007 owns the database contract.  These classes expose that released
shape to later I10 slices; this module contains no issuer, parser, handler,
provider adapter or rollout behaviour.
"""

from sqlalchemy import Column, ForeignKey, ForeignKeyConstraint, Index, Integer, String, text

from ..core.database import Base


class QrPaymentIntent(Base):
    """One immutable v1 instruction/reference/account snapshot per sales order."""

    __tablename__ = "qr_payment_intents"
    __table_args__ = (
        ForeignKeyConstraint(
            ("order_id", "shop_id"),
            ("orders.id", "orders.shop_id"),
        ),
        Index("ux_qr_payment_intents_order_id", "order_id", unique=True),
        Index(
            "ux_qr_payment_intents_reference",
            "canonical_reference",
            unique=True,
        ),
        Index(
            "ux_qr_payment_intents_id_order_shop",
            "id",
            "order_id",
            "shop_id",
            unique=True,
        ),
        Index(
            "ix_qr_payment_intents_shop_issued",
            "shop_id",
            "issued_at",
            "id",
        ),
    )

    id = Column(Integer, primary_key=True)
    contract_version = Column(Integer, nullable=False)
    order_id = Column(Integer, nullable=False)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    canonical_reference = Column(String(128), nullable=False)
    expected_vnd = Column(Integer, nullable=False)
    bank_code = Column(String(32), nullable=False)
    account_no = Column(String(64), nullable=False)
    account_name = Column(String(200), nullable=False)
    adapter_profile_id = Column(String(64), nullable=False)
    issued_at = Column(String(26), nullable=False)
    display_expires_at = Column(String(26), nullable=True)
    cancel_after = Column(String(26), nullable=True)


class BankWebhookEvent(Base):
    """Durable normalized inbox evidence; raw request bodies are never stored."""

    __tablename__ = "bank_webhook_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ("intent_id", "order_id", "shop_id"),
            (
                "qr_payment_intents.id",
                "qr_payment_intents.order_id",
                "qr_payment_intents.shop_id",
            ),
        ),
        ForeignKeyConstraint(
            ("order_id", "shop_id"),
            ("orders.id", "orders.shop_id"),
        ),
        ForeignKeyConstraint(
            ("payment_id", "order_id"),
            ("order_payments.id", "order_payments.order_id"),
        ),
        Index(
            "ux_bank_webhook_events_provider_idempotency",
            "provider",
            "idempotency_key",
            unique=True,
        ),
        Index(
            "ux_bank_webhook_events_payment_id",
            "payment_id",
            unique=True,
            sqlite_where=text("payment_id IS NOT NULL"),
        ),
        Index(
            "ix_bank_webhook_events_provider_event",
            "provider",
            "provider_event_id",
            sqlite_where=text("provider_event_id IS NOT NULL"),
        ),
        Index(
            "ix_bank_webhook_events_unapplied_shop_received",
            "shop_id",
            "received_at",
            "id",
            sqlite_where=text("disposition = 'UNAPPLIED'"),
        ),
        Index(
            "ix_bank_webhook_events_reference_received",
            "normalized_reference",
            "received_at",
            "id",
            sqlite_where=text("normalized_reference IS NOT NULL"),
        ),
        Index(
            "ix_bank_webhook_events_intent_disposition",
            "intent_id",
            "disposition",
            "received_at",
            sqlite_where=text("intent_id IS NOT NULL"),
        ),
    )

    id = Column(Integer, primary_key=True)
    provider = Column(String(32), nullable=False)
    provider_event_id = Column(String(128), nullable=True)
    idempotency_key = Column(String(64), nullable=False)
    normalized_account_no = Column(String(64), nullable=True)
    direction = Column(String, nullable=False)
    amount_vnd = Column(Integer, nullable=True)
    reference_state = Column(String, nullable=False)
    normalized_reference = Column(String(128), nullable=True)
    normalized_sha256 = Column(String(64), nullable=False)
    envelope_sha256 = Column(String(64), nullable=False)
    intent_id = Column(Integer, nullable=True)
    order_id = Column(Integer, nullable=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=True)
    payment_id = Column(Integer, nullable=True)
    disposition = Column(String, nullable=False)
    reason_code = Column(String(64), nullable=False)
    received_at = Column(String(26), nullable=False)
    updated_at = Column(String(26), nullable=False)
    state_version = Column(Integer, nullable=False, server_default=text("0"))


class BankReconciliationAction(Base):
    """Append-only audited decision over one durable bank inbox event."""

    __tablename__ = "bank_reconciliation_actions"
    __table_args__ = (
        ForeignKeyConstraint(
            ("intent_id", "order_id", "shop_id"),
            (
                "qr_payment_intents.id",
                "qr_payment_intents.order_id",
                "qr_payment_intents.shop_id",
            ),
        ),
        ForeignKeyConstraint(
            ("order_id", "shop_id"),
            ("orders.id", "orders.shop_id"),
        ),
        ForeignKeyConstraint(
            ("payment_id", "order_id"),
            ("order_payments.id", "order_payments.order_id"),
        ),
        Index(
            "ux_bank_reconciliation_actions_event_version",
            "event_id",
            "event_state_version",
            unique=True,
        ),
        Index(
            "ux_bank_reconciliation_actions_system_log",
            "system_log_id",
            unique=True,
        ),
        Index(
            "ux_bank_reconciliation_actions_terminal_event",
            "event_id",
            unique=True,
            sqlite_where=text(
                "action_kind IN ('MAP_AND_APPLY', 'REJECT_NOT_OURS', "
                "'MARK_REFUNDED_EXTERNALLY')"
            ),
        ),
        Index(
            "ix_bank_reconciliation_actions_shop_performed",
            "shop_id",
            "performed_at",
            "id",
        ),
    )

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("bank_webhook_events.id"), nullable=False)
    event_state_version = Column(Integer, nullable=False)
    action_kind = Column(String, nullable=False)
    intent_id = Column(Integer, nullable=True)
    order_id = Column(Integer, nullable=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=True)
    payment_id = Column(Integer, nullable=True)
    performed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    actor_role = Column(String, nullable=False)
    note = Column(String(500), nullable=True)
    performed_at = Column(String(26), nullable=False)
    system_log_id = Column(Integer, ForeignKey("system_logs.id"), nullable=False)
