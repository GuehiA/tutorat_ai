from __future__ import annotations

import re
from typing import Any

import sympy as sp

from services.naima.math_parser_service import (
    X,
    TRANSFORMATIONS,
    normalize_math_text,
)

from sympy.parsing.sympy_parser import (
    parse_expr,
)


def _parse(
    expression: str,
) -> sp.Expr:

    return parse_expr(
        expression,
        local_dict={
            "x": X,
            "sqrt": sp.sqrt,
        },
        transformations=TRANSFORMATIONS,
        evaluate=True,
    )


def analyze_quadratic(
    equation: str,
) -> dict:

    if not equation:
        return {
            "supported": False,
            "is_quadratic": False,
            "reason": "equation_missing",
        }

    normalized = normalize_math_text(
        equation
    )

    if "=" not in normalized:
        return {
            "supported": False,
            "is_quadratic": False,
            "reason": "invalid_equation",
        }

    try:
        left, right = normalized.split(
            "=",
            1,
        )

        expression = sp.expand(
            _parse(left)
            - _parse(right)
        )

        polynomial = sp.Poly(
            expression,
            X,
        )

    except Exception as exc:
        return {
            "supported": False,
            "is_quadratic": False,
            "reason": (
                "parse_error"
            ),
            "error": str(exc),
        }

    degree = polynomial.degree()

    if degree != 2:
        return {
            "supported": True,
            "is_quadratic": False,
            "degree": int(degree),
            "normalized_equation": (
                normalized
            ),
            "reason": (
                "not_quadratic"
            ),
        }

    a, b, c = polynomial.all_coeffs()

    discriminant = sp.simplify(
        b**2
        - 4 * a * c
    )

    solutions = sp.solve(
        sp.Eq(
            expression,
            0,
        ),
        X,
    )

    return {
        "supported": True,
        "is_quadratic": True,
        "degree": 2,
        "normalized_equation": (
            normalized
        ),
        "a": str(
            sp.simplify(a)
        ),
        "b": str(
            sp.simplify(b)
        ),
        "c": str(
            sp.simplify(c)
        ),
        "discriminant": str(
            discriminant
        ),
        "solutions": [
            str(
                sp.simplify(solution)
            )
            for solution in solutions
        ],
        "reason": (
            "quadratic_supported"
        ),
    }


def _parse_student_value(
    value: str,
):

    value = normalize_math_text(
        value
    )

    try:
        return sp.simplify(
            _parse(value)
        )
    except Exception:
        return None


def extract_student_solutions(
    student_text: str,
) -> list:

    if not student_text:
        return []

    text = (
        str(student_text)
        .replace(
            "−",
            "-",
        )
    )

    matches = re.findall(
        (
            r"\bx\s*=\s*"
            r"([+\-]?"
            r"(?:"
            r"\d+/\d+"
            r"|"
            r"\d+(?:\.\d+)?"
            r"))"
        ),
        text,
        flags=re.IGNORECASE,
    )

    values = []

    for match in matches:
        parsed = _parse_student_value(
            match
        )

        if parsed is not None:
            values.append(
                parsed
            )

    # Cas :
    # x=1 ou 2/3
    if len(values) <= 1:

        tail_match = re.search(
            r"\bx\s*=\s*(.+)$",
            text,
            flags=re.IGNORECASE,
        )

        if tail_match:

            tail = tail_match.group(1)

            parts = re.split(
                r"\bou\b|;|,|\bor\b",
                tail,
                flags=re.IGNORECASE,
            )

            parsed_parts = []

            for part in parts:

                part = re.sub(
                    r"^\s*x\s*=\s*",
                    "",
                    part.strip(),
                    flags=re.IGNORECASE,
                )

                parsed = (
                    _parse_student_value(
                        part
                    )
                )

                if parsed is not None:
                    parsed_parts.append(
                        parsed
                    )

            if parsed_parts:
                values = parsed_parts

    unique_values = []

    for value in values:

        already_present = any(
            sp.simplify(
                value - existing
            ) == 0
            for existing
            in unique_values
        )

        if not already_present:
            unique_values.append(
                value
            )

    return unique_values


def validate_solution_set(
    equation: str,
    student_text: str,
) -> dict:

    analysis = analyze_quadratic(
        equation
    )

    if not analysis.get(
        "is_quadratic"
    ):
        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "quadratic_solution_set"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": None,
            "requires_review": True,
            "reason": (
                "Quadratic equation "
                "not available."
            ),
            "details": analysis,
        }

    expected_values = []

    for raw_solution in (
        analysis.get(
            "solutions"
        )
        or []
    ):
        parsed = _parse_student_value(
            raw_solution
        )

        if parsed is not None:
            expected_values.append(
                parsed
            )

    student_values = (
        extract_student_solutions(
            student_text
        )
    )

    if not student_values:
        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "quadratic_solution_set"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": None,
            "requires_review": True,
            "reason": (
                "No exploitable solution "
                "was extracted."
            ),
            "details": analysis,
        }

    def equivalent(
        value_a,
        value_b,
    ) -> bool:

        try:
            return (
                sp.simplify(
                    value_a
                    - value_b
                )
                == 0
            )

        except Exception:
            return False

    missing = []

    for expected in expected_values:

        if not any(
            equivalent(
                expected,
                proposed,
            )
            for proposed
            in student_values
        ):
            missing.append(
                expected
            )

    extra = []

    for proposed in student_values:

        if not any(
            equivalent(
                proposed,
                expected,
            )
            for expected
            in expected_values
        ):
            extra.append(
                proposed
            )

    correct = (
        not missing
        and not extra
        and len(student_values)
        == len(expected_values)
    )

    return {
        "verdict": (
            "correct"
            if correct
            else "incorrect"
        ),
        "confidence": 1.0,
        "method": (
            "quadratic_solution_set"
        ),
        "result_correct": correct,
        "reasoning_correct": None,
        "error_type": (
            None
            if correct
            else (
                "wrong_quadratic_solution_set"
            )
        ),
        "requires_review": False,
        "reason": (
            "Exact quadratic solution set."
            if correct
            else (
                "The proposed solution set "
                "does not match exactly."
            )
        ),
        "details": {
            **analysis,
            "student_solutions": [
                str(
                    sp.simplify(value)
                )
                for value
                in student_values
            ],
            "expected_solutions": [
                str(
                    sp.simplify(value)
                )
                for value
                in expected_values
            ],
            "missing_solutions": [
                str(
                    sp.simplify(value)
                )
                for value
                in missing
            ],
            "extra_solutions": [
                str(
                    sp.simplify(value)
                )
                for value
                in extra
            ],
        },
    }


def extract_student_coefficients(
    student_text: str,
) -> dict:

    coefficients = {
        "a": None,
        "b": None,
        "c": None,
    }

    if not student_text:
        return coefficients

    for name in (
        "a",
        "b",
        "c",
    ):

        match = re.search(
            (
                rf"\b{name}\s*=\s*"
                r"([+\-]?"
                r"(?:"
                r"\d+/\d+"
                r"|"
                r"\d+(?:\.\d+)?"
                r"))"
            ),
            student_text,
            flags=re.IGNORECASE,
        )

        if match:
            coefficients[name] = (
                _parse_student_value(
                    match.group(1)
                )
            )

    return coefficients


def validate_coefficients(
    equation: str,
    student_text: str,
) -> dict:

    analysis = analyze_quadratic(
        equation
    )

    if not analysis.get(
        "is_quadratic"
    ):
        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "quadratic_coefficients"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "requires_review": True,
            "reason": (
                "Quadratic equation "
                "not available."
            ),
            "details": analysis,
        }

    student_coefficients = (
        extract_student_coefficients(
            student_text
        )
    )

    if any(
        student_coefficients[
            name
        ] is None
        for name in (
            "a",
            "b",
            "c",
        )
    ):
        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "quadratic_coefficients"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "requires_review": True,
            "reason": (
                "The three coefficients "
                "were not all provided."
            ),
            "details": analysis,
        }

    expected = {
        "a": _parse_student_value(
            analysis["a"]
        ),
        "b": _parse_student_value(
            analysis["b"]
        ),
        "c": _parse_student_value(
            analysis["c"]
        ),
    }

    correct = all(
        sp.simplify(
            student_coefficients[name]
            - expected[name]
        )
        == 0
        for name in (
            "a",
            "b",
            "c",
        )
    )

    return {
        "verdict": (
            "correct"
            if correct
            else "incorrect"
        ),
        "confidence": 1.0,
        "method": (
            "quadratic_coefficients"
        ),
        "result_correct": correct,
        "reasoning_correct": correct,
        "error_type": (
            None
            if correct
            else (
                "wrong_quadratic_coefficients"
            )
        ),
        "requires_review": False,
        "reason": (
            "Quadratic coefficients "
            "are correct."
            if correct
            else (
                "At least one quadratic "
                "coefficient is incorrect."
            )
        ),
        "details": {
            **analysis,
            "student_coefficients": {
                key: str(
                    sp.simplify(value)
                )
                for key,
                value
                in student_coefficients.items()
            },
        },
    }

def extract_student_discriminant(
    student_text: str,
) -> dict:

    result = {
        "detected": False,
        "raw_expression": None,
        "parsed_value": None,
        "is_simple_value": False,
    }

    if not student_text:
        return result

    text = (
        str(student_text)
        .replace("Δ", "delta")
        .replace("δ", "delta")
        .replace("−", "-")
        .replace("–", "-")
        .replace("—", "-")
    )

    match = re.search(
        r"\b(?:delta|discriminant)\s*=\s*(.+?)\s*$",
        text,
        flags=re.IGNORECASE,
    )

    if not match:
        return result

    raw_expression = (
        match.group(1)
        .strip()
    )

    parse_candidate = (
        raw_expression
        .replace("^", "**")
    )

    parsed_value = (
        _parse_student_value(
            parse_candidate
        )
    )

    is_simple_value = bool(
        re.fullmatch(
            r"[+\-]?"
            r"(?:"
            r"\d+/\d+"
            r"|"
            r"\d+(?:\.\d+)?"
            r")",
            raw_expression,
        )
    )

    return {
        "detected": True,
        "raw_expression": raw_expression,
        "parsed_value": parsed_value,
        "is_simple_value": is_simple_value,
    }


def validate_discriminant(
    equation: str,
    student_text: str,
) -> dict:

    analysis = analyze_quadratic(
        equation
    )

    if not analysis.get(
        "is_quadratic"
    ):
        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": "quadratic_discriminant",
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": None,
            "requires_review": True,
            "reason": (
                "Quadratic equation not available."
            ),
            "details": analysis,
        }

    extracted = (
        extract_student_discriminant(
            student_text
        )
    )

    if not extracted.get(
        "detected"
    ):
        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": "quadratic_discriminant",
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": None,
            "requires_review": True,
            "reason": (
                "No discriminant statement was extracted."
            ),
            "details": analysis,
        }

    student_value = (
        extracted.get(
            "parsed_value"
        )
    )

    expected_value = (
        _parse_student_value(
            analysis.get(
                "discriminant",
                "",
            )
        )
    )

    if (
        student_value is None
        or expected_value is None
    ):
        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": "quadratic_discriminant",
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": None,
            "requires_review": True,
            "reason": (
                "The discriminant expression "
                "could not be parsed."
            ),
            "details": {
                **analysis,
                **extracted,
            },
        }

    correct = bool(
        sp.simplify(
            student_value
            - expected_value
        )
        == 0
    )

    is_simple_value = bool(
        extracted.get(
            "is_simple_value"
        )
    )

    method = (
        "quadratic_discriminant_value"
        if is_simple_value
        else "quadratic_discriminant_expression"
    )

    return {
        "verdict": (
            "correct"
            if correct
            else "incorrect"
        ),
        "confidence": 1.0,
        "method": method,
        "result_correct": (
            correct
            if is_simple_value
            else None
        ),
        "reasoning_correct": (
            correct
            if not is_simple_value
            else None
        ),
        "error_type": (
            None
            if correct
            else (
                "wrong_quadratic_discriminant_value"
                if is_simple_value
                else "wrong_quadratic_discriminant_expression"
            )
        ),
        "requires_review": False,
        "reason": (
            "The discriminant is correct."
            if correct
            else "The discriminant is incorrect."
        ),
        "details": {
            **analysis,
            "student_discriminant_expression": (
                extracted.get(
                    "raw_expression"
                )
            ),
            "student_discriminant_value": str(
                sp.simplify(
                    student_value
                )
            ),
            "expected_discriminant": str(
                sp.simplify(
                    expected_value
                )
            ),
            "is_simple_value": (
                is_simple_value
            ),
        },
    }


def detect_discriminant_interpretation(
    student_text: str,
) -> dict:

    text = (
        student_text
        or ""
    ).lower()

    normalized = (
        text
        .replace("é", "e")
        .replace("è", "e")
        .replace("ê", "e")
        .replace("à", "a")
        .replace("Δ", "delta")
        .replace("δ", "delta")
    )

    if not any(
        marker in normalized
        for marker in (
            "delta",
            "discriminant",
        )
    ):
        return {
            "detected": False,
            "sign": None,
            "solution_count": None,
        }

    sign = None

    if any(
        marker in normalized
        for marker in (
            "positif",
            "superieur a 0",
            ">0",
            "> 0",
        )
    ):
        sign = "positive"

    elif any(
        marker in normalized
        for marker in (
            "negatif",
            "inferieur a 0",
            "<0",
            "< 0",
        )
    ):
        sign = "negative"

    elif any(
        marker in normalized
        for marker in (
            "nul",
            "egal a 0",
            "=0",
            "= 0",
        )
    ):
        sign = "zero"

    solution_count = None

    if any(
        marker in normalized
        for marker in (
            "2 solutions",
            "deux solutions",
            "2 racines",
            "deux racines",
        )
    ):
        solution_count = 2

    elif any(
        marker in normalized
        for marker in (
            "1 solution",
            "une solution",
            "solution double",
            "racine double",
        )
    ):
        solution_count = 1

    elif any(
        marker in normalized
        for marker in (
            "aucune solution",
            "pas de solution",
            "0 solution",
            "aucune racine",
        )
    ):
        solution_count = 0

    return {
        "detected": bool(
            sign is not None
            or solution_count is not None
        ),
        "sign": sign,
        "solution_count": solution_count,
    }


def validate_discriminant_interpretation(
    equation: str,
    student_text: str,
) -> dict:

    analysis = analyze_quadratic(
        equation
    )

    interpretation = (
        detect_discriminant_interpretation(
            student_text
        )
    )

    if (
        not analysis.get(
            "is_quadratic"
        )
        or not interpretation.get(
            "detected"
        )
    ):
        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "quadratic_discriminant_interpretation"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": None,
            "requires_review": True,
            "reason": (
                "No deterministic discriminant "
                "interpretation was detected."
            ),
            "details": {
                **analysis,
                **interpretation,
            },
        }

    discriminant = (
        _parse_student_value(
            analysis.get(
                "discriminant",
                "",
            )
        )
    )

    if discriminant is None:
        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "quadratic_discriminant_interpretation"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": None,
            "requires_review": True,
            "reason": (
                "The discriminant sign "
                "could not be determined."
            ),
            "details": analysis,
        }

    if discriminant > 0:
        expected_sign = "positive"
        expected_count = 2

    elif discriminant == 0:
        expected_sign = "zero"
        expected_count = 1

    else:
        expected_sign = "negative"
        expected_count = 0

    proposed_sign = (
        interpretation.get(
            "sign"
        )
    )

    proposed_count = (
        interpretation.get(
            "solution_count"
        )
    )

    sign_correct = (
        proposed_sign is None
        or proposed_sign
        == expected_sign
    )

    count_correct = (
        proposed_count is None
        or proposed_count
        == expected_count
    )

    correct = bool(
        sign_correct
        and count_correct
        and (
            proposed_sign is not None
            or proposed_count is not None
        )
    )

    return {
        "verdict": (
            "correct"
            if correct
            else "incorrect"
        ),
        "confidence": 1.0,
        "method": (
            "quadratic_discriminant_interpretation"
        ),
        "result_correct": None,
        "reasoning_correct": correct,
        "error_type": (
            None
            if correct
            else (
                "wrong_quadratic_discriminant_interpretation"
            )
        ),
        "requires_review": False,
        "reason": (
            "The discriminant interpretation is correct."
            if correct
            else (
                "The discriminant interpretation is incorrect."
            )
        ),
        "details": {
            **analysis,
            **interpretation,
            "expected_sign": expected_sign,
            "expected_solution_count": (
                expected_count
            ),
        },
    }

def detect_method_statement(
    student_text: str,
) -> dict:

    text = (
        student_text
        or ""
    ).lower()

    text = text.replace(
        "quadrqtique",
        "quadratique",
    )

    if (
        "formule quadratique"
        in text
    ):
        return {
            "detected": True,
            "method": (
                "quadratic_formula"
            ),
            "reasoning_correct": True,
            "confidence": 0.98,
        }

    if "factoris" in text:
        return {
            "detected": True,
            "method": "factorization",
            "reasoning_correct": True,
            "confidence": 0.90,
        }

    return {
        "detected": False,
        "method": None,
        "reasoning_correct": None,
        "confidence": 0.0,
    }