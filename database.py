from sqlalchemy import create_engine

# Connexion à la base SQLite (fichier)
engine = create_engine("sqlite:///plateforme_bilingue.db", echo=False)
