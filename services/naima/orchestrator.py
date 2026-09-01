from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from services.naima.context_service import (
    NaimaMathContext,
    build_math_context,
)

from services.naima.intent_service import (
    NaimaIntent,
    detect_intent,
    merge_intent,
)

from services.naima.math_router import (
    NaimaMathRouter,
)

from services.naima.pedagogical_pipeline import (
    PedagogicalPipelineResult,
    run_pedagogical_pipeline,
)

from services.naima.response_service import (
    NaimaResponseDecision,
    build_local_response,
)


@dataclass
class NaimaTurnResult:
    """
    Résultat complet d'un tour traité par Naima.
    """

    message: str

    intent: Dict[str, Any]

    context: Dict[str, Any]

    validation: Dict[str, Any]

    pedagogical: Dict[str, Any]

    response: Dict[str, Any]

    equation_type: str

    handled_deterministically: bool

    requires_llm: bool

    objective_reached: bool

    def to_dict(
        self,
    ) -> Dict[str, Any]:

        return {
            "message": self.message,
            "intent": self.intent,
            "context": self.context,
            "validation": self.validation,
            "pedagogical": self.pedagogical,
            "response": self.response,
            "equation_type": (
                self.equation_type
            ),
            "handled_deterministically": (
                self.handled_deterministically
            ),
            "requires_llm": (
                self.requires_llm
            ),
            "objective_reached": (
                self.objective_reached
            ),
        }


class NaimaOrchestrator:
    """
    Orchestrateur métier principal de Naima.

    Cette classe ne dépend volontairement pas de Flask.

    Elle ne lit directement :
    - ni request ;
    - ni session ;
    - ni base de données.

    Pipeline :

        message élève
              ↓
        détection intention
              ↓
        résolution contexte
              ↓
        routage mathématique
              ↓
        validation
              ↓
        pipeline pédagogique
              ↓
        décision de réponse
              ↓
        NaimaTurnResult

    L'intention peut être :
    - détectée automatiquement ;
    - fournie par l'ancien système ;
    - fusionnée avec l'intention déterministe.
    """

    def __init__(
        self,
        *,
        math_router: Optional[
            NaimaMathRouter
        ] = None,
    ):

        self.math_router = (
            math_router
            or NaimaMathRouter()
        )

    def process_turn(
        self,
        *,
        message: str,

        intention: Optional[
            Dict[str, Any]
        ] = None,

        current_objective: Optional[
            str
        ] = None,

        current_equation: Optional[
            str
        ] = None,

        initial_equation: Optional[
            str
        ] = None,

        extracted_equation: Optional[
            str
        ] = None,

        last_teacher_question: str = "",

        conversation: Optional[
            List[Any]
        ] = None,

        previous_recovery_state: Optional[
            Dict[str, Any]
        ] = None,

        diagnostic: Optional[
            Dict[str, Any]
        ] = None,

        recent_hint_count: int = 0,

        first_message: bool = False,

        expected_answer: Any = None,

        lang: str = "fr",

        validation_for_recovery: Any = None,
    ) -> NaimaTurnResult:

        # ======================================================
        # 0. INTENTION
        # ======================================================

        has_active_problem = bool(
            current_equation
            or current_objective
        )

        deterministic_intent: NaimaIntent = (
            detect_intent(
                message,
                has_active_problem=(
                    has_active_problem
                ),
            )
        )

        resolved_intent: NaimaIntent = (
            merge_intent(
                deterministic_intent=(
                    deterministic_intent
                ),
                external_intent=(
                    intention
                ),
            )
        )

        intention_resolue = (
            resolved_intent.to_dict()
        )

        # ======================================================
        # 1. CONTEXTE
        # ======================================================

        context: NaimaMathContext = (
            build_math_context(
                message=message,

                current_objective=(
                    current_objective
                ),

                current_equation=(
                    current_equation
                ),

                initial_equation=(
                    initial_equation
                ),

                extracted_equation=(
                    extracted_equation
                ),
            )
        )

        equation = (
            context.current_equation
        )

        # ======================================================
        # 2. VALIDATION MATHÉMATIQUE
        # ======================================================
        #
        # IMPORTANT :
        #
        # Lorsqu'un élève présente un NOUVEAU problème :
        #
        #     "resoudre 3x=5"
        #
        # l'équation extraite ne constitue pas une réponse
        # de l'élève.
        #
        # On ne doit donc pas envoyer ce message au MathRouter
        # comme s'il s'agissait d'une transformation de 3*x=5.
        #
        # Sinon ValidationEngine peut conclure à tort :
        #
        #     equation_equivalence
        #     result_correct = True
        #
        # parce que l'équation de l'énoncé est évidemment
        # équivalente à elle-même.
        #
        # Dans ce cas on produit une validation neutre :
        #
        #     new_problem_presented
        #
        # Le pipeline pédagogique peut ensuite demander au LLM
        # de formuler la première question socratique.
        # ======================================================

        if (
            context.is_new_problem
            and intention_resolue.get("type_demande")
            == "probleme_a_resoudre"
        ):
            if equation:
                context.current_objective = (
                    f"resoudre {equation}"
                )

            validation = {
                "verdict": "uncertain",
                "confidence": 1.0,
                "method": (
                    "new_problem_presented"
                ),
                "result_correct": None,
                "reasoning_correct": None,
                "error_type": None,
                "requires_review": False,
                "reason": (
                    "L'élève vient de présenter un nouveau "
                    "problème. L'énoncé ne doit pas être "
                    "interprété comme une réponse ni comme "
                    "une transformation déjà effectuée."
                ),
                "details": {
                    "new_problem": True,
                    "equation": (
                        equation
                    ),
                    "equation_type": (
                        context.equation_type
                    ),
                },
            }

        elif equation:

            validation = (
                self.math_router.validate(
                    student_answer=(
                        message
                    ),

                    equation=equation,

                    teacher_question=(
                        last_teacher_question
                    ),

                    intent=(
                        intention_resolue.get(
                            "type_demande"
                        )
                    ),

                    expected_answer=(
                        expected_answer
                    ),
                )
            )

        else:

            validation = {
                "verdict": "uncertain",
                "confidence": 0.0,
                "method": (
                    "no_math_context"
                ),
                "result_correct": None,
                "reasoning_correct": None,
                "error_type": None,
                "requires_review": True,
                "reason": (
                    "Aucune équation courante "
                    "n'est disponible."
                ),
                "details": {},
            }

        # ======================================================
        # 2B. RÉPÉTITION DE L'ÉQUATION SANS PROGRESSION
        # ======================================================

        recovery_active = bool(
            (
                previous_recovery_state
                or {}
            ).get(
                "erreur_active"
            )
            or (
                previous_recovery_state
                or {}
            ).get(
                "blocage_actif"
            )
        )

        repeated_current_equation = bool(
            recovery_active
            and not context.is_new_problem
            and context.context_preserved
            and context.extracted_equation
            and context.current_equation
            and (
                context.extracted_equation
                == context.current_equation
            )
        )

        if repeated_current_equation:

            validation = {
                "verdict": "uncertain",
                "confidence": 0.0,
                "method": (
                    "equation_repetition_no_progress"
                ),
                "result_correct": None,
                "reasoning_correct": None,
                "error_type": None,
                "requires_review": False,
                "reason": (
                    "L'élève répète exactement "
                    "l'équation courante. Cette répétition "
                    "est mathématiquement cohérente mais "
                    "ne constitue pas une progression."
                ),
                "details": {
                    "repetition_equation_courante": True,
                    "equation_repetee": (
                        context.extracted_equation
                    ),
                    "equation_courante": (
                        context.current_equation
                    ),
                },
            }

        # ======================================================
        # 3. PIPELINE PÉDAGOGIQUE
        # ======================================================

        pedagogical: (
            PedagogicalPipelineResult
        ) = run_pedagogical_pipeline(

            question=message,

            validation=validation,

            intention=(
                intention_resolue
            ),

            conversation=(
                conversation
            ),

            previous_recovery_state=(
                previous_recovery_state
            ),

            diagnostic=(
                diagnostic
                or {}
            ),

            last_teacher_question=(
                last_teacher_question
            ),

            recent_hint_count=(
                recent_hint_count
            ),

            first_message=(
                first_message
            ),

            lang=lang,

            validation_for_recovery=(
                validation_for_recovery
            ),
        )

        # ======================================================
        # 4. DÉCISION DE RÉPONSE
        # ======================================================

        response: (
            NaimaResponseDecision
        ) = build_local_response(

            validation=validation,

            pedagogical_policy=(
                pedagogical
                .pedagogical_policy
            ),

            equation=equation,

            student_answer=(
                message
            ),

            last_teacher_question=(
                last_teacher_question
            ),

            lang=lang,
        )

        # ======================================================
        # 5. NORMALISATION DU RÉSULTAT DE VALIDATION
        # ======================================================

        if isinstance(
            validation,
            dict,
        ):

            validation_dict = dict(
                validation
            )

        elif hasattr(
            validation,
            "to_dict",
        ):

            try:

                validation_dict = (
                    validation.to_dict()
                )

            except Exception:

                validation_dict = {}

        else:

            validation_dict = {}

        # ======================================================
        # 6. ÉTAT GLOBAL DU TOUR
        # ======================================================

        handled_deterministically = (
            response.use_local_response
            and not response.use_llm
        )

        # ======================================================
        # 7. RÉSULTAT FINAL
        # ======================================================

        return NaimaTurnResult(

            message=message,

            intent=(
                intention_resolue
            ),

            context=(
                context.to_dict()
            ),

            validation=(
                validation_dict
            ),

            pedagogical=(
                pedagogical.to_dict()
            ),

            response=(
                response.to_dict()
            ),

            equation_type=(
                context.equation_type
            ),

            handled_deterministically=(
                handled_deterministically
            ),

            requires_llm=(
                response.use_llm
            ),

            objective_reached=(
                response.objective_reached
            ),
        )