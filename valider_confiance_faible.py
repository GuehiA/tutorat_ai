from app import app
from models import db, Exercice


IDS_A_VALIDER = [
    10787,
    12426,
    284,
    303,
    500,
    724,
    847,
    864,
    899,
    912,
    914,
    916,
    1306,
    7713,
    7785,
    8321,
    8335,
    10725,
]


with app.app_context():
    exercices = (
        Exercice.query
        .filter(Exercice.id.in_(IDS_A_VALIDER))
        .all()
    )

    print("=" * 80)
    print(f"Exercices trouvés : {len(exercices)}")
    print("=" * 80)

    for ex in exercices:
        ex.classification_validee = True

        # On ne prétend pas que l'IA était très sûre.
        # On indique plutôt que l'exercice a été revu manuellement.
        if ex.confiance_classification is None or ex.confiance_classification < 0.70:
            ex.confiance_classification = 0.75

        if ex.classification_ia is None:
            ex.classification_ia = {}

        ex.classification_ia["validation_humaine"] = True
        ex.classification_ia["note_validation"] = (
            "Classification vérifiée manuellement après détection d'une confiance faible."
        )

        db.session.add(ex)

        print(f"✅ Exercice {ex.id} validé manuellement")

    db.session.commit()

    print("=" * 80)
    print("✅ Validation manuelle terminée.")