from sqlalchemy import create_engine, MetaData, Table, insert

# Connexion à la base de données
engine = create_engine('sqlite:///plateforme_bilingue.db')
conn = engine.connect()
metadata = MetaData()
metadata.reflect(bind=engine)

# Accès aux tables
niveaux = metadata.tables['niveaux']
matieres = metadata.tables['matieres']
unites = metadata.tables['unites']
lecons = metadata.tables['lecons']
exercices = metadata.tables['exercices']

# Insertion des données
insertions = [
    insert(niveaux).values(nom="6e"),
    insert(niveaux).values(nom="5e"),
    insert(matieres).values(nom="Mathématiques", niveau_id=1),
    insert(unites).values(nom="Statistiques", matiere_id=1),
    insert(lecons).values(
        titre_fr="Lire un graphique",
        titre_en="Reading a chart",
        objectif_fr="Savoir interpréter un graphique simple.",
        objectif_en="Understand how to read a simple chart.",
        unite_id=1
    ),
    insert(exercices).values(
        lecon_id=1,
        question_fr="Quel type de graphique permet de comparer des quantités ?",
        question_en="Which type of chart helps compare quantities?",
        options_fr="['Histogramme', 'Camembert', 'Courbe', 'Carte']",
        options_en="['Bar chart', 'Pie chart', 'Line chart', 'Map']",
        reponse_fr="Histogramme",
        reponse_en="Bar chart",
        explication_fr="L’histogramme permet une comparaison facile des quantités.",
        explication_en="Bar charts make it easy to compare quantities.",
        temps=60
    )
]

for stmt in insertions:
    conn.execute(stmt)

conn.close()
print("Contenu de base inséré avec succès.")
