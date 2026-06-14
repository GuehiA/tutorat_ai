# services/adaptive_exercise_service.py

from sqlalchemy import and_, not_


def normaliser_niveau_difficulte(niveau):
    """
    Normalise les valeurs de difficulté.
    Valeurs attendues : facile, moyen, difficile
    """
    if not niveau:
        return "moyen"

    niveau = str(niveau).strip().lower()

    correspondances = {
        "facile": "facile",
        "simple": "facile",
        "débutant": "facile",
        "debutant": "facile",

        "moyen": "moyen",
        "intermediaire": "moyen",
        "intermédiaire": "moyen",
        "standard": "moyen",

        "difficile": "difficile",
        "avance": "difficile",
        "avancé": "difficile",
        "complexe": "difficile",
        "expert": "difficile",
    }

    return correspondances.get(niveau, "moyen")


def niveau_plus_facile(niveau):
    niveau = normaliser_niveau_difficulte(niveau)

    if niveau == "difficile":
        return "moyen"

    if niveau == "moyen":
        return "facile"

    return "facile"


def niveau_plus_difficile(niveau):
    niveau = normaliser_niveau_difficulte(niveau)

    if niveau == "facile":
        return "moyen"

    if niveau == "moyen":
        return "difficile"

    return "difficile"


def determiner_strategie_adaptative(
    etoiles=None,
    score=None,
    diagnostic_bayesien=None,
    verification_calcul=None
):
    """
    Détermine la stratégie pédagogique après une réponse.

    Retourne :
    - remediation
    - consolidation
    - progression
    """

    # 1. Priorité à la vérification mathématique locale si disponible
    if isinstance(verification_calcul, dict):
        is_correct = verification_calcul.get("is_correct")

        if is_correct is True:
            return "progression"

        if is_correct is False:
            return "remediation"

    # 2. Utiliser le score si disponible
    if score is not None:
        try:
            score = float(score)

            if score >= 80:
                return "progression"

            if score >= 50:
                return "consolidation"

            return "remediation"

        except Exception:
            pass

    # 3. Utiliser les étoiles si disponibles
    if etoiles is not None:
        try:
            etoiles = int(etoiles)

            if etoiles >= 4:
                return "progression"

            if etoiles >= 2:
                return "consolidation"

            return "remediation"

        except Exception:
            pass

    # 4. Utiliser le diagnostic bayésien
    if isinstance(diagnostic_bayesien, dict):
        niveau_risque = diagnostic_bayesien.get("niveau_risque")

        if niveau_risque == "élevé":
            return "remediation"

        if niveau_risque == "moyen":
            return "consolidation"

        if niveau_risque == "faible":
            return "progression"

    # Stratégie par défaut
    return "consolidation"


def construire_requete_base(
    db,
    Exercice,
    StudentResponse,
    eleve_id,
    lecon_id,
    exclure_exercice_id=None
):
    """
    Construit la requête de base :
    - même leçon ;
    - exercice pas encore fait par l'élève ;
    - exclure l'exercice actuel.
    """

    exercices_deja_faits = (
        db.session.query(StudentResponse.exercice_id)
        .filter(StudentResponse.user_id == eleve_id)
        .filter(StudentResponse.exercice_id.isnot(None))
        .subquery()
    )

    query = (
        Exercice.query
        .filter(Exercice.lecon_id == lecon_id)
        .filter(~Exercice.id.in_(exercices_deja_faits))
    )

    if exclure_exercice_id:
        query = query.filter(Exercice.id != exclure_exercice_id)

    return query


def chercher_exercice(
    query,
    notion_cible=None,
    niveau_difficulte=None,
    types_exercice=None
):
    """
    Cherche un exercice selon notion, niveau et type.
    """

    q = query

    if notion_cible:
        q = q.filter_by(notion_cible=notion_cible)

    if niveau_difficulte:
        q = q.filter_by(niveau_difficulte=niveau_difficulte)

    if types_exercice:
        q = q.filter(q.model.type_exercice.in_(types_exercice))

    return (
        q.order_by(
            q.model.ordre_progression.asc(),
            q.model.id.asc()
        )
        .first()
    )


def choisir_prochain_exercice_adaptatif(
    db,
    Exercice,
    StudentResponse,
    eleve_id,
    lecon_id,
    exercice_actuel,
    etoiles=None,
    score=None,
    diagnostic_bayesien=None,
    verification_calcul=None
):
    """
    Choisit le prochain exercice à proposer à l'élève.

    Retourne un dictionnaire :
    {
        "exercice": exercice ou None,
        "strategie": "...",
        "raison": "...",
        "niveau_cible": "...",
        "notion_cible": "..."
    }
    """

    if not exercice_actuel:
        return {
            "exercice": None,
            "strategie": "erreur",
            "raison": "Aucun exercice actuel fourni.",
            "niveau_cible": None,
            "notion_cible": None
        }

    strategie = determiner_strategie_adaptative(
        etoiles=etoiles,
        score=score,
        diagnostic_bayesien=diagnostic_bayesien,
        verification_calcul=verification_calcul
    )

    notion_cible = exercice_actuel.notion_cible
    niveau_actuel = normaliser_niveau_difficulte(exercice_actuel.niveau_difficulte)

    if strategie == "progression":
        niveau_cible = niveau_plus_difficile(niveau_actuel)
        types_cibles = ["application", "consolidation", "defi"]

    elif strategie == "remediation":
        niveau_cible = niveau_plus_facile(niveau_actuel)
        types_cibles = ["remediation", "rappel", "application"]

    else:
        niveau_cible = niveau_actuel
        types_cibles = ["consolidation", "application", "rappel"]

    query_base = construire_requete_base(
        db=db,
        Exercice=Exercice,
        StudentResponse=StudentResponse,
        eleve_id=eleve_id,
        lecon_id=lecon_id,
        exclure_exercice_id=exercice_actuel.id
    )

    # 1. Chercher même notion + niveau cible + types ciblés
    exercice = chercher_exercice(
        query=query_base,
        notion_cible=notion_cible,
        niveau_difficulte=niveau_cible,
        types_exercice=types_cibles
    )

    if exercice:
        return {
            "exercice": exercice,
            "strategie": strategie,
            "raison": "Même notion, niveau adapté et type pédagogique ciblé.",
            "niveau_cible": niveau_cible,
            "notion_cible": notion_cible
        }

    # 2. Chercher même notion + niveau cible, peu importe le type
    exercice = chercher_exercice(
        query=query_base,
        notion_cible=notion_cible,
        niveau_difficulte=niveau_cible,
        types_exercice=None
    )

    if exercice:
        return {
            "exercice": exercice,
            "strategie": strategie,
            "raison": "Même notion et niveau adapté.",
            "niveau_cible": niveau_cible,
            "notion_cible": notion_cible
        }

    # 3. Chercher même notion, peu importe niveau/type
    exercice = chercher_exercice(
        query=query_base,
        notion_cible=notion_cible,
        niveau_difficulte=None,
        types_exercice=None
    )

    if exercice:
        return {
            "exercice": exercice,
            "strategie": strategie,
            "raison": "Même notion, autre niveau disponible.",
            "niveau_cible": niveau_cible,
            "notion_cible": notion_cible
        }

    # 4. Chercher même niveau cible, autre notion
    exercice = chercher_exercice(
        query=query_base,
        notion_cible=None,
        niveau_difficulte=niveau_cible,
        types_exercice=types_cibles
    )

    if exercice:
        return {
            "exercice": exercice,
            "strategie": strategie,
            "raison": "Autre notion, mais niveau et type adaptés.",
            "niveau_cible": niveau_cible,
            "notion_cible": notion_cible
        }

    # 5. Dernier fallback : prochain exercice non fait dans la leçon
    exercice = (
        query_base
        .order_by(
            Exercice.ordre_progression.asc(),
            Exercice.id.asc()
        )
        .first()
    )

    if exercice:
        return {
            "exercice": exercice,
            "strategie": strategie,
            "raison": "Fallback : prochain exercice non fait dans la leçon.",
            "niveau_cible": niveau_cible,
            "notion_cible": notion_cible
        }

    # 6. Aucun exercice disponible
    return {
        "exercice": None,
        "strategie": "fin_sequence",
        "raison": "Aucun autre exercice disponible pour cette leçon.",
        "niveau_cible": niveau_cible,
        "notion_cible": notion_cible
    }


def choisir_premier_exercice_adaptatif(Exercice, lecon_id):
    """
    Choisit le premier exercice d'une leçon.
    Priorité :
    - ordre_progression ;
    - difficulté facile ;
    - id.
    """

    exercice = (
        Exercice.query
        .filter(Exercice.lecon_id == lecon_id)
        .order_by(
            Exercice.ordre_progression.asc(),
            Exercice.niveau_difficulte.asc(),
            Exercice.id.asc()
        )
        .first()
    )

    return exercice