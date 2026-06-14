# creer_table_diagnostics_bayesiens.py

import os
import sys
import psycopg2
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def get_database_url():
    database_url = (
        os.getenv("RENDER_POSTGRES_URL")
        or os.getenv("DATABASE_URL")
        or os.getenv("POSTGRES_URL")
    )

    if not database_url:
        print("❌ ERREUR : aucune URL PostgreSQL trouvée.")
        print("Vérifie RENDER_POSTGRES_URL ou DATABASE_URL.")
        sys.exit(1)

    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    return database_url


def main():
    database_url = get_database_url()

    print("🔗 Connexion à PostgreSQL...")
    conn = psycopg2.connect(database_url)

    try:
        cur = conn.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS diagnostics_bayesiens (
            id SERIAL PRIMARY KEY,

            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            exercice_id INTEGER NULL REFERENCES exercices(id) ON DELETE SET NULL,
            lecon_id INTEGER NULL REFERENCES lecons(id) ON DELETE SET NULL,

            matiere VARCHAR(100),

            probabilite_difficulte DOUBLE PRECISION,
            pourcentage_difficulte DOUBLE PRECISION,
            niveau_risque VARCHAR(50),

            maitrise_cours VARCHAR(50),
            erreurs VARCHAR(50),
            temps_reponse VARCHAR(50),

            verification_calcul JSONB,
            recommandation TEXT,
            diagnostic_complet JSONB,

            source VARCHAR(50) DEFAULT 'naima',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_diagnostics_bayesiens_user_id
        ON diagnostics_bayesiens(user_id);
        """)

        cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_diagnostics_bayesiens_risque
        ON diagnostics_bayesiens(niveau_risque);
        """)

        cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_diagnostics_bayesiens_created_at
        ON diagnostics_bayesiens(created_at DESC);
        """)

        conn.commit()

        print("✅ Table diagnostics_bayesiens créée ou déjà existante.")
        print("✅ Index créés ou déjà existants.")

    except Exception as e:
        conn.rollback()
        print("❌ Erreur pendant la création de la table.")
        print(e)
        sys.exit(1)

    finally:
        conn.close()
        print("🔒 Connexion fermée.")


if __name__ == "__main__":
    main()