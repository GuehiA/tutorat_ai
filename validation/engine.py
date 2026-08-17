# validation/engine.py

from validation.normalizer import AnswerNormalizer
from validation.result import ValidationResult
from validation.numeric import NumericValidator
from validation.equation import EquationValidator
from validation.symbolic import SymbolicValidator
from validation.double_check import DoubleCheckValidator
from validation.mcq import MultipleChoiceResolver
from validation.free_numeric import FreeNumericAnswerValidator


class ValidationEngine:
    def __init__(self):
        self.normalizer = AnswerNormalizer()
        self.numeric_validator = NumericValidator()
        self.equation_validator = EquationValidator()
        self.symbolic_validator = SymbolicValidator()
        self.mcq_resolver = MultipleChoiceResolver()
        self.free_numeric_validator = FreeNumericAnswerValidator()
        self.llm_validator = DoubleCheckValidator()

    def validate(
        self,
        student_answer: str,
        expected_answer: str,
        question: str = None,
        answer_type: str = None,
        options=None,
    ) -> ValidationResult:

        question = question or ""

        normalized_student_original = self.normalizer.normalize(student_answer)
        normalized_expected_original = self.normalizer.normalize(expected_answer)

        if not normalized_student_original:
            return ValidationResult.incorrect(
                confidence=1.0,
                method="empty_answer",
                reason="La réponse de l'élève est vide.",
                normalized_student_answer=normalized_student_original,
                normalized_expected_answer=normalized_expected_original,
            )

        if not normalized_expected_original:
            return ValidationResult.error(
                method="missing_expected_answer",
                reason="La réponse attendue est absente.",
                normalized_student_answer=normalized_student_original,
                normalized_expected_answer=normalized_expected_original,
            )

        # 1) Correspondance exacte originale
        if normalized_student_original == normalized_expected_original:
            return ValidationResult.correct(
                confidence=1.0,
                method="normalized_exact_match",
                reason="La réponse normalisée est identique à la réponse attendue.",
                normalized_student_answer=normalized_student_original,
                normalized_expected_answer=normalized_expected_original,
            )

        parsed_options = self.mcq_resolver.parse_options(options)

        student_label = normalized_student_original.strip().upper()
        expected_label = normalized_expected_original.strip().upper()

        student_is_label = (
            len(student_label) == 1
            and student_label in "ABCDEFGH"
            and bool(parsed_options)
        )

        expected_is_label = (
            len(expected_label) == 1
            and expected_label in "ABCDEFGH"
            and bool(parsed_options)
        )

        # 2) Deux lettres QCM différentes => incorrect déterministe
        if student_is_label and expected_is_label and student_label != expected_label:
            return ValidationResult.incorrect(
                confidence=1.0,
                method="mcq_label_mismatch",
                reason=(
                    f"Le choix {student_label} ne correspond pas à la "
                    f"réponse attendue {expected_label}."
                ),
                normalized_student_answer=normalized_student_original,
                normalized_expected_answer=normalized_expected_original,
                details={
                    "student_label": student_label,
                    "expected_label": expected_label,
                    "options": parsed_options,
                },
            )

        # 3) Résoudre la LETTRE ÉLÈVE vers son contenu
        student_for_validation = student_answer
        student_resolved_value = None

        if student_is_label:
            student_resolved_value = parsed_options.get(student_label)
            if student_resolved_value:
                student_for_validation = student_resolved_value

        # 4) Résoudre la LETTRE ATTENDUE vers son contenu
        mcq_resolution = self.mcq_resolver.resolve(
            question=question,
            expected_answer=expected_answer,
            options=options,
        )

        expected_for_validation = (
            mcq_resolution.expected_value
            if mcq_resolution.resolved
            else expected_answer
        )

        normalized_student = self.normalizer.normalize(student_for_validation)
        normalized_expected = self.normalizer.normalize(expected_for_validation)

        # 5) Correspondance exacte après résolution d'une lettre
        if normalized_student == normalized_expected:
            return ValidationResult.correct(
                confidence=1.0,
                method="mcq_resolved_exact_match",
                reason=(
                    "Le choix ou la réponse a été résolu vers son contenu "
                    "et correspond à la réponse attendue."
                ),
                normalized_student_answer=normalized_student,
                normalized_expected_answer=normalized_expected,
                details={
                    "student_original": student_answer,
                    "student_label": student_label if student_is_label else None,
                    "student_resolved": student_resolved_value,
                    "expected_original": expected_answer,
                    "expected_label": mcq_resolution.expected_label,
                    "expected_resolved": expected_for_validation,
                    "options": parsed_options,
                },
            )

        validator_trace = {
            "reference_resolution": {
                "student_original": student_answer,
                "student_label": student_label if student_is_label else None,
                "student_resolved": student_resolved_value,
                "expected_original": expected_answer,
                "expected_label": mcq_resolution.expected_label,
                "expected_resolved": expected_for_validation,
                "options_parsed": parsed_options,
            }
        }

        # 6) Réponse libre contenant une valeur numérique
        free_numeric_result = self.free_numeric_validator.validate(
            student_answer=student_for_validation,
            expected_answer=expected_for_validation,
        )

        validator_trace["free_numeric"] = {
            "verdict": free_numeric_result.verdict,
            "confidence": free_numeric_result.confidence,
            "method": free_numeric_result.method,
            "reason": free_numeric_result.reason,
            "expected_value": free_numeric_result.expected_value,
            "candidate_value": free_numeric_result.candidate_value,
            "candidates": free_numeric_result.candidates,
            "signal": free_numeric_result.signal,
        }

        if free_numeric_result.verdict == "correct":
            result = ValidationResult.correct(
                confidence=free_numeric_result.confidence,
                method=free_numeric_result.method,
                reason=free_numeric_result.reason,
                normalized_student_answer=normalized_student,
                normalized_expected_answer=normalized_expected,
                details={"free_numeric": validator_trace["free_numeric"]},
            )

            self._attach_details(
                result,
                validator_trace,
                student_answer,
                student_for_validation,
                expected_answer,
                expected_for_validation,
                parsed_options,
            )
            return result

        if free_numeric_result.verdict == "incorrect":
            result = ValidationResult.incorrect(
                confidence=free_numeric_result.confidence,
                method=free_numeric_result.method,
                reason=free_numeric_result.reason,
                normalized_student_answer=normalized_student,
                normalized_expected_answer=normalized_expected,
                details={"free_numeric": validator_trace["free_numeric"]},
            )

            self._attach_details(
                result,
                validator_trace,
                student_answer,
                student_for_validation,
                expected_answer,
                expected_for_validation,
                parsed_options,
            )
            return result

        # 7) Numérique
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
            self._attach_details(
                numeric_result,
                validator_trace,
                student_answer,
                student_for_validation,
                expected_answer,
                expected_for_validation,
                parsed_options,
            )
            return numeric_result

        # 8) Équation
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
            self._attach_details(
                equation_result,
                validator_trace,
                student_answer,
                student_for_validation,
                expected_answer,
                expected_for_validation,
                parsed_options,
            )
            return equation_result

        # 9) Symbolique
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
            self._attach_details(
                symbolic_result,
                validator_trace,
                student_answer,
                student_for_validation,
                expected_answer,
                expected_for_validation,
                parsed_options,
            )
            return symbolic_result

        # 10) Fallback IA — avec les contenus résolus, pas seulement les lettres
        try:
            question_for_llm = question

            if parsed_options:
                options_text = "\n".join(
                    f"{label}) {value}"
                    for label, value in parsed_options.items()
                )
                question_for_llm = (
                    f"{question}\n\nCHOIX PROPOSÉS :\n{options_text}"
                )

            llm_result = self.llm_validator.validate(
                question=question_for_llm,
                student_answer=student_for_validation,
                expected_answer=expected_for_validation,
            )

            if llm_result.details is None:
                llm_result.details = {}

            llm_result.details["deterministic_trace"] = validator_trace
            llm_result.details["student_original"] = student_answer
            llm_result.details["student_resolved"] = student_for_validation
            llm_result.details["expected_original"] = expected_answer
            llm_result.details["expected_resolved"] = expected_for_validation
            llm_result.details["options"] = parsed_options

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

    @staticmethod
    def _attach_details(
        result,
        validator_trace,
        student_original,
        student_resolved,
        expected_original,
        expected_resolved,
        parsed_options,
    ):
        if result.details is None:
            result.details = {}

        result.details["deterministic_trace"] = validator_trace
        result.details["student_original"] = student_original
        result.details["student_resolved"] = student_resolved
        result.details["expected_original"] = expected_original
        result.details["expected_resolved"] = expected_resolved
        result.details["options"] = parsed_options
