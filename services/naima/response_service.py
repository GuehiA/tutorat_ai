from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class NaimaResponseDecision:
    response_type: str

    use_local_response: bool
    use_llm: bool

    text: Optional[str]

    objective_reached: bool
    keep_exercise_open: bool

    solution_leakage_blocked: bool

    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "response_type": self.response_type,
            "use_local_response": self.use_local_response,
            "use_llm": self.use_llm,
            "text": self.text,
            "objective_reached": self.objective_reached,
            "keep_exercise_open": self.keep_exercise_open,
            "solution_leakage_blocked": self.solution_leakage_blocked,
            "reason": self.reason,
        }


def _validation_to_dict(
    validation: Any,
) -> Dict[str, Any]:

    if validation is None:
        return {}

    if isinstance(
        validation,
        dict,
    ):
        return dict(
            validation
        )

    if hasattr(
        validation,
        "to_dict",
    ):
        try:
            return validation.to_dict()
        except Exception:
            pass

    return {
        "verdict": getattr(
            validation,
            "verdict",
            None,
        ),
        "confidence": getattr(
            validation,
            "confidence",
            0.0,
        ),
        "method": getattr(
            validation,
            "method",
            None,
        ),
        "result_correct": getattr(
            validation,
            "result_correct",
            None,
        ),
        "reasoning_correct": getattr(
            validation,
            "reasoning_correct",
            None,
        ),
        "error_type": getattr(
            validation,
            "error_type",
            None,
        ),
        "reason": getattr(
            validation,
            "reason",
            None,
        ),
        "details": getattr(
            validation,
            "details",
            {},
        ),
    }


def _policy_to_dict(
    pedagogical_policy: Optional[
        Dict[str, Any]
    ],
) -> Dict[str, Any]:

    return dict(
        pedagogical_policy
        or {}
    )


def _format_equation(
    equation: Optional[str],
) -> str:

    if not equation:
        return ""

    return (
        str(equation)
        .replace(
            "**2",
            "²",
        )
        .replace(
            "*",
            "",
        )
    )


def _format_solution(
    value: Any,
) -> str:

    if value is None:
        return ""

    return str(
        value
    )


def build_local_response(
    *,
    validation: Any,
    pedagogical_policy: Dict[str, Any],
    equation: Optional[str] = None,
    student_answer: str = "",
    last_teacher_question: str = "",
    lang: str = "fr",
) -> NaimaResponseDecision:
    """
    Décide si Naima peut répondre localement
    sans LLM.

    Principe fondamental :
    connaître une solution n'implique pas
    forcément qu'on peut la révéler.
    """

    validation_dict = (
        _validation_to_dict(
            validation
        )
    )

    policy = _policy_to_dict(
        pedagogical_policy
    )

    verdict = (
        validation_dict.get(
            "verdict"
        )
        or "uncertain"
    )

    method = (
        validation_dict.get(
            "method"
        )
        or ""
    )

    result_correct = (
        validation_dict.get(
            "result_correct"
        )
    )

    reasoning_correct = (
        validation_dict.get(
            "reasoning_correct"
        )
    )

    error_type = (
        validation_dict.get(
            "error_type"
        )
    )

    details = (
        validation_dict.get(
            "details"
        )
        or {}
    )

    strategy = (
        policy.get(
            "strategie"
        )
        or ""
    )

    may_reveal_solution = bool(
        policy.get(
            "peut_reveler_solution",
            False,
        )
    )

    formatted_equation = (
        _format_equation(
            equation
        )
    )

    # ==========================================================
    # 1. RÉPONSE FINALE QUADRATIQUE CORRECTE
    # ==========================================================

    if (
        verdict == "correct"
        and method
        == "quadratic_solution_set"
        and result_correct is True
    ):

        return NaimaResponseDecision(
            response_type=(
                "final_correct"
            ),

            use_local_response=True,
            use_llm=False,

            text=(
                "Exact. Tes solutions sont correctes. "
                "L’équation est résolue. — Naima ✨"
            ),

            objective_reached=True,
            keep_exercise_open=False,

            solution_leakage_blocked=False,

            reason=(
                "quadratic_solution_set_proved_correct"
            ),
        )

    # ==========================================================
    # 1B. RÉPONSE FINALE D'INÉQUATION CORRECTE
    # ==========================================================

    if (
        verdict == "correct"
        and method == "inequality_solution"
        and result_correct is True
    ):

        return NaimaResponseDecision(
            response_type=(
                "final_correct"
            ),

            use_local_response=True,
            use_llm=False,

            text=(
                "Exact. Ton inéquation finale représente "
                "correctement l’ensemble des solutions. "
                "L’exercice est résolu. — Naima ✨"
            ),

            objective_reached=True,
            keep_exercise_open=False,

            solution_leakage_blocked=False,

            reason=(
                "inequality_solution_proved_correct"
            ),
        )

    # ==========================================================
    # 1C. RÉPONSE FINALE LINÉAIRE CORRECTE
    # ==========================================================
    #
    # Cas :
    #
    #     équation active : 3*x=5
    #     élève : x=5/3
    #
    # ValidationEngine a déjà prouvé localement que la valeur
    # proposée vérifie l'équation.
    #
    # À ce stade :
    # - aucune intervention LLM n'est nécessaire ;
    # - l'objectif est atteint ;
    # - l'exercice peut être fermé ;
    # - Naima peut reconnaître le succès sans révéler une
    #   nouvelle information mathématique.
    # ==========================================================

    if (
        verdict == "correct"
        and method == "equation_solution"
        and result_correct is True
    ):

        if lang == "en":

            text = (
                "🎉 Exactly! Your value of x is correct. "
                "You have solved the equation successfully. "
                "— Naima ✨"
            )

        else:

            text = (
                "🎉 Exact ! Ta valeur de x est correcte. "
                "Tu as bien résolu l’équation. "
                "— Naima ✨"
            )

        return NaimaResponseDecision(
            response_type=(
                "final_correct"
            ),

            use_local_response=True,
            use_llm=False,

            text=text,

            objective_reached=True,
            keep_exercise_open=False,

            solution_leakage_blocked=False,

            reason=(
                "correct_linear_equation_solution"
            ),
        )

    # ==========================================================
    # 2. COEFFICIENTS QUADRATIQUES CORRECTS
    #
    # Le moteur connaît déjà Δ et les solutions,
    # mais Naima ne doit pas les révéler.
    # ==========================================================

    if (
        verdict == "correct"
        and method
        == "quadratic_coefficients"
        and reasoning_correct is True
    ):

        return NaimaResponseDecision(
            response_type=(
                "quadratic_coefficients_correct"
            ),

            use_local_response=True,
            use_llm=False,

            text=(
                "Oui, tu as correctement identifié "
                "les coefficients. Quelle est maintenant "
                "l’expression du discriminant Δ = b² - 4ac "
                "avec ces valeurs ? — Naima ✨"
            ),

            objective_reached=False,
            keep_exercise_open=True,

            solution_leakage_blocked=True,

            reason=(
                "coefficients_validated_without_revealing_discriminant"
            ),
        )

    # ==========================================================
    # 3. MÉTHODE QUADRATIQUE CORRECTE
    #
    # L'élève choisit la formule quadratique.
    # On lui demande l'étape suivante.
    # ==========================================================

    if (
        verdict == "correct"
        and method
        == "quadratic_method_choice"
        and reasoning_correct is True
    ):

        return NaimaResponseDecision(
            response_type=(
                "quadratic_method_correct"
            ),

            use_local_response=True,
            use_llm=False,

            text=(
                "Oui, la formule quadratique convient ici. "
                "Commence par identifier les coefficients "
                "a, b et c de l’équation. — Naima ✨"
            ),

            objective_reached=False,
            keep_exercise_open=True,

            solution_leakage_blocked=True,

            reason=(
                "quadratic_method_validated_socratically"
            ),
        )

    # ==========================================================
    # 4. SOLUTION QUADRATIQUE INCORRECTE
    # ==========================================================

    if (
        verdict == "incorrect"
        and method
        == "quadratic_solution_set"
    ):

        missing = (
            details.get(
                "missing_solutions"
            )
            or []
        )

        extra = (
            details.get(
                "extra_solutions"
            )
            or []
        )

        # Ne pas révéler la solution manquante.
        if extra:

            text = (
                "Au moins une des valeurs proposées "
                "ne vérifie pas l’équation. "
                "Choisis une de tes valeurs et remplace x "
                "dans l’équation pour la vérifier. — Naima ✨"
            )

        elif missing:

            text = (
                "La valeur que tu as proposée peut être "
                "correcte, mais ton ensemble de solutions "
                "n’est pas encore complet. "
                "Reviens au calcul du discriminant ou à la "
                "formule quadratique pour chercher l’autre "
                "possibilité. — Naima ✨"
            )

        else:

            text = (
                "Tes solutions ne correspondent pas encore "
                "exactement à celles de l’équation. "
                "À quelle étape de ton calcul peux-tu "
                "vérifier les valeurs obtenues ? — Naima ✨"
            )

        return NaimaResponseDecision(
            response_type=(
                "quadratic_solution_error"
            ),

            use_local_response=True,
            use_llm=False,

            text=text,

            objective_reached=False,
            keep_exercise_open=True,

            solution_leakage_blocked=True,

            reason=(
                "quadratic_error_localized_without_solution_leak"
            ),
        )

    # ==========================================================
    # 5. OPÉRATION FINALE LINÉAIRE
    #
    # V1.3.2 :
    # le moteur sait x=..., mais l'élève doit
    # produire lui-même la conclusion.
    # ==========================================================

    if (
        verdict == "correct"
        and method == "reasoning_operation"
        and reasoning_correct is True
    ):

        transformed_equation = (
            details.get(
                "transformed_equation"
            )
            or ""
        )

        expected_result = (
            details.get(
                "expected_result"
            )
        )

        transformed_is_final = (
            transformed_equation
            .replace(
                " ",
                ""
            )
            .startswith(
                "x="
            )
        )

        if (
            transformed_is_final
            and not may_reveal_solution
        ):

            operation_type = (
                details.get(
                    "operation_type"
                )
                or ""
            )

            operation_value = (
                details.get(
                    "operation_value"
                )
                or ""
            )

            if (
                operation_type
                == "divide"
                and operation_value
            ):

                text = (
                    f"Oui, diviser les deux membres par "
                    f"{operation_value} est la bonne opération"
                )

                if formatted_equation:

                    text += (
                        f" pour {formatted_equation}"
                    )

                text += (
                    ". Effectue maintenant cette division "
                    "toi-même : quelle valeur obtiens-tu "
                    "pour x ? — Naima ✨"
                )

            else:

                text = (
                    "Oui, cette opération isole correctement x. "
                    "Effectue maintenant le dernier calcul "
                    "toi-même : quelle valeur obtiens-tu "
                    "pour x ? — Naima ✨"
                )

            return NaimaResponseDecision(
                response_type=(
                    "final_operation_socratic"
                ),

                use_local_response=True,
                use_llm=False,

                text=text,

                objective_reached=False,
                keep_exercise_open=True,

                solution_leakage_blocked=(
                    expected_result
                    is not None
                ),

                reason=(
                    "final_linear_result_kept_internal"
                ),
            )

    
    # ==========================================================
    # 5B. OPÉRATION LINÉAIRE INCORRECTE PROUVÉE
    #
    # Une erreur déterministe ne doit pas être envoyée au LLM.
    #
    # Exemples :
    #   3x=5
    #   "je divise les deux membres par 2"
    #
    # Le moteur sait déjà que l'opération est incorrecte.
    # Naima localise l'erreur sans révéler la bonne réponse.
    # ==========================================================

    if (
        verdict == "incorrect"
        and method in {
            "reasoning_operation",
            "reasoning_linear_transformation",
        }
        and reasoning_correct is False
        and error_type in {
            "wrong_operation_value",
            "wrong_operation",
            "non_progressing_operation",
        }
    ):

        operation_type = (
            details.get(
                "operation_type"
            )
            or ""
        )

        operation_value = (
            details.get(
                "operation_value"
            )
            or ""
        )

        # ------------------------------------------------------
        # FRANÇAIS
        # ------------------------------------------------------

        if lang != "en":

            if (
                error_type
                == "wrong_operation_value"
                and operation_type == "divide"
            ):
                text = (
                    "Cette division n’est pas correcte "
                    "pour l’étape actuelle"
                )

                if formatted_equation:
                    text += (
                        f" : {formatted_equation}"
                    )

                if operation_value:
                    text += (
                        f". Diviser par {operation_value} "
                        "ne permet pas d’éliminer "
                        "le coefficient de x"
                    )

                text += (
                    ". Par quel nombre dois-tu réellement "
                    "diviser les deux membres pour isoler x ? "
                    "— Naima ✨"
                )

            elif (
                error_type
                == "non_progressing_operation"
            ):
                text = (
                    "Cette opération est possible, mais elle "
                    "ne fait pas progresser l’isolement de x"
                )

                if formatted_equation:
                    text += (
                        f" dans {formatted_equation}"
                    )

                text += (
                    ". Quelle opération permettrait réellement "
                    "d’éliminer le coefficient de x ? "
                    "— Naima ✨"
                )

            else:
                text = (
                    "Cette opération n’est pas correcte "
                    "pour l’étape actuelle"
                )

                if formatted_equation:
                    text += (
                        f" : {formatted_equation}"
                    )

                text += (
                    ". Quelle opération dois-tu appliquer "
                    "aux deux membres pour continuer à isoler x ? "
                    "— Naima ✨"
                )

        # ------------------------------------------------------
        # ANGLAIS
        # ------------------------------------------------------

        else:

            if (
                error_type
                == "wrong_operation_value"
                and operation_type == "divide"
            ):
                text = (
                    "That division is not correct "
                    "for the current step"
                )

                if formatted_equation:
                    text += (
                        f": {formatted_equation}"
                    )

                if operation_value:
                    text += (
                        f". Dividing by {operation_value} "
                        "does not eliminate the coefficient of x"
                    )

                text += (
                    ". What number should you actually divide "
                    "both sides by to isolate x? — Naima ✨"
                )

            elif (
                error_type
                == "non_progressing_operation"
            ):
                text = (
                    "That operation is mathematically possible, "
                    "but it does not move you closer to isolating x"
                )

                if formatted_equation:
                    text += (
                        f" in {formatted_equation}"
                    )

                text += (
                    ". What operation would eliminate "
                    "the coefficient of x? — Naima ✨"
                )

            else:
                text = (
                    "That operation is not correct "
                    "for the current step"
                )

                if formatted_equation:
                    text += (
                        f": {formatted_equation}"
                    )

                text += (
                    ". What operation should you apply "
                    "to both sides to continue isolating x? "
                    "— Naima ✨"
                )

        return NaimaResponseDecision(
            response_type=(
                "linear_operation_error"
            ),

            use_local_response=True,
            use_llm=False,

            text=text,

            objective_reached=False,
            keep_exercise_open=True,

            solution_leakage_blocked=True,

            reason=(
                "deterministic_linear_operation_error"
            ),
        )


    # ==========================================================
    # 5C. INÉQUATION : INVERSION DU SENS OUBLIÉE
    # ==========================================================

    if (
        verdict == "incorrect"
        and method == "inequality_direction_rule"
        and reasoning_correct is False
        and error_type
        == "missing_inequality_direction_flip"
    ):

        if lang == "en":

            text = (
                "Dividing or multiplying an inequality by a "
                "negative number requires reversing the "
                "inequality sign. Apply that rule now and "
                "write the inequality you obtain. — Naima ✨"
            )

        else:

            text = (
                "Comme tu divises ou multiplies une inéquation "
                "par un nombre négatif, il faut inverser le sens "
                "du symbole d’inégalité. Applique maintenant "
                "cette règle et écris l’inéquation obtenue. "
                "— Naima ✨"
            )

        return NaimaResponseDecision(
            response_type=(
                "inequality_direction_flip_missing"
            ),

            use_local_response=True,
            use_llm=False,

            text=text,

            objective_reached=False,
            keep_exercise_open=True,

            solution_leakage_blocked=True,

            reason=(
                "missing_inequality_direction_flip"
            ),
        )

    # ==========================================================
    # 5D. INÉQUATION : RÈGLE D'INVERSION CORRECTEMENT APPLIQUÉE
    # ==========================================================

    if (
        verdict == "correct"
        and method == "inequality_direction_rule"
        and reasoning_correct is True
    ):

        if lang == "en":

            text = (
                "Yes. Because you are dividing or multiplying "
                "by a negative number, the inequality sign "
                "must reverse. Now carry out the calculation "
                "yourself and write the inequality you obtain. "
                "— Naima ✨"
            )

        else:

            text = (
                "Oui. Comme tu divises ou multiplies par un "
                "nombre négatif, il faut inverser le sens de "
                "l’inégalité. Effectue maintenant le calcul "
                "toi-même et écris l’inéquation obtenue. "
                "— Naima ✨"
            )

        return NaimaResponseDecision(
            response_type=(
                "inequality_direction_rule_correct"
            ),

            use_local_response=True,
            use_llm=False,

            text=text,

            objective_reached=False,
            keep_exercise_open=True,

            solution_leakage_blocked=True,

            reason=(
                "inequality_direction_rule_validated"
            ),
        )

    # ==========================================================
    # 5E. EXPRESSION DU DISCRIMINANT CORRECTE
    # ==========================================================

    if (
        verdict == "correct"
        and method
        == "quadratic_discriminant_expression"
    ):

        return NaimaResponseDecision(
            response_type=(
                "quadratic_discriminant_expression_correct"
            ),
            use_local_response=True,
            use_llm=False,
            text=(
                "C’est exact, tu as correctement écrit "
                "l’expression du discriminant. "
                "Effectue maintenant le calcul : "
                "quelle valeur obtiens-tu pour Δ ? "
                "— Naima ✨"
            ),
            objective_reached=False,
            keep_exercise_open=True,
            solution_leakage_blocked=True,
            reason=(
                "quadratic_discriminant_expression_validated"
            ),
        )

    # ==========================================================
    # 5F. VALEUR DU DISCRIMINANT CORRECTE
    # ==========================================================

    if (
        verdict == "correct"
        and method
        == "quadratic_discriminant_value"
        and result_correct is True
    ):

        return NaimaResponseDecision(
            response_type=(
                "quadratic_discriminant_value_correct"
            ),
            use_local_response=True,
            use_llm=False,
            text=(
                "Oui, cette valeur du discriminant est correcte. "
                "Que peux-tu déduire du signe de Δ concernant "
                "le nombre de solutions de l’équation ? "
                "— Naima ✨"
            ),
            objective_reached=False,
            keep_exercise_open=True,
            solution_leakage_blocked=True,
            reason=(
                "quadratic_discriminant_value_validated"
            ),
        )

    # ==========================================================
    # 5G. INTERPRÉTATION DU DISCRIMINANT CORRECTE
    # ==========================================================

    if (
        verdict == "correct"
        and method
        == "quadratic_discriminant_interpretation"
        and reasoning_correct is True
    ):

        return NaimaResponseDecision(
            response_type=(
                "quadratic_discriminant_interpretation_correct"
            ),
            use_local_response=True,
            use_llm=False,
            text=(
                "Exact. Ton interprétation du discriminant "
                "est correcte. Utilise maintenant la formule "
                "quadratique avec a, b et Δ pour déterminer "
                "les solutions. — Naima ✨"
            ),
            objective_reached=False,
            keep_exercise_open=True,
            solution_leakage_blocked=True,
            reason=(
                "quadratic_discriminant_interpretation_validated"
            ),
        )

    # ==========================================================
    # 5H. ERREUR SUR LE DISCRIMINANT
    # ==========================================================

    if (
        verdict == "incorrect"
        and method in {
            "quadratic_discriminant_expression",
            "quadratic_discriminant_value",
            "quadratic_discriminant_interpretation",
        }
    ):

        return NaimaResponseDecision(
            response_type=(
                "quadratic_discriminant_error"
            ),
            use_local_response=True,
            use_llm=False,
            text=(
                "Il y a une erreur à cette étape du "
                "discriminant. Reprends Δ = b² - 4ac "
                "avec les coefficients déjà identifiés "
                "et vérifie ton calcul ou son interprétation. "
                "— Naima ✨"
            ),
            objective_reached=False,
            keep_exercise_open=True,
            solution_leakage_blocked=True,
            reason=(
                "quadratic_discriminant_error_localized"
            ),
        )


    # ==========================================================
    # 6. RÉSULTAT CORRECT MAIS RAISONNEMENT FAUX
    # ==========================================================

    if (
        result_correct is True
        and reasoning_correct is False
    ):

        return NaimaResponseDecision(
            response_type=(
                "reasoning_conflict"
            ),

            use_local_response=True,
            use_llm=False,

            text=(
                "Ton résultat est correct, mais l’opération "
                "que tu as décrite ne permet pas d’y arriver "
                "correctement. Reviens à l’équation courante : "
                "quelle opération dois-tu réellement appliquer "
                "aux deux membres ? — Naima ✨"
            ),

            objective_reached=False,
            keep_exercise_open=True,

            solution_leakage_blocked=True,

            reason=(
                "correct_result_wrong_reasoning"
            ),
        )

    # ==========================================================
    # 7. MAINTIEN DE CORRECTION APRÈS SIMPLE RÉPÉTITION
    # ==========================================================

    if (
        strategy
        == "maintien_correction"
    ):

        text = (
            "Oui, cette équation est bien notre étape actuelle"
        )

        if formatted_equation:

            text += (
                f" : {formatted_equation}"
            )

        text += (
            ". Mais cela ne corrige pas encore l’étape "
            "précédente. Quelle opération permet réellement "
            "de poursuivre la résolution ? — Naima ✨"
        )

        return NaimaResponseDecision(
            response_type=(
                "maintain_correction"
            ),

            use_local_response=True,
            use_llm=False,

            text=text,

            objective_reached=False,
            keep_exercise_open=True,

            solution_leakage_blocked=True,

            reason=(
                "equation_repetition_without_progress"
            ),
        )

    # ==========================================================
    # 7B. INÉQUATION FINALE INCORRECTE
    # ==========================================================

    if (
        verdict == "incorrect"
        and method == "inequality_solution"
        and result_correct is False
    ):

        return NaimaResponseDecision(
            response_type=(
                "inequality_solution_error"
            ),

            use_local_response=True,
            use_llm=False,

            text=(
                "Ta réponse finale ne représente pas encore "
                "le bon ensemble de solutions. "
                "Vérifie particulièrement le sens du symbole "
                "d’inégalité et l’opération effectuée sur les "
                "deux membres. — Naima ✨"
            ),

            objective_reached=False,
            keep_exercise_open=True,

            solution_leakage_blocked=True,

            reason=(
                "wrong_inequality_solution_without_revealing_answer"
            ),
        )

    # ==========================================================
    # 8. INCERTAIN
    #
    # Ici on laisse le LLM produire le guidage,
    # avec politique + garde-fou.
    # ==========================================================

    if verdict in {
        "uncertain",
        None,
    }:

        return NaimaResponseDecision(
            response_type=(
                "llm_guidance"
            ),

            use_local_response=False,
            use_llm=True,

            text=None,

            objective_reached=False,
            keep_exercise_open=True,

            solution_leakage_blocked=False,

            reason=(
                "deterministic_validation_inconclusive"
            ),
        )

    # ==========================================================
    # 9. FALLBACK
    # ==========================================================

    return NaimaResponseDecision(
        response_type=(
            "llm_fallback"
        ),

        use_local_response=False,
        use_llm=True,

        text=None,

        objective_reached=False,
        keep_exercise_open=True,

        solution_leakage_blocked=False,

        reason=(
            "no_special_local_response_rule"
        ),
    )