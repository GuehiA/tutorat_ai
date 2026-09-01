from __future__ import annotations

import re
from typing import Any, Dict, Optional

import sympy as sp

from services.naima.math_parser_service import (
    X,
    TRANSFORMATIONS,
    normalize_math_text,
)

from sympy.parsing.sympy_parser import (
    parse_expr,
)


def _parse_expression(
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


def normalize_inequality(
    text: str,
) -> str:

    if not text:
        return ""

    value = str(text).strip()

    replacements = {
        "≤": "<=",
        "≥": ">=",
        "≦": "<=",
        "≧": ">=",
        "−": "-",
        "–": "-",
        "—": "-",
    }

    for source, target in replacements.items():
        value = value.replace(
            source,
            target,
        )

    return normalize_math_text(
        value
    )


def detect_inequality_operator(
    text: str,
) -> Optional[str]:

    if not text:
        return None

    normalized = normalize_inequality(
        text
    )

    for operator in (
        "<=",
        ">=",
        "<",
        ">",
    ):
        if operator in normalized:
            return operator

    return None


def is_inequality(
    text: str,
) -> bool:

    return (
        detect_inequality_operator(
            text
        )
        is not None
    )


def split_inequality(
    text: str,
) -> Optional[
    tuple[str, str, str]
]:

    normalized = normalize_inequality(
        text
    )

    operator = detect_inequality_operator(
        normalized
    )

    if not operator:
        return None

    try:
        left, right = normalized.split(
            operator,
            1,
        )
    except ValueError:
        return None

    if not left or not right:
        return None

    return (
        left,
        operator,
        right,
    )


def analyze_inequality(
    inequality: str,
) -> Dict[str, Any]:

    parts = split_inequality(
        inequality
    )

    if not parts:
        return {
            "supported": False,
            "is_inequality": False,
            "reason": "invalid_inequality",
        }

    left, operator, right = parts

    try:
        expression = sp.expand(
            _parse_expression(left)
            - _parse_expression(right)
        )

        polynomial = sp.Poly(
            expression,
            X,
        )

        degree = polynomial.degree()

    except Exception as exc:
        return {
            "supported": False,
            "is_inequality": True,
            "reason": "parse_error",
            "error": str(exc),
        }

    return {
        "supported": True,
        "is_inequality": True,
        "normalized_inequality": (
            normalize_inequality(
                inequality
            )
        ),
        "operator": operator,
        "degree": (
            int(degree)
            if degree is not None
            else None
        ),
        "expression": str(
            expression
        ),
        "reason": "inequality_supported",
    }


def _build_relation(
    left_expr: sp.Expr,
    operator: str,
    right_expr: sp.Expr,
):

    if operator == "<":
        return sp.Lt(
            left_expr,
            right_expr,
        )

    if operator == "<=":
        return sp.Le(
            left_expr,
            right_expr,
        )

    if operator == ">":
        return sp.Gt(
            left_expr,
            right_expr,
        )

    if operator == ">=":
        return sp.Ge(
            left_expr,
            right_expr,
        )

    return None


def solve_inequality(
    inequality: str,
) -> Dict[str, Any]:

    analysis = analyze_inequality(
        inequality
    )

    if not analysis.get(
        "supported"
    ):
        return {
            **analysis,
            "solution_set": None,
        }

    parts = split_inequality(
        inequality
    )

    if not parts:
        return {
            **analysis,
            "solution_set": None,
        }

    left, operator, right = parts

    try:
        left_expr = _parse_expression(
            left
        )

        right_expr = _parse_expression(
            right
        )

        relation = _build_relation(
            left_expr,
            operator,
            right_expr,
        )

        if relation is None:
            return {
                **analysis,
                "solution_set": None,
            }

        solution = (
            sp.solve_univariate_inequality(
                relation,
                X,
                relational=False,
            )
        )

    except Exception as exc:
        return {
            **analysis,
            "solution_set": None,
            "reason": "solve_error",
            "error": str(exc),
        }

    return {
        **analysis,
        "solution_set": str(
            solution
        ),
        "reason": "inequality_solved",
    }


def detect_direction_rule_statement(
    student_text: str,
) -> Dict[str, Any]:

    value = (
        student_text
        or ""
    ).lower()

    # Uniformiser les différents tirets
    # susceptibles d'être saisis/copiés.
    value = (
        value
        .replace("−", "-")
        .replace("–", "-")
        .replace("—", "-")
    )

    # ==========================================================
    # 1. DÉTECTION D'UNE OPÉRATION AVEC UN NOMBRE NÉGATIF
    # ==========================================================
    #
    # Exemples reconnus :
    #
    #   je divise par -2
    #   je divise les deux membres par -2
    #   on divise les deux côtés par -3
    #   nous divisons chaque membre par -4
    #
    #   je multiplie par -2
    #   je multiplie les deux membres par -3
    #
    # L'ancienne détection cherchait littéralement :
    #
    #   "divise par -"
    #
    # et ne reconnaissait donc pas :
    #
    #   "divise les deux membres par -2"
    #
    # ==========================================================

    negative_division = bool(
        re.search(
            r"\bdivis(?:e|er|ons|ez|ent)?\b"
            r".{0,60}?"
            r"\bpar\s*-\s*\d",
            value,
            flags=re.IGNORECASE,
        )
    )

    negative_multiplication = bool(
        re.search(
            r"\bmultipli(?:e|er|ons|ez|ent)?\b"
            r".{0,60}?"
            r"\bpar\s*-\s*\d",
            value,
            flags=re.IGNORECASE,
        )
    )

    explicit_negative_number = any(
        marker in value
        for marker in (
            "nombre negatif",
            "nombre négatif",
        )
    )

    negative_operation = bool(
        negative_division
        or negative_multiplication
        or explicit_negative_number
    )

    # ==========================================================
    # 2. DÉTECTION DE L'INVERSION DU SENS
    # ==========================================================

    inversion = any(
        marker in value
        for marker in (
            "inverse le signe",
            "inverse le sens",
            "change le signe",
            "change le sens",
            "retourne le signe",
            "inverser l'inégalité",
            "inverser l'inegalite",
            "j inverse le sens",
            "j'inverse le sens",
            "il faut inverser",
            "on inverse",
            "je dois inverser",
            "le signe s'inverse",
            "le sens s'inverse",
        )
    )

    # ==========================================================
    # 3. OPÉRATION NÉGATIVE + INVERSION CORRECTEMENT MENTIONNÉE
    # ==========================================================

    if (
        negative_operation
        and inversion
    ):
        return {
            "detected": True,
            "reasoning_correct": True,
            "confidence": 0.98,
            "method": (
                "inequality_direction_rule"
            ),
            "negative_operation": True,
            "direction_flip_mentioned": True,
        }

    # ==========================================================
    # 4. OPÉRATION NÉGATIVE MAIS INVERSION NON MENTIONNÉE
    # ==========================================================

    if (
        negative_operation
        and not inversion
    ):
        return {
            "detected": True,
            "reasoning_correct": False,
            "confidence": 0.95,
            "method": (
                "inequality_direction_rule"
            ),
            "error_type": (
                "missing_inequality_direction_flip"
            ),
            "negative_operation": True,
            "direction_flip_mentioned": False,
        }

    # ==========================================================
    # 5. AUCUNE RÈGLE DÉTECTÉE
    # ==========================================================

    return {
        "detected": False,
        "reasoning_correct": None,
        "confidence": 0.0,
        "method": None,
        "negative_operation": False,
        "direction_flip_mentioned": False,
    }


def extract_student_inequality(
    student_text: str,
) -> Optional[str]:
    """
    Extrait une réponse finale du type :

        x > 4
        x < -3
        x <= 2
        x >= -5/2
    """

    if not student_text:
        return None

    value = (
        str(student_text)
        .replace("≤", "<=")
        .replace("≥", ">=")
        .replace("−", "-")
    )

    match = re.search(
        r"\bx\s*(<=|>=|<|>)\s*"
        r"([+\-]?"
        r"(?:"
        r"\d+/\d+"
        r"|"
        r"\d+(?:\.\d+)?"
        r"))",
        value,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    operator = match.group(1)
    right = match.group(2)

    return normalize_inequality(
        f"x{operator}{right}"
    )


def _solution_set_from_student_inequality(
    student_inequality: str,
):

    parts = split_inequality(
        student_inequality
    )

    if not parts:
        return None

    left, operator, right = parts

    try:
        left_expr = _parse_expression(
            left
        )

        right_expr = _parse_expression(
            right
        )

        relation = _build_relation(
            left_expr,
            operator,
            right_expr,
        )

        if relation is None:
            return None

        return sp.solve_univariate_inequality(
            relation,
            X,
            relational=False,
        )

    except Exception:
        return None


def validate_final_inequality(
    inequality: str,
    student_text: str,
) -> Dict[str, Any]:

    solved = solve_inequality(
        inequality
    )

    if not solved.get(
        "supported"
    ):
        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "inequality_solution"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": None,
            "requires_review": True,
            "reason": (
                "The source inequality "
                "cannot be solved deterministically."
            ),
            "details": solved,
        }

    student_inequality = (
        extract_student_inequality(
            student_text
        )
    )

    if not student_inequality:
        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "inequality_solution"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": None,
            "requires_review": True,
            "reason": (
                "No final inequality answer "
                "could be extracted."
            ),
            "details": solved,
        }

    expected_parts = split_inequality(
        inequality
    )

    if not expected_parts:
        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "inequality_solution"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": None,
            "requires_review": True,
            "reason": (
                "Invalid source inequality."
            ),
            "details": solved,
        }

    try:
        left, operator, right = (
            expected_parts
        )

        source_relation = (
            _build_relation(
                _parse_expression(left),
                operator,
                _parse_expression(right),
            )
        )

        expected_set = (
            sp.solve_univariate_inequality(
                source_relation,
                X,
                relational=False,
            )
        )

        student_set = (
            _solution_set_from_student_inequality(
                student_inequality
            )
        )

    except Exception:
        expected_set = None
        student_set = None

    if (
        expected_set is None
        or student_set is None
    ):
        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "inequality_solution"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": None,
            "requires_review": True,
            "reason": (
                "The solution sets could not "
                "be compared deterministically."
            ),
            "details": {
                **solved,
                "student_inequality": (
                    student_inequality
                ),
            },
        }

    correct = (
        expected_set
        == student_set
    )

    return {
        "verdict": (
            "correct"
            if correct
            else "incorrect"
        ),
        "confidence": 1.0,
        "method": (
            "inequality_solution"
        ),
        "result_correct": correct,
        "reasoning_correct": None,
        "error_type": (
            None
            if correct
            else (
                "wrong_inequality_solution"
            )
        ),
        "requires_review": False,
        "reason": (
            "The final inequality solution "
            "is correct."
            if correct
            else (
                "The proposed inequality "
                "does not represent the "
                "correct solution set."
            )
        ),
        "details": {
            **solved,
            "student_inequality": (
                student_inequality
            ),
            "student_solution_set": str(
                student_set
            ),
            "expected_solution_set": str(
                expected_set
            ),
        },
    }