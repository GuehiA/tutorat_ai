from dataclasses import dataclass
from typing import Optional, Any, Dict


VALIDATION_VERDICTS = {
    "correct",
    "incorrect",
    "uncertain",
    "unsupported",
    "error",
}


@dataclass
class ValidationResult:
    verdict: str
    confidence: float = 0.0
    method: str = "unknown"

    normalized_student_answer: Optional[str] = None
    normalized_expected_answer: Optional[str] = None

    result_correct: Optional[bool] = None
    reasoning_correct: Optional[bool] = None

    error_type: Optional[str] = None
    reason: Optional[str] = None

    details: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.verdict not in VALIDATION_VERDICTS:
            raise ValueError(
                f"Verdict invalide : {self.verdict}. "
                f"Valeurs autorisées : {sorted(VALIDATION_VERDICTS)}"
            )

        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                "La confiance doit être comprise entre 0.0 et 1.0."
            )

        if self.details is None:
            self.details = {}

    @property
    def is_correct(self) -> bool:
        return self.verdict == "correct"

    @property
    def is_incorrect(self) -> bool:
        return self.verdict == "incorrect"

    @property
    def is_uncertain(self) -> bool:
        return self.verdict == "uncertain"

    @property
    def needs_fallback(self) -> bool:
        return self.verdict in {
            "uncertain",
            "unsupported",
            "error",
        }

    @classmethod
    def correct(
        cls,
        confidence: float,
        method: str,
        reason: Optional[str] = None,
        **kwargs,
    ):
        return cls(
            verdict="correct",
            confidence=confidence,
            method=method,
            result_correct=True,
            reason=reason,
            **kwargs,
        )

    @classmethod
    def incorrect(
        cls,
        confidence: float,
        method: str,
        reason: Optional[str] = None,
        **kwargs,
    ):
        return cls(
            verdict="incorrect",
            confidence=confidence,
            method=method,
            result_correct=False,
            reason=reason,
            **kwargs,
        )

    @classmethod
    def uncertain(
        cls,
        confidence: float = 0.0,
        method: str = "unknown",
        reason: Optional[str] = None,
        **kwargs,
    ):
        return cls(
            verdict="uncertain",
            confidence=confidence,
            method=method,
            result_correct=None,
            reason=reason,
            **kwargs,
        )

    @classmethod
    def unsupported(
        cls,
        method: str = "unknown",
        reason: Optional[str] = None,
        **kwargs,
    ):
        return cls(
            verdict="unsupported",
            confidence=0.0,
            method=method,
            result_correct=None,
            reason=reason,
            **kwargs,
        )

    @classmethod
    def error(
        cls,
        method: str = "unknown",
        reason: Optional[str] = None,
        **kwargs,
    ):
        return cls(
            verdict="error",
            confidence=0.0,
            method=method,
            result_correct=None,
            reason=reason,
            **kwargs,
        )