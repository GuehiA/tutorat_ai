# services/profil_apprenant_service.py

from datetime import datetime
from models import db, ProfilApprenant


def normaliser_score(score):
    try:
        score = float(score)
    except Exception:
        return 0.0

    if score <= 5:
        return (score / 5) * 100

    return max(0.0, min(score, 100.0))


def determiner_risque(probabilite_difficulte):
    try:
        p = float(probabilite_difficulte)
    except Exception:
        p = 0.5

    if p >= 0.70:
        return "élevé"

    if p >= 0.40:
        return "moyen"

    return "faible"


def determiner_recommandation(maitrise_estimee, probabilite_difficulte):
    try:
        maitrise = float(maitrise_estimee)
    except Exception:
        maitrise = 0.0

    try:
        difficulte = float(probabilite_difficulte)
    except Exception:
        difficulte = 0.5

    if maitrise >= 80 and difficulte < 0.35:
        return "progression"

    if maitrise >= 55:
        return "consolidation"

    return "remediation"


def determiner_tendance(ancienne_maitrise, nouvelle_maitrise):
    try:
        ancienne = float(ancienne_maitrise)
        nouvelle = float(nouvelle_maitrise)
    except Exception:
        return "stable"

    difference = nouvelle - ancienne

    if difference >= 8:
        return "amélioration"

    if difference <= -8:
        return "régression"

    return "stable"


def mettre_a_jour_profil_apprenant(
    user_id,
    lecon_id,
    notion_cible,
    competence_cible=None,
    score=None,
    etoiles=None,
    diagnostic_bayesien=None,
    type_exercice=None,
    niveau_difficulte=None
):
    """
    Met à jour le profil apprenant d'un élève pour une notion donnée.

    Cette fonction est appelée après chaque exercice corrigé.
    Elle ne consomme aucun token.
    """

    if not user_id or not notion_cible:
        return None

    score_normalise = normaliser_score(score if score is not None else etoiles)

    diagnostic_bayesien = diagnostic_bayesien or {}

    probabilite_difficulte = diagnostic_bayesien.get(
        "probabilite_difficulte",
        diagnostic_bayesien.get("pourcentage_difficulte", 50)
    )

    try:
        probabilite_difficulte = float(probabilite_difficulte)
        if probabilite_difficulte > 1:
            probabilite_difficulte = probabilite_difficulte / 100
    except Exception:
        probabilite_difficulte = 0.5

    profil = ProfilApprenant.query.filter_by(
        user_id=user_id,
        lecon_id=lecon_id,
        notion_cible=notion_cible
    ).first()

    if not profil:
        profil = ProfilApprenant(
            user_id=user_id,
            lecon_id=lecon_id,
            notion_cible=notion_cible,
            competence_cible=competence_cible,
            maitrise_estimee=score_normalise,
            probabilite_difficulte=probabilite_difficulte,
            niveau_risque=determiner_risque(probabilite_difficulte),
            nombre_exercices_faits=0,
            nombre_reussites=0,
            nombre_erreurs=0,
            historique_resume=[]
        )
        db.session.add(profil)

    ancienne_maitrise = profil.maitrise_estimee or 0.0

    # Mise à jour progressive : 70 % ancien profil, 30 % nouvelle performance
    nouvelle_maitrise = (ancienne_maitrise * 0.70) + (score_normalise * 0.30)

    profil.maitrise_estimee = round(nouvelle_maitrise, 2)
    profil.probabilite_difficulte = round(probabilite_difficulte, 3)
    profil.niveau_risque = determiner_risque(probabilite_difficulte)

    profil.nombre_exercices_faits = (profil.nombre_exercices_faits or 0) + 1

    if score_normalise >= 60:
        profil.nombre_reussites = (profil.nombre_reussites or 0) + 1
    else:
        profil.nombre_erreurs = (profil.nombre_erreurs or 0) + 1

    profil.dernier_score = round(score_normalise, 2)
    profil.dernier_type_exercice = type_exercice
    profil.derniere_difficulte = niveau_difficulte

    if competence_cible:
        profil.competence_cible = competence_cible

    profil.tendance = determiner_tendance(
        ancienne_maitrise,
        nouvelle_maitrise
    )

    profil.recommandation = determiner_recommandation(
        profil.maitrise_estimee,
        profil.probabilite_difficulte
    )

    historique = profil.historique_resume or []

    historique.append({
        "date": datetime.utcnow().isoformat(),
        "score": round(score_normalise, 2),
        "maitrise_estimee": profil.maitrise_estimee,
        "probabilite_difficulte": profil.probabilite_difficulte,
        "niveau_risque": profil.niveau_risque,
        "type_exercice": type_exercice,
        "niveau_difficulte": niveau_difficulte,
        "recommandation": profil.recommandation
    })

    # On garde seulement les 10 dernières traces pour éviter de grossir inutilement
    profil.historique_resume = historique[-10:]

    profil.updated_at = datetime.utcnow()

    db.session.commit()

    return profil