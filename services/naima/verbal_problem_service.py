from __future__ import annotations

import re
import unicodedata

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Dict, List, Optional

from services.math_verification import (
    verifier_equation_intermediaire_equivalente,
)

from services.naima.semantic_compiler_service import (
    compile_parameterization,
    derive_target_value_from_product_offset,
    equations_are_same_constraint,
)

from services.naima.semantic_interpreter_service import (
    interpret_math_situation,
)

# ============================================================
# REPRÉSENTATION SÉMANTIQUE GÉNÉRIQUE
# ============================================================

@dataclass
class SemanticExpression:
    """
    Représentation générique d'une expression quantitative.

    Exemples :
        x
        30
        2*x
        x + 2*x

    Cette structure ne dépend d'aucun type particulier
    de problème verbal.
    """

    kind: str
    value: Optional[Any] = None
    variable: Optional[str] = None
    factor: Optional[Any] = None
    terms: List["SemanticExpression"] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SemanticConstraint:
    """
    Relation mathématique générique.

    Exemples :
        Marie = 2 * Paul
        Paul + Marie = 30
        coût - budget = 5
        budget - coût = 12

    Les futurs problèmes verbaux doivent converger vers
    ce format au lieu de créer un moteur particulier
    pour chaque situation.
    """

    relation: str
    left: Optional[SemanticExpression] = None
    right: Optional[SemanticExpression] = None
    value: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


def make_variable_expression(
    variable: str,
    *,
    metadata: Optional[Dict[str, Any]] = None,
) -> SemanticExpression:
    return SemanticExpression(
        kind="variable",
        variable=str(variable or "").strip().lower(),
        metadata=dict(metadata or {}),
    )


def make_constant_expression(
    value: Any,
) -> SemanticExpression:
    return SemanticExpression(
        kind="constant",
        value=value,
    )


def make_product_expression(
    factor: Any,
    expression: SemanticExpression,
) -> SemanticExpression:
    return SemanticExpression(
        kind="product",
        factor=factor,
        terms=[expression],
    )


def make_sum_expression(
    terms: List[SemanticExpression],
) -> SemanticExpression:
    return SemanticExpression(
        kind="sum",
        terms=list(terms or []),
    )

def make_difference_expression(
    left: SemanticExpression,
    right: SemanticExpression,
) -> SemanticExpression:
    """
    Construit une différence générique :

        left - right

    Cette structure pourra représenter :

        coût - budget
        budget - coût
        distance totale - distance parcourue
        température finale - température initiale
        etc.
    """

    return SemanticExpression(
        kind="difference",
        terms=[
            left,
            right,
        ],
    )


def make_offset_expression(
    expression: SemanticExpression,
    offset: Any,
) -> SemanticExpression:

    try:

        numeric_offset = float(
            offset
        )

    except (
        TypeError,
        ValueError,
    ):

        return expression

    if numeric_offset == 0:

        return expression

    if numeric_offset.is_integer():

        normalized_offset: Any = int(
            numeric_offset
        )

    else:

        normalized_offset = (
            numeric_offset
        )

    if numeric_offset > 0:

        return make_sum_expression(
            [
                expression,
                make_constant_expression(
                    normalized_offset
                ),
            ]
        )

    return make_difference_expression(
        expression,
        make_constant_expression(
            abs(
                normalized_offset
            )
        ),
    )


def convert_legacy_constraints_to_semantic(
    *,
    variable_meaning: Optional[
        Dict[str, Any]
    ],
    constraints: Optional[
        List[Dict[str, Any]]
    ],
) -> List[
    SemanticConstraint
]:
    """
    Convertit les contraintes verbales historiques
    vers la représentation sémantique générique.

    Relations actuellement prises en charge :

        multiple_of
        sum_equals
        product_offset_common_value

    La fonction n'invente jamais de relation absente.
    """

    semantic_constraints: List[
        SemanticConstraint
    ] = []

    variable_meaning = dict(
        variable_meaning
        or {}
    )

    constraints = list(
        constraints
        or []
    )

    variable = str(
        variable_meaning.get(
            "variable"
        )
        or ""
    ).strip().lower()

    reference_entity = str(
        variable_meaning.get(
            "entity"
        )
        or ""
    ).strip()

    if not variable:
        return []

    # ========================================================
    # EXPRESSION DE LA VARIABLE PRINCIPALE
    # ========================================================

    variable_expression = (
        make_variable_expression(
            variable,
            metadata={
                "entity": (
                    reference_entity
                ),
                "meaning": (
                    variable_meaning.get(
                        "meaning"
                    )
                ),
            },
        )
    )

    # ========================================================
    # TABLE DES ENTITÉS DÉJÀ CONNUES
    # ========================================================

    entity_expressions: Dict[
        str,
        SemanticExpression
    ] = {}

    if reference_entity:

        entity_expressions[
            reference_entity.lower()
        ] = variable_expression

    # ========================================================
    # 1. RELATIONS MULTIPLICATIVES
    #
    # Exemple :
    #
    #     Marie = 2 * Paul
    #
    # si :
    #
    #     Paul = x
    #
    # alors :
    #
    #     Marie = 2*x
    # ========================================================

    for constraint in constraints:

        if not isinstance(
            constraint,
            dict,
        ):
            continue

        relation = str(
            constraint.get(
                "relation"
            )
            or ""
        ).strip()

        if (
            relation
            != "multiple_of"
        ):
            continue

        subject = str(
            constraint.get(
                "subject"
            )
            or ""
        ).strip()

        reference = str(
            constraint.get(
                "reference"
            )
            or ""
        ).strip()

        factor = (
            constraint.get(
                "factor"
            )
        )

        if (
            not subject
            or not reference
            or factor is None
        ):
            continue

        reference_expression = (
            entity_expressions.get(
                reference.lower()
            )
        )

        if (
            reference_expression
            is None
        ):
            continue

        subject_expression = (
            make_product_expression(
                factor,
                reference_expression,
            )
        )

        subject_expression.metadata[
            "entity"
        ] = subject

        entity_expressions[
            subject.lower()
        ] = subject_expression

        semantic_constraints.append(
            SemanticConstraint(
                relation="equality",

                left=SemanticExpression(
                    kind="entity",
                    metadata={
                        "entity": subject,
                    },
                ),

                right=(
                    subject_expression
                ),

                metadata={
                    "source_relation": (
                        "multiple_of"
                    ),
                    "subject": subject,
                    "reference": reference,
                    "factor": factor,
                },
            )
        )

    # ========================================================
    # 2. SOMMES
    #
    # Exemple :
    #
    #     Paul + Marie = 30
    #
    # devient :
    #
    #     x + 2*x = 30
    # ========================================================

    for constraint in constraints:

        if not isinstance(
            constraint,
            dict,
        ):
            continue

        relation = str(
            constraint.get(
                "relation"
            )
            or ""
        ).strip()

        if relation != "sum_equals":
            continue

        entities = list(
            constraint.get(
                "entities",
                [],
            )
            or []
        )

        value = (
            constraint.get(
                "value"
            )
        )

        if (
            not entities
            or value is None
        ):
            continue

        terms: List[
            SemanticExpression
        ] = []

        complete = True

        for entity in entities:

            entity_key = str(
                entity
                or ""
            ).strip().lower()

            expression = (
                entity_expressions.get(
                    entity_key
                )
            )

            if (
                expression
                is None
            ):

                complete = False
                break

            terms.append(
                expression
            )

        if not complete:
            continue

        semantic_constraints.append(
            SemanticConstraint(
                relation="equality",

                left=(
                    make_sum_expression(
                        terms
                    )
                ),

                right=(
                    make_constant_expression(
                        value
                    )
                ),

                metadata={
                    "source_relation": (
                        "sum_equals"
                    ),
                    "entities": entities,
                },
            )
        )

    # ========================================================
    # 3. PRODUIT + OFFSET VERS VALEUR COMMUNE
    #
    # Exemple :
    #
    #     budget = 10*x - 5
    #
    #     budget = 5*x + 12
    #
    # Les deux expressions désignent la même quantité.
    # ========================================================

    common_role_expressions: Dict[
        str,
        List[
            SemanticExpression
        ],
    ] = {}

    for constraint in constraints:

        if not isinstance(
            constraint,
            dict,
        ):
            continue

        relation = str(
            constraint.get(
                "relation"
            )
            or ""
        ).strip()

        if (
            relation
            != "product_offset_common_value"
        ):
            continue

        quantity = (
            constraint.get(
                "quantity"
            )
        )

        offset = (
            constraint.get(
                "offset"
            )
        )

        common_role = str(
            constraint.get(
                "common_role"
            )
            or "common_value"
        ).strip()

        if (
            quantity
            is None
        ):
            continue

        # ----------------------------------------------------
        # quantité * variable
        #
        # Ex. 10*x
        # ----------------------------------------------------

        product_expression = (
            make_product_expression(
                quantity,
                variable_expression,
            )
        )

        # ----------------------------------------------------
        # quantité * variable + offset
        #
        # Ex.
        #
        #     10*x - 5
        #     5*x + 12
        # ----------------------------------------------------

        common_expression = (
            make_offset_expression(
                product_expression,
                (
                    offset
                    if offset is not None
                    else 0
                ),
            )
        )

        common_expression.metadata.update(
            {
                "common_role": (
                    common_role
                ),
                "item": (
                    constraint.get(
                        "item"
                    )
                ),
                "quantity": (
                    quantity
                ),
                "offset": (
                    offset
                ),
                "offset_kind": (
                    constraint.get(
                        "offset_kind"
                    )
                ),
                "source_relation": (
                    "product_offset_common_value"
                ),
            }
        )

        common_role_expressions.setdefault(
            common_role,
            [],
        ).append(
            common_expression
        )

    # ========================================================
    # 4. ÉGALITÉ ENTRE EXPRESSIONS D'UNE MÊME VALEUR
    #
    # Si :
    #
    #     B = 10*x - 5
    #
    # et :
    #
    #     B = 5*x + 12
    #
    # alors :
    #
    #     10*x - 5 = 5*x + 12
    # ========================================================

    for (
        common_role,
        expressions,
    ) in (
        common_role_expressions.items()
    ):

        if (
            len(
                expressions
            )
            < 2
        ):
            continue

        first_expression = (
            expressions[0]
        )

        for other_expression in (
            expressions[1:]
        ):

            semantic_constraints.append(
                SemanticConstraint(
                    relation="equality",

                    left=(
                        first_expression
                    ),

                    right=(
                        other_expression
                    ),

                    metadata={
                        "source_relation": (
                            "common_value_equivalence"
                        ),
                        "common_role": (
                            common_role
                        ),
                    },
                )
            )

    # ========================================================
    # IMPORTANT :
    #
    # LE RETURN DOIT ÊTRE APRÈS TOUS LES PASSAGES.
    # ========================================================

    return semantic_constraints

def semantic_expression_to_math(
    expression: SemanticExpression,
) -> Optional[str]:
    """Compile une expression sémantique vers de l'algèbre simple."""

    if not isinstance(expression, SemanticExpression):
        return None

    kind = str(expression.kind or "").strip()

    if kind == "variable":
        variable = str(expression.variable or "").strip().lower()
        return variable or None

    if kind == "constant":
        if expression.value is None:
            return None
        return str(expression.value)

    if kind == "product":
        if expression.factor is None or not expression.terms:
            return None
        inner = semantic_expression_to_math(expression.terms[0])
        if not inner:
            return None
        return f"{expression.factor}*{inner}"

    if kind == "sum":
        compiled_terms: List[str] = []
        for term in expression.terms or []:
            compiled = semantic_expression_to_math(term)
            if not compiled:
                return None
            compiled_terms.append(compiled)
        if not compiled_terms:
            return None
        return "+".join(compiled_terms)

    # --------------------------------------------------------
    # DIFFÉRENCE
    # --------------------------------------------------------

    if kind == "difference":

        if (
            len(
                expression.terms
                or []
            )
            != 2
        ):
            return None

        left = (
            semantic_expression_to_math(
                expression.terms[0]
            )
        )

        right = (
            semantic_expression_to_math(
                expression.terms[1]
            )
        )

        if (
            not left
            or not right
        ):
            return None

        return (
            f"{left}-{right}"
        )

    if kind == "entity":
        return None

    return None


def compile_semantic_constraint_equation(
    constraint: SemanticConstraint,
) -> Optional[str]:
    """Compile une contrainte sémantique d'égalité vers une équation."""

    if not isinstance(constraint, SemanticConstraint):
        return None
    if constraint.relation != "equality":
        return None
    if constraint.left is None or constraint.right is None:
        return None

    left = semantic_expression_to_math(constraint.left)
    right = semantic_expression_to_math(constraint.right)

    if not left or not right:
        return None

    return f"{left}={right}"


def build_semantic_model_from_verbal_constraints(
    *,
    variable_meaning: Optional[
        Dict[str, Any]
    ],
    constraints: Optional[
        List[Dict[str, Any]]
    ],
) -> Dict[str, Any]:

    semantic_constraints = (
        convert_legacy_constraints_to_semantic(
            variable_meaning=(
                variable_meaning
            ),
            constraints=(
                constraints
            ),
        )
    )

    equations: List[
        str
    ] = []

    for constraint in (
        semantic_constraints
    ):

        equation = (
            compile_semantic_constraint_equation(
                constraint
            )
        )

        if (
            equation
            and equation
            not in equations
        ):

            equations.append(
                equation
            )

    return {
        "constraints": (
            semantic_constraints
        ),
        "equations": (
            equations
        ),
    }


# ============================================================
# OUTILS GÉNÉRAUX
# ============================================================

def _walk_texts(
    value: Any,
) -> List[str]:
    """
    Parcourt récursivement une structure
    dict/list/tuple/str et retourne tous
    les textes rencontrés.
    """

    texts: List[str] = []

    if isinstance(
        value,
        str,
    ):
        texts.append(
            value
        )

    elif isinstance(
        value,
        dict,
    ):
        for item in value.values():
            texts.extend(
                _walk_texts(
                    item
                )
            )

    elif isinstance(
        value,
        (
            list,
            tuple,
        ),
    ):
        for item in value:
            texts.extend(
                _walk_texts(
                    item
                )
            )

    return texts


def _normalize_relation_symbols(
    text: Any,
) -> str:

    return (
        str(
            text
            or ""
        )
        .replace(
            "≤",
            "<=",
        )
        .replace(
            "≥",
            ">=",
        )
        .replace(
            "×",
            "*",
        )
        .replace(
            "÷",
            "/",
        )
        .replace(
            ",",
            ".",
        )
    )


# ============================================================
# EXTRACTION D'ÉQUATIONS
# ============================================================

def extract_equations_from_text(
    text: Any,
) -> List[str]:
    """
    Extrait des équations algébriques simples de manière
    conservatrice.

    Variables scolaires supportées :
        x, y, z, p, n, t, a, b, m

    Le whitelist évite d'absorber des mots de prose autour
    de l'équation (ex. "avec2(x+2x)=30").
    """

    normalized = _normalize_relation_symbols(text).lower()
    variable_chars = "xyzpntabm"

    candidates = re.findall(
        rf"(?<![a-zà-ÿ])"
        rf"[-+0-9{variable_chars}().*/\s]+"
        rf"="
        rf"[-+0-9{variable_chars}().*/\s]+"
        rf"(?![a-zà-ÿ])",
        normalized,
        flags=re.IGNORECASE,
    )

    equations: List[str] = []

    for candidate in candidates:
        equation = re.sub(r"\s+", "", candidate).strip()

        # Retirer uniquement la ponctuation de fin de phrase,
        # sans toucher aux points décimaux internes.
        while equation.endswith("."):
            equation = equation[:-1]

        equation = equation.rstrip("+-*/")

        if not equation or equation.count("=") != 1:
            continue

        left, right = equation.split("=", 1)
        if not left or not right:
            continue

        if not re.search(
            rf"[{variable_chars}]",
            equation,
            flags=re.IGNORECASE,
        ):
            continue

        if not re.fullmatch(
            rf"[0-9{variable_chars}+\-*/().=]+",
            equation,
            flags=re.IGNORECASE,
        ):
            continue

        if equation not in equations:
            equations.append(equation)

    return equations

def extract_reference_equations(
    correction: Any,
) -> List[str]:
    """
    Extrait les équations utilisables comme
    références depuis la correction structurée
    d'un exercice généré.

    Aucun accès Flask/session ici.
    """

    equations: List[str] = []

    for text in _walk_texts(
        correction
    ):

        for equation in (
            extract_equations_from_text(
                text
            )
        ):

            if equation not in equations:
                equations.append(
                    equation
                )

    return equations


# ============================================================
# MODÉLISATION
# ============================================================

def validate_modeling_equation(
    *,
    student_answer: str,
    correction: Any,
) -> Dict[str, Any]:
    """
    Vérifie si l'équation de modélisation
    proposée par l'élève est équivalente à
    une équation présente dans la correction.

    IMPORTANT :

    absence de preuve != réponse incorrecte.

    Si aucune équation exploitable n'est
    disponible, verdict = uncertain.
    """

    references = (
        extract_reference_equations(
            correction
        )
    )

    if not references:

        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "verbal_problem_modeling"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": None,
            "requires_review": True,
            "reason": (
                "No deterministic reference "
                "equation is available."
            ),
            "details": {
                "reference_equations": [],
            },
        }

    checked = []

    for reference in references:

        try:

            verification = (
                verifier_equation_intermediaire_equivalente(
                    equation_initiale=(
                        reference
                    ),
                    reponse_eleve=(
                        student_answer
                    ),
                )
            )

        except Exception as exc:

            checked.append({
                "reference_equation": (
                    reference
                ),
                "error": (
                    type(
                        exc
                    ).__name__
                ),
            })

            continue

        checked.append({
            "reference_equation": (
                reference
            ),
            "verification": (
                verification
            ),
        })

        if not verification.get(
            "verification_equation_intermediaire"
        ):
            continue

        if verification.get(
            "est_correct"
        ) is True:

            student_equation = (
                verification.get(
                    "equation_eleve"
                )
            )

            return {
                "verdict": "correct",
                "confidence": 1.0,
                "method": (
                    "verbal_problem_modeling"
                ),
                "result_correct": None,
                "reasoning_correct": True,
                "error_type": None,
                "requires_review": False,
                "reason": (
                    "The learner's modeling "
                    "equation is equivalent "
                    "to a deterministic reference "
                    "equation."
                ),
                "details": {
                    "reference_equation": (
                        reference
                    ),
                    "student_equation": (
                        student_equation
                    ),
                    "reference_equations": (
                        references
                    ),
                    "verification": (
                        verification
                    ),
                },
            }

    # --------------------------------------------------------
    # PRUDENCE
    # --------------------------------------------------------
    #
    # Plusieurs équations peuvent apparaître
    # dans une correction.
    #
    # Le fait qu'aucune ne corresponde ne
    # prouve pas encore nécessairement que
    # la modélisation de l'élève est fausse.
    # --------------------------------------------------------

    return {
        "verdict": "uncertain",
        "confidence": 0.0,
        "method": (
            "verbal_problem_modeling"
        ),
        "result_correct": None,
        "reasoning_correct": None,
        "error_type": None,
        "requires_review": True,
        "reason": (
            "The proposed modeling equation "
            "could not be deterministically "
            "matched to the available references."
        ),
        "details": {
            "reference_equations": (
                references
            ),
            "checked_references": (
                checked
            ),
        },
    }


# ============================================================
# RÉPONSE FINALE DE RÉFÉRENCE
# ============================================================

def extract_final_reference_answer(
    correction: Any,
) -> str:
    """
    Récupère une réponse finale explicite
    depuis la correction structurée.

    Les valeurs génériques comme
    'réponse à vérifier' sont rejetées.
    """

    if not isinstance(
        correction,
        dict,
    ):
        return ""

    possible_keys = [
        "reponse_finale",
        "réponse_finale",
        "resultat_final",
        "résultat_final",
        "solution_finale",
        "solution",
    ]

    for key in possible_keys:

        value = (
            correction.get(
                key
            )
        )

        if not isinstance(
            value,
            str,
        ):
            continue

        value = (
            value.strip()
        )

        if not value:
            continue

        if (
            value.lower()
            in {
                "réponse à vérifier",
                "reponse a verifier",
                "à vérifier",
                "a verifier",
            }
        ):
            continue

        return value

    return ""


# ============================================================
# NOMBRES / FRACTIONS
# ============================================================

def extract_numeric_values(
    text: Any,
) -> List[Fraction]:
    """
    Extrait les valeurs numériques et
    fractionnaires explicites d'un texte.

    Exemples :

        12
        -3
        2.5
        5/3
    """

    values: List[Fraction] = []

    normalized = (
        str(
            text
            or ""
        )
        .replace(
            ",",
            ".",
        )
    )

    matches = re.findall(
        r"(?<![\w.])"
        r"[-+]?\d+(?:\.\d+)?"
        r"(?:\s*/\s*[-+]?\d+(?:\.\d+)?)?",
        normalized,
    )

    for item in matches:

        item = re.sub(
            r"\s+",
            "",
            item,
        )

        try:

            if "/" in item:

                numerator, denominator = (
                    item.split(
                        "/",
                        1,
                    )
                )

                value = Fraction(
                    numerator
                ) / Fraction(
                    denominator
                )

            else:

                value = Fraction(
                    item
                )

        except Exception:
            continue

        if value not in values:
            values.append(
                value
            )

    return values


# ============================================================
# NORMALISATION SÉMANTIQUE SIMPLE
# ============================================================

def normalize_semantic_text(
    text: Any,
) -> str:

    normalized = (
        str(
            text
            or ""
        )
        .lower()
    )

    normalized = "".join(
        character
        for character in (
            unicodedata.normalize(
                "NFD",
                normalized,
            )
        )
        if (
            unicodedata.category(
                character
            )
            != "Mn"
        )
    )

    normalized = re.sub(
        r"[^a-z0-9%€$]+",
        " ",
        normalized,
    )

    return (
        re.sub(
            r"\s+",
            " ",
            normalized,
        )
        .strip()
    )


# ============================================================
# LA RÉPONSE VISE-T-ELLE LE BUT FINAL ?
# ============================================================

def targets_final_problem_objective(
    *,
    student_answer: str,
    last_teacher_question: str,
    objective: str,
) -> bool:
    """
    Repère prudemment si le tour actuel
    semble répondre à la grande question
    finale du problème verbal.

    Cette détection ne valide pas le résultat.
    """

    student = (
        normalize_semantic_text(
            student_answer
        )
    )

    teacher = (
        normalize_semantic_text(
            last_teacher_question
        )
    )

    target = (
        normalize_semantic_text(
            objective
        )
    )

    if (
        not student
        or not target
    ):
        return False

    semantic_families = [
        [
            "budget",
            "cout",
            "prix",
            "montant",
            "argent",
        ],
        [
            "aire",
            "surface",
        ],
        [
            "perimetre",
        ],
        [
            "volume",
        ],
        [
            "distance",
        ],
        [
            "duree",
            "temps",
        ],
        [
            "vitesse",
        ],
        [
            "age",
            "ages",
        ],
        [
            "largeur",
            "longueur",
            "dimensions",
        ],
        [
            "nombre total",
            "total",
        ],
    ]

    for family in semantic_families:

        if not any(
            marker in target
            for marker in family
        ):
            continue

        if (
            any(
                marker in student
                for marker in family
            )
            or any(
                marker in teacher
                for marker in family
            )
        ):
            return True

    stopwords = {
        "quel",
        "quelle",
        "quels",
        "quelles",
        "combien",
        "sera",
        "seront",
        "est",
        "sont",
        "pour",
        "avec",
        "dans",
        "des",
        "les",
        "une",
        "un",
        "du",
        "de",
        "la",
        "le",
        "et",
        "qui",
        "que",
        "ce",
        "cet",
        "cette",
        "tous",
        "toutes",
        "leur",
        "leurs",
        "sur",
        "par",
        "afin",
    }

    target_words = {
        word
        for word in (
            target.split()
        )
        if (
            len(
                word
            )
            >= 4
            and word
            not in stopwords
        )
    }

    current_words = set(
        (
            teacher
            + " "
            + student
        )
        .split()
    )

    return (
        len(
            target_words
            & current_words
        )
        >= 3
    )


# ============================================================
# VALIDATION DE LA RÉPONSE FINALE
# ============================================================

def validate_final_answer(
    *,
    student_answer: str,
    correction: Any,
) -> Dict[str, Any]:
    """
    Validation conservatrice d'une réponse
    finale de problème verbal.

    Comme dans la version historique :
    on exige qu'une réponse de référence
    explicite soit disponible.

    Si la preuve est insuffisante :
        verdict = uncertain

    On ne transforme jamais automatiquement
    l'absence de preuve en erreur.
    """

    reference = (
        extract_final_reference_answer(
            correction
        )
    )

    if not reference:

        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "verbal_problem_final_answer"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": None,
            "requires_review": True,
            "reason": (
                "No explicit final reference "
                "answer is available."
            ),
            "details": {
                "reference_answer": None,
            },
        }

    expected_values = (
        extract_numeric_values(
            reference
        )
    )

    student_values = (
        extract_numeric_values(
            student_answer
        )
    )

    if not expected_values:

        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "verbal_problem_final_answer"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": None,
            "requires_review": True,
            "reason": (
                "The reference answer contains "
                "no deterministic numeric value."
            ),
            "details": {
                "reference_answer": (
                    reference
                ),
            },
        }

    all_expected_present = all(
        value in student_values
        for value in expected_values
    )

    if not all_expected_present:

        # ----------------------------------------------------
        # IMPORTANT :
        #
        # on conserve le comportement historique :
        # une correction textuelle peut contenir des
        # nombres intermédiaires.
        #
        # Donc on NE déclare PAS automatiquement faux.
        # ----------------------------------------------------

        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "verbal_problem_final_answer"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": None,
            "requires_review": True,
            "reason": (
                "The final answer cannot be "
                "deterministically confirmed."
            ),
            "details": {
                "reference_answer": (
                    reference
                ),
                "expected_values": [
                    str(
                        value
                    )
                    for value
                    in expected_values
                ],
                "student_values": [
                    str(
                        value
                    )
                    for value
                    in student_values
                ],
            },
        }

    return {
        "verdict": "correct",
        "confidence": 1.0,
        "method": (
            "verbal_problem_final_answer"
        ),
        "result_correct": True,
        "reasoning_correct": None,
        "error_type": None,
        "requires_review": False,
        "reason": (
            "All deterministically expected "
            "final numeric values are present "
            "in the learner's answer."
        ),
        "details": {
            "reference_answer": (
                reference
            ),
            "expected_values": [
                str(
                    value
                )
                for value
                in expected_values
            ],
            "student_values": [
                str(
                    value
                )
                for value
                in student_values
            ],
        },
    }

# ============================================================
# DÉTECTION D'UN ÉNONCÉ VERBAL SAISI PAR L'ÉLÈVE
# ============================================================

def is_probable_verbal_problem_statement(
    text: Any,
) -> bool:
    """
    Détecte prudemment si un message ressemble à l'énoncé
    d'un problème mathématique verbal.

    Cette fonction ne résout rien et ne valide rien.

    Elle sert uniquement à décider si Naima doit conserver
    le message comme objectif verbal actif.

    Exemples positifs :

        Marie a deux fois l'âge de Paul.
        La somme de leurs âges est 30 ans.

        Un rectangle a une longueur de 12 cm...
        Quel est son périmètre ?

    Exemples négatifs :

        Bonjour Naima

        x=10

        je divise par 3
    """

    raw = str(
        text
        or ""
    ).strip()

    if len(raw) < 20:
        return False

    # Une équation explicite relève d'abord du moteur
    # mathématique, pas de la détection d'énoncé verbal.
    if extract_equations_from_text(
        raw
    ):
        return False

    normalized = (
        normalize_semantic_text(
            raw
        )
    )

    if not normalized:
        return False

    # --------------------------------------------------------
    # PRÉSENCE D'UNE QUANTITÉ
    # --------------------------------------------------------

    number_words = {
        "zero",
        "un",
        "une",
        "deux",
        "trois",
        "quatre",
        "cinq",
        "six",
        "sept",
        "huit",
        "neuf",
        "dix",
        "onze",
        "douze",
        "treize",
        "quatorze",
        "quinze",
        "seize",
        "vingt",
        "trente",
        "quarante",
        "cinquante",
        "cent",
    }

    words = set(
        normalized.split()
    )

    has_quantity = bool(
        re.search(
            r"\d",
            normalized,
        )
        or (
            words
            & number_words
        )
    )

    if not has_quantity:
        return False

    # --------------------------------------------------------
    # INDICES DE RELATION MATHÉMATIQUE CONTEXTUELLE
    # --------------------------------------------------------

    relation_markers = [
        "somme",
        "total",
        "difference",
        "produit",
        "fois",
        "double",
        "triple",
        "moitie",
        "plus que",
        "moins que",
        "reste",
        "restent",
        "partage",
        "repartir",
        "rapport",
        "proportion",
        "pourcentage",
        "age",
        "ages",
        "prix",
        "cout",
        "budget",
        "argent",
        "distance",
        "vitesse",
        "temps",
        "duree",
        "longueur",
        "largeur",
        "hauteur",
        "perimetre",
        "aire",
        "surface",
        "volume",
        "nombre",
        "quantite",
    ]

    relation_score = sum(
        1
        for marker
        in relation_markers
        if marker in normalized
    )

    # --------------------------------------------------------
    # INDICES DE QUESTION / OBJECTIF
    # --------------------------------------------------------

    question_markers = [
        "combien",
        "quel",
        "quelle",
        "quels",
        "quelles",
        "determine",
        "determiner",
        "trouve",
        "trouver",
        "calcule",
        "calculer",
        "cherche",
        "chercher",
    ]

    has_question_signal = bool(
        "?" in raw
        or any(
            marker in normalized
            for marker
            in question_markers
        )
    )

    # --------------------------------------------------------
    # DÉCISION CONSERVATRICE
    # --------------------------------------------------------
    #
    # Deux relations contextuelles suffisent.
    #
    # Sinon :
    #     une relation + une question explicite.
    # --------------------------------------------------------

    if relation_score >= 2:
        return True

    if (
        relation_score >= 1
        and has_question_signal
    ):
        return True

    return False


def extract_proved_algebraic_solution(
    validation: Any,
) -> Optional[Dict[str, Any]]:
    """
    Extrait une solution algébrique uniquement lorsque le
    moteur déterministe l'a réellement prouvée.

    La variable est récupérée dynamiquement et n'est plus
    forcée à x.
    """

    if validation is None:
        return None

    if isinstance(validation, dict):
        data = dict(validation)
    elif hasattr(validation, "to_dict"):
        try:
            data = validation.to_dict()
        except Exception:
            return None
    else:
        return None

    if data.get("verdict") != "correct":
        return None
    if data.get("result_correct") is not True:
        return None

    method = str(data.get("method") or "").strip()
    if method not in {
        "equation_solution",
        "verbal_problem_intermediate_solution",
    }:
        return None

    details = data.get("details") or {}
    if not isinstance(details, dict):
        details = {}

    value = None
    for key in (
        "valeur_x_proposee",
        "valeur_x_calculee",
        "solution",
        "proposed_value",
        "calculated_value",
    ):
        candidate = details.get(key)
        if candidate is not None:
            value = candidate
            break

    if value is None:
        return None

    value = str(value).strip()
    if not value:
        return None

    variable = ""

    for key in (
        "variable",
        "solved_variable",
        "variable_resolue",
        "variable_proposee",
    ):
        candidate = str(details.get(key) or "").strip().lower()
        if re.fullmatch(r"[a-z]", candidate):
            variable = candidate
            break

    if not variable:
        equation_like_keys = (
            "student_equation",
            "equation_eleve",
            "equation",
            "transformed_equation",
            "equation_transformee",
        )

        search_values = []
        for key in equation_like_keys:
            candidate = details.get(key)
            if isinstance(candidate, str) and candidate.strip():
                search_values.append(candidate)

        # Compatibilité : certaines validations placent
        # l'équation sous un autre champ textuel.
        for candidate in details.values():
            if isinstance(candidate, str) and candidate.strip():
                if candidate not in search_values:
                    search_values.append(candidate)

        for candidate in search_values:
            equations = extract_equations_from_text(candidate)
            if not equations:
                continue
            match = re.search(r"([a-z])", equations[0], flags=re.IGNORECASE)
            if match:
                variable = match.group(1).lower()
                break

    # Rétrocompatibilité historique : les anciennes validations
    # n'enregistraient pas explicitement la variable.
    if not variable:
        variable = "x"

    if not re.fullmatch(r"[a-z]", variable):
        return None

    return {
        "variable": variable,
        "value": value,
        "proved": True,
        "validation_method": method,
    }

def extract_variable_meaning(
    text: str,
) -> Optional[Dict[str, str]]:
    """
    Extrait de manière conservatrice la signification
    explicitement donnée à une variable par l'élève.

    Exemples supportés :

        Soit x l'âge de Paul
        x représente l'âge de Paul
        x est l'âge de Paul
        Si P est l'âge de Paul

        x est le prix d'un CD
        x représente le prix d'un billet
        Soit x le prix d'un CD

        x est la longueur du rectangle
        x représente la distance parcourue

        Je préfère appeler x le prix d'un CD

    Aucune signification n'est devinée.
    """

    value = str(
        text
        or ""
    ).strip()

    if not value:
        return None

    # ========================================================
    # NORMALISATION LÉGÈRE
    # ========================================================

    value = (
        value
        .replace("’", "'")
        .strip()
    )

    # ========================================================
    # 1. CAS HISTORIQUE : ÂGE D'UNE PERSONNE
    # ========================================================

    age_patterns = [
        (
            r"\bsoit\s+([A-Za-z])\s+"
            r"(?:l'\s*)?"
            r"(âge|age)\s+de\s+"
            r"([A-Za-zÀ-ÖØ-öø-ÿ'-]+)"
        ),
        (
            r"\b([A-Za-z])\s+"
            r"(?:représente|represente)\s+"
            r"(?:l'\s*)?"
            r"(âge|age)\s+de\s+"
            r"([A-Za-zÀ-ÖØ-öø-ÿ'-]+)"
        ),
        (
            r"\b([A-Za-z])\s+"
            r"(?:est|=)\s+"
            r"(?:l'\s*)?"
            r"(âge|age)\s+de\s+"
            r"([A-Za-zÀ-ÖØ-öø-ÿ'-]+)"
        ),
        (
            r"\bsi\s+([A-Za-z])\s+est\s+"
            r"(?:l'\s*)?"
            r"(âge|age)\s+de\s+"
            r"([A-Za-zÀ-ÖØ-öø-ÿ'-]+)"
        ),
    ]

    for pattern in age_patterns:

        match = re.search(
            pattern,
            value,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        variable = (
            match.group(1)
            .lower()
            .strip()
        )

        concept = (
            match.group(2)
            .lower()
            .strip()
        )

        entity = (
            match.group(3)
            .strip()
        )

        if concept == "age":
            concept = "âge"

        return {
            "variable": variable,
            "meaning": (
                f"{concept} de {entity}"
            ),
            "entity": entity,
        }

    # ========================================================
    # 2. CAS GÉNÉRIQUE
    # ========================================================

    generic_patterns = [
        (
            r"\b(?:je\s+)?"
            r"(?:préfère|prefere)\s+"
            r"(?:appeler|nommer)\s+"
            r"([A-Za-z])\s+"
            r"("
                r"(?:le|la|l')\s*"
                r"[A-Za-zÀ-ÖØ-öø-ÿ'-]+"
                r"(?:\s+"
                    r"(?:de|du|des|d')\s*"
                    r"(?:un|une|le|la|les)?\s*"
                    r"[A-Za-zÀ-ÖØ-öø-ÿ'-]+"
                r")?"
            r")"
        ),
        (
            r"\bsoit\s+([A-Za-z])\s+"
            r"("
                r"(?:le|la|l')\s*"
                r"[A-Za-zÀ-ÖØ-öø-ÿ'-]+"
                r"(?:\s+"
                    r"(?:de|du|des|d')\s*"
                    r"(?:un|une|le|la|les)?\s*"
                    r"[A-Za-zÀ-ÖØ-öø-ÿ'-]+"
                r")?"
            r")"
        ),
        (
            r"\b([A-Za-z])\s+"
            r"(?:représente|represente)\s+"
            r"("
                r"(?:le|la|l')\s*"
                r"[A-Za-zÀ-ÖØ-öø-ÿ'-]+"
                r"(?:\s+"
                    r"(?:de|du|des|d')\s*"
                    r"(?:un|une|le|la|les)?\s*"
                    r"[A-Za-zÀ-ÖØ-öø-ÿ'-]+"
                r")?"
            r")"
        ),
        (
            r"\b([A-Za-z])\s+"
            r"(?:est|=)\s+"
            r"("
                r"(?:le|la|l')\s*"
                r"[A-Za-zÀ-ÖØ-öø-ÿ'-]+"
                r"(?:\s+"
                    r"(?:de|du|des|d')\s*"
                    r"(?:un|une|le|la|les)?\s*"
                    r"[A-Za-zÀ-ÖØ-öø-ÿ'-]+"
                r")?"
            r")"
        ),
    ]

    for pattern in generic_patterns:

        match = re.search(
            pattern,
            value,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        variable = (
            match.group(1)
            .lower()
            .strip()
        )

        meaning = (
            match.group(2)
            .strip()
        )

        meaning = re.sub(
            r"\s+",
            " ",
            meaning,
        )

        # ====================================================
        # EXTRACTION DE L'ENTITÉ
        # ====================================================
        #
        # Cas :
        #
        #   prix d'un CD
        #       -> CD
        #
        #   prix d'une pomme
        #       -> pomme
        #
        #   longueur du rectangle
        #       -> rectangle
        #
        #   âge de Paul
        #       -> Paul
        #
        # Le groupe "un / une / le / la / les" est consommé
        # mais n'est jamais capturé comme entité.
        # ====================================================

        entity = None

        entity_match = re.search(
            r"(?:"
                r"\bde\s+"
                r"(?:un|une|le|la|les)?\s*"
                r"|"
                r"\bdu\s+"
                r"|"
                r"\bdes\s+"
                r"|"
                r"\bd'\s*"
                r"(?:un|une|le|la|les)?\s*"
            r")"
            r"([A-Za-zÀ-ÖØ-öø-ÿ'-]+)"
            r"\s*$",
            meaning,
            flags=re.IGNORECASE,
        )

        if entity_match:

            entity = (
                entity_match
                .group(1)
                .strip()
            )

        result = {
            "variable": variable,
            "meaning": meaning,
        }

        if entity:

            result[
                "entity"
            ] = entity

        return result

    return None


def _number_word_to_value(
    value: str,
) -> Optional[int]:
    """
    Convertit quelques multiplicateurs verbaux simples
    en valeurs numériques.

    Cette fonction reste volontairement conservatrice.
    """

    normalized = (
        str(
            value
            or ""
        )
        .strip()
        .lower()
    )

    mapping = {
        "deux": 2,
        "double": 2,
        "trois": 3,
        "triple": 3,
        "quatre": 4,
        "quadruple": 4,
        "cinq": 5,
    }

    if normalized in mapping:
        return mapping[
            normalized
        ]

    try:

        numeric_value = int(
            normalized
        )

        if numeric_value > 0:
            return numeric_value

    except Exception:
        pass

    return None


def extract_simple_verbal_relation(
    text: str,
) -> Optional[Dict[str, Any]]:
    """
    Extrait une relation verbale simple entre deux entités.

    Cas actuellement supportés :

        "Marie a deux fois l'âge de Paul"
        "Marie a 2 fois l'âge de Paul"
        "Marie a le double de l'âge de Paul"
        "Marie a trois fois l'âge de Paul"
        "Marie a le triple de l'âge de Paul"

    Retour exemple :

        {
            "subject": "Marie",
            "relation": "multiple_of",
            "factor": 2,
            "reference": "Paul",
            "attribute": "âge",
        }

    IMPORTANT :
    cette fonction ne doit jamais inventer une relation
    qui n'est pas explicitement présente dans le texte.
    """

    import re

    value = str(
        text
        or ""
    ).strip()

    if not value:
        return None

    # --------------------------------------------------------
    # NORMALISATION LÉGÈRE
    # --------------------------------------------------------

    normalized = (
        value
        .replace(
            "’",
            "'",
        )
    )

    # --------------------------------------------------------
    # CAS :
    #
    # Marie a deux fois l'âge de Paul
    # Marie a 2 fois l'âge de Paul
    # --------------------------------------------------------

    pattern_times = (
        r"\b"
        r"([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'-]*)"
        r"\s+a\s+"
        r"(deux|trois|quatre|cinq|\d+)"
        r"\s+fois\s+"
        r"(?:l['']\s*)?"
        r"(âge|age)"
        r"\s+de\s+"
        r"([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'-]*)"
        r"\b"
    )

    match = re.search(
        pattern_times,
        normalized,
        flags=re.IGNORECASE,
    )

    if match:

        subject = (
            match.group(1)
            .strip()
        )

        factor = (
            _number_word_to_value(
                match.group(2)
            )
        )

        attribute = (
            match.group(3)
            .lower()
            .strip()
        )

        reference = (
            match.group(4)
            .strip()
        )

        if factor is None:
            return None

        if attribute == "age":
            attribute = "âge"

        return {
            "subject": subject,
            "relation": "multiple_of",
            "factor": factor,
            "reference": reference,
            "attribute": attribute,
        }

    # --------------------------------------------------------
    # CAS :
    #
    # Marie a le double de l'âge de Paul
    # Marie a le triple de l'âge de Paul
    # --------------------------------------------------------

    pattern_named_multiple = (
        r"\b"
        r"([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'-]*)"
        r"\s+a\s+"
        r"(?:le\s+)?"
        r"(double|triple|quadruple)"
        r"\s+de\s+"
        r"(?:l['']\s*)?"
        r"(âge|age)"
        r"\s+de\s+"
        r"([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'-]*)"
        r"\b"
    )

    match = re.search(
        pattern_named_multiple,
        normalized,
        flags=re.IGNORECASE,
    )

    if match:

        subject = (
            match.group(1)
            .strip()
        )

        factor = (
            _number_word_to_value(
                match.group(2)
            )
        )

        attribute = (
            match.group(3)
            .lower()
            .strip()
        )

        reference = (
            match.group(4)
            .strip()
        )

        if factor is None:
            return None

        if attribute == "age":
            attribute = "âge"

        return {
            "subject": subject,
            "relation": "multiple_of",
            "factor": factor,
            "reference": reference,
            "attribute": attribute,
        }

    return None

def extract_simple_sum_relation(
    text: str,
) -> Optional[Dict[str, Any]]:
    """
    Extrait de manière conservatrice une relation de somme
    entre deux entités dans un problème verbal simple.

    Cas supportés notamment :

        "Marie a deux fois l'âge de Paul.
         La somme de leurs âges est 30 ans."

        "Paul et Marie ont ensemble 30 ans."

        "La somme des âges de Paul et Marie est 30 ans."

    Retour exemple :

        {
            "relation": "sum_equals",
            "entities": ["Paul", "Marie"],
            "value": 30,
            "attribute": "âge",
        }

    IMPORTANT :
    aucune entité ni aucune valeur ne doit être inventée.
    """

    import re

    value = str(
        text
        or ""
    ).strip()

    if not value:
        return None

    normalized = (
        value
        .replace(
            "’",
            "'",
        )
    )

    # --------------------------------------------------------
    # 1. ESSAYER DE RÉCUPÉRER LES DEUX ENTITÉS DEPUIS
    #    UNE RELATION VERBALE DÉJÀ SUPPORTÉE
    # --------------------------------------------------------
    #
    # Exemple :
    #
    #     Marie a deux fois l'âge de Paul.
    #
    # donne :
    #
    #     subject   = Marie
    #     reference = Paul
    # --------------------------------------------------------

    known_relation = (
        extract_simple_verbal_relation(
            normalized
        )
    )

    known_entities = []

    if known_relation:

        reference = str(
            known_relation.get(
                "reference"
            )
            or ""
        ).strip()

        subject = str(
            known_relation.get(
                "subject"
            )
            or ""
        ).strip()

        if reference:
            known_entities.append(
                reference
            )

        if (
            subject
            and subject.lower()
            not in {
                item.lower()
                for item in known_entities
            }
        ):
            known_entities.append(
                subject
            )

    # --------------------------------------------------------
    # 2. CAS :
    #
    #     La somme de leurs âges est 30 ans
    #
    # Ce cas nécessite que les deux personnes aient déjà été
    # identifiées explicitement ailleurs dans l'énoncé.
    # --------------------------------------------------------

    pattern_their_sum = (
        r"\b"
        r"(?:la\s+)?"
        r"sommes?\s+de\s+"
        r"leur(?:s)?\s+"
        r"(âge|age|âges|ages)"
        r"\s+"
        r"(?:est|vaut|donne|fait|égale|egale)"
        r"\s+"
        r"(-?\d+(?:[.,]\d+)?)"
        r"(?:\s*ans?)?"
        r"\b"
    )

    match = re.search(
        pattern_their_sum,
        normalized,
        flags=re.IGNORECASE,
    )

    if (
        match
        and len(
            known_entities
        )
        == 2
    ):

        numeric_text = (
            match.group(2)
            .replace(
                ",",
                ".",
            )
            .strip()
        )

        try:

            numeric_value = float(
                numeric_text
            )

        except Exception:
            return None

        if numeric_value.is_integer():

            numeric_value = int(
                numeric_value
            )

        return {
            "relation": "sum_equals",
            "entities": known_entities,
            "value": numeric_value,
            "attribute": "âge",
        }

    # --------------------------------------------------------
    # 3. CAS :
    #
    #     La somme des âges de Paul et Marie est 30 ans
    # --------------------------------------------------------

    pattern_named_sum = (
        r"\b"
        r"(?:la\s+)?somme\s+des\s+"
        r"(âges|ages)\s+de\s+"
        r"([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'-]*)"
        r"\s+et\s+"
        r"([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'-]*)"
        r"\s+(?:est|vaut|égale|egale)\s+"
        r"(-?\d+(?:[.,]\d+)?)"
        r"(?:\s*ans?)?"
        r"\b"
    )

    match = re.search(
        pattern_named_sum,
        normalized,
        flags=re.IGNORECASE,
    )

    if match:

        first_entity = (
            match.group(2)
            .strip()
        )

        second_entity = (
            match.group(3)
            .strip()
        )

        numeric_text = (
            match.group(4)
            .replace(
                ",",
                ".",
            )
            .strip()
        )

        try:

            numeric_value = float(
                numeric_text
            )

        except Exception:
            return None

        if numeric_value.is_integer():

            numeric_value = int(
                numeric_value
            )

        return {
            "relation": "sum_equals",
            "entities": [
                first_entity,
                second_entity,
            ],
            "value": numeric_value,
            "attribute": "âge",
        }

    # --------------------------------------------------------
    # 4. CAS :
    #
    #     Paul et Marie ont ensemble 30 ans
    # --------------------------------------------------------

    pattern_together = (
        r"\b"
        r"([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'-]*)"
        r"\s+et\s+"
        r"([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'-]*)"
        r"\s+ont\s+ensemble\s+"
        r"(-?\d+(?:[.,]\d+)?)"
        r"\s*ans?"
        r"\b"
    )

    match = re.search(
        pattern_together,
        normalized,
        flags=re.IGNORECASE,
    )

    if match:

        first_entity = (
            match.group(1)
            .strip()
        )

        second_entity = (
            match.group(2)
            .strip()
        )

        numeric_text = (
            match.group(3)
            .replace(
                ",",
                ".",
            )
            .strip()
        )

        try:

            numeric_value = float(
                numeric_text
            )

        except Exception:
            return None

        if numeric_value.is_integer():

            numeric_value = int(
                numeric_value
            )

        return {
            "relation": "sum_equals",
            "entities": [
                first_entity,
                second_entity,
            ],
            "value": numeric_value,
            "attribute": "âge",
        }

    return None


def extract_simple_verbal_constraints(
    text: str,
) -> list:
    """
    Extrait toutes les contraintes verbales simples
    actuellement supportées.

    L'objectif est de fournir une représentation structurée
    et déterministe de l'énoncé avant toute validation
    de la modélisation algébrique.
    """

    constraints = []

    multiple_relation = (
        extract_simple_verbal_relation(
            text
        )
    )

    if multiple_relation:

        constraints.append(
            multiple_relation
        )

    sum_relation = (
        extract_simple_sum_relation(
            text
        )
    )

    if sum_relation:

        constraints.append(
            sum_relation
        )

    # ========================================================
    # RELATIONS GÉNÉRIQUES QUANTITÉ × VALEUR + DÉCALAGE
    # ========================================================

    product_offset_constraints = (
        extract_product_offset_constraints(
            text
        )
    )

    for constraint in (
        product_offset_constraints
    ):

        if constraint not in constraints:

            constraints.append(
                constraint
            )

    return constraints

def build_expected_equation_from_verbal_constraints(
    *,
    variable_meaning: Optional[Dict[str, Any]],
    constraints: Optional[list],
) -> Optional[Dict[str, Any]]:
    """
    Construit une équation attendue à partir d'une
    signification explicite de variable et de contraintes
    verbales déterministes.

    Exemple :

        variable_meaning:
            x = âge de Paul

        constraints:
            Marie = 2 * Paul
            Paul + Marie = 30

    devient :

        x + 2*x = 30

    IMPORTANT :
    cette fonction reste volontairement conservatrice.

    Si la chaîne de correspondances entre :
        - la variable,
        - les entités,
        - la relation multiplicative,
        - la relation de somme

    n'est pas complète, elle retourne None.
    """

    variable_meaning = dict(
        variable_meaning
        or {}
    )

    constraints = list(
        constraints
        or []
    )

    variable = str(
        variable_meaning.get(
            "variable"
        )
        or ""
    ).strip()

    variable_entity = str(
        variable_meaning.get(
            "entity"
        )
        or ""
    ).strip()

    if (
        not variable
        or not variable_entity
    ):
        return None

    multiple_relation = None
    sum_relation = None

    # --------------------------------------------------------
    # 1. TROUVER LA RELATION MULTIPLICATIVE
    # --------------------------------------------------------

    for constraint in constraints:

        if not isinstance(
            constraint,
            dict,
        ):
            continue

        if (
            constraint.get(
                "relation"
            )
            != "multiple_of"
        ):
            continue

        reference = str(
            constraint.get(
                "reference"
            )
            or ""
        ).strip()

        subject = str(
            constraint.get(
                "subject"
            )
            or ""
        ).strip()

        factor = (
            constraint.get(
                "factor"
            )
        )

        if (
            reference.lower()
            == variable_entity.lower()
            and subject
            and factor is not None
        ):

            multiple_relation = (
                constraint
            )

            break

    if not multiple_relation:
        return None

    related_entity = str(
        multiple_relation.get(
            "subject"
        )
        or ""
    ).strip()

    factor = (
        multiple_relation.get(
            "factor"
        )
    )

    if (
        not related_entity
        or factor is None
    ):
        return None

    # --------------------------------------------------------
    # 2. TROUVER LA RELATION DE SOMME
    # --------------------------------------------------------

    for constraint in constraints:

        if not isinstance(
            constraint,
            dict,
        ):
            continue

        if (
            constraint.get(
                "relation"
            )
            != "sum_equals"
        ):
            continue

        entities = list(
            constraint.get(
                "entities"
            )
            or []
        )

        normalized_entities = {
            str(entity).strip().lower()
            for entity in entities
            if str(entity).strip()
        }

        if (
            variable_entity.lower()
            in normalized_entities
            and related_entity.lower()
            in normalized_entities
        ):

            sum_relation = (
                constraint
            )

            break

    if not sum_relation:
        return None

    total = (
        sum_relation.get(
            "value"
        )
    )

    if total is None:
        return None

    # --------------------------------------------------------
    # 3. CONSTRUCTION DE L'ÉQUATION ATTENDUE
    # --------------------------------------------------------

    equation = (
        f"{variable}"
        f"+{factor}*{variable}"
        f"={total}"
    )

    return {
        "equation": equation,

        "variable": variable,

        "variable_entity": (
            variable_entity
        ),

        "related_entity": (
            related_entity
        ),

        "factor": factor,

        "total": total,

        "multiple_relation": (
            multiple_relation
        ),

        "sum_relation": (
            sum_relation
        ),
    }


def validate_direct_verbal_modeling(
    *,
    student_answer: str,
    variable_meaning: Optional[Dict[str, Any]],
    constraints: Optional[list],
    statement: str = "",
) -> Dict[str, Any]:
    """
    Valide déterministiquement une modélisation proposée
    pour un problème verbal direct.

    Architecture hybride :

        contraintes déterministes existantes
                    ↓
        SemanticInterpreterService
        uniquement si structure insuffisante
                    ↓
        SemanticSituation
                    ↓
        reparamétrisation selon la variable élève
                    ↓
        compilation déterministe
                    ↓
        comparaison algébrique déterministe

    IMPORTANT :

    - le LLM peut INTERPRÉTER l'énoncé ;
    - il ne déclare jamais la réponse correcte ;
    - seule la compilation déterministe et la comparaison
      algébrique peuvent produire verdict="correct".

    Le chemin historique reste disponible en fallback afin
    de préserver les cas déjà couverts, notamment les
    problèmes d'âge.
    """

    import sympy as sp

    student_answer = str(
        student_answer
        or ""
    ).strip()

    statement = str(
        statement
        or ""
    ).strip()

    variable_meaning = dict(
        variable_meaning
        or {}
    )

    constraints = list(
        constraints
        or []
    )

    # ========================================================
    # 1. RÉPONSE VIDE
    # ========================================================

    if not student_answer:

        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "direct_verbal_modeling"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": None,
            "requires_review": True,
            "reason": (
                "No modeling answer was provided."
            ),
            "details": {},
        }

    # ========================================================
    # 2. EXTRACTION DES ÉQUATIONS ÉLÈVE
    # ========================================================

    student_equations = (
        extract_equations_from_text(
            student_answer
        )
    )

    if not student_equations:

        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "direct_verbal_modeling"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": (
                "missing_model_equation"
            ),
            "requires_review": True,
            "reason": (
                "No explicit equation was found "
                "in the student's modeling answer."
            ),
            "details": {
                "variable_meaning": (
                    variable_meaning
                ),
                "constraints": (
                    constraints
                ),
            },
        }

    student_equation = (
        student_equations[0]
    )

    # ========================================================
    # 3. VARIABLE UTILISÉE PAR L'ÉLÈVE
    # ========================================================
    #
    # Exemple :
    #
    #     Soit x le prix d'un CD
    #
    # ou :
    #
    #     x représente l'argent disponible
    #
    # --------------------------------------------------------

    student_variable = str(
        variable_meaning.get(
            "variable"
        )
        or ""
    ).strip()

    variable_description = str(
        variable_meaning.get(
            "meaning"
        )
        or ""
    ).strip()

    # --------------------------------------------------------
    # FALLBACK :
    # récupérer la variable directement dans l'équation
    # si aucune définition explicite n'est encore disponible.
    #
    # Cela ne donne PAS le sens de la variable, seulement
    # son symbole.
    # --------------------------------------------------------

    if not student_variable:

        try:

            symbols = sorted(
                {
                    str(symbol)
                    for symbol in (
                        sp.sympify(
                            student_equation
                            .split(
                                "=",
                                1,
                            )[0]
                            .replace(
                                "^",
                                "**",
                            )
                        ).free_symbols
                    )
                }
            )

        except Exception:

            symbols = []

        if len(
            symbols
        ) == 1:

            student_variable = (
                symbols[0]
            )

    # ========================================================
    # 4. INTERPRÉTATION SÉMANTIQUE HYBRIDE
    # ========================================================
    #
    # Si les contraintes déterministes existantes sont déjà
    # suffisantes, aucun appel LLM n'est effectué.
    #
    # Si elles sont incomplètes et que l'énoncé est connu,
    # SemanticInterpreterService peut proposer les relations
    # structurées manquantes.
    #
    # La sortie du LLM n'est toujours PAS un verdict.
    # ========================================================

    semantic_situation = None

    try:

        semantic_situation = (
            interpret_math_situation(
                statement=(
                    statement
                ),

                deterministic_constraints=(
                    constraints
                ),

                use_llm_fallback=bool(
                    statement
                ),
            )
        )

    except Exception:

        semantic_situation = None

    # ========================================================
    # 5. RECHERCHE DES RÔLES SÉMANTIQUES POSSIBLES
    # ========================================================
    #
    # On ne force pas :
    #
    #     x = prix unitaire
    #
    # Le même énoncé peut être paramétré avec :
    #
    #     x = prix unitaire
    #
    # ou :
    #
    #     x = montant disponible
    #
    # On compile donc toutes les paramétrisations cohérentes
    # présentes dans le modèle sémantique et on vérifie
    # laquelle correspond réellement à l'équation de l'élève.
    #
    # C'est l'équation mathématique qui tranche.
    # ========================================================

    semantic_roles = []

    if semantic_situation is not None:

        for constraint in (
            semantic_situation.constraints
        ):

            data = dict(
                constraint.data
                or {}
            )

            for key in (
                "unit_role",
                "common_role",
                "subject_role",
                "reference_role",
            ):

                role = str(
                    data.get(
                        key
                    )
                    or ""
                ).strip()

                if (
                    role
                    and role
                    not in semantic_roles
                ):

                    semantic_roles.append(
                        role
                    )

        # ----------------------------------------------------
        # Les entités interprétées peuvent fournir d'autres
        # rôles génériques.
        # ----------------------------------------------------

        for entity in (
            semantic_situation.entities
        ):

            role = str(
                entity.role
                or ""
            ).strip()

            if (
                role
                and role
                not in semantic_roles
            ):

                semantic_roles.append(
                    role
                )

    # ========================================================
    # 6. VALIDATION PAR REPARAMÉTRISATION DÉTERMINISTE
    # ========================================================

    semantic_attempts = []

    if (
        semantic_situation is not None
        and student_variable
        and semantic_roles
    ):

        for role in (
            semantic_roles
        ):

            try:

                parameterization = (
                    compile_parameterization(
                        situation=(
                            semantic_situation
                        ),

                        variable=(
                            student_variable
                        ),

                        role=role,

                        meaning=(
                            variable_description
                        ),
                    )
                )

            except Exception:

                continue

            expected_equations = list(
                parameterization.equations
                or []
            )

            if not expected_equations:
                continue

            for expected_equation in (
                expected_equations
            ):

                try:

                    same_constraint = (
                        equations_are_same_constraint(
                            student_equation,
                            expected_equation,
                        )
                    )

                except Exception:

                    same_constraint = None

                semantic_attempts.append({
                    "role": role,
                    "student_equation": (
                        student_equation
                    ),
                    "expected_equation": (
                        expected_equation
                    ),
                    "same_constraint": (
                        same_constraint
                    ),
                })

                # ============================================
                # MODÉLISATION PROUVÉE PAR LE NOUVEAU MOTEUR
                # ============================================

                if same_constraint is True:

                    return {
                        "verdict": "correct",
                        "confidence": 1.0,
                        "method": (
                            "direct_verbal_modeling"
                        ),
                        "result_correct": True,
                        "reasoning_correct": True,
                        "error_type": None,
                        "requires_review": False,
                        "reason": (
                            "The student's modeling equation "
                            "matches a deterministic "
                            "parameterization of the semantic "
                            "model derived from the verbal "
                            "situation."
                        ),
                        "details": {
                            "student_equation": (
                                student_equation
                            ),

                            "expected_equation": (
                                expected_equation
                            ),

                            "matched_model_source": (
                                "semantic_hybrid"
                            ),

                            "matched_role": (
                                role
                            ),

                            "student_variable": (
                                student_variable
                            ),

                            "variable_meaning": (
                                variable_description
                            ),

                            "semantic_source": (
                                semantic_situation.source
                            ),

                            "semantic_confidence": (
                                semantic_situation.confidence
                            ),

                            "semantic_constraints": [
                                constraint.to_dict()
                                for constraint
                                in (
                                    semantic_situation.constraints
                                )
                            ],

                            "semantic_ambiguities": (
                                list(
                                    semantic_situation.ambiguities
                                )
                            ),
                        },
                    }

    # ========================================================
    # 7. ANCIEN MODÈLE SÉMANTIQUE DÉTERMINISTE
    # ========================================================
    #
    # Migration progressive :
    #
    # le moteur actuellement présent dans
    # verbal_problem_service.py reste actif.
    #
    # Il couvre déjà :
    #
    #     multiple_of
    #     sum_equals
    #     product_offset_common_value
    #
    # et constitue un fallback sûr.
    # ========================================================

    expected_equations = []

    semantic_model = (
        build_semantic_model_from_verbal_constraints(
            variable_meaning=(
                variable_meaning
            ),
            constraints=(
                constraints
            ),
        )
    )

    if isinstance(
        semantic_model,
        dict,
    ):

        semantic_equations = list(
            semantic_model.get(
                "equations",
                [],
            )
            or []
        )

        for equation in (
            semantic_equations
        ):

            equation = str(
                equation
                or ""
            ).strip()

            if (
                equation
                and equation
                not in expected_equations
            ):

                expected_equations.append(
                    equation
                )

    # ========================================================
    # 8. FALLBACK HISTORIQUE
    # ========================================================

    historical_expected = (
        build_expected_equation_from_verbal_constraints(
            variable_meaning=(
                variable_meaning
            ),

            constraints=(
                constraints
            ),
        )
    )

    if (
        isinstance(
            historical_expected,
            dict,
        )
        and historical_expected.get(
            "equation"
        )
    ):

        historical_equation = str(
            historical_expected.get(
                "equation"
            )
            or ""
        ).strip()

        if (
            historical_equation
            and historical_equation
            not in expected_equations
        ):

            expected_equations.append(
                historical_equation
            )

    # ========================================================
    # 9. AUCUN MODÈLE PROUVABLE
    # ========================================================

    if not expected_equations:

        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "direct_verbal_modeling"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": None,
            "requires_review": True,
            "reason": (
                "Insufficient deterministic semantic "
                "structure to prove the modeling equation."
            ),
            "details": {
                "student_equation": (
                    student_equation
                ),

                "variable_meaning": (
                    variable_meaning
                ),

                "constraints": (
                    constraints
                ),

                "semantic_attempts": (
                    semantic_attempts
                ),

                "semantic_source": (
                    semantic_situation.source
                    if semantic_situation
                    else None
                ),

                "semantic_ambiguities": (
                    list(
                        semantic_situation.ambiguities
                    )
                    if semantic_situation
                    else []
                ),
            },
        }

    # ========================================================
    # 10. COMPARAISON AVEC LES MODÈLES HISTORIQUES
    # ========================================================

    checked_equations = []

    parseable_reference_found = False

    for expected_equation in (
        expected_equations
    ):

        try:

            same_constraint = (
                equations_are_same_constraint(
                    student_equation,
                    expected_equation,
                )
            )

        except Exception:

            same_constraint = None

        checked_equations.append({
            "expected_equation": (
                expected_equation
            ),
            "same_constraint": (
                same_constraint
            ),
        })

        if same_constraint is None:
            continue

        parseable_reference_found = True

        if same_constraint is not True:
            continue

        matched_source = (
            "semantic_legacy"
            if (
                isinstance(
                    semantic_model,
                    dict,
                )
                and expected_equation
                in (
                    semantic_model.get(
                        "equations",
                        [],
                    )
                    or []
                )
            )
            else "historical"
        )

        details = {
            "student_equation": (
                student_equation
            ),

            "expected_equation": (
                expected_equation
            ),

            "expected_equations": (
                expected_equations
            ),

            "matched_model_source": (
                matched_source
            ),

            "semantic_attempts": (
                semantic_attempts
            ),
        }

        if isinstance(
            historical_expected,
            dict,
        ):

            for key in (
                "variable",
                "variable_entity",
                "related_entity",
                "factor",
                "total",
            ):

                if (
                    historical_expected.get(
                        key
                    )
                    is not None
                ):

                    details[
                        key
                    ] = (
                        historical_expected.get(
                            key
                        )
                    )

        return {
            "verdict": "correct",
            "confidence": 1.0,
            "method": (
                "direct_verbal_modeling"
            ),
            "result_correct": True,
            "reasoning_correct": True,
            "error_type": None,
            "requires_review": False,
            "reason": (
                "The student's modeling equation matches "
                "a deterministic equation derived from "
                "the verbal constraints."
            ),
            "details": (
                details
            ),
        }

    # ========================================================
    # 11. IMPOSSIBILITÉ DE COMPARAISON
    # ========================================================

    if not parseable_reference_found:

        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "direct_verbal_modeling"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": (
                "reference_model_parse_failure"
            ),
            "requires_review": True,
            "reason": (
                "The deterministic verbal model was built, "
                "but its equations could not be compared."
            ),
            "details": {
                "student_equation": (
                    student_equation
                ),

                "expected_equations": (
                    expected_equations
                ),

                "checked_equations": (
                    checked_equations
                ),

                "semantic_attempts": (
                    semantic_attempts
                ),
            },
        }

    # ========================================================
    # 12. MODÈLE PROUVÉ INCOMPATIBLE
    # ========================================================

    return {
        "verdict": "incorrect",
        "confidence": 1.0,
        "method": (
            "direct_verbal_modeling"
        ),
        "result_correct": False,
        "reasoning_correct": False,
        "error_type": (
            "verbal_model_constraint_mismatch"
        ),
        "requires_review": False,
        "reason": (
            "The proposed equation does not match "
            "any deterministic parameterization derived "
            "from the verbal situation."
        ),
        "details": {
            "student_equation": (
                student_equation
            ),

            "expected_equations": (
                expected_equations
            ),

            "checked_equations": (
                checked_equations
            ),

            "semantic_attempts": (
                semantic_attempts
            ),

            "semantic_source": (
                semantic_situation.source
                if semantic_situation
                else None
            ),
        },
    }

def validate_semantic_verbal_final_answer(
    *,
    student_answer: str,
    statement: str,
    variable_meaning: Optional[Dict[str, Any]],
    algebraic_solution: Optional[Dict[str, Any]],
    constraints: Optional[list],
) -> Dict[str, Any]:
    """
    Valide une réponse finale à partir du modèle sémantique.

    Architecture :

        énoncé verbal
            ↓
        SemanticSituation
            ↓
        rôle de la variable résolue
            ↓
        valeur algébrique prouvée
            ↓
        rôle cible demandé par l'énoncé
            ↓
        dérivation déterministe éventuelle
            ↓
        comparaison avec la réponse finale de l'élève

    PRIORITÉ POUR LE RÔLE DE LA VARIABLE :

        1. semantic_role déjà prouvé lors de la modélisation ;
        2. correspondance avec les entités sémantiques ;
        3. rôle unique non ambigu dans le modèle.

    IMPORTANT :

    - le LLM peut interpréter les contraintes, les rôles
      et la cible ;
    - il ne décide jamais si la réponse finale est correcte ;
    - la valeur finale doit être établie par le moteur
      déterministe ;
    - un rôle sémantique mémorisé n'est accepté que s'il
      existe réellement dans le modèle courant.
    """

    import re
    from fractions import Fraction

    student_answer = str(
        student_answer
        or ""
    ).strip()

    statement = str(
        statement
        or ""
    ).strip()

    variable_meaning = dict(
        variable_meaning
        or {}
    )

    algebraic_solution = dict(
        algebraic_solution
        or {}
    )

    constraints = list(
        constraints
        or []
    )

    # ========================================================
    # 1. SOLUTION ALGÉBRIQUE PROUVÉE OBLIGATOIRE
    # ========================================================

    if not algebraic_solution.get(
        "proved"
    ):

        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "semantic_verbal_final_answer"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": None,
            "requires_review": True,
            "reason": (
                "No proved algebraic solution is available."
            ),
            "details": {},
        }

    solved_value = (
        algebraic_solution.get(
            "value"
        )
    )

    solved_variable = str(
        algebraic_solution.get(
            "variable"
        )
        or variable_meaning.get(
            "variable"
        )
        or ""
    ).strip()

    if solved_value is None:

        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "semantic_verbal_final_answer"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": None,
            "requires_review": True,
            "reason": (
                "The proved algebraic solution has no value."
            ),
            "details": {},
        }

    # ========================================================
    # 2. CONSTRUIRE LA SITUATION SÉMANTIQUE
    # ========================================================

    try:

        semantic_situation = (
            interpret_math_situation(
                statement=(
                    statement
                ),

                deterministic_constraints=(
                    constraints
                ),

                use_llm_fallback=bool(
                    statement
                ),
            )
        )

    except Exception:

        semantic_situation = None

    if semantic_situation is None:

        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "semantic_verbal_final_answer"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": None,
            "requires_review": True,
            "reason": (
                "No semantic situation could be built."
            ),
            "details": {},
        }

    # ========================================================
    # 3. RÔLES POSSIBLES DU MODÈLE
    # ========================================================
    #
    # On construit d'abord la liste complète des rôles
    # présents dans la situation.
    #
    # Elle servira notamment à vérifier qu'un semantic_role
    # mémorisé appartient bien au modèle actuel.
    # ========================================================

    candidate_roles = []

    for constraint in (
        semantic_situation.constraints
    ):

        data = dict(
            constraint.data
            or {}
        )

        for key in (
            "unit_role",
            "common_role",
            "subject_role",
            "reference_role",
            "target_role",
        ):

            role = str(
                data.get(
                    key
                )
                or ""
            ).strip()

            if (
                role
                and role
                not in candidate_roles
            ):

                candidate_roles.append(
                    role
                )

    # --------------------------------------------------------
    # Les entités sémantiques peuvent également apporter
    # des rôles.
    # --------------------------------------------------------

    for entity in (
        semantic_situation.entities
    ):

        role = str(
            entity.role
            or ""
        ).strip()

        if (
            role
            and role
            not in candidate_roles
        ):

            candidate_roles.append(
                role
            )

    # --------------------------------------------------------
    # La cible elle-même est aussi un rôle connu.
    # --------------------------------------------------------

    semantic_target_role = str(
        semantic_situation.target_role
        or ""
    ).strip()

    if (
        semantic_target_role
        and semantic_target_role
        not in candidate_roles
    ):

        candidate_roles.append(
            semantic_target_role
        )

    # ========================================================
    # 4. RÔLE DE LA VARIABLE RÉSOLUE
    # ========================================================

    solved_role = None
    solved_role_source = None

    # ========================================================
    # 4A. RÔLE DÉJÀ PROUVÉ LORS DE LA MODÉLISATION
    # ========================================================
    #
    # Exemple :
    #
    #     variable_meaning["semantic_role"] = "unit_value"
    #
    # Ce rôle a été mémorisé uniquement lorsqu'une
    # paramétrisation déterministe correspondait réellement
    # à l'équation proposée.
    #
    # On ne le réutilise que s'il existe encore dans le modèle
    # sémantique courant.
    # ========================================================

    remembered_semantic_role = str(
        variable_meaning.get(
            "semantic_role"
        )
        or ""
    ).strip()

    if (
        remembered_semantic_role
        and remembered_semantic_role
        in candidate_roles
    ):

        solved_role = (
            remembered_semantic_role
        )

        solved_role_source = (
            "proved_model_parameterization"
        )

    # ========================================================
    # 4B. CORRESPONDANCE TEXTUELLE AVEC LES ENTITÉS
    # ========================================================
    #
    # Ce chemin reste un fallback.
    #
    # Il ne doit pas écraser un rôle déjà prouvé par
    # l'équation de modélisation.
    # ========================================================

    variable_description = str(
        variable_meaning.get(
            "meaning"
        )
        or ""
    ).strip().lower()

    if (
        not solved_role
        and variable_description
    ):

        for entity in (
            semantic_situation.entities
        ):

            label = str(
                entity.label
                or ""
            ).strip().lower()

            if not label:
                continue

            if (
                label in variable_description
                or variable_description in label
            ):

                candidate_role = str(
                    entity.role
                    or ""
                ).strip()

                if (
                    candidate_role
                    and candidate_role
                    in candidate_roles
                ):

                    solved_role = (
                        candidate_role
                    )

                    solved_role_source = (
                        "semantic_entity_label"
                    )

                    break

    # ========================================================
    # 4C. UN SEUL RÔLE POSSIBLE
    # ========================================================
    #
    # Si le modèle ne contient réellement qu'un seul rôle,
    # il n'y a aucune ambiguïté.
    # ========================================================

    if (
        not solved_role
        and len(
            candidate_roles
        )
        == 1
    ):

        solved_role = (
            candidate_roles[0]
        )

        solved_role_source = (
            "single_candidate_role"
        )

    # ========================================================
    # 5. CIBLE DEMANDÉE PAR LE PROBLÈME
    # ========================================================

    target_role = (
        semantic_target_role
    )

    if not target_role:

        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "semantic_verbal_final_answer"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": (
                "semantic_target_unknown"
            ),
            "requires_review": True,
            "reason": (
                "The semantic target of the verbal problem "
                "could not be determined."
            ),
            "details": {
                "solved_variable": (
                    solved_variable
                ),
                "solved_value": (
                    str(
                        solved_value
                    )
                ),
                "solved_role": (
                    solved_role
                ),
                "solved_role_source": (
                    solved_role_source
                ),
                "candidate_roles": (
                    candidate_roles
                ),
                "remembered_semantic_role": (
                    remembered_semantic_role
                ),
                "semantic_source": (
                    semantic_situation.source
                ),
            },
        }

    if not solved_role:

        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "semantic_verbal_final_answer"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": (
                "semantic_variable_role_unknown"
            ),
            "requires_review": True,
            "reason": (
                "The role of the solved variable could not "
                "be determined safely."
            ),
            "details": {
                "solved_variable": (
                    solved_variable
                ),
                "solved_value": (
                    str(
                        solved_value
                    )
                ),
                "target_role": (
                    target_role
                ),
                "candidate_roles": (
                    candidate_roles
                ),
                "remembered_semantic_role": (
                    remembered_semantic_role
                ),
            },
        }

    # ========================================================
    # 6. DÉTERMINER LA VALEUR DE LA CIBLE
    # ========================================================

    target_value = None
    target_proof = None

    # --------------------------------------------------------
    # A. La variable résolue EST directement la cible.
    # --------------------------------------------------------

    if solved_role == target_role:

        target_value = str(
            solved_value
        )

        target_proof = {
            "type": (
                "solved_variable_is_target"
            ),
            "solved_role": (
                solved_role
            ),
            "solved_role_source": (
                solved_role_source
            ),
        }

    # --------------------------------------------------------
    # B. La variable résolue représente une autre quantité.
    #
    # On dérive alors la cible déterministiquement.
    # --------------------------------------------------------

    else:

        try:

            derived = (
                derive_target_value_from_product_offset(
                    situation=(
                        semantic_situation
                    ),

                    solved_variable_role=(
                        solved_role
                    ),

                    solved_value=(
                        solved_value
                    ),
                )
            )

        except Exception:

            derived = None

        if (
            isinstance(
                derived,
                dict,
            )
            and derived.get(
                "proved"
            )
            and str(
                derived.get(
                    "role"
                )
                or ""
            ).strip()
            == target_role
        ):

            target_value = str(
                derived.get(
                    "value"
                )
            )

            target_proof = {
                "type": (
                    "derived_from_semantic_constraints"
                ),
                "solved_role_source": (
                    solved_role_source
                ),
                "derivation": (
                    derived
                ),
            }

    if target_value is None:

        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "semantic_verbal_final_answer"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": (
                "semantic_target_not_derivable"
            ),
            "requires_review": True,
            "reason": (
                "The target value could not be derived "
                "deterministically from the proved solution "
                "and semantic constraints."
            ),
            "details": {
                "solved_role": (
                    solved_role
                ),
                "solved_role_source": (
                    solved_role_source
                ),
                "solved_value": (
                    str(
                        solved_value
                    )
                ),
                "target_role": (
                    target_role
                ),
            },
        }

    # ========================================================
    # 7. EXTRAIRE LES VALEURS NUMÉRIQUES DE LA RÉPONSE
    # ========================================================

    number_pattern = re.compile(
        r"""
        (?<![\w])
        [+-]?
        (?:
            \d+\s*/\s*\d+
            |
            \d+(?:[.,]\d+)?
        )
        (?![\w])
        """,
        re.VERBOSE,
    )

    matches = (
        number_pattern.findall(
            student_answer
        )
    )

    if not matches:

        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "semantic_verbal_final_answer"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": (
                "missing_final_numeric_value"
            ),
            "requires_review": True,
            "reason": (
                "No explicit numeric value was found "
                "in the final answer."
            ),
            "details": {
                "target_role": (
                    target_role
                ),
                "target_value": (
                    target_value
                ),
            },
        }

    # ========================================================
    # 8. NORMALISATION EXACTE
    # ========================================================

    def _to_fraction(
        value: Any,
    ) -> Optional[Fraction]:

        if value is None:
            return None

        text = str(
            value
        ).strip()

        text = text.replace(
            ",",
            ".",
        )

        text = re.sub(
            r"\s+",
            "",
            text,
        )

        try:

            if "/" in text:

                numerator, denominator = (
                    text.split(
                        "/",
                        1,
                    )
                )

                denominator_value = (
                    Fraction(
                        denominator
                    )
                )

                if denominator_value == 0:
                    return None

                return (
                    Fraction(
                        numerator
                    )
                    / denominator_value
                )

            return Fraction(
                text
            )

        except Exception:

            return None

    expected_fraction = (
        _to_fraction(
            target_value
        )
    )

    if expected_fraction is None:

        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "semantic_verbal_final_answer"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": (
                "semantic_target_parse_failure"
            ),
            "requires_review": True,
            "reason": (
                "The deterministic target value could not "
                "be normalized."
            ),
            "details": {
                "target_value": (
                    target_value
                ),
            },
        }

    student_values = []

    for match in (
        matches
    ):

        parsed = (
            _to_fraction(
                match
            )
        )

        if parsed is not None:

            student_values.append({
                "raw": (
                    match
                ),
                "value": (
                    parsed
                ),
            })

    if not student_values:

        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "semantic_verbal_final_answer"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": (
                "student_numeric_parse_failure"
            ),
            "requires_review": True,
            "reason": (
                "The numeric value in the student's final "
                "answer could not be normalized."
            ),
            "details": {
                "matches": (
                    matches
                ),
            },
        }

    # ========================================================
    # 9. VALIDATION DÉTERMINISTE DE LA VALEUR
    # ========================================================

    for candidate in (
        student_values
    ):

        if (
            candidate[
                "value"
            ]
            == expected_fraction
        ):

            return {
                "verdict": "correct",
                "confidence": 1.0,
                "method": (
                    "semantic_verbal_final_answer"
                ),
                "result_correct": True,
                "reasoning_correct": True,
                "error_type": None,
                "requires_review": False,
                "reason": (
                    "The final value matches the target "
                    "derived deterministically from the "
                    "semantic model."
                ),
                "details": {
                    "student_value": (
                        candidate[
                            "raw"
                        ]
                    ),

                    "expected_value": (
                        str(
                            expected_fraction
                        )
                    ),

                    "target_role": (
                        target_role
                    ),

                    "solved_role": (
                        solved_role
                    ),

                    "solved_role_source": (
                        solved_role_source
                    ),

                    "solved_value": (
                        str(
                            solved_value
                        )
                    ),

                    "target_proof": (
                        target_proof
                    ),

                    "remembered_semantic_role": (
                        remembered_semantic_role
                    ),

                    "semantic_source": (
                        semantic_situation.source
                    ),

                    "semantic_constraints": [
                        constraint.to_dict()
                        for constraint
                        in (
                            semantic_situation.constraints
                        )
                    ],
                },
            }

    # ========================================================
    # 10. VALEUR FINALE INCORRECTE
    # ========================================================

    return {
        "verdict": "incorrect",
        "confidence": 1.0,
        "method": (
            "semantic_verbal_final_answer"
        ),
        "result_correct": False,
        "reasoning_correct": False,
        "error_type": (
            "wrong_semantic_final_value"
        ),
        "requires_review": False,
        "reason": (
            "The final numeric value does not match "
            "the target derived deterministically from "
            "the semantic model."
        ),
        "details": {
            "student_values": [
                item[
                    "raw"
                ]
                for item
                in student_values
            ],

            "expected_value": (
                str(
                    expected_fraction
                )
            ),

            "target_role": (
                target_role
            ),

            "solved_role": (
                solved_role
            ),

            "solved_role_source": (
                solved_role_source
            ),

            "solved_value": (
                str(
                    solved_value
                )
            ),

            "target_proof": (
                target_proof
            ),

            "remembered_semantic_role": (
                remembered_semantic_role
            ),
        },
    }


def _validate_direct_verbal_final_answer_legacy(
    *,
    student_answer: str,
    variable_meaning: Optional[Dict[str, Any]],
    algebraic_solution: Optional[Dict[str, Any]],
    verbal_relations: Optional[list],
) -> Dict[str, Any]:
    """
    Valide une réponse finale contextuelle pour un problème
    verbal saisi directement par l'élève.

    Exemple supporté :

        variable_meaning:
            x = âge de Paul

        algebraic_solution:
            x = 10

        verbal_relation:
            Marie = 2 * Paul

        student_answer:
            "Paul a 10 ans et Marie a 20 ans"

    IMPORTANT :
    - aucune correction cachée n'est utilisée ;
    - aucune relation absente n'est inventée ;
    - si les preuves disponibles sont insuffisantes,
      le verdict reste "uncertain".
    """

    import re
    from fractions import Fraction

    answer = str(
        student_answer
        or ""
    ).strip()

    if not answer:

        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "direct_verbal_final_answer"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": None,
            "requires_review": True,
            "reason": (
                "No final answer was provided."
            ),
            "details": {},
        }

    variable_meaning = dict(
        variable_meaning
        or {}
    )

    algebraic_solution = dict(
        algebraic_solution
        or {}
    )

    verbal_relations = list(
        verbal_relations
        or []
    )

    # --------------------------------------------------------
    # PREUVES MINIMALES REQUISES
    # --------------------------------------------------------

    variable = str(
        variable_meaning.get(
            "variable"
        )
        or ""
    ).strip()

    reference_entity = str(
        variable_meaning.get(
            "entity"
        )
        or ""
    ).strip()

    solved_variable = str(
        algebraic_solution.get(
            "variable"
        )
        or ""
    ).strip()

    solved_value_raw = (
        algebraic_solution.get(
            "value"
        )
    )

    solution_proved = bool(
        algebraic_solution.get(
            "proved",
            False,
        )
    )

    if (
        not variable
        or not reference_entity
        or not solved_variable
        or solved_value_raw is None
        or not solution_proved
    ):

        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "direct_verbal_final_answer"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": None,
            "requires_review": True,
            "reason": (
                "Insufficient deterministic memory "
                "to validate the contextual answer."
            ),
            "details": {
                "variable_meaning": (
                    variable_meaning
                ),
                "algebraic_solution": (
                    algebraic_solution
                ),
                "verbal_relations": (
                    verbal_relations
                ),
            },
        }

    if (
        variable.lower()
        != solved_variable.lower()
    ):

        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "direct_verbal_final_answer"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": None,
            "requires_review": True,
            "reason": (
                "The proved algebraic variable does not "
                "match the variable meaning stored for "
                "the verbal problem."
            ),
            "details": {
                "variable": variable,
                "solved_variable": (
                    solved_variable
                ),
            },
        }

    try:
        solved_value = Fraction(
            str(
                solved_value_raw
            )
        )
    except Exception:

        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "direct_verbal_final_answer"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": None,
            "requires_review": True,
            "reason": (
                "The proved algebraic value could not "
                "be interpreted numerically."
            ),
            "details": {
                "value": solved_value_raw,
            },
        }

    # --------------------------------------------------------
    # EXTRACTION DES VALEURS NOMMÉES DANS LA RÉPONSE
    # --------------------------------------------------------
    #
    # Cas :
    #
    #     Paul a 10 ans
    #     Marie a 20 ans
    #
    # ou :
    #
    #     Paul = 10
    #     Marie = 20
    #
    # --------------------------------------------------------

    assignment_pattern = re.compile(
        r"\b"
        r"([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'-]*)"
        r"\s*"
        r"(?:"
            r"a(?:\s+donc)?"
            r"|="
            r"|vaut"
            r"|a\s+pour\s+âge"
            r"|a\s+pour\s+age"
        r")"
        r"\s*"
        r"(-?\d+(?:[.,]\d+)?)"
        r"(?:\s*ans?)?"
        r"\b",
        flags=re.IGNORECASE,
    )

    assignments = {}

    for match in assignment_pattern.finditer(
        answer
    ):

        entity = (
            match.group(1)
            .strip()
        )

        numeric_text = (
            match.group(2)
            .replace(
                ",",
                ".",
            )
            .strip()
        )

        try:
            numeric_value = Fraction(
                numeric_text
            )
        except Exception:
            continue

        assignments[
            entity.lower()
        ] = {
            "entity": entity,
            "value": numeric_value,
        }


    # Forme abrégée courante : "Marie 20 ans".
    # On exige explicitement l'unité "ans" pour éviter de
    # transformer arbitrairement tout nombre suivant un nom
    # en affectation contextuelle.
    bare_age_assignment_pattern = re.compile(
        r"\b"
        r"([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'-]*)"
        r"\s+"
        r"(-?\d+(?:[.,]\d+)?)"
        r"\s*ans?"
        r"\b",
        flags=re.IGNORECASE,
    )

    for match in bare_age_assignment_pattern.finditer(answer):
        entity = match.group(1).strip()
        key = entity.lower()
        if key in assignments:
            continue

        numeric_text = match.group(2).replace(",", ".").strip()
        try:
            numeric_value = Fraction(numeric_text)
        except Exception:
            continue

        assignments[key] = {
            "entity": entity,
            "value": numeric_value,
        }

    if not assignments:

        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": (
                "direct_verbal_final_answer"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": None,
            "requires_review": True,
            "reason": (
                "No explicit entity-value assignments "
                "were found in the final answer."
            ),
            "details": {},
        }

    reference_key = (
        reference_entity.lower()
    )

    reference_assignment = (
        assignments.get(
            reference_key
        )
    )

    if not reference_assignment:

        return {
            "verdict": "uncertain",
            "confidence": 0.5,
            "method": (
                "direct_verbal_final_answer"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": (
                "missing_reference_entity"
            ),
            "requires_review": True,
            "reason": (
                "The answer does not explicitly give "
                "the value of the entity represented "
                "by the solved variable."
            ),
            "details": {
                "expected_entity": (
                    reference_entity
                ),
                "assignments": (
                    assignments
                ),
            },
        }

    # --------------------------------------------------------
    # VÉRIFICATION DE L'ENTITÉ PORTÉE PAR x
    # --------------------------------------------------------

    if (
        reference_assignment[
            "value"
        ]
        != solved_value
    ):

        return {
            "verdict": "incorrect",
            "confidence": 1.0,
            "method": (
                "direct_verbal_final_answer"
            ),
            "result_correct": False,
            "reasoning_correct": None,
            "error_type": (
                "wrong_reference_entity_value"
            ),
            "requires_review": False,
            "reason": (
                "The value assigned to the entity "
                "represented by the solved variable "
                "does not match the proved algebraic solution."
            ),
            "details": {
                "entity": (
                    reference_entity
                ),
                "expected_value": (
                    str(
                        solved_value
                    )
                ),
                "student_value": (
                    str(
                        reference_assignment[
                            "value"
                        ]
                    )
                ),
            },
        }

    # --------------------------------------------------------
    # VÉRIFICATION DES RELATIONS VERBALES SUPPORTÉES
    # --------------------------------------------------------

    checked_relations = []

    for relation in verbal_relations:

        if not isinstance(
            relation,
            dict,
        ):
            continue

        relation_type = (
            relation.get(
                "relation"
            )
        )

        if (
            relation_type
            != "multiple_of"
        ):
            continue

        subject = str(
            relation.get(
                "subject"
            )
            or ""
        ).strip()

        relation_reference = str(
            relation.get(
                "reference"
            )
            or ""
        ).strip()

        factor_raw = (
            relation.get(
                "factor"
            )
        )

        if (
            not subject
            or not relation_reference
            or factor_raw is None
        ):
            continue

        try:
            factor = Fraction(
                str(
                    factor_raw
                )
            )
        except Exception:
            continue

        subject_assignment = (
            assignments.get(
                subject.lower()
            )
        )

        reference_relation_assignment = (
            assignments.get(
                relation_reference.lower()
            )
        )

        if (
            subject_assignment is None
            or reference_relation_assignment is None
        ):

            return {
                "verdict": "uncertain",
                "confidence": 0.6,
                "method": (
                    "direct_verbal_final_answer"
                ),
                "result_correct": None,
                "reasoning_correct": None,
                "error_type": (
                    "incomplete_contextual_answer"
                ),
                "requires_review": True,
                "reason": (
                    "The answer does not contain all "
                    "entities required to verify the "
                    "stored verbal relation."
                ),
                "details": {
                    "relation": relation,
                    "assignments": assignments,
                },
            }

        expected_subject_value = (
            reference_relation_assignment[
                "value"
            ]
            * factor
        )

        actual_subject_value = (
            subject_assignment[
                "value"
            ]
        )

        if (
            actual_subject_value
            != expected_subject_value
        ):

            return {
                "verdict": "incorrect",
                "confidence": 1.0,
                "method": (
                    "direct_verbal_final_answer"
                ),
                "result_correct": False,
                "reasoning_correct": None,
                "error_type": (
                    "verbal_relation_not_satisfied"
                ),
                "requires_review": False,
                "reason": (
                    "The final answer does not satisfy "
                    "a verbal relation stored from "
                    "the original problem."
                ),
                "details": {
                    "relation": relation,
                    "expected_value": (
                        str(
                            expected_subject_value
                        )
                    ),
                    "student_value": (
                        str(
                            actual_subject_value
                        )
                    ),
                },
            }

        checked_relations.append(
            relation
        )

    # --------------------------------------------------------
    # AUCUNE RELATION VÉRIFIABLE
    # --------------------------------------------------------

    if not checked_relations:

        return {
            "verdict": "uncertain",
            "confidence": 0.7,
            "method": (
                "direct_verbal_final_answer"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": None,
            "requires_review": True,
            "reason": (
                "The proved variable value matches the "
                "student answer, but no supported verbal "
                "relation was available to validate the "
                "complete contextual answer."
            ),
            "details": {
                "assignments": assignments,
            },
        }

    # --------------------------------------------------------
    # PREUVE COMPLÈTE
    # --------------------------------------------------------

    return {
        "verdict": "correct",
        "confidence": 1.0,
        "method": (
            "direct_verbal_final_answer"
        ),
        "result_correct": True,
        "reasoning_correct": None,
        "error_type": None,
        "requires_review": False,
        "reason": (
            "The final contextual answer matches the proved "
            "algebraic solution and all supported verbal "
            "relations."
        ),
        "details": {
            "reference_entity": (
                reference_entity
            ),
            "proved_value": (
                str(
                    solved_value
                )
            ),
            "assignments": {
                key: {
                    "entity": value[
                        "entity"
                    ],
                    "value": str(
                        value[
                            "value"
                        ]
                    ),
                }
                for key, value
                in assignments.items()
            },
            "checked_relations": (
                checked_relations
            ),
        },
    }

def validate_direct_verbal_final_answer(
    *,
    student_answer: str,
    variable_meaning: Optional[Dict[str, Any]],
    algebraic_solution: Optional[Dict[str, Any]],
    verbal_relations: Optional[list],
    statement: str = "",
    constraints: Optional[list] = None,
) -> Dict[str, Any]:
    """
    Point d'entrée principal pour la validation finale
    d'un problème verbal saisi directement par l'élève.

    Ordre de validation :

        1. modèle sémantique générique ;
        2. validation déterministe de la cible ;
        3. fallback historique si le nouveau moteur
           ne peut pas conclure.

    IMPORTANT :

    - l'IA peut interpréter la situation ;
    - elle ne décide jamais si la réponse est correcte ;
    - un verdict semantic "correct" ou "incorrect" provient
      uniquement d'une preuve déterministe ;
    - l'ancien moteur reste disponible pendant la migration.
    """

    statement = str(
        statement
        or ""
    ).strip()

    constraints = list(
        constraints
        or []
    )

    # ========================================================
    # 1. NOUVELLE VOIE SÉMANTIQUE
    # ========================================================
    #
    # On ne déclenche cette voie que si nous avons une
    # véritable structure de problème à interpréter.
    #
    # Cela évite d'envoyer inutilement les anciens cas
    # historiques vers le LLM.
    # ========================================================

    if (
        statement
        and constraints
    ):

        try:

            semantic_validation = (
                validate_semantic_verbal_final_answer(
                    student_answer=(
                        student_answer
                    ),

                    statement=(
                        statement
                    ),

                    variable_meaning=(
                        variable_meaning
                    ),

                    algebraic_solution=(
                        algebraic_solution
                    ),

                    constraints=(
                        constraints
                    ),
                )
            )

        except Exception:

            semantic_validation = None

        # ----------------------------------------------------
        # Le nouveau moteur a une preuve déterministe.
        # ----------------------------------------------------

        if (
            isinstance(
                semantic_validation,
                dict,
            )
            and semantic_validation.get(
                "verdict"
            )
            in {
                "correct",
                "incorrect",
            }
        ):

            result = dict(
                semantic_validation
            )

            # ------------------------------------------------
            # CONTRAT EXTERNE HISTORIQUE
            # ------------------------------------------------
            #
            # L'orchestrateur connaît déjà :
            #
            #     direct_verbal_final_answer
            #
            # On conserve ce contrat pour ne pas modifier
            # ResponseService / PedagogicalPipeline.
            #
            # Le chemin réel est conservé dans details.
            # ------------------------------------------------

            result[
                "method"
            ] = (
                "direct_verbal_final_answer"
            )

            details = dict(
                result.get(
                    "details"
                )
                or {}
            )

            details[
                "validation_path"
            ] = (
                "semantic"
            )

            details[
                "semantic_method"
            ] = (
                "semantic_verbal_final_answer"
            )

            result[
                "details"
            ] = details

            return result

    # ========================================================
    # 2. FALLBACK HISTORIQUE
    # ========================================================
    #
    # Cas déjà validés :
    #
    #     Paul / Marie
    #     relations multiple_of
    #     réponses contextuelles nommées
    #
    # Rien n'est supprimé.
    # ========================================================

    legacy_result = (
        _validate_direct_verbal_final_answer_legacy(
            student_answer=(
                student_answer
            ),

            variable_meaning=(
                variable_meaning
            ),

            algebraic_solution=(
                algebraic_solution
            ),

            verbal_relations=(
                verbal_relations
            ),
        )
    )

    # --------------------------------------------------------
    # Trace utile pour savoir que le fallback a été utilisé.
    # --------------------------------------------------------

    if isinstance(
        legacy_result,
        dict,
    ):

        result = dict(
            legacy_result
        )

        details = dict(
            result.get(
                "details"
            )
            or {}
        )

        details.setdefault(
            "validation_path",
            "legacy",
        )

        result[
            "details"
        ] = details

        return result

    return legacy_result

def _normalize_numeric_value(
    value: Any,
) -> Optional[Any]:
    """
    Convertit une valeur numérique textuelle simple.

    Exemples :
        "5"   -> 5
        "5,5" -> 5.5
        "5.5" -> 5.5
    """

    if value is None:
        return None

    raw = str(
        value
    ).strip()

    if not raw:
        return None

    raw = raw.replace(
        ",",
        ".",
    )

    try:

        number = float(
            raw
        )

    except (
        TypeError,
        ValueError,
    ):

        return None

    if number.is_integer():
        return int(
            number
        )

    return number

def _clean_semantic_item_name(
    value: Optional[str],
) -> Optional[str]:
    """
    Nettoie légèrement le nom d'un objet.

    Exemples :
        "CD"       -> "CD"
        "billets"  -> "billets"

    Aucun singulier n'est inventé.
    """

    item = str(
        value
        or ""
    ).strip()

    if not item:
        return None

    item = re.sub(
        r"\s+",
        " ",
        item,
    )

    item = item.strip(
        " ,.;:!?$€"
    )

    if not item:
        return None

    return item

def extract_product_offset_constraints(
    text: str,
) -> List[Dict[str, Any]]:
    """
    Extrait des contraintes génériques de type :

        valeur_commune
        =
        quantité * valeur_unitaire + offset

    Exemples :

        Si j'achète 10 objets il me manque 5
            -> valeur_commune = 10*x - 5

        Si j'en achète 5 il me reste 12
            -> valeur_commune = 5*x + 12

        10 objets coûtent 5 de plus que mon budget
            -> valeur_commune = 10*x - 5

        5 objets coûtent 12 de moins que mon budget
            -> valeur_commune = 5*x + 12

    IMPORTANT :

    Cette fonction est indépendante du domaine.

    Elle ne connaît pas :
        - CD ;
        - billets ;
        - prix ;
        - âge ;
        - etc.

    Elle reconnaît uniquement une structure quantitative :

        quantité
        + décalage
        + valeur commune.

    La fonction tolère également certaines erreurs de saisie
    courantes comme :

        j,achete
        j'achete
        j’achète
        j'en achète
    """

    value = str(
        text
        or ""
    ).strip()

    if not value:
        return []

    # ========================================================
    # 0. NORMALISATION LINGUISTIQUE LÉGÈRE
    # ========================================================
    #
    # On ne transforme pas le sens de l'énoncé.
    #
    # On homogénéise uniquement :
    #
    #     apostrophes typographiques
    #     symbole monétaire
    #     faute courante : j,achete
    #
    # Exemple :
    #
    #     j,achete
    #
    # devient :
    #
    #     j'achete
    #
    # Cette normalisation est linguistique et non liée
    # à un domaine particulier.
    # ========================================================

    normalized = (
        value
        .replace(
            "’",
            "'",
        )
        .replace(
            "€",
            "$",
        )
    )

    normalized = re.sub(
        r"\bj\s*,\s*"
        r"(?="
            r"(?:en\s+)?"
            r"(?:"
                r"ach[eè]te"
                r"|achete"
                r"|ach[eè]terais"
                r"|acheterais"
                r"|prends"
                r"|prendrais"
                r"|commande"
                r"|commanderais"
            r")"
        r")",
        "j'",
        normalized,
        flags=re.IGNORECASE,
    )

    constraints: List[
        Dict[str, Any]
    ] = []

    # ========================================================
    # MÉMOIRE DU NOM D'OBJET
    # ========================================================
    #
    # Exemple :
    #
    #     si j'achète 10 objets ...
    #     mais si j'en achète 5 ...
    #
    # La seconde clause peut ne pas répéter le nom.
    #
    # On peut alors réutiliser uniquement le dernier nom
    # explicitement rencontré.
    # ========================================================

    last_item: Optional[
        str
    ] = None

    # ========================================================
    # 1. DÉCOUPAGE DES CLAUSES
    # ========================================================
    #
    # Chaque clause quantitative doit être traitée
    # indépendamment.
    #
    # Exemple :
    #
    #     si j'achète 10 objets il me manque 15,
    #     mais si j'en achète 5 il me reste 10
    #
    # devient deux clauses.
    # ========================================================

    action_verb_pattern = (
        r"(?:"
            r"ach[eè]te"
            r"|achete"
            r"|ach[eè]terais"
            r"|acheterais"
            r"|prends"
            r"|prendrais"
            r"|commande"
            r"|commanderais"
        r")"
    )

    clause_pattern = re.compile(
        r"(?:"
            r"\b(?:mais\s+)?si\s+"
            r"j"
            r"(?:['’,]\s*)?"
            r"(?:en\s+)?"
            + action_verb_pattern +
            r"\s+"
            r"\d+(?:[.,]\d+)?"
        r")"
        r".*?"
        r"(?="
            r"\b(?:mais\s+)?si\s+"
            r"j"
            r"(?:['’,]\s*)?"
            r"|$"
        r")",
        flags=(
            re.IGNORECASE
            | re.DOTALL
        ),
    )

    clauses = [
        match.group(0).strip(
            " ,.;"
        )
        for match in (
            clause_pattern.finditer(
                normalized
            )
        )
    ]

    # --------------------------------------------------------
    # FALLBACK
    # --------------------------------------------------------
    #
    # Certains énoncés n'utilisent pas explicitement "si".
    #
    # Dans ce cas on conserve tout le texte pour les autres
    # extracteurs génériques ci-dessous.
    # --------------------------------------------------------

    if not clauses:

        clauses = [
            normalized
        ]

    # ========================================================
    # 2. EXTRACTION DE L'ACTION QUANTIFIÉE
    # ========================================================

    action_pattern = re.compile(
        r"\b"
        r"(?:mais\s+)?"
        r"(?:si\s+)?"
        r"j"
        r"(?:['’,]\s*)?"
        r"(?:en\s+)?"
        + action_verb_pattern +
        r"\s+"
        r"(\d+(?:[.,]\d+)?)"
        r"(?:"
            r"\s+"
            r"([A-Za-zÀ-ÖØ-öø-ÿ'-]+)"
        r")?"
        r"(.*)",
        flags=(
            re.IGNORECASE
            | re.DOTALL
        ),
    )

    for clause in clauses:

        match = (
            action_pattern.search(
                clause
            )
        )

        if not match:
            continue

        quantity = (
            _normalize_numeric_value(
                match.group(
                    1
                )
            )
        )

        explicit_item = (
            _clean_semantic_item_name(
                match.group(
                    2
                )
            )
        )

        tail = str(
            match.group(
                3
            )
            or ""
        ).strip()

        # ====================================================
        # MOTS FONCTIONNELS À NE PAS PRENDRE POUR UN OBJET
        # ====================================================

        if (
            explicit_item
            and explicit_item.lower()
            not in {
                "il",
                "je",
                "me",
                "mon",
                "ma",
                "mes",
                "et",
                "mais",
                "alors",
                "donc",
                "puis",
                "en",
            }
        ):

            last_item = (
                explicit_item
            )

        else:

            explicit_item = None

        item = (
            explicit_item
            or last_item
        )

        # ====================================================
        # 3. MANQUE / INSUFFISANCE
        # ====================================================
        #
        # Si :
        #
        #     coût = quantité * valeur_unitaire
        #
        # et :
        #
        #     il manque M
        #
        # alors :
        #
        #     valeur_commune
        #     =
        #     coût - M
        #
        # donc offset = -M.
        # ====================================================

        shortfall_patterns = [
            (
                r"(?:il\s+)?me\s+"
                r"(?:manque|manquera|manquerait)"
                r"(?:\s+(?:de|d['’]))?"
                r"\s*"
                r"(\d+(?:[.,]\d+)?)"
                r"\s*\$?"
            ),
            (
                r"(?:mon|le)\s+budget\s+"
                r"(?:est\s+)?insuffisant"
                r"(?:\s+(?:de|d['’]))?"
                r"\s*"
                r"(\d+(?:[.,]\d+)?)"
                r"\s*\$?"
            ),
            (
                r"je\s+n['’]?ai\s+pas\s+assez"
                r"(?:\s+(?:de|d['’]))?"
                r"\s*"
                r"(\d+(?:[.,]\d+)?)"
                r"\s*\$?"
            ),
            (
                r"il\s+me\s+faudrait\s+"
                r"(\d+(?:[.,]\d+)?)"
                r"\s*\$?"
                r"\s+de\s+plus"
            ),
        ]

        shortfall_amount = None

        for pattern in (
            shortfall_patterns
        ):

            shortfall_match = (
                re.search(
                    pattern,
                    tail,
                    flags=re.IGNORECASE,
                )
            )

            if shortfall_match:

                shortfall_amount = (
                    _normalize_numeric_value(
                        shortfall_match.group(
                            1
                        )
                    )
                )

                break

        if (
            quantity is not None
            and shortfall_amount
            is not None
        ):

            constraint = {
                "relation": (
                    "product_offset_common_value"
                ),

                "common_role": (
                    "available_amount"
                ),

                "quantity": (
                    quantity
                ),

                "offset": (
                    -shortfall_amount
                ),

                "offset_kind": (
                    "shortfall"
                ),
            }

            if item:

                constraint[
                    "item"
                ] = item

            constraints.append(
                constraint
            )

            continue

        # ====================================================
        # 4. RESTE / EXCÉDENT
        # ====================================================
        #
        # Si :
        #
        #     il reste R
        #
        # alors :
        #
        #     valeur_commune
        #     =
        #     coût + R
        #
        # donc offset = +R.
        # ====================================================

        remainder_patterns = [
            (
                r"(?:il\s+)?me\s+"
                r"(?:reste|restera|resterait)"
                r"\s*"
                r"(\d+(?:[.,]\d+)?)"
                r"\s*\$?"
            ),
            (
                r"j['’]?aurai(?:s)?\s+"
                r"(\d+(?:[.,]\d+)?)"
                r"\s*\$?"
                r"(?:\s+"
                    r"(?:"
                        r"de\s+reste"
                        r"|restants?"
                        r"|restantes?"
                        r"|en\s+reste"
                    r")"
                r")?"
            ),
            (
                r"il\s+restera\s+"
                r"(\d+(?:[.,]\d+)?)"
                r"\s*\$?"
            ),
            (
                r"j['’]?aurai(?:s)?\s+"
                r"un\s+exc[eé]dent\s+de\s+"
                r"(\d+(?:[.,]\d+)?)"
                r"\s*\$?"
            ),
        ]

        remainder_amount = None

        for pattern in (
            remainder_patterns
        ):

            remainder_match = (
                re.search(
                    pattern,
                    tail,
                    flags=re.IGNORECASE,
                )
            )

            if remainder_match:

                remainder_amount = (
                    _normalize_numeric_value(
                        remainder_match.group(
                            1
                        )
                    )
                )

                break

        if (
            quantity is not None
            and remainder_amount
            is not None
        ):

            constraint = {
                "relation": (
                    "product_offset_common_value"
                ),

                "common_role": (
                    "available_amount"
                ),

                "quantity": (
                    quantity
                ),

                "offset": (
                    remainder_amount
                ),

                "offset_kind": (
                    "remainder"
                ),
            }

            if item:

                constraint[
                    "item"
                ] = item

            constraints.append(
                constraint
            )

    # ========================================================
    # 5. COMPARAISON DIRECTE À UNE VALEUR COMMUNE
    # ========================================================
    #
    # Exemple générique :
    #
    #     10 objets coûtent 5 de plus que mon budget
    #
    #     5 objets coûtent 12 de moins que mon budget
    #
    # ========================================================

    comparative_cost_pattern = re.compile(
        r"\b"
        r"(\d+(?:[.,]\d+)?)"
        r"\s+"
        r"([A-Za-zÀ-ÖØ-öø-ÿ'-]+)"
        r"\s+"
        r"(?:"
            r"co[uû]tent?"
            r"|reviennent?"
            r"|valent?"
        r")"
        r"\s+"
        r"(\d+(?:[.,]\d+)?)"
        r"\s*\$?"
        r"\s+de\s+"
        r"(plus|moins)"
        r"\s+que\s+"
        r"(?:mon|le)\s+budget",
        flags=re.IGNORECASE,
    )

    for match in (
        comparative_cost_pattern.finditer(
            normalized
        )
    ):

        quantity = (
            _normalize_numeric_value(
                match.group(
                    1
                )
            )
        )

        item = (
            _clean_semantic_item_name(
                match.group(
                    2
                )
            )
        )

        amount = (
            _normalize_numeric_value(
                match.group(
                    3
                )
            )
        )

        direction = (
            match.group(
                4
            )
            .lower()
            .strip()
        )

        if (
            quantity is None
            or amount is None
        ):
            continue

        if direction == "plus":

            offset = (
                -amount
            )

            offset_kind = (
                "shortfall"
            )

        else:

            offset = (
                amount
            )

            offset_kind = (
                "remainder"
            )

        constraint = {
            "relation": (
                "product_offset_common_value"
            ),

            "common_role": (
                "available_amount"
            ),

            "quantity": (
                quantity
            ),

            "offset": (
                offset
            ),

            "offset_kind": (
                offset_kind
            ),
        }

        if item:

            constraint[
                "item"
            ] = item

        constraints.append(
            constraint
        )

    # ========================================================
    # 6. DÉPASSEMENT DE LA VALEUR DISPONIBLE
    # ========================================================
    #
    # Exemple :
    #
    #     avec 10 objets je dépasse mon budget de 5
    #
    # ========================================================

    exceeds_budget_pattern = re.compile(
        r"\b"
        r"(?:avec|pour)"
        r"\s+"
        r"(\d+(?:[.,]\d+)?)"
        r"\s+"
        r"([A-Za-zÀ-ÖØ-öø-ÿ'-]+)"
        r".{0,60}?"
        r"(?:"
            r"je\s+d[eé]passe"
            r"|cela\s+d[eé]passe"
            r"|le\s+co[uû]t\s+d[eé]passe"
        r")"
        r"\s+"
        r"(?:mon|le)\s+budget"
        r"\s+de\s+"
        r"(\d+(?:[.,]\d+)?)"
        r"\s*\$?",
        flags=re.IGNORECASE,
    )

    for match in (
        exceeds_budget_pattern.finditer(
            normalized
        )
    ):

        quantity = (
            _normalize_numeric_value(
                match.group(
                    1
                )
            )
        )

        item = (
            _clean_semantic_item_name(
                match.group(
                    2
                )
            )
        )

        amount = (
            _normalize_numeric_value(
                match.group(
                    3
                )
            )
        )

        if (
            quantity is None
            or amount is None
        ):
            continue

        constraint = {
            "relation": (
                "product_offset_common_value"
            ),

            "common_role": (
                "available_amount"
            ),

            "quantity": (
                quantity
            ),

            "offset": (
                -amount
            ),

            "offset_kind": (
                "shortfall"
            ),
        }

        if item:

            constraint[
                "item"
            ] = item

        constraints.append(
            constraint
        )

    # ========================================================
    # 7. DÉDOUBLONNAGE
    # ========================================================
    #
    # Deux contraintes ayant la même structure quantitative
    # ne doivent être mémorisées qu'une fois.
    # ========================================================

    unique_constraints: List[
        Dict[str, Any]
    ] = []

    seen = set()

    for constraint in constraints:

        fingerprint = (
            constraint.get(
                "relation"
            ),

            constraint.get(
                "common_role"
            ),

            str(
                constraint.get(
                    "quantity"
                )
            ),

            str(
                constraint.get(
                    "offset"
                )
            ),

            str(
                constraint.get(
                    "item"
                )
                or ""
            ).lower(),
        )

        if fingerprint in seen:
            continue

        seen.add(
            fingerprint
        )

        unique_constraints.append(
            constraint
        )

    return unique_constraints