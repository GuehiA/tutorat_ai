from app import app
from models import db, Exercice


def afficher_resume_global():
    total = Exercice.query.count()

    classifies = Exercice.query.filter(
        Exercice.classification_ia.isnot(None)
    ).count()

    non_classifies = Exercice.query.filter(
        Exercice.classification_ia.is_(None)
    ).count()

    valides = Exercice.query.filter_by(
        classification_validee=True
    ).count()

    non_valides = Exercice.query.filter_by(
        classification_validee=False
    ).count()

    faibles_confiances = Exercice.query.filter(
        Exercice.classification_ia.isnot(None),
        Exercice.confiance_classification < 0.7
    ).count()

    print("=" * 80)
    print("RÉSUMÉ GLOBAL")
    print("=" * 80)
    print(f"Total exercices                : {total}")
    print(f"Exercices classifiés           : {classifies}")
    print(f"Exercices non classifiés       : {non_classifies}")
    print(f"Classifications validées       : {valides}")
    print(f"Classifications non validées   : {non_valides}")
    print(f"Confiance faible (< 0.70)      : {faibles_confiances}")


def afficher_repartition_difficulte():
    print("\n" + "=" * 80)
    print("RÉPARTITION PAR DIFFICULTÉ")
    print("=" * 80)

    resultats = (
        db.session.query(
            Exercice.niveau_difficulte,
            db.func.count(Exercice.id)
        )
        .filter(Exercice.classification_ia.isnot(None))
        .group_by(Exercice.niveau_difficulte)
        .order_by(db.func.count(Exercice.id).desc())
        .all()
    )

    for niveau, total in resultats:
        print(f"{niveau or 'Non défini'} : {total}")


def afficher_repartition_type():
    print("\n" + "=" * 80)
    print("RÉPARTITION PAR TYPE D’EXERCICE")
    print("=" * 80)

    resultats = (
        db.session.query(
            Exercice.type_exercice,
            db.func.count(Exercice.id)
        )
        .filter(Exercice.classification_ia.isnot(None))
        .group_by(Exercice.type_exercice)
        .order_by(db.func.count(Exercice.id).desc())
        .all()
    )

    for type_exercice, total in resultats:
        print(f"{type_exercice or 'Non défini'} : {total}")


def afficher_repartition_validation():
    print("\n" + "=" * 80)
    print("RÉPARTITION PAR CONFIANCE")
    print("=" * 80)

    tres_forte = Exercice.query.filter(
        Exercice.classification_ia.isnot(None),
        Exercice.confiance_classification >= 0.9
    ).count()

    forte = Exercice.query.filter(
        Exercice.classification_ia.isnot(None),
        Exercice.confiance_classification >= 0.8,
        Exercice.confiance_classification < 0.9
    ).count()

    acceptable = Exercice.query.filter(
        Exercice.classification_ia.isnot(None),
        Exercice.confiance_classification >= 0.7,
        Exercice.confiance_classification < 0.8
    ).count()

    faible = Exercice.query.filter(
        Exercice.classification_ia.isnot(None),
        Exercice.confiance_classification < 0.7
    ).count()

    print(f"Très forte confiance (>= 0.90) : {tres_forte}")
    print(f"Forte confiance (0.80 - 0.89) : {forte}")
    print(f"Acceptable (0.70 - 0.79)      : {acceptable}")
    print(f"Faible (< 0.70)               : {faible}")


def afficher_notions_detectees(limite=None):
    print("\n" + "=" * 80)
    print("NOTIONS DÉTECTÉES")
    print("=" * 80)

    query = (
        db.session.query(
            Exercice.notion_cible,
            db.func.count(Exercice.id)
        )
        .filter(Exercice.classification_ia.isnot(None))
        .group_by(Exercice.notion_cible)
        .order_by(db.func.count(Exercice.id).desc())
    )

    if limite:
        query = query.limit(limite)

    resultats = query.all()

    for notion, total in resultats:
        print(f"{notion or 'Non définie'} : {total}")


def afficher_notions_rares():
    print("\n" + "=" * 80)
    print("NOTIONS RARES OU ISOLÉES")
    print("=" * 80)

    resultats = (
        db.session.query(
            Exercice.notion_cible,
            db.func.count(Exercice.id)
        )
        .filter(Exercice.classification_ia.isnot(None))
        .group_by(Exercice.notion_cible)
        .having(db.func.count(Exercice.id) == 1)
        .order_by(Exercice.notion_cible.asc())
        .all()
    )

    if not resultats:
        print("Aucune notion isolée.")
        return

    for notion, total in resultats:
        print(f"{notion or 'Non définie'} : {total}")


def afficher_echantillon(limite=5):
    print("\n" + "=" * 80)
    print(f"ÉCHANTILLON DES {limite} PREMIERS EXERCICES CLASSIFIÉS")
    print("=" * 80)

    exercices = (
        Exercice.query
        .filter(Exercice.classification_ia.isnot(None))
        .order_by(Exercice.id.asc())
        .limit(limite)
        .all()
    )

    for ex in exercices:
        print("-" * 80)
        print(f"ID : {ex.id}")
        print(f"Niveau : {ex.niveau}")
        print(f"Thème : {ex.theme}")
        print(f"Question : {(ex.question_fr or '')[:180]}")
        print(f"Notion : {ex.notion_cible}")
        print(f"Compétence : {ex.competence_cible}")
        print(f"Difficulté : {ex.niveau_difficulte}")
        print(f"Type : {ex.type_exercice}")
        print(f"Ordre : {ex.ordre_progression}")
        print(f"Prérequis : {ex.prerequis}")
        print(f"Confiance : {ex.confiance_classification}")
        print(f"Validée : {ex.classification_validee}")


def verifier_exercice_precis(exercice_id):
    ex = db.session.get(Exercice, exercice_id)

    if not ex:
        print(f"Exercice {exercice_id} introuvable.")
        return

    print("\n" + "=" * 80)
    print(f"DÉTAIL EXERCICE {exercice_id}")
    print("=" * 80)
    print(f"Question FR : {ex.question_fr}")
    print(f"Réponse FR : {ex.reponse_fr}")
    print(f"Explication FR : {ex.explication_fr}")
    print("-" * 80)
    print(f"Notion : {ex.notion_cible}")
    print(f"Compétence : {ex.competence_cible}")
    print(f"Difficulté : {ex.niveau_difficulte}")
    print(f"Type : {ex.type_exercice}")
    print(f"Ordre : {ex.ordre_progression}")
    print(f"Prérequis : {ex.prerequis}")
    print(f"Confiance : {ex.confiance_classification}")
    print(f"Validée : {ex.classification_validee}")
    print(f"Classification IA complète : {ex.classification_ia}")


if __name__ == "__main__":
    with app.app_context():
        afficher_resume_global()
        afficher_repartition_difficulte()
        afficher_repartition_type()
        afficher_repartition_validation()
        afficher_notions_detectees()
        afficher_notions_rares()

        # Échantillon réduit pour garder la sortie lisible
        afficher_echantillon(limite=5)

        # Décommente cette ligne seulement si tu veux inspecter un exercice précis
        # verifier_exercice_precis(1)