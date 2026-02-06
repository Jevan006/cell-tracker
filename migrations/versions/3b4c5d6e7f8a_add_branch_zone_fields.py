"""add branch/zone fields and constraints

Revision ID: 3b4c5d6e7f8a
Revises: 2a3b4c5d6e7f
Create Date: 2026-02-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "3b4c5d6e7f8a"
down_revision = "2a3b4c5d6e7f"
branch_labels = None
depends_on = None


def upgrade():
    # Add active flags
    with op.batch_alter_table("branch", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")
            )
        )

    # Add zone active flag and unique constraint per branch
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("zone", schema=None, recreate="always") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "is_active",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("1"),
                )
            )
            batch_op.create_unique_constraint(
                "uq_zone_branch_name", ["branch_id", "name"]
            )
    else:
        with op.batch_alter_table("zone", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "is_active",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("true"),
                )
            )
            batch_op.drop_constraint("zone_name_key", type_="unique")
            batch_op.create_unique_constraint(
                "uq_zone_branch_name", ["branch_id", "name"]
            )

    # Add leader branch_id
    with op.batch_alter_table("leader", schema=None) as batch_op:
        batch_op.add_column(sa.Column("branch_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_leader_branch", "branch", ["branch_id"], ["id"])


def downgrade():
    with op.batch_alter_table("leader", schema=None) as batch_op:
        batch_op.drop_constraint("fk_leader_branch", type_="foreignkey")
        batch_op.drop_column("branch_id")

    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("zone", schema=None, recreate="always") as batch_op:
            batch_op.drop_constraint("uq_zone_branch_name", type_="unique")
            batch_op.drop_column("is_active")
            batch_op.create_unique_constraint("uq_zone_name", ["name"])
    else:
        with op.batch_alter_table("zone", schema=None) as batch_op:
            batch_op.drop_constraint("uq_zone_branch_name", type_="unique")
            batch_op.drop_column("is_active")
            batch_op.create_unique_constraint("zone_name_key", ["name"])

    with op.batch_alter_table("branch", schema=None) as batch_op:
        batch_op.drop_column("is_active")
