# validation/llm.py

import os
from enum import Enum
from typing import Optional

from openai import OpenAI
from pydantic import BaseModel, Field

from config import OPENAI_API_KEY
from validation.result import ValidationResult
from validation.normalizer import AnswerNormalizer


class LLMVerdict(str, Enum):
    correct = "correct"
    incorrect = "incorrect"
    uncertain = "uncertain"


class LLMValidationOutput(BaseModel):
    verdict: LLMVerdict

    confidence: float = Field(
        ge=0.0,
        le=1.0
    )

    result_correct: Optional[bool] = None
    reasoning_correct: Optional[bool] = None

    error_type: Optional[str] = None
    reason: str


class LLMValidator:
    def __init__(
        self,
        client: Optional[OpenAI] = None,
        model: Optional[str] = None,
        acceptance_threshold: float = 0.95,
    ):
        self.client = client or OpenAI(
            api_key=OPENAI_API_KEY
        )

        self.normalizer = AnswerNormalizer()

        self.model = (
            model
            or os.getenv("TUTORATAI_VALIDATOR_MODEL")
            or "gpt-5.6-luna"
        )

        self.acceptance_threshold = acceptance_threshold

    def validate(
        self,
        question: str,
        student_answer: str,
        expected_answer: str,
        explanation: Optional[str] = None,
    ) -> ValidationResult:

        normalized_student = self.normalizer.normalize(
            student_answer
        )

        normalized_expected = self.normalizer.normalize(
            expected_answer
        )

        if not normalized_student:
            return ValidationResult.incorrect(
                confidence=1.0,
                method="llm_empty_answer",
                reason="La réponse de l'élève est vide.",
                normalized_student_answer=normalized_student,
                normalized_expected_answer=normalized_expected,
            )

        if not normalized_expected:
            return ValidationResult.error(
                method="llm_missing_expected_answer",
                reason="La réponse attendue est absente.",
                normalized_student_answer=normalized_student,
                normalized_expected_answer=normalized_expected,
            )

        # Prompt volontairement court :
        # moins de tokens, tout en conservant les règles de sécurité.
        system_prompt = """
Tu valides uniquement la justesse mathématique d'une réponse d'élève.

Règles :
- Une formulation différente ou une expression équivalente peut être correcte.
- Distingue résultat final et raisonnement.
- Une explication incomplète n'annule pas un résultat correct.
- N'invente pas d'erreur parce que la formulation diffère de la référence.
- Si plusieurs interprétations sont raisonnables, réponds uncertain.
- Si tu n'es pas très certain d'un verdict négatif, réponds uncertain.
- incorrect exige une erreur mathématique identifiable.
- Évite en priorité les faux rejets.
""".strip()

        user_prompt = f"""
QUESTION:
{question or "Non fournie"}

RÉFÉRENCE:
{expected_answer}

RÉPONSE ÉLÈVE:
{student_answer}

NORMALISÉE:
{normalized_student}

RÉFÉRENCE NORMALISÉE:
{normalized_expected}
""".strip()

        if explanation:
            user_prompt += f"""

EXPLICATION DE RÉFÉRENCE:
{explanation}
"""

        try:
            completion = self.client.chat.completions.parse(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": user_prompt,
                    },
                ],
                response_format=LLMValidationOutput,
            )

            parsed = completion.choices[0].message.parsed

            if parsed is None:
                return ValidationResult.uncertain(
                    confidence=0.0,
                    method="llm_no_parsed_output",
                    reason=(
                        "Le validateur IA n'a pas retourné "
                        "une décision structurée exploitable."
                    ),
                    normalized_student_answer=normalized_student,
                    normalized_expected_answer=normalized_expected,
                    details={
                        "model": self.model,
                    },
                )

        except Exception as exc:
            return ValidationResult.error(
                method="llm_validation",
                reason=(
                    "Le validateur IA a rencontré "
                    "une erreur technique."
                ),
                normalized_student_answer=normalized_student,
                normalized_expected_answer=normalized_expected,
                details={
                    "model": self.model,
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                },
            )

        confidence = float(parsed.confidence)

        details = {
            "model": self.model,
            "raw_verdict": parsed.verdict.value,
            "raw_confidence": confidence,
            "result_correct": parsed.result_correct,
            "reasoning_correct": parsed.reasoning_correct,
            "error_type": parsed.error_type,
        }

        # ============================================================
        # CORRECT
        # ============================================================

        if parsed.verdict == LLMVerdict.correct:

            if confidence >= self.acceptance_threshold:
                return ValidationResult.correct(
                    confidence=confidence,
                    method="llm_validation",
                    reason=parsed.reason,
                    normalized_student_answer=normalized_student,
                    normalized_expected_answer=normalized_expected,
                    reasoning_correct=parsed.reasoning_correct,
                    error_type=parsed.error_type,
                    details=details,
                )

            return ValidationResult.uncertain(
                confidence=confidence,
                method="llm_low_confidence_correct",
                reason=(
                    "L'IA considère la réponse correcte, "
                    "mais sa confiance est sous le seuil automatique."
                ),
                normalized_student_answer=normalized_student,
                normalized_expected_answer=normalized_expected,
                reasoning_correct=parsed.reasoning_correct,
                error_type=parsed.error_type,
                details=details,
            )

        # ============================================================
        # INCORRECT
        # ============================================================
        #
        # Aucun verdict négatif IA n'est accepté ici.
        # Il doit passer par DoubleCheckValidator.
        # ============================================================

        if parsed.verdict == LLMVerdict.incorrect:
            return ValidationResult.uncertain(
                confidence=confidence,
                method="llm_incorrect_requires_confirmation",
                reason=(
                    "Le premier validateur IA considère la réponse incorrecte, "
                    "mais ce verdict doit être confirmé avant toute pénalisation."
                ),
                normalized_student_answer=normalized_student,
                normalized_expected_answer=normalized_expected,
                reasoning_correct=parsed.reasoning_correct,
                error_type=parsed.error_type,
                details=details,
            )

        # ============================================================
        # UNCERTAIN
        # ============================================================

        return ValidationResult.uncertain(
            confidence=confidence,
            method="llm_uncertain",
            reason=parsed.reason,
            normalized_student_answer=normalized_student,
            normalized_expected_answer=normalized_expected,
            reasoning_correct=parsed.reasoning_correct,
            error_type=parsed.error_type,
            details=details,
        )
