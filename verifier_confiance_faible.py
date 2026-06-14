from app import app
from models import db, Exercice


with app.app_context():
    exercices = (
        Exercice.query
        .filter(
            Exercice.classification_ia.isnot(None),
            Exercice.confiance_classification < 0.70
        )
        .order_by(Exercice.confiance_classification.asc(), Exercice.id.asc())
        .all()
    )

    print("=" * 80)
    print(f"EXERCICES À CONFIANCE FAIBLE : {len(exercices)}")
    print("=" * 80)

    for ex in exercices:
        print("-" * 80)
        print(f"ID : {ex.id}")
        print(f"Niveau : {ex.niveau}")
        print(f"Thème : {ex.theme}")
        print(f"Question : {(ex.question_fr or '')[:500]}")
        print(f"Réponse : {(ex.reponse_fr or '')[:300]}")
        print(f"Notion : {ex.notion_cible}")
        print(f"Compétence : {ex.competence_cible}")
        print(f"Difficulté : {ex.niveau_difficulte}")
        print(f"Type : {ex.type_exercice}")
        print(f"Ordre : {ex.ordre_progression}")
        print(f"Confiance : {ex.confiance_classification}")
        print(f"Validée : {ex.classification_validee}")
        print(f"Classification IA : {ex.classification_ia}")