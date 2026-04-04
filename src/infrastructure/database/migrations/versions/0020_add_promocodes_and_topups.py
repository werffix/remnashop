from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    table_names = set(inspector.get_table_names())

    op.execute("ALTER TYPE plan_availability ADD VALUE IF NOT EXISTS 'TRAFFIC_TOPUP'")
    op.execute("ALTER TYPE plan_availability ADD VALUE IF NOT EXISTS 'DEVICE_TOPUP'")
    op.execute("ALTER TYPE purchase_type ADD VALUE IF NOT EXISTS 'TRAFFIC_TOPUP'")
    op.execute("ALTER TYPE purchase_type ADD VALUE IF NOT EXISTS 'DEVICE_TOPUP'")

    if "promocodes" not in table_names:
        op.create_table(
            "promocodes",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("code", sa.String(length=64), nullable=False),
            sa.Column("discount_percent", sa.Integer(), nullable=False),
            sa.Column("max_activations", sa.Integer(), nullable=True),
            sa.Column("max_activations_per_user", sa.Integer(), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("timezone('UTC', now())"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("timezone('UTC', now())"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("code"),
        )
    else:
        promocode_columns = {column["name"] for column in inspector.get_columns("promocodes")}
        if "discount_percent" not in promocode_columns:
            op.add_column("promocodes", sa.Column("discount_percent", sa.Integer(), nullable=True))
            if "reward_type" in promocode_columns:
                op.execute(
                    """
                    UPDATE promocodes
                    SET discount_percent = CASE
                        WHEN reward_type::text = 'PURCHASE_DISCOUNT'
                            AND reward IS NOT NULL
                            AND reward BETWEEN 1 AND 100
                        THEN reward
                        ELSE 10
                    END
                    WHERE discount_percent IS NULL
                    """
                )
                op.execute(
                    """
                    UPDATE promocodes
                    SET is_active = FALSE
                    WHERE reward_type::text <> 'PURCHASE_DISCOUNT'
                    """
                )
            else:
                op.execute(
                    "UPDATE promocodes SET discount_percent = 10 WHERE discount_percent IS NULL"
                )
            op.alter_column("promocodes", "discount_percent", nullable=False)

        if "expires_at" not in promocode_columns:
            op.add_column(
                "promocodes",
                sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            )
        if "max_activations_per_user" not in promocode_columns:
            op.add_column(
                "promocodes",
                sa.Column("max_activations_per_user", sa.Integer(), nullable=True),
            )
            op.execute(
                "UPDATE promocodes SET max_activations_per_user = 1 WHERE max_activations_per_user IS NULL"
            )

    inspector = sa.inspect(conn)
    transaction_columns = {column["name"] for column in inspector.get_columns("transactions")}
    transaction_fks = {fk["name"] for fk in inspector.get_foreign_keys("transactions")}
    if "promocode_id" not in transaction_columns:
        op.add_column("transactions", sa.Column("promocode_id", sa.Integer(), nullable=True))
    if "transactions_promocode_id_fkey" not in transaction_fks:
        op.create_foreign_key(
            "transactions_promocode_id_fkey",
            "transactions",
            "promocodes",
            ["promocode_id"],
            ["id"],
        )

    inspector = sa.inspect(conn)
    table_names = set(inspector.get_table_names())
    if "promocode_activations" not in table_names:
        op.create_table(
            "promocode_activations",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("promocode_id", sa.Integer(), nullable=False),
            sa.Column("user_telegram_id", sa.BigInteger(), nullable=False),
            sa.Column("transaction_payment_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("timezone('UTC', now())"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("timezone('UTC', now())"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["promocode_id"], ["promocodes.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["transaction_payment_id"],
                ["transactions.payment_id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(["user_telegram_id"], ["users.telegram_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    else:
        activation_columns = {
            column["name"] for column in inspector.get_columns("promocode_activations")
        }
        activation_fks = {fk["name"] for fk in inspector.get_foreign_keys("promocode_activations")}
        if "transaction_payment_id" not in activation_columns:
            op.add_column(
                "promocode_activations",
                sa.Column("transaction_payment_id", postgresql.UUID(as_uuid=True), nullable=True),
            )
        if "created_at" not in activation_columns:
            op.add_column(
                "promocode_activations",
                sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            )
            if "activated_at" in activation_columns:
                op.execute(
                    "UPDATE promocode_activations SET created_at = activated_at WHERE created_at IS NULL"
                )
            else:
                op.execute(
                    "UPDATE promocode_activations SET created_at = timezone('UTC', now()) WHERE created_at IS NULL"
                )
            op.alter_column(
                "promocode_activations",
                "created_at",
                nullable=False,
                server_default=sa.text("timezone('UTC', now())"),
            )
        if "updated_at" not in activation_columns:
            op.add_column(
                "promocode_activations",
                sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            )
            op.execute(
                "UPDATE promocode_activations SET updated_at = COALESCE(created_at, timezone('UTC', now())) WHERE updated_at IS NULL"
            )
            op.alter_column(
                "promocode_activations",
                "updated_at",
                nullable=False,
                server_default=sa.text("timezone('UTC', now())"),
            )
        if "promocode_activations_transaction_payment_id_fkey" not in activation_fks:
            op.create_foreign_key(
                "promocode_activations_transaction_payment_id_fkey",
                "promocode_activations",
                "transactions",
                ["transaction_payment_id"],
                ["payment_id"],
                ondelete="SET NULL",
            )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    activation_columns = {column["name"] for column in inspector.get_columns("promocode_activations")}
    activation_fks = {fk["name"] for fk in inspector.get_foreign_keys("promocode_activations")}
    if "promocode_activations_transaction_payment_id_fkey" in activation_fks:
        op.drop_constraint(
            "promocode_activations_transaction_payment_id_fkey",
            "promocode_activations",
            type_="foreignkey",
        )
    if "transaction_payment_id" in activation_columns:
        op.drop_column("promocode_activations", "transaction_payment_id")
    if "updated_at" in activation_columns:
        op.drop_column("promocode_activations", "updated_at")
    if "created_at" in activation_columns:
        op.drop_column("promocode_activations", "created_at")

    transaction_columns = {column["name"] for column in inspector.get_columns("transactions")}
    transaction_fks = {fk["name"] for fk in inspector.get_foreign_keys("transactions")}
    if "transactions_promocode_id_fkey" in transaction_fks:
        op.drop_constraint("transactions_promocode_id_fkey", "transactions", type_="foreignkey")
    if "promocode_id" in transaction_columns:
        op.drop_column("transactions", "promocode_id")

    promocode_columns = {column["name"] for column in inspector.get_columns("promocodes")}
    if "expires_at" in promocode_columns:
        op.drop_column("promocodes", "expires_at")
    if "max_activations_per_user" in promocode_columns:
        op.drop_column("promocodes", "max_activations_per_user")
    if "discount_percent" in promocode_columns:
        op.drop_column("promocodes", "discount_percent")
