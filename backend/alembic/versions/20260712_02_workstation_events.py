"""Add durable workstation event rows for cross-process SSE replay.

Revision ID: 20260712_02
Revises: 20260712_01
Create Date: 2026-07-12 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260712_02"
down_revision = "20260712_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the append-only event log used by the workstation SSE endpoint."""
    op.create_table(
        "workstationevent",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("payload_json", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workstationevent_event_type", "workstationevent", ["event_type"])
    op.create_index("ix_workstationevent_entity_id", "workstationevent", ["entity_id"])
    op.create_index("ix_workstationevent_created_at", "workstationevent", ["created_at"])


def downgrade() -> None:
    """Remove the event log without affecting task or queue projections."""
    op.drop_index("ix_workstationevent_created_at", table_name="workstationevent")
    op.drop_index("ix_workstationevent_entity_id", table_name="workstationevent")
    op.drop_index("ix_workstationevent_event_type", table_name="workstationevent")
    op.drop_table("workstationevent")
