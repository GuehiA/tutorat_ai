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
        self.client = client or OpenAI(api_key=OPENAI_API_KEY)
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

        system_prompt = """
Tu es un validateur mathématique prudent pour une plateforme éducative.

Ton rôle n'est PAS de produire une correction pédagogique complète.
Ton rôle est uniquement d'évaluer si la réponse de l'élève est
mathématiquement acceptable.

RÈGLES FONDAMENTALES :

1. Une formulation différente de la réponse de référence peut être correcte.

2. Une expression mathématiquement équivalente doit être considérée
   comme correcte.

3. Une notation inhabituelle ne doit pas être considérée automatiquement
   comme incorrecte.

4. Distingue le résultat final du raisonnement.

5. Un résultat peut être correct même si l'explication est incomplète.

6. N'invente jamais une erreur simplement parce que la réponse diffère
   textuellement de la réponse de référence.

7. Si plusieurs interprétations raisonnables sont possibles,
   utilise "uncertain".

8. Si tu n'es pas suffisamment certain que la réponse est incorrecte,
   utilise "uncertain".

9. "incorrect" doit être réservé aux situations où une erreur
   mathématique identifiable est présente.

10. La confiance représente ta certitude dans le verdict,
    et non la qualité générale du travail de l'élève.

Sois particulièrement prudent afin d'éviter les faux rejets
d'une réponse réellement correcte.
""".strip()

        user_prompt = f"""
QUESTION :
{question or "Non fournie"}

RÉPONSE ATTENDUE :
{expected_answer}

RÉPONSE DE L'ÉLÈVE :
{student_answer}

RÉPONSE NORMALISÉE DE L'ÉLÈVE :
{normalized_student}

RÉPONSE ATTENDUE NORMALISÉE :
{normalized_expected}
"""

        if explanation:
            user_prompt += f"""

EXPLICATION DE RÉFÉRENCE :
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
                reason="Le validateur IA a rencontré une erreur technique.",
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

        # -------------------------------------------------
        # RÈGLE DE PROTECTION CONTRE LES FAUX REJETS
        # -------------------------------------------------
        #
        # Même si le modèle dit "incorrect",
        # nous ne l'acceptons automatiquement que si sa
        # confiance atteint le seuil défini.
        #
        # Sinon : UNCERTAIN.
        # -------------------------------------------------

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

        if parsed.verdict == LLMVerdict.incorrect:
            return ValidationResult.uncertain(
                confidence=confidence,
                method="llm_incorrect_requires_confirmation",
                reason=(
                    "Le premier validateur IA considère la réponse incorrecte, "
                    "mais un verdict négatif produit par l'IA doit être confirmé "
                    "par une seconde validation avant de pénaliser l'élève."
                ),
                normalized_student_answer=normalized_student,
                normalized_expected_answer=normalized_expected,
                reasoning_correct=parsed.reasoning_correct,
                error_type=parsed.error_type,
                details=details,
            )

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