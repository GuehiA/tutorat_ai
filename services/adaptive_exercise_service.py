# services/adaptive_exercise_service.py

from sqlalchemy import and_, not_


# ============================================================
# 1. OUTILS DE NORMALISATION
# ============================================================

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
        "defi": "difficile",
        "défi": "difficile",
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


def normaliser_score(score):
    """
    Convertit un score en pourcentage.
    Accepte :
    - score sur 5 ;
    - score sur 100.
    """

    if score is None:
        return None

    try:
        score = float(score)
    except Exception:
        return None

    if score <= 5:
        return max(0.0, min((score / 5) * 100, 100.0))

    return max(0.0, min(score, 100.0))


# ============================================================
# 2. LECTURE DU PROFIL APPRENANT
# ============================================================

def charger_profil_apprenant(eleve_id, lecon_id, notion_cible):
    """
    Charge le ProfilApprenant si la table et la classe existent.
    Retourne None si le profil n'existe pas encore ou si le modèle
    n'est pas disponible.
    """

    if not eleve_id or not notion_cible:
        return None

    try:
        from models import ProfilApprenant

        profil = ProfilApprenant.query.filter_by(
            user_id=eleve_id,
            lecon_id=lecon_id,
            notion_cible=notion_cible
        ).first()

        return profil

    except Exception as e:
        print(f"⚠️ ProfilApprenant non disponible dans adaptive_exercise_service : {e}")
        return None


def extraire_infos_profil(profil):
    """
    Transforme un ProfilApprenant en dictionnaire simple.
    """

    if not profil:
        return {
            "existe": False,
            "maitrise_estimee": None,
            "probabilite_difficulte": None,
            "niveau_risque": None,
            "nombre_exercices_faits": 0,
            "nombre_reussites": 0,
            "nombre_erreurs": 0,
            "tendance": None,
            "recommandation": None,
        }

    return {
        "existe": True,
        "maitrise_estimee": profil.maitrise_estimee,
        "probabilite_difficulte": profil.probabilite_difficulte,
        "niveau_risque": profil.niveau_risque,
        "nombre_exercices_faits": profil.nombre_exercices_faits or 0,
        "nombre_reussites": profil.nombre_reussites or 0,
        "nombre_erreurs": profil.nombre_erreurs or 0,
        "tendance": profil.tendance,
        "recommandation": profil.recommandation,
    }


# ============================================================
# 3. STRATÉGIE ADAPTATIVE
# ============================================================

def determiner_strategie_de_base(
    etoiles=None,
    score=None,
    diagnostic_bayesien=None,
    verification_calcul=None
):
    """
    Détermine la stratégie pédagogique uniquement à partir
    de la dernière réponse.

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
    score_normalise = normaliser_score(score)

    if score_normalise is not None:
        if score_normalise >= 80:
            return "progression"

        if score_normalise >= 50:
            return "consolidation"

        return "remediation"

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

    return "consolidation"


def ajuster_strategie_avec_profil(
    strategie_base,
    profil=None,
    score=None,
    diagnostic_bayesien=None,
    verification_calcul=None
):
    """
    Ajuste la stratégie à partir du ProfilApprenant.

    Idée :
    - Si l'élève réussit aujourd'hui mais a encore une faible maîtrise globale,
      on consolide au lieu d'aller trop vite.
    - Si l'élève est en régression, on évite d'augmenter la difficulté trop vite.
    - Si l'élève a une bonne maîtrise globale, on peut progresser.
    """

    infos = extraire_infos_profil(profil)

    if not infos["existe"]:
        return strategie_base, "Stratégie basée sur la dernière réponse, aucun profil apprenant disponible."

    maitrise = infos["maitrise_estimee"]
    proba = infos["probabilite_difficulte"]
    risque = infos["niveau_risque"]
    erreurs = infos["nombre_erreurs"]
    tendance = infos["tendance"]
    recommandation_profil = infos["recommandation"]

    score_normalise = normaliser_score(score)

    try:
        maitrise = float(maitrise) if maitrise is not None else None
    except Exception:
        maitrise = None

    try:
        proba = float(proba) if proba is not None else None
    except Exception:
        proba = None

    # Si erreur mathématique confirmée, on garde remédiation.
    if isinstance(verification_calcul, dict):
        if verification_calcul.get("is_correct") is False:
            return "remediation", "Erreur mathématique détectée : remédiation prioritaire."

    # Profil très fragile : on ne progresse pas trop vite.
    if maitrise is not None and maitrise < 45:
        return "remediation", "Profil apprenant fragile : maîtrise estimée inférieure à 45 %."

    # Risque élevé dans le profil : remédiation ou consolidation.
    if risque == "élevé":
        if strategie_base == "progression":
            return "consolidation", "Le profil indique un risque élevé : progression transformée en consolidation."
        return "remediation", "Le profil indique un risque élevé sur cette notion."

    # Probabilité de difficulté élevée.
    if proba is not None and proba >= 0.70:
        if strategie_base == "progression":
            return "consolidation", "Probabilité de difficulté élevée : on consolide avant de progresser."
        return "remediation", "Probabilité de difficulté élevée : remédiation recommandée."

    # Régression : ne pas augmenter la difficulté immédiatement.
    if tendance == "régression":
        if strategie_base == "progression":
            return "consolidation", "Tendance en régression : consolidation avant progression."
        return strategie_base, "Tendance en régression prise en compte."

    # Beaucoup d'erreurs sur la notion.
    if erreurs is not None and erreurs >= 3:
        if strategie_base == "progression":
            return "consolidation", "Plusieurs erreurs antérieures : consolidation avant progression."
        if strategie_base == "consolidation":
            return "consolidation", "Plusieurs erreurs antérieures : consolidation maintenue."
        return "remediation", "Plusieurs erreurs antérieures : remédiation maintenue."

    # Bonne maîtrise + bonne réponse récente : progression.
    if (
        maitrise is not None
        and maitrise >= 80
        and strategie_base == "progression"
    ):
        return "progression", "Bonne maîtrise globale et bonne réponse récente : progression."

    # Maîtrise moyenne : consolidation.
    if maitrise is not None and 50 <= maitrise < 80:
        if strategie_base == "progression":
            return "consolidation", "Maîtrise moyenne : consolidation avant progression."
        return strategie_base, "Maîtrise moyenne : stratégie de base conservée."

    # Recommandation du profil si disponible
    if recommandation_profil in ["remediation", "consolidation", "progression"]:
        if strategie_base == "progression" and recommandation_profil == "consolidation":
            return "consolidation", "Profil apprenant recommande la consolidation."
        if strategie_base == "consolidation" and recommandation_profil == "remediation":
            return "remediation", "Profil apprenant recommande la remédiation."

    return strategie_base, "Profil apprenant consulté : stratégie de base conservée."


def determiner_strategie_adaptative(
    etoiles=None,
    score=None,
    diagnostic_bayesien=None,
    verification_calcul=None,
    profil_apprenant=None
):
    """
    Détermine la stratégie pédagogique finale.

    Elle combine :
    - dernière réponse ;
    - vérification mathématique ;
    - diagnostic bayésien ;
    - ProfilApprenant.
    """

    strategie_base = determiner_strategie_de_base(
        etoiles=etoiles,
        score=score,
        diagnostic_bayesien=diagnostic_bayesien,
        verification_calcul=verification_calcul
    )

    strategie_finale, raison_profil = ajuster_strategie_avec_profil(
        strategie_base=strategie_base,
        profil=profil_apprenant,
        score=score,
        diagnostic_bayesien=diagnostic_bayesien,
        verification_calcul=verification_calcul
    )

    return strategie_finale, raison_profil


# ============================================================
# 4. REQUÊTES EXERCICES
# ============================================================

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
    Exercice,
    notion_cible=None,
    niveau_difficulte=None,
    types_exercice=None
):
    """
    Cherche un exercice selon notion, niveau et type.
    """

    q = query

    if notion_cible:
        q = q.filter(Exercice.notion_cible == notion_cible)

    if niveau_difficulte:
        q = q.filter(Exercice.niveau_difficulte == niveau_difficulte)

    if types_exercice:
        q = q.filter(Exercice.type_exercice.in_(types_exercice))

    return (
        q.order_by(
            Exercice.ordre_progression.asc(),
            Exercice.id.asc()
        )
        .first()
    )


def definir_cibles_pedagogiques(strategie, niveau_actuel):
    """
    Détermine le niveau et les types d'exercices ciblés.
    """

    niveau_actuel = normaliser_niveau_difficulte(niveau_actuel)

    if strategie == "progression":
        return {
            "niveau_cible": niveau_plus_difficile(niveau_actuel),
            "types_cibles": ["application", "consolidation", "defi", "défi"]
        }

    if strategie == "remediation":
        return {
            "niveau_cible": niveau_plus_facile(niveau_actuel),
            "types_cibles": ["remediation", "rappel", "application"]
        }

    return {
        "niveau_cible": niveau_actuel,
        "types_cibles": ["consolidation", "application", "rappel"]
    }


# ============================================================
# 5. CHOIX DU PROCHAIN EXERCICE
# ============================================================

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
    verification_calcul=None,
    profil_apprenant=None
):
    """
    Choisit le prochain exercice à proposer à l'élève.

    Retourne un dictionnaire :
    {
        "exercice": exercice ou None,
        "strategie": "...",
        "raison": "...",
        "niveau_cible": "...",
        "notion_cible": "...",
        "profil_apprenant": {...}
    }
    """

    if not exercice_actuel:
        return {
            "exercice": None,
            "strategie": "erreur",
            "raison": "Aucun exercice actuel fourni.",
            "niveau_cible": None,
            "notion_cible": None,
            "profil_apprenant": {}
        }

    notion_cible = exercice_actuel.notion_cible
    niveau_actuel = normaliser_niveau_difficulte(exercice_actuel.niveau_difficulte)

    profil = profil_apprenant

    if profil is None:
        profil = charger_profil_apprenant(
            eleve_id=eleve_id,
            lecon_id=lecon_id,
            notion_cible=notion_cible
        )

    infos_profil = extraire_infos_profil(profil)

    strategie, raison_profil = determiner_strategie_adaptative(
        etoiles=etoiles,
        score=score,
        diagnostic_bayesien=diagnostic_bayesien,
        verification_calcul=verification_calcul,
        profil_apprenant=profil
    )

    cibles = definir_cibles_pedagogiques(
        strategie=strategie,
        niveau_actuel=niveau_actuel
    )

    niveau_cible = cibles["niveau_cible"]
    types_cibles = cibles["types_cibles"]

    query_base = construire_requete_base(
        db=db,
        Exercice=Exercice,
        StudentResponse=StudentResponse,
        eleve_id=eleve_id,
        lecon_id=lecon_id,
        exclure_exercice_id=exercice_actuel.id
    )

    # Charger les exercices candidats une seule fois.
    # no_autoflush évite une écriture prématurée du profil.
    with db.session.no_autoflush:
        candidats = (
            query_base
            .order_by(
                Exercice.ordre_progression.asc(),
                Exercice.id.asc()
            )
            .all()
        )

    def prendre_candidat(notion=None, niveau=None, types=None):
        for candidat in candidats:
            if notion is not None and candidat.notion_cible != notion:
                continue
            if niveau is not None and candidat.niveau_difficulte != niveau:
                continue
            if types and candidat.type_exercice not in types:
                continue
            return candidat
        return None

    # ------------------------------------------------------------
    # 1. Même notion + niveau cible + type ciblé
    # ------------------------------------------------------------

    exercice = prendre_candidat(
        notion=notion_cible,
        niveau=niveau_cible,
        types=types_cibles
    )

    if exercice:
        return {
            "exercice": exercice,
            "strategie": strategie,
            "raison": f"{raison_profil} Même notion, niveau adapté et type pédagogique ciblé.",
            "niveau_cible": niveau_cible,
            "notion_cible": notion_cible,
            "profil_apprenant": infos_profil
        }

    # ------------------------------------------------------------
    # 2. Même notion + niveau cible, peu importe le type
    # ------------------------------------------------------------

    exercice = prendre_candidat(
        notion=notion_cible,
        niveau=niveau_cible,
        types=None
    )

    if exercice:
        return {
            "exercice": exercice,
            "strategie": strategie,
            "raison": f"{raison_profil} Même notion et niveau adapté.",
            "niveau_cible": niveau_cible,
            "notion_cible": notion_cible,
            "profil_apprenant": infos_profil
        }

    # ------------------------------------------------------------
    # 3. Même notion, peu importe niveau/type
    # ------------------------------------------------------------

    exercice = prendre_candidat(
        notion=notion_cible,
        niveau=None,
        types=None
    )

    if exercice:
        return {
            "exercice": exercice,
            "strategie": strategie,
            "raison": f"{raison_profil} Même notion, autre niveau disponible.",
            "niveau_cible": niveau_cible,
            "notion_cible": notion_cible,
            "profil_apprenant": infos_profil
        }

    # ------------------------------------------------------------
    # 4. Même niveau cible + type ciblé, autre notion
    # ------------------------------------------------------------

    exercice = prendre_candidat(
        notion=None,
        niveau=niveau_cible,
        types=types_cibles
    )

    if exercice:
        return {
            "exercice": exercice,
            "strategie": strategie,
            "raison": f"{raison_profil} Autre notion, mais niveau et type adaptés.",
            "niveau_cible": niveau_cible,
            "notion_cible": notion_cible,
            "profil_apprenant": infos_profil
        }

    # ------------------------------------------------------------
    # 5. Prochain exercice non fait dans la leçon
    # ------------------------------------------------------------

    exercice = candidats[0] if candidats else None

    if exercice:
        return {
            "exercice": exercice,
            "strategie": strategie,
            "raison": f"{raison_profil} Fallback : prochain exercice non fait dans la leçon.",
            "niveau_cible": niveau_cible,
            "notion_cible": notion_cible,
            "profil_apprenant": infos_profil
        }

    # ------------------------------------------------------------
    # 6. Aucun exercice disponible
    # ------------------------------------------------------------

    return {
        "exercice": None,
        "strategie": "fin_sequence",
        "raison": "Aucun autre exercice disponible pour cette leçon.",
        "niveau_cible": niveau_cible,
        "notion_cible": notion_cible,
        "profil_apprenant": infos_profil
    }


# ============================================================
# 6. PREMIER EXERCICE
# ============================================================

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