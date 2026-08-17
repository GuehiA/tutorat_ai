from typing import Optional

from validation.result import ValidationResult
from validation.llm import LLMValidator


class DoubleCheckValidator:
    def __init__(
        self,
        first_validator: Optional[LLMValidator] = None,
        second_validator: Optional[LLMValidator] = None,
        confirmation_threshold: float = 0.95,
    ):
        self.first_validator = first_validator or LLMValidator()
        self.second_validator = second_validator or LLMValidator()
        self.confirmation_threshold = confirmation_threshold

    def validate(
        self,
        question: str,
        student_answer: str,
        expected_answer: str,
        explanation: Optional[str] = None,
    ) -> ValidationResult:

        first_result = self.first_validator.validate(
            question=question,
            student_answer=student_answer,
            expected_answer=expected_answer,
            explanation=explanation,
        )

        # Si le premier juge accepte clairement la réponse,
        # inutile de faire un deuxième appel.
        if first_result.verdict == "correct":
            return first_result

        # Si le premier juge ne demande pas explicitement
        # confirmation d'un verdict négatif, on conserve
        # son résultat.
        if first_result.method != "llm_incorrect_requires_confirmation":
            return first_result

        # Deuxième jugement indépendant.
        second_result = self.second_validator.validate(
            question=question,
            student_answer=student_answer,
            expected_answer=expected_answer,
            explanation=explanation,
        )

        details = {
            "first_judge": {
                "verdict": first_result.verdict,
                "confidence": first_result.confidence,
                "method": first_result.method,
                "details": first_result.details,
            },
            "second_judge": {
                "verdict": second_result.verdict,
                "confidence": second_result.confidence,
                "method": second_result.method,
                "details": second_result.details,
            },
        }

        # --------------------------------------------------
        # Le deuxième juge pense que la réponse est correcte.
        # On protège l'élève.
        # --------------------------------------------------
        if second_result.verdict == "correct":
            return ValidationResult.correct(
                confidence=second_result.confidence,
                method="llm_second_judge_correct",
                reason=(
                    "Le second validateur considère la réponse correcte. "
                    "Le verdict négatif initial n'est donc pas retenu."
                ),
                normalized_student_answer=(
                    second_result.normalized_student_answer
                ),
                normalized_expected_answer=(
                    second_result.normalized_expected_answer
                ),
                reasoning_correct=second_result.reasoning_correct,
                error_type=second_result.error_type,
                details=details,
            )

        # --------------------------------------------------
        # Important :
        # LLMValidator transforme lui-même un verdict brut
        # "incorrect" en uncertain.
        #
        # Nous regardons donc le raw_verdict conservé
        # dans details.
        # --------------------------------------------------
        second_raw_verdict = None
        second_raw_confidence = 0.0

        if second_result.details:
            second_raw_verdict = second_result.details.get(
                "raw_verdict"
            )
            second_raw_confidence = float(
                second_result.details.get(
                    "raw_confidence",
                    0.0
                )
            )

        first_raw_verdict = None
        first_raw_confidence = 0.0

        if first_result.details:
            first_raw_verdict = first_result.details.get(
                "raw_verdict"
            )
            first_raw_confidence = float(
                first_result.details.get(
                    "raw_confidence",
                    0.0
                )
            )

        # --------------------------------------------------
        # Deux juges indépendants concluent incorrect
        # avec forte confiance.
        # --------------------------------------------------
        if (
            first_raw_verdict == "incorrect"
            and second_raw_verdict == "incorrect"
            and first_raw_confidence >= self.confirmation_threshold
            and second_raw_confidence >= self.confirmation_threshold
        ):
            final_confidence = min(
                first_raw_confidence,
                second_raw_confidence,
            )

            return ValidationResult.incorrect(
                confidence=final_confidence,
                method="llm_double_confirmed_incorrect",
                reason=(
                    "Deux validations IA indépendantes concluent "
                    "avec une forte confiance que la réponse "
                    "contient une erreur mathématique."
                ),
                normalized_student_answer=(
                    first_result.normalized_student_answer
                ),
                normalized_expected_answer=(
                    first_result.normalized_expected_answer
                ),
                reasoning_correct=first_result.reasoning_correct,
                error_type=first_result.error_type,
                details=details,
            )

        # Désaccord ou confiance insuffisante :
        # aucune pénalisation automatique.
        return ValidationResult.uncertain(
            confidence=max(
                first_result.confidence,
                second_result.confidence,
            ),
            method="llm_double_check_uncertain",
            reason=(
                "Les validations IA ne permettent pas de confirmer "
                "un verdict négatif avec suffisamment de fiabilité."
            ),
            normalized_student_answer=(
                first_result.normalized_student_answer
            ),
            normalized_expected_answer=(
                first_result.normalized_expected_answer
            ),
            details=details,
        )