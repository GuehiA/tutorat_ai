from __future__ import annotations
from typing import Any, Dict, Optional


def choisir_intervention_pedagogique(
    *,
    validation: Optional[Dict[str, Any]] = None,
    intention: Optional[Dict[str, Any]] = None,
    etat_comportemental: Optional[Dict[str, Any]] = None,
    controle_cognitif: Optional[Dict[str, Any]] = None,
    diagnostic: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    validation = validation or {}
    intention = intention or {}
    etat_comportemental = etat_comportemental or {}
    controle_cognitif = controle_cognitif or {}
    diagnostic = diagnostic or {}

    verdict = validation.get("verdict") or validation.get("validation_verdict")
    result_correct = validation.get("result_correct")
    reasoning_correct = validation.get("reasoning_correct")
    error_type = validation.get("error_type")

    intention_type = intention.get("type_demande")
    etat = etat_comportemental.get("etat")
    controle = controle_cognitif.get("niveau")

    decision = {
        "strategie": "guidage_leger",
        "niveau_aide": 1,
        "peut_reveler_solution": False,
        "peut_declencher_remediation": False,
        "requires_review": False,
        "raison": "Guidage pédagogique léger par défaut.",
    }

    # Résultat correct, mais justification fausse :
    # ne pas invalider le résultat et ne pas déclencher de remédiation.
    if (
        verdict == "correct"
        and result_correct is True
        and reasoning_correct is False
    ):
        decision.update({
            "strategie": "correction_raisonnement_resultat_correct",
            "niveau_aide": 1,
            "peut_reveler_solution": True,
            "peut_declencher_remediation": False,
            "requires_review": False,
            "raison": (
                "Le résultat final est prouvé correct, mais le raisonnement "
                "contient une incohérence prouvée. Reconnaître le résultat "
                "sans valider la justification fautive."
            ),
            "error_type": error_type,
        })
        return decision

    if controle == "delegation_strategique" or etat == "dependance_probable":
        decision.update({
            "strategie": "rendre_controle_a_eleve",
            "niveau_aide": 1,
            "peut_reveler_solution": False,
            "peut_declencher_remediation": False,
            "requires_review": verdict == "uncertain",
            "raison": (
                "L'élève semble déléguer la planification. "
                "Naïma doit rendre la décision stratégique à l'élève "
                "sans donner la prochaine opération."
            ),
        })
        return decision

    if verdict == "uncertain":
        if etat == "blocage":
            decision.update({
                "strategie": "clarification",
                "niveau_aide": 1,
                "peut_reveler_solution": False,
                "peut_declencher_remediation": False,
                "requires_review": True,
                "raison": (
                    "Le moteur n'a pas assez de preuve et l'élève semble bloqué. "
                    "Donner une clarification minimale sans juger la réponse."
                ),
            })
        else:
            decision.update({
                "strategie": "verification_sans_sanction",
                "niveau_aide": 1,
                "peut_reveler_solution": False,
                "peut_declencher_remediation": False,
                "requires_review": True,
                "raison": (
                    "Le moteur n'a pas assez de preuve. "
                    "Demander une précision sans pénaliser."
                ),
            })
        return decision

    if intention_type == "demande_indice" or controle == "demande_indice":
        decision.update({
            "strategie": "indice_socratique",
            "niveau_aide": 1,
            "peut_reveler_solution": False,
            "raison": "L'élève demande un indice ; fournir le plus petit indice utile.",
        })
        return decision

    if verdict == "incorrect":
        if etat == "blocage":
            decision.update({
                "strategie": "clarification",
                "niveau_aide": 2,
                "peut_reveler_solution": False,
                "peut_declencher_remediation": True,
                "raison": "Une erreur est prouvée et l'élève montre des signes de blocage.",
            })
        else:
            decision.update({
                "strategie": "localisation_erreur",
                "niveau_aide": 1,
                "peut_reveler_solution": False,
                "peut_declencher_remediation": True,
                "raison": "Erreur prouvée : localiser l'étape problématique.",
            })
        return decision

    if verdict == "correct":
        decision.update({
            "strategie": "felicitation_et_approfondissement",
            "niveau_aide": 0,
            "peut_reveler_solution": False,
            "peut_declencher_remediation": False,
            "raison": "Réponse prouvée correcte : reconnaître puis approfondir.",
        })
        return decision

    if intention_type == "demande_verification" or controle == "demande_validation":
        decision.update({
            "strategie": "question_diagnostique",
            "niveau_aide": 1,
            "peut_reveler_solution": False,
            "raison": (
                "L'élève demande une validation, mais aucune preuve déterministe "
                "n'est encore disponible."
            ),
        })

    return decision


def construire_instruction_pedagogique(
    decision: Dict[str, Any],
    lang: str = "fr"
) -> str:
    decision = decision or {}
    strategie = decision.get("strategie", "guidage_leger")
    niveau = decision.get("niveau_aide", 1)
    peut_reveler = bool(decision.get("peut_reveler_solution", False))
    raison = decision.get("raison", "")

    if lang == "en":
        extra = ""

        if strategie == "correction_raisonnement_resultat_correct":
            extra = (
                "The final result is correct, but the written reasoning contains "
                "a proven inconsistency. Acknowledge the correct result, then ask "
                "the student to correct only the faulty operation or justification. "
                "Ask at most one question.\n"
            )
        elif strategie == "rendre_controle_a_eleve":
            extra = (
                "Do not choose the next operation for the student. "
                "Ask the student to propose a possible next step or explain "
                "what they are trying to eliminate.\n"
            )

        return (
            "\n\nPEDAGOGICAL POLICY (must be followed):\n"
            f"- strategy: {strategie}\n"
            f"- help level: {niveau}\n"
            f"- may reveal final solution: {'yes' if peut_reveler else 'no'}\n"
            f"- rationale: {raison}\n"
            + extra
            + "Do not override this policy.\n"
        )

    extra = ""

    if strategie == "correction_raisonnement_resultat_correct":
        extra = (
            "Le résultat final est correct, mais le raisonnement écrit contient "
            "une incohérence prouvée. Reconnais le résultat correct, puis demande "
            "à l'élève de corriger uniquement l'opération ou la justification "
            "fautive. Pose au maximum une question.\n"
        )
    elif strategie == "rendre_controle_a_eleve":
        extra = (
            "Ne choisis PAS la prochaine opération à la place de l'élève. "
            "Demande-lui de proposer une étape possible ou d'identifier "
            "ce qu'il cherche à éliminer.\n"
        )

    return (
        "\n\nPOLITIQUE PÉDAGOGIQUE (à respecter obligatoirement) :\n"
        f"- stratégie : {strategie}\n"
        f"- niveau d'aide : {niveau}\n"
        f"- peut révéler la solution finale : {'oui' if peut_reveler else 'non'}\n"
        f"- raison : {raison}\n"
        + extra
        + "Ne remplace pas cette décision par ta propre stratégie.\n"
    )
