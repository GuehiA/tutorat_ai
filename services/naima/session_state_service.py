from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class NaimaSessionState:
    """
    Représentation centralisée de l'état de session de Naima.

    Cette classe ne dépend pas de Flask.
    Elle accepte un simple dictionnaire.
    """

    current_objective: Optional[str] = None
    current_equation: Optional[str] = None
    initial_equation: Optional[str] = None

    last_teacher_question: str = ""

    conversation: List[Any] = field(
        default_factory=list
    )

    recovery_state: Dict[str, Any] = field(
        default_factory=dict
    )

    diagnostic: Dict[str, Any] = field(
        default_factory=dict
    )

    recent_hint_count: int = 0

    first_message: bool = False

    language: str = "fr"

    def to_dict(
        self,
    ) -> Dict[str, Any]:
        return {
            "current_objective": (
                self.current_objective
            ),
            "current_equation": (
                self.current_equation
            ),
            "initial_equation": (
                self.initial_equation
            ),
            "last_teacher_question": (
                self.last_teacher_question
            ),
            "conversation": list(
                self.conversation
            ),
            "recovery_state": dict(
                self.recovery_state
            ),
            "diagnostic": dict(
                self.diagnostic
            ),
            "recent_hint_count": (
                self.recent_hint_count
            ),
            "first_message": (
                self.first_message
            ),
            "language": (
                self.language
            ),
        }


def read_naima_session(
    session_data: Dict[str, Any],
) -> NaimaSessionState:
    """
    Lit l'état Naima depuis un dictionnaire de session.

    Les noms correspondent progressivement
    aux clés déjà utilisées dans l'application.
    """

    conversation = (
        session_data.get(
            "conversation_naima"
        )
        or session_data.get(
            "conversation"
        )
        or []
    )

    recovery_state = (
        session_data.get(
            "recuperation_apprentissage_naima"
        )
        or {}
    )

    diagnostic = (
        session_data.get(
            "diagnostic_naima"
        )
        or {}
    )

    recent_hint_count = (
        session_data.get(
            "nb_indices_recents_naima",
            0,
        )
        or 0
    )

    first_message = bool(
        session_data.get(
            "premier_message_naima",
            False,
        )
    )

    language = (
        session_data.get(
            "lang_naima"
        )
        or session_data.get(
            "lang"
        )
        or "fr"
    )

    return NaimaSessionState(
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

        last_teacher_question=(
            session_data.get(
                "derniere_question_naima"
            )
            or ""
        ),

        conversation=list(
            conversation
        ),

        recovery_state=dict(
            recovery_state
        ),

        diagnostic=dict(
            diagnostic
        ),

        recent_hint_count=int(
            recent_hint_count
        ),

        first_message=(
            first_message
        ),

        language=str(
            language
        ),
    )


def apply_context_state(
    *,
    session_data: Dict[str, Any],
    context: Dict[str, Any],
) -> None:
    """
    Applique le contexte mathématique produit
    par l'orchestrateur.
    """

    current_equation = (
        context.get(
            "current_equation"
        )
    )

    initial_equation = (
        context.get(
            "initial_equation"
        )
    )

    objective = (
        context.get(
            "objective"
        )
    )

    if current_equation:
        session_data[
            "equation_courante_naima"
        ] = current_equation

    if initial_equation:
        session_data[
            "equation_initiale_naima"
        ] = initial_equation

    if objective:
        session_data[
            "objectif_initial_naima"
        ] = objective


def apply_pedagogical_state(
    *,
    session_data: Dict[str, Any],
    pedagogical: Dict[str, Any],
) -> None:
    """
    Persiste uniquement les éléments pédagogiques
    qui doivent survivre entre deux tours.
    """

    recovery_state = (
        pedagogical.get(
            "recovery_state"
        )
    )

    if isinstance(
        recovery_state,
        dict,
    ):
        session_data[
            "recuperation_apprentissage_naima"
        ] = recovery_state

    recent_hint_count = (
        pedagogical.get(
            "recent_hint_count"
        )
    )

    if recent_hint_count is not None:
        session_data[
            "nb_indices_recents_naima"
        ] = int(
            recent_hint_count
        )


def append_conversation_turn(
    *,
    session_data: Dict[str, Any],
    student_message: Optional[str] = None,
    naima_message: Optional[str] = None,
    max_messages: int = 20,
) -> None:
    """
    Ajoute un tour à l'historique conversationnel.

    Le format reste compatible avec celui
    déjà utilisé par behavioral_state_service.
    """

    conversation = list(
        session_data.get(
            "conversation_naima"
        )
        or session_data.get(
            "conversation"
        )
        or []
    )

    if student_message:
        conversation.append(
            f"👤 Élève: {student_message}"
        )

    if naima_message:
        conversation.append(
            f"🤖 Naima: {naima_message}"
        )

    if max_messages > 0:
        conversation = (
            conversation[
                -max_messages:
            ]
        )

    session_data[
        "conversation_naima"
    ] = conversation


def update_last_teacher_question(
    *,
    session_data: Dict[str, Any],
    question: Optional[str],
) -> None:
    """
    Mémorise la dernière question pédagogique
    réellement posée par Naima.
    """

    if question:
        session_data[
            "derniere_question_naima"
        ] = str(
            question
        )


def mark_first_message_processed(
    session_data: Dict[str, Any],
) -> None:
    """
    Après le premier tour traité, les tours suivants
    ne sont plus considérés comme premier message.
    """

    session_data[
        "premier_message_naima"
    ] = False


def apply_turn_result(
    *,
    session_data: Dict[str, Any],
    turn_result: Dict[str, Any],
) -> None:
    """
    Applique en une seule opération les états persistants
    produits par NaimaOrchestrator.

    Ne ferme pas encore directement un exercice Flask.
    Cette responsabilité restera au futur adaptateur de route.
    """

    context = (
        turn_result.get(
            "context"
        )
        or {}
    )

    pedagogical = (
        turn_result.get(
            "pedagogical"
        )
        or {}
    )

    response = (
        turn_result.get(
            "response"
        )
        or {}
    )

    apply_context_state(
        session_data=session_data,
        context=context,
    )

    apply_pedagogical_state(
        session_data=session_data,
        pedagogical=pedagogical,
    )

    naima_text = (
        response.get(
            "text"
        )
    )

    student_message = (
        turn_result.get(
            "message"
        )
    )

    append_conversation_turn(
        session_data=session_data,
        student_message=(
            student_message
        ),
        naima_message=(
            naima_text
        ),
    )

    mark_first_message_processed(
        session_data
    )


def reset_naima_math_state(
    session_data: Dict[str, Any],
) -> None:
    """
    Réinitialise uniquement le contexte mathématique
    courant de Naima.

    Le profil élève, les diagnostics globaux
    et les autres informations de session
    ne sont pas supprimés.
    """

    keys_to_remove = (
        "objectif_initial_naima",
        "equation_courante_naima",
        "equation_initiale_naima",
        "derniere_question_naima",
        "recuperation_apprentissage_naima",
        "nb_indices_recents_naima",
    )

    for key in keys_to_remove:
        session_data.pop(
            key,
            None,
        )