"""phase-6 approval kind, request payload, GRN acceptance link

Revision ID: b8d3e2f0c4a5
Revises: a7c2f1e9b3d4
Create Date: 2026-09-10
"""

from __future__ import annotations

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision = "b8d3e2f0c4a5"
down_revision = "a7c2f1e9b3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("approval_request") as batch:
        batch.add_column(
            sa.Column(
                "kind",
                sqlmodel.sql.sqltypes.AutoString(length=32),
                nullable=False,
                server_default="po_approval",
            )
        )
        batch.add_column(sa.Column("payload_json", sa.JSON(), nullable=True))
        batch.create_index("ix_approval_request_kind", ["kind"], unique=False)
    with op.batch_alter_table("goods_receipt") as batch:
        batch.add_column(
            sa.Column(
                "acceptance_request_id", sqlmodel.sql.sqltypes.AutoString(length=26), nullable=True
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("goods_receipt") as batch:
        batch.drop_column("acceptance_request_id")
    with op.batch_alter_table("approval_request") as batch:
        batch.drop_index("ix_approval_request_kind")
        batch.drop_column("payload_json")
        batch.drop_column("kind")
