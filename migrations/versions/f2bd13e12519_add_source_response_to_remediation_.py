"""add source response to remediation suggestion

Revision ID: f2bd13e12519
Revises: d5baf2a4f65b
Create Date: 2026-09-05 19:51:59.633165
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f2bd13e12519"
down_revision = "d5baf2a4f65b"
branch_labels = None
depends_on = None


def upgrade():
    # Ajouter uniquement la référence vers la StudentResponse
    # qui a déclenché la remédiation.
    with op.batch_alter_table(
        "remediation_suggestion",
        schema=None
    ) as batch_op:

        batch_op.add_column(
            sa.Column(
                "source_response_id",
                sa.Integer(),
                nullable=True
            )
        )

        batch_op.create_index(
            batch_op.f(
                "ix_remediation_suggestion_source_response_id"
            ),
            ["source_response_id"],
            unique=False
        )

        batch_op.create_foreign_key(
            "fk_remediation_suggestion_source_response_id",
            "student_responses",
            ["source_response_id"],
            ["id"],
            ondelete="SET NULL"
        )


def downgrade():
    with op.batch_alter_table(
        "remediation_suggestion",
        schema=None
    ) as batch_op:

        batch_op.drop_constraint(
            "fk_remediation_suggestion_source_response_id",
            type_="foreignkey"
        )

        batch_op.drop_index(
            batch_op.f(
                "ix_remediation_suggestion_source_response_id"
            )
        )

        batch_op.drop_column(
            "source_response_id"
        )