# ajouter_champs_diagnostic_postgre.py

import os
import sys
import psycopg2
from dotenv import load_dotenv


load_dotenv()


def get_database_url():
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        print("❌ ERREUR : DATABASE_URL est introuvable dans ton fichier .env")
        print("Ajoute ton URL PostgreSQL Render dans .env avant d'exécuter ce script.")
        sys.exit(1)

    # Certaines anciennes configs Render utilisent postgres://
    # psycopg2 préfère postgresql://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    return database_url


def colonne_existe(cursor, table_name, column_name):
    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = %s
            AND column_name = %s
        );
        """,
        (table_name, column_name)
    )

    return cursor.fetchone()[0]


def ajouter_colonne_si_absente(cursor, table_name, column_name, column_type):
    if colonne_existe(cursor, table_name, column_name):
        print(f"ℹ️ La colonne {column_name} existe déjà dans {table_name}.")
        return

    sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type};"
    cursor.execute(sql)
    print(f"✅ Colonne ajoutée : {column_name} ({column_type})")


def main():
    database_url = get_database_url()

    print("🔗 Connexion à PostgreSQL...")
    conn = psycopg2.connect(database_url)

    try:
        cursor = conn.cursor()

        table_name = "student_responses"

        print(f"📌 Vérification de la table : {table_name}")

        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_name = %s
            );
            """,
            (table_name,)
        )

        table_exists = cursor.fetchone()[0]

        if not table_exists:
            print(f"❌ ERREUR : la table {table_name} n'existe pas dans PostgreSQL.")
            conn.rollback()
            sys.exit(1)

        print("✅ Table trouvée.")

        ajouter_colonne_si_absente(cursor, table_name, "score", "DOUBLE PRECISION")
        ajouter_colonne_si_absente(cursor, table_name, "type_erreur", "VARCHAR(100)")
        ajouter_colonne_si_absente(cursor, table_name, "niveau_difficulte", "VARCHAR(50)")
        ajouter_colonne_si_absente(cursor, table_name, "temps_passe", "INTEGER")
        ajouter_colonne_si_absente(cursor, table_name, "aide_utilisee", "BOOLEAN DEFAULT FALSE")
        ajouter_colonne_si_absente(cursor, table_name, "feedback_ia_structure", "JSONB")

        conn.commit()

        print("\n🎉 Mise à jour terminée avec succès.")
        print("Les champs du diagnostic bayésien ont été ajoutés à student_responses.")

    except Exception as e:
        conn.rollback()
        print("\n❌ ERREUR pendant la mise à jour.")
        print(e)
        sys.exit(1)

    finally:
        conn.close()
        print("🔒 Connexion fermée.")


if __name__ == "__main__":
    main()