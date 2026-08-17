import sympy as sp

from validation.normalizer import AnswerNormalizer
from validation.result import ValidationResult


class EquationValidator:
    def __init__(self):
        self.normalizer = AnswerNormalizer()

    def _parse_equation(self, text: str):
        normalized = self.normalizer.normalize(text)

        if "=" not in normalized:
            return None

        parts = normalized.split("=")

        if len(parts) != 2:
            return None

        left = parts[0].strip()
        right = parts[1].strip()

        if not left or not right:
            return None

        left = left.replace("^", "**")
        right = right.replace("^", "**")

        try:
            left_expr = sp.sympify(left)
            right_expr = sp.sympify(right)

            return sp.Eq(left_expr, right_expr)

        except Exception:
            return None

    def _extract_simple_solution(self, text: str):
        normalized = self.normalizer.normalize(text)

        if "=" not in normalized:
            return None

        parts = normalized.split("=")

        if len(parts) != 2:
            return None

        left = parts[0].strip()
        right = parts[1].strip()

        try:
            left_expr = sp.sympify(left.replace("^", "**"))
            right_expr = sp.sympify(right.replace("^", "**"))
        except Exception:
            return None

        # x = 3
        if isinstance(left_expr, sp.Symbol) and not right_expr.free_symbols:
            return {
                "variable": left_expr,
                "value": right_expr,
            }

        # 3 = x
        if isinstance(right_expr, sp.Symbol) and not left_expr.free_symbols:
            return {
                "variable": right_expr,
                "value": left_expr,
            }

        return None

    def _solve_equation(self, equation):
        if equation is None:
            return None

        symbols = list(equation.free_symbols)

        if len(symbols) != 1:
            return None

        variable = symbols[0]

        try:
            solution_set = sp.solveset(
                equation,
                variable,
                domain=sp.S.Reals
            )

            return {
                "variable": variable,
                "solutions": solution_set,
            }

        except Exception:
            return None

    def validate(
        self,
        student_answer: str,
        expected_answer: str,
    ) -> ValidationResult:

        normalized_student = self.normalizer.normalize(student_answer)
        normalized_expected = self.normalizer.normalize(expected_answer)

        student_solution = self._extract_simple_solution(
            normalized_student
        )

        expected_solution = self._extract_simple_solution(
            normalized_expected
        )

        # Cas simple : x=3 comparé à x=3 ou x=6/2
        if student_solution and expected_solution:

            if (
                student_solution["variable"]
                != expected_solution["variable"]
            ):
                return ValidationResult.uncertain(
                    confidence=0.0,
                    method="equation_variable_mismatch",
                    reason="Les réponses utilisent des variables différentes.",
                    normalized_student_answer=normalized_student,
                    normalized_expected_answer=normalized_expected,
                )

            try:
                difference = sp.simplify(
                    student_solution["value"]
                    - expected_solution["value"]
                )

                if difference == 0:
                    return ValidationResult.correct(
                        confidence=1.0,
                        method="equation_solution_equivalence",
                        reason=(
                            "Les deux équations donnent la même "
                            "solution pour la même variable."
                        ),
                        normalized_student_answer=normalized_student,
                        normalized_expected_answer=normalized_expected,
                        details={
                            "variable": str(
                                student_solution["variable"]
                            ),
                            "student_value": str(
                                student_solution["value"]
                            ),
                            "expected_value": str(
                                expected_solution["value"]
                            ),
                        },
                    )

                return ValidationResult.uncertain(
                    confidence=0.0,
                    method="equation_solution_difference",
                    reason=(
                        "Les solutions semblent différentes, "
                        "mais une validation supplémentaire est requise."
                    ),
                    normalized_student_answer=normalized_student,
                    normalized_expected_answer=normalized_expected,
                )

            except Exception as exc:
                return ValidationResult.error(
                    method="equation_solution",
                    reason=(
                        "Une erreur est survenue pendant "
                        "la comparaison des solutions."
                    ),
                    normalized_student_answer=normalized_student,
                    normalized_expected_answer=normalized_expected,
                    details={
                        "exception_type": type(exc).__name__,
                        "exception_message": str(exc),
                    },
                )

        student_equation = self._parse_equation(
            normalized_student
        )

        expected_equation = self._parse_equation(
            normalized_expected
        )

        # Si la réponse attendue est simple, mais la réponse élève
        # est une équation générale, on transforme la réponse attendue
        # elle aussi en équation.
        if student_equation is not None and expected_solution is not None:
            expected_equation = sp.Eq(
                expected_solution["variable"],
                expected_solution["value"]
            )

        if expected_equation is not None and student_solution is not None:
            student_equation = sp.Eq(
                student_solution["variable"],
                student_solution["value"]
            )

        if student_equation is None or expected_equation is None:
            return ValidationResult.unsupported(
                method="equation",
                reason=(
                    "Les réponses ne correspondent pas à un format "
                    "d'équation actuellement pris en charge."
                ),
                normalized_student_answer=normalized_student,
                normalized_expected_answer=normalized_expected,
            )

        student_solved = self._solve_equation(
            student_equation
        )

        expected_solved = self._solve_equation(
            expected_equation
        )

        if student_solved is None or expected_solved is None:
            return ValidationResult.uncertain(
                confidence=0.0,
                method="equation_solving_failed",
                reason=(
                    "Le moteur n'a pas pu déterminer de manière fiable "
                    "les ensembles de solutions."
                ),
                normalized_student_answer=normalized_student,
                normalized_expected_answer=normalized_expected,
            )

        if (
            student_solved["variable"]
            != expected_solved["variable"]
        ):
            return ValidationResult.uncertain(
                confidence=0.0,
                method="equation_variable_mismatch",
                reason="Les équations utilisent des variables différentes.",
                normalized_student_answer=normalized_student,
                normalized_expected_answer=normalized_expected,
            )

        try:
            student_set = student_solved["solutions"]
            expected_set = expected_solved["solutions"]

            if student_set == expected_set:
                return ValidationResult.correct(
                    confidence=1.0,
                    method="equation_solution_set_equivalence",
                    reason=(
                        "Les deux équations ont le même ensemble "
                        "de solutions réelles."
                    ),
                    normalized_student_answer=normalized_student,
                    normalized_expected_answer=normalized_expected,
                    details={
                        "variable": str(
                            student_solved["variable"]
                        ),
                        "student_solutions": str(student_set),
                        "expected_solutions": str(expected_set),
                    },
                )

            # Toujours prudent :
            # ensemble différent ≠ incorrect automatique pour l'instant
            return ValidationResult.uncertain(
                confidence=0.0,
                method="equation_solution_set_difference",
                reason=(
                    "Les ensembles de solutions calculés sont différents. "
                    "Une validation supplémentaire est requise avant "
                    "de déclarer la réponse incorrecte."
                ),
                normalized_student_answer=normalized_student,
                normalized_expected_answer=normalized_expected,
                details={
                    "student_solutions": str(student_set),
                    "expected_solutions": str(expected_set),
                },
            )

        except Exception as exc:
            return ValidationResult.error(
                method="equation_solution_set",
                reason=(
                    "Une erreur est survenue pendant la comparaison "
                    "des ensembles de solutions."
                ),
                normalized_student_answer=normalized_student,
                normalized_expected_answer=normalized_expected,
                details={
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                },
            )