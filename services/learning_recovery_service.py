"""
Learning Recovery v1.1 pour Naïma.

Principes :
- état de session compact ;
- l'historique complet vit dans TraceApprentissage, pas dans le cookie/session ;
- résultat correct + raisonnement faux n'est PAS une récupération complète ;
- uncertain ne devient jamais une erreur ;
- les drapeaux d'aide/blocage sont nettoyés à la fin d'une séquence.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validation_dict(validation: Optional[Any]) -> Dict[str, Any]:
    if validation is None:
        return {}
    if isinstance(validation, dict):
        return validation
    if hasattr(validation, "to_dict"):
        try:
            return validation.to_dict()
        except Exception:
            return {}
    return {
        "verdict": getattr(validation, "verdict", None),
        "confidence": getattr(validation, "confidence", None),
        "method": getattr(validation, "method", None),
        "result_correct": getattr(validation, "result_correct", None),
        "reasoning_correct": getattr(validation, "reasoning_correct", None),
        "error_type": getattr(validation, "error_type", None),
    }


def _compteurs_init() -> Dict[str, int]:
    return {
        "recuperation_autonome": 0,
        "recuperation_apres_aide": 0,
        "reussite_assistee": 0,
        "sortie_blocage_apres_aide": 0,
        "blocage_observe": 0,
        "delegation_observee": 0,
        "raisonnement_a_corriger": 0,
    }


def _etat_initial() -> Dict[str, Any]:
    return {
        "phase": "neutre",
        "erreur_active": False,
        "blocage_actif": False,
        "derniere_erreur_type": None,
        "derniere_validation_method": None,

        "aide_depuis_erreur": False,
        "aide_depuis_blocage": False,
        "niveau_aide_max": 0,
        "delegation_depuis_erreur": False,
        "delegation_depuis_blocage": False,

        "nb_erreurs_consecutives": 0,
        "nb_tentatives_depuis_erreur": 0,
        "nb_tentatives_depuis_aide": 0,

        "dernier_statut_recuperation": "aucune_preuve",
        "confiance_recuperation": 0.0,
        "derniere_strategie_aide": None,
        "dernier_verdict": None,

        # Important : aucun historique cumulatif ici.
        "dernier_evenement": None,
        "compteurs": _compteurs_init(),
        "mis_a_jour_le": _utc_iso(),
    }


def _normaliser_etat(etat_precedent: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    etat = _etat_initial()

    if isinstance(etat_precedent, dict):
        for cle, valeur in etat_precedent.items():
            if cle in etat:
                etat[cle] = deepcopy(valeur)

    compteurs = etat.get("compteurs")
    if not isinstance(compteurs, dict):
        compteurs = {}

    base = _compteurs_init()
    for cle in base:
        try:
            base[cle] = int(compteurs.get(cle, 0) or 0)
        except Exception:
            base[cle] = 0

    etat["compteurs"] = base
    return etat


def _strategie_est_aide(strategie: Optional[str]) -> bool:
    return strategie in {
        "indice_socratique",
        "clarification",
        "localisation_erreur",
        "question_diagnostique",
        "guidage_leger",
        "correction_raisonnement_resultat_correct",
    }


def _strategie_est_controle_rendu(strategie: Optional[str]) -> bool:
    return strategie == "rendre_controle_a_eleve"


def _aide_est_forte(
    strategie: Optional[str],
    niveau_aide: int,
    controle: Optional[str],
) -> bool:
    if niveau_aide >= 2:
        return True
    if controle == "delegation_strategique":
        return True
    return strategie in {
        "explication_directe",
        "solution_partielle",
        "solution_complete",
    }


def _incrementer_compteur(etat: Dict[str, Any], statut: str) -> None:
    compteurs = etat.setdefault("compteurs", _compteurs_init())
    if statut in compteurs:
        compteurs[statut] = int(compteurs.get(statut, 0) or 0) + 1


def analyser_recuperation_apprentissage(
    *,
    etat_precedent: Optional[Dict[str, Any]] = None,
    validation: Optional[Any] = None,
    etat_comportemental: Optional[Dict[str, Any]] = None,
    controle_cognitif: Optional[Dict[str, Any]] = None,
    politique_pedagogique: Optional[Dict[str, Any]] = None,
    intention: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:

    etat = _normaliser_etat(etat_precedent)

    validation_d = _validation_dict(validation)
    comportement = etat_comportemental or {}
    controle_d = controle_cognitif or {}
    politique = politique_pedagogique or {}
    intention_d = intention or {}

    verdict = str(validation_d.get("verdict") or "uncertain")
    confidence = float(validation_d.get("confidence") or 0.0)
    method = validation_d.get("method")
    error_type = validation_d.get("error_type")
    result_correct = validation_d.get("result_correct")
    reasoning_correct = validation_d.get("reasoning_correct")

    comportement_etat = comportement.get("etat")
    controle = controle_d.get("niveau")
    strategie = politique.get("strategie")

    try:
        niveau_aide = int(politique.get("niveau_aide") or 0)
    except Exception:
        niveau_aide = 0

    avait_erreur_active = bool(etat.get("erreur_active"))
    avait_blocage_actif = bool(etat.get("blocage_actif"))
    avait_aide_depuis_erreur = bool(etat.get("aide_depuis_erreur"))
    avait_aide_depuis_blocage = bool(etat.get("aide_depuis_blocage"))
    niveau_aide_avant = int(etat.get("niveau_aide_max") or 0)
    delegation_avant_erreur = bool(etat.get("delegation_depuis_erreur"))
    delegation_avant_blocage = bool(etat.get("delegation_depuis_blocage"))

    statut = "aucune_preuve"
    confiance = 0.0
    signal = "validation_non_conclusive"

    # ------------------------------------------------------------
    # 0. RÉSULTAT CORRECT MAIS RAISONNEMENT FAUX
    # ------------------------------------------------------------
    if (
        verdict == "correct"
        and confidence >= 0.95
        and result_correct is True
        and reasoning_correct is False
    ):
        etat["phase"] = "raisonnement_a_corriger"
        etat["erreur_active"] = True
        etat["derniere_erreur_type"] = (
            error_type or "correct_result_wrong_reasoning"
        )
        etat["derniere_validation_method"] = method
        etat["nb_erreurs_consecutives"] = max(
            1,
            int(etat.get("nb_erreurs_consecutives") or 0)
        )

        statut = "raisonnement_a_corriger"
        confiance = 1.0
        signal = "resultat_correct_raisonnement_incorrect"

    # ------------------------------------------------------------
    # 1. ERREUR DÉTERMINISTE
    # ------------------------------------------------------------
    elif verdict == "incorrect" and confidence >= 0.95:
        etat["phase"] = "erreur_active"
        etat["erreur_active"] = True
        etat["blocage_actif"] = comportement_etat == "blocage"
        etat["derniere_erreur_type"] = error_type
        etat["derniere_validation_method"] = method
        etat["nb_erreurs_consecutives"] = int(
            etat.get("nb_erreurs_consecutives") or 0
        ) + 1
        etat["nb_tentatives_depuis_erreur"] = 0
        etat["nb_tentatives_depuis_aide"] = 0

        etat["aide_depuis_erreur"] = False
        etat["niveau_aide_max"] = 0
        etat["delegation_depuis_erreur"] = False

        statut = "erreur_active"
        confiance = 1.0
        signal = "erreur_deterministe_prouvee"

    # ------------------------------------------------------------
    # 2. RÉPONSE CORRECTE DÉTERMINISTE
    # ------------------------------------------------------------
    elif verdict == "correct" and confidence >= 0.95:
        if avait_erreur_active:
            etat["nb_tentatives_depuis_erreur"] = int(
                etat.get("nb_tentatives_depuis_erreur") or 0
            ) + 1

            if avait_aide_depuis_erreur:
                if delegation_avant_erreur or niveau_aide_avant >= 2:
                    statut = "reussite_assistee"
                    confiance = 0.92
                    signal = "correct_apres_aide_forte_ou_delegation"
                else:
                    statut = "recuperation_apres_aide"
                    confiance = 0.95
                    signal = "correct_apres_aide_legere"
            else:
                statut = "recuperation_autonome"
                confiance = 0.98
                signal = "correct_apres_erreur_sans_aide"

            etat["phase"] = "recupere"
            etat["erreur_active"] = False
            etat["blocage_actif"] = False
            etat["nb_erreurs_consecutives"] = 0

            # Nettoyage complet de la séquence terminée.
            etat["aide_depuis_erreur"] = False
            etat["aide_depuis_blocage"] = False
            etat["niveau_aide_max"] = 0
            etat["delegation_depuis_erreur"] = False
            etat["delegation_depuis_blocage"] = False

        elif avait_blocage_actif:
            if avait_aide_depuis_blocage:
                if delegation_avant_blocage or niveau_aide_avant >= 2:
                    statut = "reussite_apres_blocage_assistee"
                    confiance = 0.84
                    signal = "correct_apres_blocage_et_aide_forte"
                else:
                    statut = "sortie_blocage_apres_aide"
                    confiance = 0.88
                    signal = "correct_apres_blocage_et_aide_legere"
            else:
                statut = "sortie_blocage_autonome"
                confiance = 0.90
                signal = "correct_apres_blocage_sans_aide"

            etat["phase"] = "recupere"
            etat["blocage_actif"] = False
            etat["erreur_active"] = False
            etat["aide_depuis_blocage"] = False
            etat["aide_depuis_erreur"] = False
            etat["delegation_depuis_blocage"] = False
            etat["delegation_depuis_erreur"] = False
            etat["niveau_aide_max"] = 0

        else:
            etat["phase"] = "reussite"
            statut = "reussite_isolee"
            confiance = 1.0
            signal = "correct_sans_sequence_precedente"

    # ------------------------------------------------------------
    # 3. UNCERTAIN / NON ÉVALUÉ
    # ------------------------------------------------------------
    else:
        if comportement_etat == "blocage":
            etat["phase"] = "blocage"
            etat["blocage_actif"] = True
            statut = "blocage_observe"
            confiance = float(comportement.get("confiance") or 0.70)
            signal = "blocage_sans_jugement_math"

        elif controle == "delegation_strategique":
            etat["phase"] = "delegation"
            statut = "delegation_observee"
            confiance = float(controle_d.get("confiance") or 0.90)
            signal = "delegation_sans_jugement_math"

        else:
            statut = "aucune_preuve"
            confiance = 0.0

    aide_ce_tour = (
        _strategie_est_aide(strategie)
        or _strategie_est_controle_rendu(strategie)
    )

    if aide_ce_tour:
        etat["derniere_strategie_aide"] = strategie
        etat["niveau_aide_max"] = max(
            int(etat.get("niveau_aide_max") or 0),
            niveau_aide,
        )

        if etat.get("erreur_active"):
            etat["aide_depuis_erreur"] = True
            if controle == "delegation_strategique":
                etat["delegation_depuis_erreur"] = True

        if etat.get("blocage_actif"):
            etat["aide_depuis_blocage"] = True
            if controle == "delegation_strategique":
                etat["delegation_depuis_blocage"] = True

    if (
        verdict in {"correct", "incorrect"}
        and (avait_aide_depuis_erreur or avait_aide_depuis_blocage)
    ):
        etat["nb_tentatives_depuis_aide"] = int(
            etat.get("nb_tentatives_depuis_aide") or 0
        ) + 1

    evenement = {
        "timestamp": _utc_iso(),
        "verdict": verdict,
        "validation_confidence": confidence,
        "validation_method": method,
        "result_correct": result_correct,
        "reasoning_correct": reasoning_correct,
        "error_type": error_type,
        "etat_comportemental": comportement_etat,
        "controle_cognitif": controle,
        "strategie_pedagogique": strategie,
        "niveau_aide": niveau_aide,
        "type_demande": intention_d.get("type_demande"),
        "statut_recuperation": statut,
        "confiance_recuperation": round(confiance, 3),
        "signal": signal,
    }

    etat["dernier_evenement"] = evenement
    _incrementer_compteur(etat, statut)

    etat["dernier_statut_recuperation"] = statut
    etat["confiance_recuperation"] = round(confiance, 3)
    etat["dernier_verdict"] = verdict
    etat["mis_a_jour_le"] = _utc_iso()
    return etat


def resume_recuperation_apprentissage(
    etat: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    etat = _normaliser_etat(etat)
    return {
        "phase": etat.get("phase"),
        "erreur_active": bool(etat.get("erreur_active")),
        "blocage_actif": bool(etat.get("blocage_actif")),
        "dernier_statut_recuperation": etat.get(
            "dernier_statut_recuperation"
        ),
        "confiance_recuperation": etat.get(
            "confiance_recuperation"
        ),
        "derniere_erreur_type": etat.get("derniere_erreur_type"),
        "nb_erreurs_consecutives": int(
            etat.get("nb_erreurs_consecutives") or 0
        ),
        "aide_depuis_erreur": bool(etat.get("aide_depuis_erreur")),
        "aide_depuis_blocage": bool(etat.get("aide_depuis_blocage")),
        "niveau_aide_max": int(etat.get("niveau_aide_max") or 0),
        "compteurs": deepcopy(etat.get("compteurs") or _compteurs_init()),
        "dernier_evenement": deepcopy(etat.get("dernier_evenement")),
        "mis_a_jour_le": etat.get("mis_a_jour_le"),
    }
