from __future__ import annotations

from fractions import Fraction
from typing import Any, Dict, List, Optional

import sympy as sp

from services.naima.semantic_schema import (
    SemanticConstraint,
    SemanticParameterization,
    SemanticSituation,
)


def _number_to_text(value: Any) -> str:
    if isinstance(value, Fraction):
        if value.denominator == 1:
            return str(value.numerator)
        return f"({value.numerator}/{value.denominator})"
    return str(value)


def _as_fraction(value: Any) -> Optional[Fraction]:
    if value is None:
        return None

    try:
        if isinstance(value, Fraction):
            return value
        return Fraction(str(value))
    except Exception:
        return None


def get_constraints_by_relation(
    situation: SemanticSituation,
    relation: str,
) -> List[SemanticConstraint]:

    return [
        item
        for item in situation.constraints
        if item.relation == relation
    ]


def compile_product_offset_parameterization(
    *,
    constraints: List[SemanticConstraint],
    variable: str,
    role: str,
) -> List[str]:
    """
    Convention :
        common = quantity * unit + offset

    Si la variable représente unit_value :
        q1*x + o1 = q2*x + o2

    Si la variable représente common_value :
        (x-o1)/q1 = (x-o2)/q2
    """

    usable: List[Dict[str, Any]] = []

    for constraint in constraints:
        data = dict(constraint.data or {})

        quantity = _as_fraction(data.get("quantity"))
        offset = _as_fraction(data.get("offset"))

        if quantity is None or quantity == 0 or offset is None:
            continue

        usable.append({
            "quantity": quantity,
            "offset": offset,
            "unit_role": str(
                data.get("unit_role")
                or "unit_value"
            ),
            "common_role": str(
                data.get("common_role")
                or "available_amount"
            ),
        })

    if len(usable) < 2:
        return []

    equations: List[str] = []

    first = usable[0]

    for other in usable[1:]:

        if role == first["unit_role"]:

            q1 = _number_to_text(first["quantity"])
            o1 = _number_to_text(first["offset"])
            q2 = _number_to_text(other["quantity"])
            o2 = _number_to_text(other["offset"])

            equations.append(
                f"({q1})*{variable}+({o1})="
                f"({q2})*{variable}+({o2})"
            )

        elif role == first["common_role"]:

            q1 = _number_to_text(first["quantity"])
            o1 = _number_to_text(first["offset"])
            q2 = _number_to_text(other["quantity"])
            o2 = _number_to_text(other["offset"])

            equations.append(
                f"({variable}-({o1}))/({q1})="
                f"({variable}-({o2}))/({q2})"
            )

    return equations


def compile_parameterization(
    *,
    situation: SemanticSituation,
    variable: str,
    role: str,
    meaning: str = "",
) -> SemanticParameterization:

    equations: List[str] = []

    product_offset_constraints = (
        get_constraints_by_relation(
            situation,
            "product_offset_common_value",
        )
    )

    if product_offset_constraints:
        equations.extend(
            compile_product_offset_parameterization(
                constraints=product_offset_constraints,
                variable=variable,
                role=role,
            )
        )

    return SemanticParameterization(
        variable=variable,
        role=role,
        meaning=meaning,
        equations=equations,
        metadata={
            "compiled_deterministically": True,
        },
    )


def equation_to_residual(
    equation_text: str,
):
    """
    Convertit une équation scolaire en résidu SymPy.

    Accepte notamment :

        10x-5=5x+12
        10*x-5=5*x+12
        2p+3=7
        x^2=9

    Retour :

        gauche - droite

    après simplification algébrique.
    """

    from sympy.parsing.sympy_parser import (
        convert_xor,
        implicit_multiplication_application,
        parse_expr,
        standard_transformations,
    )

    value = str(
        equation_text
        or ""
    ).strip()

    if value.count("=") != 1:
        return None

    left_text, right_text = (
        value.split(
            "=",
            1,
        )
    )

    left_text = (
        left_text
        .strip()
        .replace(
            "^",
            "**",
        )
        .replace(
            ",",
            ".",
        )
    )

    right_text = (
        right_text
        .strip()
        .replace(
            "^",
            "**",
        )
        .replace(
            ",",
            ".",
        )
    )

    if (
        not left_text
        or not right_text
    ):
        return None

    transformations = (
        standard_transformations
        + (
            implicit_multiplication_application,
            convert_xor,
        )
    )

    try:

        left = parse_expr(
            left_text,
            transformations=(
                transformations
            ),
            evaluate=True,
        )

        right = parse_expr(
            right_text,
            transformations=(
                transformations
            ),
            evaluate=True,
        )

        return sp.expand(
            sp.simplify(
                left
                - right
            )
        )

    except Exception:

        return None


def equations_are_same_constraint(
    equation_a: str,
    equation_b: str,
) -> Optional[bool]:
    """
    Vérifie si deux équations représentent la même
    contrainte algébrique.

    Sont notamment acceptées :

        10x-5 = 5x+12
        5x+12 = 10x-5

    ainsi que les multiplications globales non nulles :

        5x = 17
        10x = 34

    On ne compare pas simplement les solutions :
    les résidus doivent être proportionnels par une
    constante non nulle.

    Cela reste plus conservateur qu'une comparaison
    du seul ensemble de solutions.
    """

    residual_a = (
        equation_to_residual(
            equation_a
        )
    )

    residual_b = (
        equation_to_residual(
            equation_b
        )
    )

    if (
        residual_a is None
        or residual_b is None
    ):
        return None

    # --------------------------------------------------------
    # CAS EXACT
    # --------------------------------------------------------

    if (
        sp.simplify(
            residual_a
            - residual_b
        )
        == 0
    ):
        return True

    # --------------------------------------------------------
    # CAS MEMBRES INVERSÉS
    # --------------------------------------------------------

    if (
        sp.simplify(
            residual_a
            + residual_b
        )
        == 0
    ):
        return True

    # --------------------------------------------------------
    # PROPORTIONNALITÉ PAR CONSTANTE NON NULLE
    # --------------------------------------------------------
    #
    # Exemple :
    #
    #     5x - 17
    #     10x - 34
    #
    # ratio = 1/2
    #
    # La constante ne doit dépendre d'aucune variable.
    # --------------------------------------------------------

    try:

        if residual_b == 0:
            return bool(
                residual_a == 0
            )

        ratio = sp.simplify(
            residual_a
            / residual_b
        )

        if (
            ratio != 0
            and not ratio.free_symbols
            and ratio.is_number
        ):
            return True

    except Exception:

        pass

    return False


def validate_student_parameterization(
    *,
    situation: SemanticSituation,
    student_equation: str,
    variable: str,
    role: str,
    meaning: str = "",
) -> Dict[str, Any]:

    compiled = compile_parameterization(
        situation=situation,
        variable=variable,
        role=role,
        meaning=meaning,
    )

    if not compiled.equations:
        return {
            "verdict": "uncertain",
            "result_correct": None,
            "reason": (
                "Aucune équation déterministe n'a pu être "
                "compilée pour cette paramétrisation."
            ),
            "details": {
                "variable": variable,
                "role": role,
                "meaning": meaning,
            },
        }

    for expected_equation in compiled.equations:

        same = equations_are_same_constraint(
            student_equation,
            expected_equation,
        )

        if same is True:
            return {
                "verdict": "correct",
                "result_correct": True,
                "reason": (
                    "L'équation de l'élève correspond à une "
                    "paramétrisation déterministe du modèle "
                    "sémantique."
                ),
                "details": {
                    "student_equation": student_equation,
                    "expected_equation": expected_equation,
                    "variable": variable,
                    "role": role,
                    "meaning": meaning,
                },
            }

    return {
        "verdict": "incorrect",
        "result_correct": False,
        "reason": (
            "L'équation proposée ne correspond pas aux "
            "équations déterministes compilées pour cette "
            "paramétrisation."
        ),
        "details": {
            "student_equation": student_equation,
            "expected_equations": list(compiled.equations),
            "variable": variable,
            "role": role,
            "meaning": meaning,
        },
    }


def derive_target_value_from_product_offset(
    *,
    situation: SemanticSituation,
    solved_variable_role: str,
    solved_value: Any,
) -> Optional[Dict[str, Any]]:

    constraints = get_constraints_by_relation(
        situation,
        "product_offset_common_value",
    )

    if not constraints:
        return None

    solved = _as_fraction(solved_value)

    if solved is None:
        return None

    derived_values: List[Fraction] = []
    derived_role: Optional[str] = None

    for constraint in constraints:
        data = dict(constraint.data or {})

        quantity = _as_fraction(data.get("quantity"))
        offset = _as_fraction(data.get("offset"))

        if quantity is None or quantity == 0 or offset is None:
            continue

        unit_role = str(
            data.get("unit_role")
            or "unit_value"
        )
        common_role = str(
            data.get("common_role")
            or "available_amount"
        )

        if solved_variable_role == unit_role:
            derived_values.append(
                quantity * solved + offset
            )
            derived_role = common_role

        elif solved_variable_role == common_role:
            derived_values.append(
                (solved - offset) / quantity
            )
            derived_role = unit_role

    if not derived_values:
        return None

    reference = derived_values[0]

    if any(
        value != reference
        for value in derived_values[1:]
    ):
        return None

    return {
        "role": derived_role,
        "value": (
            str(reference.numerator)
            if reference.denominator == 1
            else (
                f"{reference.numerator}/"
                f"{reference.denominator}"
            )
        ),
        "proved": True,
        "proof_count": len(derived_values),
    }

def equations_have_same_solution_set(
    equation_a: str,
    equation_b: str,
) -> Optional[bool]:
    """
    Vérifie si deux équations décrivent le même
    sous-problème algébrique.

    Exemples :

        10x-5=5x+12
        5x=17
        x=17/5

    appartiennent à la même chaîne.

    Mais :

        2x-6=7

    n'appartient pas à cette chaîne.
    """

    residual_a = (
        equation_to_residual(
            equation_a
        )
    )

    residual_b = (
        equation_to_residual(
            equation_b
        )
    )

    if (
        residual_a is None
        or residual_b is None
    ):
        return None

    symbols = (
        residual_a.free_symbols
        | residual_b.free_symbols
    )

    if not symbols:
        return None

    try:

        variables = sorted(
            symbols,
            key=lambda item: str(
                item
            ),
        )

        solutions_a = sp.solve(
            residual_a,
            variables,
            dict=True,
        )

        solutions_b = sp.solve(
            residual_b,
            variables,
            dict=True,
        )

    except Exception:

        return None

    return (
        solutions_a
        == solutions_b
    )