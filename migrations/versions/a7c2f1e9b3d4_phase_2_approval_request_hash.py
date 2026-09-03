"""phase-2 approval request: request_hash, nullable document_id

Revision ID: a7c2f1e9b3d4
Revises: e01e50e0d577
Create Date: 2026-09-03
"""

from __future__ import annotations

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision = "a7c2f1e9b3d4"
down_revision = "e01e50e0d577"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("approval_request") as batch:
        batch.add_column(
            sa.Column("request_hash", sqlmodel.sql.sqltypes.AutoString(length=80), nullable=True)
        )
        batch.alter_column(
            "document_id", existing_type=sqlmodel.sql.sqltypes.AutoString(length=26), nullable=True
        )
        batch.create_index("ix_approval_request_request_hash", ["request_hash"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("approval_request") as batch:
        batch.drop_index("ix_approval_request_request_hash")
        batch.alter_column(
            "document_id", existing_type=sqlmodel.sql.sqltypes.AutoString(length=26), nullable=False
        )
        batch.drop_column("request_hash")
