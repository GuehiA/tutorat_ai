from sqlalchemy import create_engine, inspect
from sqlalchemy.sql import text

engine = create_engine('sqlite:///plateforme_bilingue.db')
inspector = inspect(engine)

tables_to_keep = {
    'user', 'enseignant', 'parent', 'parent_eleve',
    'student_response', 'remediation', 'admin', 'session'
}

with engine.connect() as conn:
    for table in inspector.get_table_names():
        if table not in tables_to_keep:
            conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
            print(f"✅ Table supprimée : {table}")
