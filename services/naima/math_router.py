from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from services.naima.math_parser_service import (
    classify_equation,
)

from services.naima.linear_equation_service import (
    LinearEquationService,
)

from services.naima.quadratic_equation_service import (
    analyze_quadratic,
    detect_method_statement,
    validate_coefficients,
    validate_discriminant,
    validate_discriminant_interpretation,
    validate_solution_set,
)

from services.naima.inequality_service import (
    analyze_inequality,
    detect_direction_rule_statement,
    extract_student_inequality,
    is_inequality,
    solve_inequality,
    validate_final_inequality,
)


@dataclass
class MathRouteDecision:
    domain: str
    equation_type: str
    equation: Optional[str]

    handler: str
    confidence: float

    reason: str


class NaimaMathRouter:

    def __init__(
        self,
        *,
        linear_service: Optional[
            LinearEquationService
        ] = None,
    ):

        self.linear_service = (
            linear_service
            or LinearEquationService()
        )

    # ==========================================================
    # ROUTAGE
    # ==========================================================

    def detect_route(
        self,
        *,
        equation: Optional[str],
    ) -> MathRouteDecision:

        if not equation:
            return MathRouteDecision(
                domain="mathematics",
                equation_type="unknown",
                equation=None,
                handler="fallback",
                confidence=0.0,
                reason="no_equation",
            )

        # ------------------------------------------------------
        # PRIORITÉ AUX INÉQUATIONS
        # ------------------------------------------------------

        if is_inequality(
            equation
        ):
            analysis = (
                analyze_inequality(
                    equation
                )
            )

            degree = (
                analysis.get(
                    "degree"
                )
            )

            return MathRouteDecision(
                domain="mathematics",
                equation_type=(
                    "inequality"
                ),
                equation=equation,
                handler=(
                    "inequality_service"
                ),
                confidence=1.0,
                reason=(
                    f"inequality_degree_{degree}"
                    if degree is not None
                    else "inequality_detected"
                ),
            )

        # ------------------------------------------------------
        # ÉQUATIONS
        # ------------------------------------------------------

        equation_type = (
            classify_equation(
                equation
            )
        )

        if equation_type == "linear":

            return MathRouteDecision(
                domain="mathematics",
                equation_type="linear",
                equation=equation,
                handler=(
                    "linear_equation_service"
                ),
                confidence=1.0,
                reason=(
                    "degree_one_equation"
                ),
            )

        if equation_type == "quadratic":

            return MathRouteDecision(
                domain="mathematics",
                equation_type="quadratic",
                equation=equation,
                handler=(
                    "quadratic_equation_service"
                ),
                confidence=1.0,
                reason=(
                    "degree_two_equation"
                ),
            )

        return MathRouteDecision(
            domain="mathematics",
            equation_type=(
                equation_type
            ),
            equation=equation,
            handler="fallback",
            confidence=0.5,
            reason=(
                "unsupported_equation_type"
            ),
        )

    # ==========================================================
    # VALIDATION
    # ==========================================================

    def validate(
        self,
        *,
        student_answer: str,
        equation: str,
        teacher_question: str = "",
        intent: Optional[str] = None,
        expected_answer: Any = None,
        **kwargs,
    ):

        decision = self.detect_route(
            equation=equation
        )

        # ------------------------------------------------------
        # LINÉAIRE
        # ------------------------------------------------------

        if (
            decision.equation_type
            == "linear"
        ):

            return (
                self.linear_service.validate(
                    student_answer=(
                        student_answer
                    ),
                    equation=equation,
                    teacher_question=(
                        teacher_question
                    ),
                    expected_answer=(
                        expected_answer
                    ),
                    **kwargs,
                )
            )

        # ------------------------------------------------------
        # QUADRATIQUE
        # ------------------------------------------------------

        if (
            decision.equation_type
            == "quadratic"
        ):

            return (
                self._validate_quadratic(
                    student_answer=(
                        student_answer
                    ),
                    equation=equation,
                    teacher_question=(
                        teacher_question
                    ),
                    intent=intent,
                )
            )

        # ------------------------------------------------------
        # INÉQUATION
        # ------------------------------------------------------

        if (
            decision.equation_type
            == "inequality"
        ):

            return (
                self._validate_inequality(
                    student_answer=(
                        student_answer
                    ),
                    inequality=equation,
                    teacher_question=(
                        teacher_question
                    ),
                    intent=intent,
                )
            )

        # ------------------------------------------------------
        # FALLBACK
        # ------------------------------------------------------

        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "naima_math_router"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": None,
            "requires_review": True,
            "reason": (
                "No deterministic handler "
                "is available for this "
                "equation type."
            ),
            "details": {
                "route": (
                    decision.__dict__
                ),
            },
        }

    # ==========================================================
    # QUADRATIQUE
    # ==========================================================

    def _validate_quadratic(
        self,
        *,
        student_answer: str,
        equation: str,
        teacher_question: str,
        intent: Optional[str],
    ):

        analysis = (
            analyze_quadratic(
                equation
            )
        )

        lower_answer = (
            student_answer
            or ""
        ).lower()

        # ------------------------------------------------------
        # COEFFICIENTS a, b, c
        # ------------------------------------------------------

        if (
            "a="
            in lower_answer
            and "b="
            in lower_answer
            and "c="
            in lower_answer
        ):

            return (
                validate_coefficients(
                    equation,
                    student_answer,
                )
            )

        # ------------------------------------------------------
        # DISCRIMINANT :
        # EXPRESSION, VALEUR OU INTERPRÉTATION
        # ------------------------------------------------------
        #
        # Exemples :
        #
        #   delta = (-5)^2 - 4*3*2
        #   delta = 1
        #   le discriminant est positif donc 2 solutions
        #
        # On essaie d'abord de valider l'expression / valeur.
        # Si cela reste incertain, on essaie l'interprétation
        # du signe de Δ.
        # ------------------------------------------------------

        if (
            "delta"
            in lower_answer
            or "δ"
            in lower_answer
            or "Δ"
            in student_answer
            or "discriminant"
            in lower_answer
        ):

            discriminant_validation = (
                validate_discriminant(
                    equation,
                    student_answer,
                )
            )

            if (
                discriminant_validation.get(
                    "verdict"
                )
                != "uncertain"
            ):
                return (
                    discriminant_validation
                )

            interpretation_validation = (
                validate_discriminant_interpretation(
                    equation,
                    student_answer,
                )
            )

            if (
                interpretation_validation.get(
                    "verdict"
                )
                != "uncertain"
            ):
                return (
                    interpretation_validation
                )

        # ------------------------------------------------------
        # ENSEMBLE DE SOLUTIONS
        # ------------------------------------------------------

        if "x=" in lower_answer:

            solution_validation = (
                validate_solution_set(
                    equation,
                    student_answer,
                )
            )

            if (
                solution_validation.get(
                    "verdict"
                )
                != "uncertain"
            ):
                return (
                    solution_validation
                )

        # ------------------------------------------------------
        # CHOIX DE MÉTHODE
        # ------------------------------------------------------

        method_statement = (
            detect_method_statement(
                student_answer
            )
        )

        if method_statement.get(
            "detected"
        ):

            return {
                "verdict": "correct",
                "confidence": (
                    method_statement.get(
                        "confidence",
                        0.9,
                    )
                ),
                "method": (
                    "quadratic_method_choice"
                ),
                "result_correct": None,
                "reasoning_correct": True,
                "error_type": None,
                "requires_review": False,
                "reason": (
                    "The proposed method "
                    "is appropriate for the "
                    "quadratic equation."
                ),
                "details": {
                    **analysis,
                    **method_statement,
                },
            }

        # ------------------------------------------------------
        # PAS DE CONCLUSION DÉTERMINISTE
        # ------------------------------------------------------

        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "quadratic_no_deterministic_conclusion"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": None,
            "requires_review": True,
            "reason": (
                "The quadratic service "
                "cannot yet prove this "
                "specific reasoning step."
            ),
            "details": analysis,
        }

    # ==========================================================
    # INÉQUATIONS
    # ==========================================================

    def _validate_inequality(
        self,
        *,
        student_answer: str,
        inequality: str,
        teacher_question: str,
        intent: Optional[str],
    ):

        analysis = (
            analyze_inequality(
                inequality
            )
        )

        solved = (
            solve_inequality(
                inequality
            )
        )

        # ------------------------------------------------------
        # RÉPONSE FINALE D'INÉQUATION
        # ------------------------------------------------------

        student_final_inequality = (
            extract_student_inequality(
                student_answer
            )
        )

        if student_final_inequality:

            final_validation = (
                validate_final_inequality(
                    inequality,
                    student_answer,
                )
            )

            if (
                final_validation.get(
                    "verdict"
                )
                != "uncertain"
            ):
                return final_validation

        # ------------------------------------------------------
        # RÈGLE D'INVERSION DU SENS
        # ------------------------------------------------------

        direction_rule = (
            detect_direction_rule_statement(
                student_answer
            )
        )

        if direction_rule.get(
            "detected"
        ):

            reasoning_correct = (
                direction_rule.get(
                    "reasoning_correct"
                )
            )

            if reasoning_correct is True:

                return {
                    "verdict": "correct",
                    "confidence": (
                        direction_rule.get(
                            "confidence",
                            0.98,
                        )
                    ),
                    "method": (
                        "inequality_direction_rule"
                    ),
                    "result_correct": None,
                    "reasoning_correct": True,
                    "error_type": None,
                    "requires_review": False,
                    "reason": (
                        "The learner correctly "
                        "applies the inequality "
                        "direction rule."
                    ),
                    "details": {
                        **analysis,
                        "solution_set": (
                            solved.get(
                                "solution_set"
                            )
                        ),
                        **direction_rule,
                    },
                }

            if reasoning_correct is False:

                return {
                    "verdict": "incorrect",
                    "confidence": (
                        direction_rule.get(
                            "confidence",
                            0.95,
                        )
                    ),
                    "method": (
                        "inequality_direction_rule"
                    ),
                    "result_correct": None,
                    "reasoning_correct": False,
                    "error_type": (
                        direction_rule.get(
                            "error_type"
                        )
                        or (
                            "incorrect_inequality_direction_rule"
                        )
                    ),
                    "requires_review": False,
                    "reason": (
                        "When multiplying or "
                        "dividing an inequality "
                        "by a negative quantity, "
                        "the inequality direction "
                        "must be reversed."
                    ),
                    "details": {
                        **analysis,
                        "solution_set": (
                            solved.get(
                                "solution_set"
                            )
                        ),
                        **direction_rule,
                    },
                }

        # ------------------------------------------------------
        # POUR LE MOMENT :
        # résultat final d'inéquation non validé ici.
        #
        # On reste prudent jusqu'à ce qu'on ajoute
        # un parseur déterministe de réponses :
        #
        # x > 4
        # x <= -3
        # ]4,+∞[
        # etc.
        # ------------------------------------------------------

        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "inequality_no_deterministic_conclusion"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": None,
            "requires_review": True,
            "reason": (
                "The inequality is supported, "
                "but this learner response "
                "cannot yet be proved "
                "deterministically."
            ),
            "details": {
                **analysis,
                "solution_set": (
                    solved.get(
                        "solution_set"
                    )
                ),
            },
        }