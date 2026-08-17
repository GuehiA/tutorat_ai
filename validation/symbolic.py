import sympy as sp

from validation.normalizer import AnswerNormalizer
from validation.result import ValidationResult


class SymbolicValidator:
    def __init__(self):
        self.normalizer = AnswerNormalizer()

    def _prepare_expression(self, value: str) -> str:
        text = self.normalizer.normalize(value)

        # SymPy utilise ** pour les puissances
        text = text.replace("^", "**")

        return text

    def validate(
        self,
        student_answer: str,
        expected_answer: str,
    ) -> ValidationResult:

        normalized_student = self.normalizer.normalize(student_answer)
        normalized_expected = self.normalizer.normalize(expected_answer)

        if not normalized_student or not normalized_expected:
            return ValidationResult.unsupported(
                method="symbolic",
                reason="Une des réponses est vide.",
                normalized_student_answer=normalized_student,
                normalized_expected_answer=normalized_expected,
            )

        # Pour cette première version, on ne traite pas encore les équations
        # contenant explicitement "=".
        if "=" in normalized_student or "=" in normalized_expected:
            return ValidationResult.unsupported(
                method="symbolic",
                reason="Les équations seront prises en charge par un validateur spécialisé.",
                normalized_student_answer=normalized_student,
                normalized_expected_answer=normalized_expected,
            )

        student_text = self._prepare_expression(normalized_student)
        expected_text = self._prepare_expression(normalized_expected)

        try:
            student_expr = sp.sympify(student_text)
            expected_expr = sp.sympify(expected_text)

        except Exception as exc:
            return ValidationResult.unsupported(
                method="symbolic_parse",
                reason="SymPy n'a pas pu interpréter au moins une des expressions.",
                normalized_student_answer=normalized_student,
                normalized_expected_answer=normalized_expected,
                details={
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                },
            )

        try:
            difference = sp.simplify(student_expr - expected_expr)

            if difference == 0:
                return ValidationResult.correct(
                    confidence=1.0,
                    method="symbolic_equivalence",
                    reason="Les deux expressions sont symboliquement équivalentes.",
                    normalized_student_answer=normalized_student,
                    normalized_expected_answer=normalized_expected,
                    details={
                        "student_expression": str(student_expr),
                        "expected_expression": str(expected_expr),
                        "difference": str(difference),
                    },
                )

            # IMPORTANT :
            # Pour l'instant, une différence symbolique ne suffit PAS
            # à déclarer automatiquement la réponse incorrecte.
            return ValidationResult.uncertain(
                confidence=0.0,
                method="symbolic_non_equivalence",
                reason=(
                    "SymPy n'a pas démontré l'équivalence. "
                    "Cela ne suffit pas encore à déclarer la réponse incorrecte."
                ),
                normalized_student_answer=normalized_student,
                normalized_expected_answer=normalized_expected,
                details={
                    "student_expression": str(student_expr),
                    "expected_expression": str(expected_expr),
                    "difference": str(difference),
                },
            )

        except Exception as exc:
            return ValidationResult.error(
                method="symbolic",
                reason="Une erreur est survenue pendant la comparaison symbolique.",
                normalized_student_answer=normalized_student,
                normalized_expected_answer=normalized_expected,
                details={
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                },
            )