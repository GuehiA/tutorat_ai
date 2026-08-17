from fractions import Fraction
from decimal import Decimal, InvalidOperation
from typing import Optional

from validation.result import ValidationResult
from validation.normalizer import AnswerNormalizer


class NumericValidator:
    def __init__(self, tolerance: float = 1e-9):
        self.normalizer = AnswerNormalizer()
        self.tolerance = tolerance

    def _parse_number(self, value: str) -> Optional[float]:
        if value is None:
            return None

        text = self.normalizer.normalize(value)

        if not text:
            return None

        # Fraction simple : 1/2, 3/4, 2.5/5, etc.
        if "/" in text:
            parts = text.split("/")

            if len(parts) == 2:
                numerator = parts[0].strip()
                denominator = parts[1].strip()

                try:
                    numerator_value = Decimal(numerator)
                    denominator_value = Decimal(denominator)

                    if denominator_value == 0:
                        return None

                    value = numerator_value / denominator_value
                    return float(value)

                except (
                    ValueError,
                    ZeroDivisionError,
                    InvalidOperation,
                ):
                    return None

        # Nombre décimal ou entier
        try:
            return float(Decimal(text))
        except (ValueError, InvalidOperation):
            return None

    def validate(
        self,
        student_answer: str,
        expected_answer: str,
    ) -> ValidationResult:

        normalized_student = self.normalizer.normalize(student_answer)
        normalized_expected = self.normalizer.normalize(expected_answer)

        student_value = self._parse_number(normalized_student)
        expected_value = self._parse_number(normalized_expected)

        if student_value is None or expected_value is None:
            return ValidationResult.unsupported(
                method="numeric",
                reason="Au moins une des réponses n'est pas interprétable comme un nombre.",
                normalized_student_answer=normalized_student,
                normalized_expected_answer=normalized_expected,
            )

        difference = abs(student_value - expected_value)

        if difference <= self.tolerance:
            return ValidationResult.correct(
                confidence=1.0,
                method="numeric_equivalence",
                reason="Les deux réponses représentent la même valeur numérique.",
                normalized_student_answer=normalized_student,
                normalized_expected_answer=normalized_expected,
                details={
                    "student_value": student_value,
                    "expected_value": expected_value,
                    "difference": difference,
                },
            )

        return ValidationResult.incorrect(
            confidence=1.0,
            method="numeric_equivalence",
            reason="Les deux valeurs numériques ne sont pas équivalentes.",
            normalized_student_answer=normalized_student,
            normalized_expected_answer=normalized_expected,
            details={
                "student_value": student_value,
                "expected_value": expected_value,
                "difference": difference,
            },
        )