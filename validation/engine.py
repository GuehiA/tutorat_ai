from validation.normalizer import AnswerNormalizer
from validation.result import ValidationResult
from validation.numeric import NumericValidator
from validation.equation import EquationValidator
from validation.symbolic import SymbolicValidator
from validation.double_check import DoubleCheckValidator


class ValidationEngine:
    def __init__(self):
        self.normalizer = AnswerNormalizer()
        self.numeric_validator = NumericValidator()
        self.equation_validator = EquationValidator()
        self.symbolic_validator = SymbolicValidator()
        self.llm_validator = DoubleCheckValidator()

    def validate(
        self,
        student_answer: str,
        expected_answer: str,
        question: str = None,
        answer_type: str = None,
    ) -> ValidationResult:

        normalized_student = self.normalizer.normalize(student_answer)
        normalized_expected = self.normalizer.normalize(expected_answer)

        # 1. Réponse vide
        if not normalized_student:
            return ValidationResult.incorrect(
                confidence=1.0,
                method="empty_answer",
                reason="La réponse de l'élève est vide.",
                normalized_student_answer=normalized_student,
                normalized_expected_answer=normalized_expected,
            )

        # 2. Réponse attendue absente
        if not normalized_expected:
            return ValidationResult.error(
                method="missing_expected_answer",
                reason="La réponse attendue est absente.",
                normalized_student_answer=normalized_student,
                normalized_expected_answer=normalized_expected,
            )

        # 3. Égalité exacte après normalisation
        if normalized_student == normalized_expected:
            return ValidationResult.correct(
                confidence=1.0,
                method="normalized_exact_match",
                reason="La réponse normalisée est identique à la réponse attendue.",
                normalized_student_answer=normalized_student,
                normalized_expected_answer=normalized_expected,
            )

        validator_trace = {}

        # 4. Validation numérique
        numeric_result = self.numeric_validator.validate(
            normalized_student,
            normalized_expected,
        )

        validator_trace["numeric"] = {
            "verdict": numeric_result.verdict,
            "method": numeric_result.method,
            "reason": numeric_result.reason,
        }

        if numeric_result.verdict in {"correct", "incorrect"}:
            return numeric_result

        # 5. Validation d'équation
        equation_result = self.equation_validator.validate(
            normalized_student,
            normalized_expected,
        )

        validator_trace["equation"] = {
            "verdict": equation_result.verdict,
            "method": equation_result.method,
            "reason": equation_result.reason,
        }

        if equation_result.verdict == "correct":
            return equation_result

        # Un résultat "uncertain" provenant du validateur
        # d'équations ne devient PAS incorrect.

        # 6. Validation symbolique
        symbolic_result = self.symbolic_validator.validate(
            normalized_student,
            normalized_expected,
        )

        validator_trace["symbolic"] = {
            "verdict": symbolic_result.verdict,
            "method": symbolic_result.method,
            "reason": symbolic_result.reason,
        }

        if symbolic_result.verdict == "correct":
            return symbolic_result

        # 7. Fallback IA uniquement si les validateurs
        # déterministes n'ont pas réussi à conclure.
        try:
            llm_result = self.llm_validator.validate(
                question=question or "",
                student_answer=student_answer,
                expected_answer=expected_answer,
            )

            if llm_result.details is None:
                llm_result.details = {}

            llm_result.details["deterministic_trace"] = validator_trace

            return llm_result

        except Exception as exc:
            return ValidationResult.uncertain(
                confidence=0.0,
                method="llm_fallback_error",
                reason=(
                    "Les validateurs déterministes n'ont pas pu conclure "
                    "et le fallback IA a rencontré une erreur. "
                    "La réponse ne doit pas être pénalisée automatiquement."
                ),
                normalized_student_answer=normalized_student,
                normalized_expected_answer=normalized_expected,
                details={
                    "validator_trace": validator_trace,
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                },
            )