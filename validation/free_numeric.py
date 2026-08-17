# validation/free_numeric.py
#
# Extraction prudente d'une réponse numérique contenue dans une phrase.
# VERSION AVEC CONTRÔLE DE COHÉRENCE ARITHMÉTIQUE DES ÉGALITÉS.
#
# Principe de sécurité :
# - une égalité comme "100 + 100*0.1 = 110" peut être validée localement ;
# - une égalité comme "1000*0.03*1 = 60" NE PEUT PAS être déclarée correcte,
#   même si 60 correspond à la réponse officielle, car le calcul écrit vaut 30 ;
# - si l'expression est trop complexe pour être évaluée sûrement, on ne conclut
#   pas négativement : on retourne unresolved et le moteur poursuit.

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import ast
import operator
import re
from typing import List, Optional, Tuple


@dataclass
class FreeNumericEvidence:
    verdict: str = "unresolved"   # correct | incorrect | unresolved
    confidence: float = 0.0
    method: str = "free_numeric_unresolved"
    reason: str = ""
    expected_value: Optional[float] = None
    candidate_value: Optional[float] = None
    candidates: List[float] = field(default_factory=list)
    signal: Optional[str] = None
    expression_value: Optional[float] = None
    equality_consistent: Optional[bool] = None


class FreeNumericAnswerValidator:
    """
    Validateur conservateur pour les réponses libres numériques.

    Signaux :
      1. égalité finale explicite
      2. formulation finale explicite
      3. valeur numérique unique

    Pour une égalité contenant un calcul, le calcul de gauche est vérifié
    localement avec un évaluateur arithmétique strictement limité.
    """

    _NUM = r"[-+]?(?:\d+(?:[.,]\d+)?|\d*[.,]\d+)(?:\s*/\s*[-+]?\d+(?:[.,]\d+)?)?\s*%?"

    _EXPLICIT_FINAL_PATTERNS = (
        re.compile(
            rf"(?:réponse|reponse|answer|résultat|resultat|total|montant|intérêt|interet|interest)"
            rf"\s*(?:final(?:e)?\s*)?(?:est|is|=|:|de|à|a)?\s*({_NUM})"
            rf"\s*(?:\\?\$|€|£|cad|usd|dollars?|euros?)?\s*[.!]?\s*$",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?:donc|ainsi|so|therefore)\s*(?:la\s+réponse\s+est\s*)?"
            rf"({_NUM})\s*(?:\\?\$|€|£|cad|usd|dollars?|euros?)?\s*[.!]?\s*$",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?:est\s+de|is)\s*({_NUM})"
            rf"\s*(?:\\?\$|€|£|cad|usd|dollars?|euros?)?\s*[.!]?\s*$",
            re.IGNORECASE,
        ),
    )

    _BIN_OPS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
    }

    _UNARY_OPS = {
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
    }

    def validate(self, student_answer: str, expected_answer: str) -> FreeNumericEvidence:
        student = (student_answer or "").strip()
        expected = (expected_answer or "").strip()

        expected_value = self._parse_reference_value(expected)
        if expected_value is None:
            return FreeNumericEvidence(
                verdict="unresolved",
                method="free_numeric_reference_not_scalar",
                reason="La réponse attendue n'est pas une valeur numérique scalaire exploitable.",
            )

        if not student:
            return FreeNumericEvidence(
                verdict="unresolved",
                method="free_numeric_empty_student",
                reason="La réponse de l'élève est vide.",
                expected_value=expected_value,
            )

        candidates = self._extract_all_numbers(student)

        # ==========================================================
        # 1. Dernière égalité
        # ==========================================================
        equality_data = self._extract_last_equality(student)

        if equality_data is not None:
            lhs_text, rhs_value = equality_data

            expression_value = self._safe_eval_arithmetic(lhs_text)

            # Si le membre gauche ressemble à un véritable calcul et qu'il
            # est évalué localement, on exige sa cohérence avec le RHS.
            if expression_value is not None:
                equality_consistent = self._equivalent(
                    expression_value,
                    rhs_value
                )

                if not equality_consistent:
                    return FreeNumericEvidence(
                        verdict="unresolved",
                        confidence=0.0,
                        method="free_numeric_inconsistent_equality",
                        reason=(
                            "La valeur finale correspond peut-être à la référence, "
                            "mais le calcul écrit dans l'égalité n'est pas cohérent "
                            "avec son membre droit. Une validation plus approfondie "
                            "est nécessaire."
                        ),
                        expected_value=expected_value,
                        candidate_value=rhs_value,
                        candidates=candidates,
                        signal="last_equality_rhs",
                        expression_value=expression_value,
                        equality_consistent=False,
                    )

                # L'égalité est arithmétiquement cohérente.
                if self._equivalent(rhs_value, expected_value):
                    return FreeNumericEvidence(
                        verdict="correct",
                        confidence=0.999,
                        method="free_numeric_verified_equality",
                        reason=(
                            "Le calcul écrit est arithmétiquement cohérent et son "
                            "résultat correspond à la réponse attendue."
                        ),
                        expected_value=expected_value,
                        candidate_value=rhs_value,
                        candidates=candidates,
                        signal="verified_equality",
                        expression_value=expression_value,
                        equality_consistent=True,
                    )

                return FreeNumericEvidence(
                    verdict="incorrect",
                    confidence=0.995,
                    method="free_numeric_verified_equality_mismatch",
                    reason=(
                        "Le calcul écrit est arithmétiquement cohérent, mais son "
                        "résultat final ne correspond pas à la réponse attendue."
                    ),
                    expected_value=expected_value,
                    candidate_value=rhs_value,
                    candidates=candidates,
                    signal="verified_equality",
                    expression_value=expression_value,
                    equality_consistent=True,
                )

            # Si le membre gauche ne peut pas être évalué de manière sûre,
            # ne pas attribuer un verdict négatif ou positif sur cette seule
            # égalité. On poursuit vers les signaux textuels.
            if self._looks_like_arithmetic(lhs_text):
                return FreeNumericEvidence(
                    verdict="unresolved",
                    confidence=0.0,
                    method="free_numeric_unverified_equality",
                    reason=(
                        "Une égalité numérique est présente, mais son calcul ne "
                        "peut pas être vérifié localement avec suffisamment de sécurité."
                    ),
                    expected_value=expected_value,
                    candidate_value=rhs_value,
                    candidates=candidates,
                    signal="unverified_equality",
                )

        # ==========================================================
        # 2. Formulation finale explicite
        # ==========================================================
        explicit_candidate = self._extract_explicit_final(student)
        if explicit_candidate is not None:
            return self._compare(
                candidate=explicit_candidate,
                expected=expected_value,
                candidates=candidates,
                signal="explicit_final_phrase",
                correct_confidence=0.995,
                incorrect_confidence=0.99,
                correct_method="free_numeric_explicit_final",
                incorrect_method="free_numeric_explicit_final_mismatch",
                correct_reason=(
                    "La réponse finale numérique explicitement formulée "
                    "correspond à la référence."
                ),
                incorrect_reason=(
                    "La réponse finale numérique explicitement formulée "
                    "ne correspond pas à la référence."
                ),
            )

        # ==========================================================
        # 3. Valeur unique
        # ==========================================================
        if len(candidates) == 1:
            return self._compare(
                candidate=candidates[0],
                expected=expected_value,
                candidates=candidates,
                signal="single_numeric_candidate",
                correct_confidence=0.99,
                incorrect_confidence=0.985,
                correct_method="free_numeric_single_value",
                incorrect_method="free_numeric_single_value_mismatch",
                correct_reason=(
                    "La réponse contient une seule valeur numérique et elle "
                    "correspond à la référence."
                ),
                incorrect_reason=(
                    "La réponse contient une seule valeur numérique explicite "
                    "et elle ne correspond pas à la référence."
                ),
            )

        # ==========================================================
        # 4. Plusieurs nombres sans conclusion sûre
        # ==========================================================
        if any(self._equivalent(value, expected_value) for value in candidates):
            return FreeNumericEvidence(
                verdict="unresolved",
                confidence=0.0,
                method="free_numeric_ambiguous_contains_expected",
                reason=(
                    "La valeur attendue apparaît dans la réponse, mais plusieurs "
                    "nombres sont présents sans signal final suffisamment clair."
                ),
                expected_value=expected_value,
                candidates=candidates,
                signal="ambiguous_multiple_numbers",
            )

        return FreeNumericEvidence(
            verdict="unresolved",
            confidence=0.0,
            method="free_numeric_ambiguous",
            reason=(
                "Plusieurs valeurs numériques sont présentes sans réponse finale "
                "suffisamment explicite. Aucun verdict négatif déterministe."
            ),
            expected_value=expected_value,
            candidates=candidates,
            signal="ambiguous_multiple_numbers",
        )

    # ==============================================================
    # Référence numérique
    # ==============================================================

    def _parse_reference_value(self, text: str) -> Optional[float]:
        cleaned = self._clean_scalar_text(text)

        pattern = (
            rf"\s*({self._NUM})\s*"
            r"(?:\\?\$|€|£|cad|usd|dollars?|euros?)?\s*"
        )

        match = re.fullmatch(pattern, cleaned, re.IGNORECASE)
        if not match:
            return None

        return self._token_to_float(match.group(1))

    @staticmethod
    def _clean_scalar_text(text: str) -> str:
        return (
            (text or "")
            .strip()
            .replace("\u00a0", " ")
            .replace("\\$", "$")
        )

    # ==============================================================
    # Égalités
    # ==============================================================

    def _extract_last_equality(
        self,
        text: str
    ) -> Optional[Tuple[str, float]]:

        if "=" not in text:
            return None

        lhs, rhs = text.rsplit("=", 1)

        rhs_match = re.match(
            rf"^\s*({self._NUM})",
            rhs.strip(),
            re.IGNORECASE
        )

        if not rhs_match:
            return None

        rhs_value = self._token_to_float(rhs_match.group(1))
        if rhs_value is None:
            return None

        # Pour une réponse comportant du texte avant le calcul :
        # "le total est 600*0.07*1=42"
        # on extrait la dernière séquence arithmétique du membre gauche.
        lhs_expression = self._extract_trailing_arithmetic(lhs)

        return lhs_expression, rhs_value

    @staticmethod
    def _looks_like_arithmetic(text: str) -> bool:
        return bool(re.search(r"[\d][\s]*(?:[+\-*/^×÷])", text or ""))

    def _extract_trailing_arithmetic(self, lhs: str) -> str:
        raw = (lhs or "").strip()

        # Cherche la dernière séquence composée uniquement de nombres,
        # espaces, séparateurs décimaux, opérateurs et parenthèses.
        match = re.search(
            r"([-+*/^×÷().,\d\s%]+)\s*$",
            raw
        )

        if match:
            candidate = match.group(1).strip()
            if any(ch.isdigit() for ch in candidate):
                return candidate

        return raw

    # ==============================================================
    # Évaluateur arithmétique sûr
    # ==============================================================

    def _safe_eval_arithmetic(self, expression: str) -> Optional[float]:
        """
        Évalue uniquement :
          nombres, +, -, *, /, **, parenthèses, pourcentages simples.

        Aucun nom, appel de fonction, attribut ou code arbitraire n'est permis.
        """
        raw = (expression or "").strip()

        # Normalisation mathématique.
        raw = raw.replace("×", "*").replace("÷", "/").replace("^", "**")
        raw = raw.replace(",", ".")

        # 10% -> (10/100)
        raw = re.sub(
            r"(\d+(?:\.\d+)?)\s*%",
            r"(\1/100)",
            raw
        )

        # Seulement caractères arithmétiques autorisés.
        if not re.fullmatch(r"[\d\s+\-*/().]+", raw):
            return None

        # Limites anti-abus / anti-complexité.
        if len(raw) > 200:
            return None

        try:
            tree = ast.parse(raw, mode="eval")
            value = self._eval_ast_node(tree.body)

            if value is None:
                return None

            value = float(value)

            # Évite valeurs absurdes/infinies.
            if not (-1e15 <= value <= 1e15):
                return None

            return value

        except Exception:
            return None

    def _eval_ast_node(self, node):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return float(node.value)
            raise ValueError("Constante non numérique")

        if isinstance(node, ast.UnaryOp):
            op_type = type(node.op)
            if op_type not in self._UNARY_OPS:
                raise ValueError("Opérateur unaire interdit")

            operand = self._eval_ast_node(node.operand)
            return self._UNARY_OPS[op_type](operand)

        if isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type not in self._BIN_OPS:
                raise ValueError("Opérateur interdit")

            left = self._eval_ast_node(node.left)
            right = self._eval_ast_node(node.right)

            if op_type is ast.Div and right == 0:
                raise ZeroDivisionError

            # Exposants volontairement limités.
            if op_type is ast.Pow and abs(right) > 12:
                raise ValueError("Exposant trop grand")

            return self._BIN_OPS[op_type](left, right)

        raise ValueError("Expression non autorisée")

    # ==============================================================
    # Extraction générale
    # ==============================================================

    def _extract_explicit_final(self, text: str) -> Optional[float]:
        normalized = (
            (text or "")
            .strip()
            .replace("\u00a0", " ")
        )

        for pattern in self._EXPLICIT_FINAL_PATTERNS:
            match = pattern.search(normalized)
            if match:
                value = self._token_to_float(match.group(1))
                if value is not None:
                    return value

        return None

    def _extract_all_numbers(self, text: str) -> List[float]:
        normalized = (
            (text or "")
            .replace("\\$", "$")
            .replace("\u00a0", " ")
        )

        values = []

        for match in re.finditer(self._NUM, normalized):
            value = self._token_to_float(match.group(0))
            if value is not None:
                values.append(value)

        return values

    @staticmethod
    def _token_to_float(token: str) -> Optional[float]:
        if token is None:
            return None

        raw = token.strip().replace(" ", "")
        if not raw:
            return None

        is_percent = raw.endswith("%")
        if is_percent:
            raw = raw[:-1]

        raw = raw.replace(",", ".")

        try:
            if "/" in raw:
                numerator, denominator = raw.split("/", 1)

                numerator_decimal = Decimal(numerator)
                denominator_decimal = Decimal(denominator)

                if denominator_decimal == 0:
                    return None

                value = numerator_decimal / denominator_decimal
            else:
                value = Decimal(raw)

            if is_percent:
                value = value / Decimal("100")

            return float(value)

        except (InvalidOperation, ValueError, ZeroDivisionError):
            return None

    @staticmethod
    def _equivalent(a: float, b: float) -> bool:
        tolerance = max(
            1e-9,
            1e-9 * max(abs(a), abs(b), 1.0)
        )

        return abs(a - b) <= tolerance

    def _compare(
        self,
        *,
        candidate: float,
        expected: float,
        candidates: List[float],
        signal: str,
        correct_confidence: float,
        incorrect_confidence: float,
        correct_method: str,
        incorrect_method: str,
        correct_reason: str,
        incorrect_reason: str,
    ) -> FreeNumericEvidence:

        if self._equivalent(candidate, expected):
            return FreeNumericEvidence(
                verdict="correct",
                confidence=correct_confidence,
                method=correct_method,
                reason=correct_reason,
                expected_value=expected,
                candidate_value=candidate,
                candidates=candidates,
                signal=signal,
            )

        return FreeNumericEvidence(
            verdict="incorrect",
            confidence=incorrect_confidence,
            method=incorrect_method,
            reason=incorrect_reason,
            expected_value=expected,
            candidate_value=candidate,
            candidates=candidates,
            signal=signal,
        )
