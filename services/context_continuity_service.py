from __future__ import annotations

import re
from typing import Any, Dict, Optional


_OPERATION_PATTERNS = [
    r"\bajout(?:e|er|ons)?\b",
    r"\bsoustra(?:is|ire|yons|it)?\b",
    r"\bdivis(?:e|er|ons)?\b",
    r"\bmultipli(?:e|er|ons)?\b",
    r"\bon\s+(?:ajoute|soustrait|divise|multiplie)\b",
]

_CORRECTION_PATTERNS = [
    r"\bje\s+corrige\b",
    r"\bje\s+rectifie\b",
    r"\bplut[oô]t\b",
    r"\ben\s+fait\b",
    r"\bon\s+[ée]tait\s+[àa]\b",
    r"\battention\b",
]

_EXPLICIT_NEW_PROBLEM_PATTERNS = [
    r"\bnouveau\s+probl[eè]me\b",
    r"\bnouvelle\s+[ée]quation\b",
    r"\bautre\s+probl[eè]me\b",
    r"\bautre\s+[ée]quation\b",
    r"\bchangeons\s+de\s+probl[eè]me\b",
    r"\bchangeons\s+d['’]?[ée]quation\b",
]


def _matches(text: str, patterns) -> bool:
    return any(re.search(p, text, flags=re.IGNORECASE) for p in patterns)


def detecter_continuation_contextuelle(
    message_eleve: str,
    *,
    objectif_actif: Optional[str] = None,
    equation_courante: Optional[str] = None,
    derniere_question_naima: Optional[str] = None,
    phase_recuperation: Optional[str] = None,
) -> Dict[str, Any]:
    """Détermine si le message est une continuation/correction du problème actif.

    Règle conservatrice : cette fonction n'invente jamais un nouveau problème.
    Elle empêche seulement de réinitialiser le contexte lorsqu'il existe déjà
    un objectif et que le message ressemble clairement à une étape de résolution.
    """
    texte = str(message_eleve or "").strip().lower()
    objectif_actif = str(objectif_actif or "").strip()
    equation_courante = str(equation_courante or "").strip()
    derniere_question_naima = str(derniere_question_naima or "").strip()
    phase_recuperation = str(phase_recuperation or "").strip().lower()

    if not texte or not objectif_actif:
        return {
            "est_continuation": False,
            "confiance": 0.0,
            "raison": "Aucun objectif actif à préserver.",
        }

    if _matches(texte, _EXPLICIT_NEW_PROBLEM_PATTERNS):
        return {
            "est_continuation": False,
            "confiance": 1.0,
            "raison": "Changement de problème explicitement demandé.",
        }

    operation = _matches(texte, _OPERATION_PATTERNS)
    correction = _matches(texte, _CORRECTION_PATTERNS)
    contient_resultat = bool(re.search(r"\b[xyz]\s*=", texte, flags=re.IGNORECASE))
    contexte_actif = bool(equation_courante or derniere_question_naima)

    if phase_recuperation == "raisonnement_a_corriger" and (operation or correction):
        return {
            "est_continuation": True,
            "confiance": 0.99,
            "raison": "Correction d'un raisonnement encore actif.",
        }

    if correction and (operation or contient_resultat):
        return {
            "est_continuation": True,
            "confiance": 0.97,
            "raison": "Le message corrige explicitement une étape du problème actif.",
        }

    if operation and contexte_actif:
        return {
            "est_continuation": True,
            "confiance": 0.94,
            "raison": "Opération de résolution formulée dans un contexte déjà actif.",
        }

    if contient_resultat and derniere_question_naima:
        return {
            "est_continuation": True,
            "confiance": 0.90,
            "raison": "Résultat proposé en réponse à une question pédagogique active.",
        }

    return {
        "est_continuation": False,
        "confiance": 0.55,
        "raison": "Pas assez d'indices pour forcer la continuité contextuelle.",
    }
