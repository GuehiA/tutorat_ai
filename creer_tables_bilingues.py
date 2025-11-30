# fichier : creer_tables_bilingues.py
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, ForeignKey, Text

engine = create_engine('sqlite:///plateforme_bilingue.db')
metadata = MetaData()

niveaux = Table('niveaux', metadata,
    Column('id', Integer, primary_key=True),
    Column('nom', String(50), nullable=False)
)

matieres = Table('matieres', metadata,
    Column('id', Integer, primary_key=True),
    Column('nom', String(100), nullable=False),
    Column('niveau_id', Integer, ForeignKey('niveaux.id'))
)

unites = Table('unites', metadata,
    Column('id', Integer, primary_key=True),
    Column('nom', String(100), nullable=False),
    Column('matiere_id', Integer, ForeignKey('matieres.id'))
)

lecons = Table('lecons', metadata,
    Column('id', Integer, primary_key=True),
    Column('titre_fr', String(255), nullable=False),
    Column('titre_en', String(255), nullable=False),
    Column('objectif_fr', Text),
    Column('objectif_en', Text),
    Column('unite_id', Integer, ForeignKey('unites.id'))
)

exercices = Table('exercices', metadata,
    Column('id', Integer, primary_key=True),
    Column('lecon_id', Integer, ForeignKey('lecons.id')),
    Column('question_fr', Text),
    Column('question_en', Text),
    Column('options_fr', Text),
    Column('options_en', Text),
    Column('reponse_fr', Text),
    Column('reponse_en', Text),
    Column('explication_fr', Text),
    Column('explication_en', Text),
    Column('temps', Integer)
)

tests_sommatifs = Table('tests_sommatifs', metadata,
    Column('id', Integer, primary_key=True),
    Column('lecon_id', Integer, ForeignKey('lecons.id')),
    Column('question_fr', Text),
    Column('question_en', Text),
    Column('options_fr', Text),
    Column('options_en', Text),
    Column('reponse_fr', Text),
    Column('reponse_en', Text),
    Column('explication_fr', Text),
    Column('explication_en', Text),
    Column('temps', Integer)
)

metadata.create_all(engine)
print("✅ Base de données bilingue créée avec succès.")
