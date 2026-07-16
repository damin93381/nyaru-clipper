"""Add immutable automatic-highlight filtering to each task.

Revision ID: 20260714_01
Revises: 20260712_02
Create Date: 2026-07-14 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260714_01"
down_revision = "20260712_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Enable automatic highlight filtering for historical tasks."""
    bind = op.get_bind()
    task_columns = {column["name"] for column in sa.inspect(bind).get_columns("task")}
    if "highlight_filtering_enabled" not in task_columns:
        op.add_column(
            "task",
            sa.Column("highlight_filtering_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        )


def downgrade() -> None:
    """Remove the per-task automatic-highlight filtering option."""
    op.drop_column("task", "highlight_filtering_enabled")
