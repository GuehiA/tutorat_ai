# services/recommandations.py

from models import Exercice
from sqlalchemy.sql.expression import func


def recommander_prochaine_action(diagnostic):
    risque = diagnostic.get("niveau_risque")

    if risque == "élevé":
        return {
            "type": "remediation",
            "message": "Proposer une explication guidée et un exercice plus simple.",
            "mode_chatbot": "socratique_guidé"
        }

    if risque == "moyen":
        return {
            "type": "consolidation",
            "message": "Proposer un exercice de consolidation avec une question socratique.",
            "mode_chatbot": "socratique_normal"
        }

    if risque == "faible":
        return {
            "type": "progression",
            "message": "Proposer un exercice plus difficile ou passer à la suite.",
            "mode_chatbot": "socratique_avancé"
        }

    return {
        "type": "observation",
        "message": "Demander à l’élève de faire quelques exercices pour établir un diagnostic.",
        "mode_chatbot": "socratique_normal"
    }


def choisir_exercice_pour_lecon(lecon_id):
    return (
        Exercice.query
        .filter_by(lecon_id=lecon_id)
        .order_by(func.random())
        .first()
    )