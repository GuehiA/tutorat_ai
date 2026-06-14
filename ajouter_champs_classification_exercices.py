from app import app
from models import db
from sqlalchemy import text


def colonne_existe_sqlite(conn, table, colonne):
    result = conn.execute(text(f"PRAGMA table_info({table})"))
    colonnes = [row[1] for row in result.fetchall()]
    return colonne in colonnes


def colonne_existe_postgres(conn, table, colonne):
    result = conn.execute(text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = :table
        AND column_name = :colonne
    """), {
        "table": table,
        "colonne": colonne
    })

    return result.fetchone() is not None


def ajouter_colonne_si_absente(conn, engine_name, table, colonne, type_sql):
    if engine_name == "sqlite":
        existe = colonne_existe_sqlite(conn, table, colonne)
    else:
        existe = colonne_existe_postgres(conn, table, colonne)

    if existe:
        print(f"ℹ️ Colonne déjà existante : {colonne}")
        return

    conn.execute(text(
        f"ALTER TABLE {table} ADD COLUMN {colonne} {type_sql}"
    ))

    print(f"✅ Colonne ajoutée : {colonne}")


with app.app_context():
    engine_name = db.engine.name
    print(f"🔌 Base détectée : {engine_name}")

    table = "exercices"

    with db.engine.begin() as conn:
        if engine_name == "sqlite":
            json_type = "JSON"
            bool_type = "BOOLEAN"
            float_type = "FLOAT"
        else:
            json_type = "JSONB"
            bool_type = "BOOLEAN"
            float_type = "DOUBLE PRECISION"

        ajouter_colonne_si_absente(
            conn, engine_name, table,
            "notion_cible", "VARCHAR(255)"
        )

        ajouter_colonne_si_absente(
            conn, engine_name, table,
            "competence_cible", "VARCHAR(255)"
        )

        ajouter_colonne_si_absente(
            conn, engine_name, table,
            "niveau_difficulte", "VARCHAR(50)"
        )

        ajouter_colonne_si_absente(
            conn, engine_name, table,
            "type_exercice", "VARCHAR(100)"
        )

        ajouter_colonne_si_absente(
            conn, engine_name, table,
            "ordre_progression", "INTEGER"
        )

        ajouter_colonne_si_absente(
            conn, engine_name, table,
            "prerequis", json_type
        )

        ajouter_colonne_si_absente(
            conn, engine_name, table,
            "classification_ia", json_type
        )

        ajouter_colonne_si_absente(
            conn, engine_name, table,
            "classification_validee", bool_type
        )

        ajouter_colonne_si_absente(
            conn, engine_name, table,
            "confiance_classification", float_type
        )

    print("✅ Migration terminée avec succès.")