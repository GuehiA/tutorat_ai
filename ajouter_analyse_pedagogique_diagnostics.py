import os
import sys
import psycopg2
from dotenv import load_dotenv

load_dotenv()


def get_database_url():
    database_url = (
        os.getenv("RENDER_POSTGRES_URL")
        or os.getenv("DATABASE_URL")
        or os.getenv("POSTGRES_URL")
    )

    if not database_url:
        print("❌ Aucune URL PostgreSQL trouvée.")
        sys.exit(1)

    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    return database_url


def main():
    conn = psycopg2.connect(get_database_url())

    try:
        cur = conn.cursor()

        cur.execute("""
        ALTER TABLE diagnostics_bayesiens
        ADD COLUMN IF NOT EXISTS notion_cible VARCHAR(255);
        """)

        cur.execute("""
        ALTER TABLE diagnostics_bayesiens
        ADD COLUMN IF NOT EXISTS notions_maitrisees JSONB;
        """)

        cur.execute("""
        ALTER TABLE diagnostics_bayesiens
        ADD COLUMN IF NOT EXISTS notions_non_maitrisees JSONB;
        """)

        cur.execute("""
        ALTER TABLE diagnostics_bayesiens
        ADD COLUMN IF NOT EXISTS erreurs_probables JSONB;
        """)

        cur.execute("""
        ALTER TABLE diagnostics_bayesiens
        ADD COLUMN IF NOT EXISTS recommandation_enseignant TEXT;
        """)

        cur.execute("""
        ALTER TABLE diagnostics_bayesiens
        ADD COLUMN IF NOT EXISTS exercice_remediation_suggere TEXT;
        """)

        cur.execute("""
        ALTER TABLE diagnostics_bayesiens
        ADD COLUMN IF NOT EXISTS niveau_intervention VARCHAR(50);
        """)

        cur.execute("""
        ALTER TABLE diagnostics_bayesiens
        ADD COLUMN IF NOT EXISTS analyse_pedagogique_ia JSONB;
        """)

        conn.commit()
        print("✅ Colonnes d'analyse pédagogique ajoutées avec succès.")

    except Exception as e:
        conn.rollback()
        print("❌ Erreur :", e)
        sys.exit(1)

    finally:
        conn.close()


if __name__ == "__main__":
    main()