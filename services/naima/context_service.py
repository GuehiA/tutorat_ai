from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from services.naima.math_parser_service import (
    choose_safe_equation,
    classify_equation,
    extract_equation_from_text,
    normalize_math_text,
)


@dataclass
class NaimaMathContext:
    """
    Contexte mathématique courant de Naima.

    Cette structure ne dépend pas directement de Flask.
    Elle peut être construite depuis une session, un test
    ou un autre orchestrateur.
    """

    original_message: str

    objective: Optional[str] = None

    current_equation: Optional[str] = None
    initial_equation: Optional[str] = None

    extracted_equation: Optional[str] = None
    safe_equation: Optional[str] = None

    equation_type: str = "unknown"

    is_new_problem: bool = False
    context_preserved: bool = False

    extraction_consistent: bool = True

    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_message": self.original_message,
            "objective": self.objective,
            "current_equation": self.current_equation,
            "initial_equation": self.initial_equation,
            "extracted_equation": self.extracted_equation,
            "safe_equation": self.safe_equation,
            "equation_type": self.equation_type,
            "is_new_problem": self.is_new_problem,
            "context_preserved": self.context_preserved,
            "extraction_consistent": self.extraction_consistent,
            "reason": self.reason,
        }


def detect_new_math_problem(
    *,
    message: str,
    current_objective: Optional[str],
    current_equation: Optional[str],
) -> bool:
    """
    Détection prudente d'un nouveau problème.

    Une équation complète dans un message peut être un nouveau problème,
    mais elle peut aussi être simplement une correction ou un rappel.

    Cette fonction reste volontairement conservatrice.
    """

    extracted = extract_equation_from_text(
        message
    )

    if not extracted:
        return False

    if not current_equation:
        return True

    normalized_current = normalize_math_text(
        current_equation
    )

    normalized_new = normalize_math_text(
        extracted
    )

    if normalized_current == normalized_new:
        return False

    lower_message = (
        message
        or ""
    ).lower()

    new_problem_markers = (
        "résoudre",
        "resoudre",
        "nouvelle équation",
        "nouvelle equation",
        "nouvel exercice",
        "autre équation",
        "autre equation",
        "solve",
    )

    if any(
        marker in lower_message
        for marker in new_problem_markers
    ):
        return True

    # En l'absence de marqueur clair,
    # on ne détruit pas le contexte existant.
    return False


def build_math_context(
    *,
    message: str,
    current_objective: Optional[str] = None,
    current_equation: Optional[str] = None,
    initial_equation: Optional[str] = None,
    extracted_equation: Optional[str] = None,
) -> NaimaMathContext:
    """
    Construit un contexte mathématique sûr.

    Rôle principal :
    empêcher une extraction incorrecte de remplacer
    l'équation réellement saisie par l'élève.

    Exemple critique :
        message = "résoudre 3x²-5x+2=0"
        extracted_equation = "-5x+2=0"

    Le service préférera :
        3*x**2-5*x+2=0
    """

    local_extracted = (
        extracted_equation
        or extract_equation_from_text(
            message
        )
    )

    safety = choose_safe_equation(
        original_text=message,
        extracted_equation=local_extracted,
    )

    safe_equation = safety.get(
        "preferred_equation"
    )

    extraction_consistent = bool(
        safety.get(
            "consistent",
            True,
        )
    )

    is_new_problem = detect_new_math_problem(
        message=message,
        current_objective=current_objective,
        current_equation=current_equation,
    )

    # Si nouveau problème :
    # la nouvelle équation devient la référence.
    if is_new_problem and safe_equation:
        resolved_current = safe_equation
        resolved_initial = safe_equation
        context_preserved = False

        reason = (
            "new_math_problem_detected"
        )

    # Sinon on conserve l'équation pédagogique existante.
    elif current_equation:
        resolved_current = (
            normalize_math_text(
                current_equation
            )
        )

        resolved_initial = (
            normalize_math_text(
                initial_equation
            )
            if initial_equation
            else resolved_current
        )

        context_preserved = True

        reason = (
            "existing_math_context_preserved"
        )

    # Aucun contexte existant :
    # utiliser l'équation sûre extraite.
    elif safe_equation:
        resolved_current = safe_equation
        resolved_initial = safe_equation
        context_preserved = False

        reason = (
            "math_context_initialized"
        )

    else:
        resolved_current = None
        resolved_initial = (
            normalize_math_text(
                initial_equation
            )
            if initial_equation
            else None
        )

        context_preserved = bool(
            current_equation
        )

        reason = (
            "no_equation_available"
        )

    equation_type = (
        classify_equation(
            resolved_current
        )
        if resolved_current
        else "unknown"
    )

    return NaimaMathContext(
        original_message=message,
        objective=current_objective,

        current_equation=resolved_current,
        initial_equation=resolved_initial,

        extracted_equation=local_extracted,
        safe_equation=safe_equation,

        equation_type=equation_type,

        is_new_problem=is_new_problem,
        context_preserved=context_preserved,

        extraction_consistent=(
            extraction_consistent
        ),

        reason=reason,
    )


def context_from_session(
    *,
    message: str,
    session_data: Dict[str, Any],
    extracted_equation: Optional[str] = None,
) -> NaimaMathContext:
    """
    Adaptateur temporaire entre la session Flask actuelle
    et la nouvelle architecture.

    Aucune dépendance Flask ici :
    session_data est simplement un dictionnaire.
    """

    return build_math_context(
        message=message,

        current_objective=(
            session_data.get(
                "objectif_initial_naima"
            )
        ),

        current_equation=(
            session_data.get(
                "equation_courante_naima"
            )
        ),

        initial_equation=(
            session_data.get(
                "equation_initiale_naima"
            )
        ),

        extracted_equation=(
            extracted_equation
        ),
    )


def apply_context_to_session(
    *,
    context: NaimaMathContext,
    session_data: Dict[str, Any],
) -> None:
    """
    Applique uniquement les informations mathématiques
    nécessaires au dictionnaire de session.

    À utiliser plus tard depuis l'orchestrateur.
    """

    if context.current_equation:
        session_data[
            "equation_courante_naima"
        ] = context.current_equation

    if context.initial_equation:
        session_data[
            "equation_initiale_naima"
        ] = context.initial_equation

    if (
        context.is_new_problem
        and context.original_message
    ):
        session_data[
            "objectif_initial_naima"
        ] = context.original_message