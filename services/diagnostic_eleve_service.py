# services/diagnostic_eleve_service.py

from models import StudentResponse
from services.bayesian_diagnostic import diagnostiquer_difficulte


def convertir_etoiles_en_maitrise(moyenne_etoiles):
    if moyenne_etoiles is None:
        return "moyenne"

    if moyenne_etoiles < 2.5:
        return "faible"
    elif moyenne_etoiles < 4:
        return "moyenne"
    return "bonne"


def convertir_echecs_en_erreurs(nombre_reponses, nombre_echecs):
    if nombre_reponses == 0:
        return "peu"

    taux_echec = nombre_echecs / nombre_reponses

    if taux_echec >= 0.50:
        return "beaucoup"

    return "peu"


def diagnostiquer_eleve_sur_lecon(eleve_id, lecon_id):
    """
    Analyse les réponses d'un élève sur une leçon donnée.
    Utilise les exercices liés à cette leçon.
    """

    reponses = (
        StudentResponse.query
        .join(StudentResponse.exercice)
        .filter(
            StudentResponse.user_id == eleve_id,
            StudentResponse.exercice.has(lecon_id=lecon_id)
        )
        .all()
    )

    if not reponses:
        return {
            "message": "Aucune réponse trouvée pour cette leçon.",
            "probabilite_difficulte": None,
            "niveau_risque": "inconnu"
        }

    total = len(reponses)

    etoiles_valides = [
        r.etoiles for r in reponses
        if r.etoiles is not None
    ]

    moyenne_etoiles = (
        sum(etoiles_valides) / len(etoiles_valides)
        if etoiles_valides
        else None
    )

    nombre_echecs = sum(
        1 for r in reponses
        if r.etoiles is not None and r.etoiles < 3
    )

    maitrise_cours = convertir_etoiles_en_maitrise(moyenne_etoiles)
    erreurs = convertir_echecs_en_erreurs(total, nombre_echecs)

    # Pour le moment, ton modèle StudentResponse ne contient pas encore temps_passe.
    # Donc on met une valeur neutre.
    temps_reponse = "rapide"

    diagnostic = diagnostiquer_difficulte(
        maitrise_cours=maitrise_cours,
        erreurs=erreurs,
        temps_reponse=temps_reponse
    )

    diagnostic.update({
        "eleve_id": eleve_id,
        "lecon_id": lecon_id,
        "nombre_reponses": total,
        "nombre_echecs": nombre_echecs,
        "moyenne_etoiles": round(moyenne_etoiles, 2) if moyenne_etoiles is not None else None,
        "maitrise_cours": maitrise_cours,
        "erreurs": erreurs,
        "temps_reponse": temps_reponse
    })

    return diagnostic