from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import sympy as sp
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)


X = sp.Symbol("x")

TRANSFORMATIONS = (
    standard_transformations
    + (
        implicit_multiplication_application,
        convert_xor,
    )
)


@dataclass
class ParsedEquation:
    raw_text: str
    extracted_equation: Optional[str]
    normalized_equation: Optional[str]

    parse_success: bool

    degree: Optional[int] = None
    equation_type: Optional[str] = None

    reason: Optional[str] = None


# ============================================================
# NORMALISATION
# ============================================================

def normalize_math_text(
    text: str,
) -> str:

    if text is None:
        return ""

    value = str(
        text
    ).strip()

    replacements = {
        "−": "-",
        "–": "-",
        "—": "-",
        "×": "*",
        "÷": "/",

        "≤": "<=",
        "≥": ">=",
        "≦": "<=",
        "≧": ">=",

        "²": "**2",
        "³": "**3",
    }

    for source, target in (
        replacements.items()
    ):
        value = value.replace(
            source,
            target,
        )

    value = value.replace(
        "^",
        "**",
    )

    value = re.sub(
        r"\s+",
        "",
        value,
    )

    # 3x -> 3*x
    value = re.sub(
        r"(?<=\d)(?=[a-zA-Z])",
        "*",
        value,
    )

    # 2(x+1) -> 2*(x+1)
    value = re.sub(
        r"(?<=\d)(?=\()",
        "*",
        value,
    )

    # x(x+1) -> x*(x+1)
    value = re.sub(
        r"(?<=[a-zA-Z])(?=\()",
        "*",
        value,
    )

    # (x+1)(x-2)
    value = re.sub(
        r"(?<=\))(?=\()",
        "*",
        value,
    )

    value = re.sub(
        r"\*{3,}",
        "**",
        value,
    )

    return value


def _strip_trailing_sentence_punctuation(
    relation: Optional[str],
) -> Optional[str]:
    """
    Retire uniquement la ponctuation de phrase placée
    après une relation mathématique extraite.

    Exemples :

        x+2x=30.
            -> x+2x=30

        3x=15,
            -> 3x=15

        x=2.5
            -> x=2.5

    IMPORTANT :
    on ne retire PAS les opérateurs mathématiques
    + - * / afin de ne pas modifier silencieusement
    une expression mathématique.
    """

    if relation is None:
        return None

    value = str(
        relation
    ).strip()

    if not value:
        return None

    value = value.rstrip(
        ".,;:!?"
    )

    value = value.strip()

    if not value:
        return None

    return value


def _normalize_extracted_relation(
    relation: Optional[str],
) -> Optional[str]:
    """
    Normalisation finale commune des relations extraites.

    Cette fonction garantit notamment qu'une ponctuation
    de phrase ne soit jamais conservée dans l'équation
    mémorisée par Naima.
    """

    cleaned = (
        _strip_trailing_sentence_punctuation(
            relation
        )
    )

    if not cleaned:
        return None

    normalized = (
        normalize_math_text(
            cleaned
        )
    )

    normalized = (
        _strip_trailing_sentence_punctuation(
            normalized
        )
    )

    if not normalized:
        return None

    return normalized


def _parse_expression(
    expression: str,
) -> sp.Expr:

    return parse_expr(
        expression,
        local_dict={
            "x": X,
            "sqrt": sp.sqrt,
        },
        transformations=(
            TRANSFORMATIONS
        ),
        evaluate=True,
    )


# ============================================================
# OPÉRATEURS
# ============================================================

def detect_relation_operator(
    text: Optional[str],
) -> Optional[str]:

    if not text:
        return None

    normalized = (
        normalize_math_text(
            text
        )
    )

    # Important :
    # les opérateurs doubles avant les simples.
    for operator in (
        "<=",
        ">=",
        "=",
        "<",
        ">",
    ):
        if operator in normalized:
            return operator

    return None


def is_inequality_relation(
    text: Optional[str],
) -> bool:

    return (
        detect_relation_operator(
            text
        )
        in {
            "<",
            ">",
            "<=",
            ">=",
        }
    )


def split_math_relation(
    text: str,
) -> Optional[
    tuple[str, str, str]
]:

    cleaned = (
        _strip_trailing_sentence_punctuation(
            text
        )
    )

    if not cleaned:
        return None

    normalized = (
        normalize_math_text(
            cleaned
        )
    )

    operator = (
        detect_relation_operator(
            normalized
        )
    )

    if not operator:
        return None

    try:
        left, right = (
            normalized.split(
                operator,
                1,
            )
        )

    except ValueError:
        return None

    left = (
        left.strip()
    )

    right = (
        _strip_trailing_sentence_punctuation(
            right
        )
        or ""
    )

    if (
        not left
        or not right
    ):
        return None

    return (
        left,
        operator,
        right,
    )


# ============================================================
# DEGRÉ
# ============================================================

def equation_degree(
    equation: Optional[str],
) -> Optional[int]:
    """
    Retourne le degré polynomial d'une relation mathématique.

    Fonctionne notamment pour :
        3x=5
        3x²-5x+2=0
        -2x>6
        x²<=9
    """

    if not equation:
        return None

    parts = split_math_relation(
        equation
    )

    if not parts:
        return None

    left, _operator, right = (
        parts
    )

    try:
        expression = sp.expand(
            _parse_expression(
                left
            )
            - _parse_expression(
                right
            )
        )

        polynomial = sp.Poly(
            expression,
            X,
        )

        degree = (
            polynomial.degree()
        )

        if degree is None:
            return None

        return int(
            degree
        )

    except Exception:
        return None


# ============================================================
# CLASSIFICATION
# ============================================================

def classify_equation(
    equation: Optional[str],
) -> str:
    """
    Classification historique conservée,
    mais étendue aux inéquations.

    Retour possible :
        unknown
        constant
        linear
        quadratic
        polynomial_other
        inequality
    """

    if not equation:
        return "unknown"

    if is_inequality_relation(
        equation
    ):
        return "inequality"

    degree = equation_degree(
        equation
    )

    if degree is None:
        return "unknown"

    if degree == 0:
        return "constant"

    if degree == 1:
        return "linear"

    if degree == 2:
        return "quadratic"

    return "polynomial_other"


# ============================================================
# RÉPONSE FINALE VS NOUVEAU PROBLÈME
# ============================================================

def looks_like_solution_statement(
    text: str,
) -> bool:
    """
    Détecte une réponse finale de type x=...

    Important :
    une réponse d'inéquation comme x<-3
    est également une réponse finale si elle est isolée.

    Cela évite qu'elle remplace le problème actif.
    """

    if not text:
        return False

    value = str(
        text
    ).strip().lower()

    # --------------------------------------------------------
    # Plusieurs solutions d'équation :
    # x=1 ou x=2/3
    # --------------------------------------------------------

    x_equal_assignments = re.findall(
        r"\bx\s*=",
        value,
        flags=re.IGNORECASE,
    )

    if len(
        x_equal_assignments
    ) >= 2:
        return True

    # --------------------------------------------------------
    # Réponse finale simple :
    # x=5/3
    # x<-3
    # x>=4
    #
    # Une ponctuation terminale est maintenant tolérée :
    # x=10.
    # --------------------------------------------------------

    if re.fullmatch(
        r"\s*x\s*"
        r"(?:=|<=|>=|<|>)\s*"
        r"[+\-]?"
        r"(?:"
        r"\d+(?:\.\d+)?"
        r"|"
        r"\d+/\d+"
        r")"
        r"\s*[.,;:!?]?\s*",
        value,
        flags=re.IGNORECASE,
    ):
        return True

    solution_markers = (
        "les solutions sont",
        "les racines sont",
        "la solution est",
        "solution est",
        "solutions:",
        "solutions :",
        "racines:",
        "racines :",
        "solution:",
        "solution :",
    )

    if (
        any(
            marker in value
            for marker
            in solution_markers
        )
        and "x" in value
    ):
        return True

    return False


# ============================================================
# EXTRACTION D'UNE RELATION MATHÉMATIQUE
# ============================================================

def extract_equation_from_text(
    text: str,
) -> Optional[str]:
    """
    Nom historique conservé pour compatibilité.

    La fonction extrait maintenant aussi bien :
        équations
        inéquations

    Exemples
    --------
    résoudre 3x²-5x+2=0
        -> 3*x**2-5*x+2=0

    résoudre -2x>6
        -> -2*x>6

    Attention, on est ici 3x=5
        -> 3*x=5

    Soit x l'âge de Paul, donc x+2x=30.
        -> x+2*x=30

    x=1 ou x=2/3
        -> None

    x<-3
        -> None

    Une réponse finale ne doit pas devenir
    un nouveau problème.
    """

    if not text:
        return None

    if looks_like_solution_statement(
        text
    ):
        return None

    raw = str(
        text
    )

    prepared = (
        raw.replace(
            "²",
            "^2",
        )
        .replace(
            "³",
            "^3",
        )
        .replace(
            "−",
            "-",
        )
        .replace(
            "–",
            "-",
        )
        .replace(
            "—",
            "-",
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
            "≤",
            "<=",
        )
        .replace(
            "≥",
            ">=",
        )
        .replace(
            "≦",
            "<=",
        )
        .replace(
            "≧",
            ">=",
        )
    )

    # ========================================================
    # 1. RECHERCHE PRINCIPALE
    # ========================================================

    matches = re.findall(
        r"("
        r"[+\-]?"
        r"(?:"
        r"\d+(?:\.\d+)?"
        r"\s*\*?\s*"
        r")?"
        r"(?:"
        r"x"
        r"(?:"
        r"\s*\^\s*[0-9]+"
        r")?"
        r"|"
        r"\([^<>=]+\)"
        r")"
        r"(?:"
        r"[\s0-9xX+\-*/^().]*?"
        r")"
        r"(?:<=|>=|=|<|>)"
        r"[\s0-9xX+\-*/^().]+"
        r")",
        prepared,
        flags=re.IGNORECASE,
    )

    candidates = []

    for candidate in matches:

        candidate = (
            candidate.strip()
        )

        normalized = (
            _normalize_extracted_relation(
                candidate
            )
        )

        if not normalized:
            continue

        operator = (
            detect_relation_operator(
                normalized
            )
        )

        if not operator:
            continue

        if (
            "x"
            not in normalized.lower()
        ):
            continue

        degree = equation_degree(
            normalized
        )

        if degree is not None:
            candidates.append(
                normalized
            )

    # ========================================================
    # 2. FALLBACK AUTOUR DE L'OPÉRATEUR
    # ========================================================

    if not candidates:

        relation_match = re.search(
            r"<=|>=|=|<|>",
            prepared,
        )

        if not relation_match:
            return None

        operator = (
            relation_match.group(0)
        )

        operator_start = (
            relation_match.start()
        )

        operator_end = (
            relation_match.end()
        )

        left_text = prepared[
            :operator_start
        ]

        right_text = prepared[
            operator_end:
        ]

        # Dernière portion mathématique contenant x.
        left_matches = re.findall(
            r"("
            r"[+\-]?"
            r"[0-9xX().*/^+\-\s]*"
            r"[xX]"
            r"[0-9xX().*/^+\-\s]*"
            r")$",
            left_text,
        )

        if not left_matches:
            return None

        left_candidate = (
            left_matches[-1]
            .strip()
        )

        # Première portion mathématique à droite.
        right_match = re.match(
            r"\s*("
            r"[+\-]?"
            r"[0-9xX().*/^+\-\s]+"
            r")",
            right_text,
        )

        if not right_match:
            return None

        right_candidate = (
            right_match
            .group(1)
            .strip()
        )

        right_candidate = (
            _strip_trailing_sentence_punctuation(
                right_candidate
            )
        )

        if not right_candidate:
            return None

        candidate = (
            f"{left_candidate}"
            f"{operator}"
            f"{right_candidate}"
        )

        normalized = (
            _normalize_extracted_relation(
                candidate
            )
        )

        if (
            normalized
            and equation_degree(
                normalized
            )
            is not None
        ):
            candidates.append(
                normalized
            )

    if not candidates:
        return None

    # ========================================================
    # 3. CHOISIR LA RELATION LA PLUS COMPLÈTE
    # ========================================================

    def candidate_score(
        candidate: str,
    ):

        degree = equation_degree(
            candidate
        )

        return (
            (
                degree
                if degree is not None
                else -1
            ),
            len(
                candidate
            ),
        )

    best_candidate = max(
        candidates,
        key=candidate_score,
    )

    # ========================================================
    # 4. NORMALISATION FINALE
    # ========================================================
    #
    # Sécurité importante :
    #
    #   "x+2x=30."
    #
    # ne doit jamais être mémorisé comme :
    #
    #   "x+2*x=30."
    #
    # mais comme :
    #
    #   "x+2*x=30"
    # ========================================================

    return (
        _normalize_extracted_relation(
            best_candidate
        )
    )


# Alias plus clair pour la nouvelle architecture.
def extract_math_relation_from_text(
    text: str,
) -> Optional[str]:

    relation = (
        extract_equation_from_text(
            text
        )
    )

    return (
        _normalize_extracted_relation(
            relation
        )
    )


# ============================================================
# PARSING COMPLET
# ============================================================

def parse_equation_from_text(
    text: str,
) -> ParsedEquation:

    extracted = (
        extract_equation_from_text(
            text
        )
    )

    if not extracted:
        return ParsedEquation(
            raw_text=text,
            extracted_equation=None,
            normalized_equation=None,
            parse_success=False,
            degree=None,
            equation_type=None,
            reason="equation_not_found",
        )

    normalized = (
        _normalize_extracted_relation(
            extracted
        )
    )

    if not normalized:
        return ParsedEquation(
            raw_text=text,
            extracted_equation=None,
            normalized_equation=None,
            parse_success=False,
            degree=None,
            equation_type=None,
            reason="equation_not_found",
        )

    degree = equation_degree(
        normalized
    )

    equation_type = (
        classify_equation(
            normalized
        )
    )

    return ParsedEquation(
        raw_text=text,
        extracted_equation=(
            normalized
        ),
        normalized_equation=(
            normalized
        ),
        parse_success=True,
        degree=degree,
        equation_type=(
            equation_type
        ),
        reason="equation_parsed",
    )


# ============================================================
# PROTECTION DU CONTEXTE
# ============================================================

def choose_safe_equation(
    *,
    original_text: str,
    extracted_equation: Optional[
        str
    ],
) -> dict:

    source_equation = (
        extract_equation_from_text(
            original_text
        )
    )

    source_equation = (
        _normalize_extracted_relation(
            source_equation
        )
    )

    extracted_equation = (
        _normalize_extracted_relation(
            extracted_equation
        )
    )

    source_degree = (
        equation_degree(
            source_equation
        )
    )

    extracted_degree = (
        equation_degree(
            extracted_equation
        )
    )

    # --------------------------------------------------------
    # Protection classique :
    # quadratique tronqué en linéaire.
    # --------------------------------------------------------

    if (
        source_degree is not None
        and extracted_degree is not None
        and source_degree
        > extracted_degree
    ):
        return {
            "consistent": False,
            "reason": (
                "higher_degree_term_lost"
            ),
            "preferred_equation": (
                source_equation
            ),
            "source_equation": (
                source_equation
            ),
            "extracted_equation": (
                extracted_equation
            ),
            "source_degree": (
                source_degree
            ),
            "extracted_degree": (
                extracted_degree
            ),
        }

    # --------------------------------------------------------
    # Protection supplémentaire :
    # type de relation différent.
    #
    # Exemple :
    # source -2x>6
    # extraction -2x=6
    # --------------------------------------------------------

    source_operator = (
        detect_relation_operator(
            source_equation
        )
    )

    extracted_operator = (
        detect_relation_operator(
            extracted_equation
        )
    )

    if (
        source_equation
        and extracted_equation
        and source_operator
        and extracted_operator
        and source_operator
        != extracted_operator
    ):
        return {
            "consistent": False,
            "reason": (
                "relation_operator_changed"
            ),
            "preferred_equation": (
                source_equation
            ),
            "source_equation": (
                source_equation
            ),
            "extracted_equation": (
                extracted_equation
            ),
            "source_degree": (
                source_degree
            ),
            "extracted_degree": (
                extracted_degree
            ),
        }

    preferred = (
        source_equation
        or extracted_equation
    )

    return {
        "consistent": True,
        "reason": (
            "equation_consistent"
        ),
        "preferred_equation": (
            preferred
        ),
        "source_equation": (
            source_equation
        ),
        "extracted_equation": (
            extracted_equation
        ),
        "source_degree": (
            source_degree
        ),
        "extracted_degree": (
            extracted_degree
        ),
    }