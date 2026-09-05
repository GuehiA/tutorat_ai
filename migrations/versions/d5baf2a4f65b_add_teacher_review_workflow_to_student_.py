"""add teacher review workflow to student responses

Revision ID: d5baf2a4f65b
Revises: d63441fb4d3c
Create Date: 2026-09-05 13:45:55.027201

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d5baf2a4f65b"
down_revision = "d63441fb4d3c"
branch_labels = None
depends_on = None


def upgrade():
    """
    Ajoute uniquement le workflow de révision humaine
    aux réponses des élèves.

    IMPORTANT :
    cette migration ne modifie volontairement :

    - aucun champ JSON / JSONB ;
    - aucun index de diagnostics_bayesiens ;
    - aucune colonne de users ;
    - aucune colonne de traces_apprentissage ;
    - aucune clé étrangère existante exercice_id.

    Elle ajoute seulement les informations nécessaires
    à la révision d'une réponse par l'enseignant suiveur.
    """

    # ============================================================
    # COLONNES DE RÉVISION ENSEIGNANT
    # ============================================================

    with op.batch_alter_table(
        "student_responses",
        schema=None
    ) as batch_op:

        # --------------------------------------------------------
        # Statut de révision
        # --------------------------------------------------------
        #
        # server_default est nécessaire pour les lignes existantes.
        #
        # Les anciennes réponses deviennent :
        #
        #     not_required
        #
        # Elles ne sont donc pas automatiquement placées dans
        # la file de correction enseignant.
        # --------------------------------------------------------

        batch_op.add_column(
            sa.Column(
                "review_status",
                sa.String(length=30),
                nullable=False,
                server_default="not_required"
            )
        )

        # --------------------------------------------------------
        # Évaluation humaine
        # --------------------------------------------------------

        batch_op.add_column(
            sa.Column(
                "teacher_score",
                sa.Float(),
                nullable=True
            )
        )

        batch_op.add_column(
            sa.Column(
                "teacher_etoiles",
                sa.Integer(),
                nullable=True
            )
        )

        batch_op.add_column(
            sa.Column(
                "teacher_feedback",
                sa.Text(),
                nullable=True
            )
        )

        # --------------------------------------------------------
        # Enseignant ayant effectué la révision
        # --------------------------------------------------------

        batch_op.add_column(
            sa.Column(
                "reviewed_by",
                sa.Integer(),
                nullable=True
            )
        )

        # --------------------------------------------------------
        # Date de révision
        # --------------------------------------------------------

        batch_op.add_column(
            sa.Column(
                "reviewed_at",
                sa.DateTime(),
                nullable=True
            )
        )

    # ============================================================
    # INDEX
    # ============================================================

    op.create_index(
        "ix_student_responses_review_status",
        "student_responses",
        ["review_status"],
        unique=False
    )

    op.create_index(
        "ix_student_responses_reviewed_by",
        "student_responses",
        ["reviewed_by"],
        unique=False
    )

    # ============================================================
    # CLÉ ÉTRANGÈRE VERS L'ENSEIGNANT
    # ============================================================

    op.create_foreign_key(
        "fk_student_responses_reviewed_by_users",
        "student_responses",
        "users",
        ["reviewed_by"],
        ["id"],
        ondelete="SET NULL"
    )


def downgrade():
    """
    Supprime uniquement les éléments ajoutés par cette migration.

    Aucune autre structure existante n'est modifiée.
    """

    # ============================================================
    # CLÉ ÉTRANGÈRE
    # ============================================================

    op.drop_constraint(
        "fk_student_responses_reviewed_by_users",
        "student_responses",
        type_="foreignkey"
    )

    # ============================================================
    # INDEX
    # ============================================================

    op.drop_index(
        "ix_student_responses_reviewed_by",
        table_name="student_responses"
    )

    op.drop_index(
        "ix_student_responses_review_status",
        table_name="student_responses"
    )

    # ============================================================
    # COLONNES
    # ============================================================

    with op.batch_alter_table(
        "student_responses",
        schema=None
    ) as batch_op:

        batch_op.drop_column(
            "reviewed_at"
        )

        batch_op.drop_column(
            "reviewed_by"
        )

        batch_op.drop_column(
            "teacher_feedback"
        )

        batch_op.drop_column(
            "teacher_etoiles"
        )

        batch_op.drop_column(
            "teacher_score"
        )

        batch_op.drop_column(
            "review_status"
        )