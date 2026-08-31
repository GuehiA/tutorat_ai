from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from services.naima.math_parser_service import (
    extract_equation_from_text,
    looks_like_solution_statement,
)


@dataclass
class NaimaIntent:
    type_demande: str

    domaine: str = "mathematiques"
    objectif: Optional[str] = None

    confidence: float = 0.0
    source: str = "deterministic"

    reason: Optional[str] = None

    def to_dict(
        self,
    ) -> Dict[str, Any]:
        return {
            "type_demande": self.type_demande,
            "domaine": self.domaine,
            "objectif": self.objectif,
            "confidence": self.confidence,
            "source": self.source,
            "reason": self.reason,
        }


def _normalize(
    text: str,
) -> str:

    if not text:
        return ""

    value = str(
        text
    ).lower().strip()

    value = (
        value
        .replace("’", "'")
        .replace("–", "-")
        .replace("—", "-")
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value


def detect_help_request(
    text: str,
) -> bool:

    value = _normalize(
        text
    )

    markers = (
        "donne moi un indice",
        "donne-moi un indice",
        "un indice",
        "aide moi",
        "aide-moi",
        "peux tu m'aider",
        "peux-tu m'aider",
        "je suis bloque",
        "je suis bloqué",
        "je bloque",
        "je ne sais pas",
        "je ne sais plus",
    )

    return any(
        marker in value
        for marker in markers
    )


def detect_explanation_request(
    text: str,
) -> bool:

    value = _normalize(
        text
    )

    markers = (
        "explique",
        "explique moi",
        "explique-moi",
        "je ne comprends pas",
        "je ne comprend pas",
        "je n'ai pas compris",
        "pourquoi",
        "comment faire",
        "comment on fait",
    )

    return any(
        marker in value
        for marker in markers
    )


def detect_final_answer(
    text: str,
) -> bool:
    """
    Détecte une réponse finale explicite.

    Exemples :
        x=5/3
        x=1 ou x=2/3
        les solutions sont x=1 et x=2/3
    """

    if looks_like_solution_statement(
        text
    ):
        return True

    value = _normalize(
        text
    )

    final_markers = (
        "la réponse est",
        "la solution est",
        "les solutions sont",
        "donc x=",
        "alors x=",
    )

    return any(
        marker in value
        for marker in final_markers
    )


def detect_new_problem(
    text: str,
) -> bool:
    """
    Détecte une nouvelle consigne ou équation à résoudre.
    """

    value = _normalize(
        text
    )

    equation = (
        extract_equation_from_text(
            text
        )
    )

    markers = (
        "résoudre",
        "resoudre",
        "solve",
        "nouvelle équation",
        "nouvelle equation",
        "nouvel exercice",
        "autre équation",
        "autre equation",
    )

    if (
        equation
        and any(
            marker in value
            for marker in markers
        )
    ):
        return True

    # Si aucune session n'existe encore,
    # l'orchestrateur pourra considérer une équation seule
    # comme problème initial.
    return False


def detect_intermediate_reasoning(
    text: str,
) -> bool:

    value = _normalize(
        text
    )

    reasoning_markers = (
        "on ajoute",
        "j'ajoute",
        "je vais ajouter",
        "on soustrait",
        "je soustrais",
        "je vais soustraire",
        "on divise",
        "je divise",
        "je vais diviser",
        "on multiplie",
        "je multiplie",
        "je vais multiplier",
        "on utilise",
        "j'utilise",
        "je vais utiliser",
        "a=",
        "b=",
        "c=",
        "delta",
        "discriminant",
        "factorise",
        "factoriser",
        "formule quadratique",
    )

    return any(
        marker in value
        for marker in reasoning_markers
    )


def detect_intent(
    text: str,
    *,
    has_active_problem: bool = False,
) -> NaimaIntent:
    """
    Détecteur déterministe principal.

    Ordre important :
    1. aide ;
    2. explication ;
    3. réponse finale ;
    4. nouveau problème ;
    5. raisonnement intermédiaire ;
    6. fallback contextuel.
    """

    if not text:
        return NaimaIntent(
            type_demande="message_vide",
            domaine="general",
            objectif=None,
            confidence=1.0,
            reason="empty_message",
        )

    if detect_help_request(
        text
    ):
        return NaimaIntent(
            type_demande="demande_indice",
            domaine="mathematiques",
            objectif="obtenir_indice",
            confidence=0.95,
            reason="help_request_detected",
        )

    if detect_explanation_request(
        text
    ):
        return NaimaIntent(
            type_demande="demande_explication",
            domaine="mathematiques",
            objectif="comprendre_etape",
            confidence=0.92,
            reason="explanation_request_detected",
        )

    if detect_final_answer(
        text
    ):
        return NaimaIntent(
            type_demande="reponse_finale",
            domaine="mathematiques",
            objectif="soumettre_reponse",
            confidence=0.98,
            reason="final_answer_detected",
        )

    if detect_new_problem(
        text
    ):
        return NaimaIntent(
            type_demande="probleme_a_resoudre",
            domaine="mathematiques",
            objectif="resoudre_equation",
            confidence=0.98,
            reason="new_problem_detected",
        )

    if detect_intermediate_reasoning(
        text
    ):
        return NaimaIntent(
            type_demande="reponse_intermediaire",
            domaine="mathematiques",
            objectif="poursuivre_raisonnement",
            confidence=0.90,
            reason="intermediate_reasoning_detected",
        )

    equation = (
        extract_equation_from_text(
            text
        )
    )

    if (
        equation
        and not has_active_problem
    ):
        return NaimaIntent(
            type_demande="probleme_a_resoudre",
            domaine="mathematiques",
            objectif="resoudre_equation",
            confidence=0.85,
            reason="equation_without_active_context",
        )

    if has_active_problem:
        return NaimaIntent(
            type_demande="reponse_intermediaire",
            domaine="mathematiques",
            objectif="poursuivre_raisonnement",
            confidence=0.60,
            reason="active_problem_context_fallback",
        )

    return NaimaIntent(
        type_demande="conversation_generale",
        domaine="general",
        objectif=None,
        confidence=0.40,
        reason="no_specific_intent_detected",
    )


def merge_intent(
    *,
    deterministic_intent: NaimaIntent,
    external_intent: Optional[
        Dict[str, Any]
    ] = None,
) -> NaimaIntent:
    """
    Permet plus tard de combiner :
    - l'intention déterministe locale ;
    - l'intention déjà produite par ton système actuel/LLM.

    Pour l'instant, une intention externe de confiance élevée
    peut remplacer le fallback déterministe faible.
    """

    if not external_intent:
        return deterministic_intent

    external_type = (
        external_intent.get(
            "type_demande"
        )
    )

    external_confidence = float(
        external_intent.get(
            "confidence"
        )
        or external_intent.get(
            "confiance"
        )
        or 0.0
    )

    if not external_type:
        return deterministic_intent

    # Une détection locale forte garde la priorité.
    if (
        deterministic_intent.confidence
        >= 0.90
    ):
        return deterministic_intent

    if external_confidence >= 0.80:
        return NaimaIntent(
            type_demande=(
                external_type
            ),
            domaine=(
                external_intent.get(
                    "domaine"
                )
                or "mathematiques"
            ),
            objectif=(
                external_intent.get(
                    "objectif"
                )
            ),
            confidence=(
                external_confidence
            ),
            source="external",
            reason=(
                "external_intent_high_confidence"
            ),
        )

    return deterministic_intent