from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ValidationResult:
    """
    Résultat standardisé d'une validation de réponse élève.

    verdict :
        - correct
        - incorrect
        - uncertain
        - unsupported
        - error
    """

    verdict: str

    confidence: float = 0.0
    method: str = "unknown"

    normalized_student_answer: Optional[str] = None
    normalized_expected_answer: Optional[str] = None

    result_correct: Optional[bool] = None
    reasoning_correct: Optional[bool] = None

    error_type: Optional[str] = None
    reason: Optional[str] = None

    requires_review: bool = False

    details: Dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def is_correct(self):
        return self.verdict == "correct"

    @property
    def is_incorrect(self):
        return self.verdict == "incorrect"

    @property
    def is_uncertain(self):
        return self.verdict == "uncertain"

    def to_dict(self):
        return {
            "verdict": self.verdict,
            "confidence": self.confidence,
            "method": self.method,

            "normalized_student_answer":
                self.normalized_student_answer,

            "normalized_expected_answer":
                self.normalized_expected_answer,

            "result_correct": self.result_correct,
            "reasoning_correct":
                self.reasoning_correct,

            "error_type": self.error_type,
            "reason": self.reason,

            "requires_review":
                self.requires_review,

            "details": self.details,
        }