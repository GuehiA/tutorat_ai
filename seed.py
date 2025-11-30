from models import db, User, Exercise, Parent, ParentEleve
from app import app

with app.app_context():
    # 🔄 Réinitialise la base de données
    db.drop_all()
    db.create_all()

    # 👨‍👧 Création d'un parent
    parent = Parent(nom_complet="Mme Dupont", email="parent1@example.com")
    db.session.add(parent)
    db.session.commit()

    # 👧 Création d'un élève
    eleve = User(
        username="student_001",
        nom_complet="Alice Dupont",
        email="alice@example.com",
        niveau="2nde",
        role="élève"
    )
    db.session.add(eleve)
    db.session.commit()

    # 🔗 Lier l'élève au parent
    lien = ParentEleve(parent_id=parent.id, eleve_id=eleve.id)
    db.session.add(lien)

    # 📘 Exercices avec leçons
    exercices = [
        Exercise(niveau="2nde", theme="algèbre", lecon="équations", enonce="Résous : 2x + 3 = 7", reponse_correcte="x = 2"),
        Exercise(niveau="2nde", theme="algèbre", lecon="factorisation", enonce="Factorise : x² - 9", reponse_correcte="(x - 3)(x + 3)"),
        Exercise(niveau="2nde", theme="géométrie", lecon="triangles", enonce="Calcule l'aire d'un triangle de base 4cm et hauteur 5cm", reponse_correcte="10 cm²"),
        Exercise(niveau="1ère", theme="analyse", lecon="fonctions", enonce="Détermine l’image de 2 par f(x) = x² - 1", reponse_correcte="3"),
        Exercise(niveau="Terminale", theme="analyse", lecon="dérivées", enonce="Calcule f'(x) si f(x) = 3x²", reponse_correcte="6x"),
    ]

    db.session.add_all(exercices)
    db.session.commit()

    print("✅ Données initiales insérées avec le champ 'lecon'.")
