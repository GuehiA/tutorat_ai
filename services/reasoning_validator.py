import re
import unicodedata
from fractions import Fraction

from services.validation_result import ValidationResult
from services.answer_normalizer import AnswerNormalizer


class ReasoningValidator:
    """
    Validation déterministe des opérations mathématiques
    exprimées verbalement par l'élève.

    Objectif :
    vérifier certaines transformations d'équations linéaires
    sans dépendre d'une liste de réponses pré-écrites.

    Formes actuellement prises en charge :

        a*x = b

        a*x + b = c

        a*x + b = c*x + d

    Exemples :

        7*x - 5 = 4*x + 3

        "J'ajoute -4x aux deux membres"
        -> transformation :
           3*x - 5 = 3
        -> raisonnement correct

        3*x - 5 = 3

        "J'ajoute l'opposé de -5 aux deux membres"
        -> ajouter 5
        -> transformation :
           3*x = 8
        -> raisonnement correct

        3*x = 8

        "Je divise les deux membres par 3"
        -> x = 8/3
        -> raisonnement correct

    Principe de sécurité :

    - correct seulement si une justification déterministe
      suffisamment forte existe ;

    - incorrect seulement si une erreur peut être démontrée ;

    - sinon uncertain.

    IMPORTANT :

        uncertain != incorrect
    """

    def __init__(self):
        self.normalizer = AnswerNormalizer()

    # ============================================================
    # API PUBLIQUE
    # ============================================================

    def validate(
        self,
        student_answer,
        previous_equation=None,
        last_teacher_question=None,
    ):
        student_answer = str(
            student_answer or ""
        ).strip()

        previous_equation = str(
            previous_equation or ""
        ).strip()

        last_teacher_question = str(
            last_teacher_question or ""
        ).strip()

        # --------------------------------------------------------
        # RÉPONSE VIDE
        # --------------------------------------------------------

        if not student_answer:
            return self._uncertain(
                student_answer,
                previous_equation,
                "Réponse vide."
            )

        # --------------------------------------------------------
        # AUCUNE ÉQUATION DE RÉFÉRENCE
        # --------------------------------------------------------

        if not previous_equation:
            return self._uncertain(
                student_answer,
                previous_equation,
                (
                    "Aucune équation précédente fiable "
                    "n'est disponible."
                )
            )

        # --------------------------------------------------------
        # ANALYSE DE L'ÉQUATION
        # --------------------------------------------------------

        equation_info = self._parse_linear_equation(
            previous_equation
        )

        if not equation_info:
            return self._uncertain(
                student_answer,
                previous_equation,
                (
                    "L'équation précédente n'est pas encore "
                    "prise en charge par le validateur "
                    "déterministe de raisonnement."
                )
            )

        # --------------------------------------------------------
        # EXTRACTION DE L'OPÉRATION
        # --------------------------------------------------------

        operation = self._extract_operation(
            student_answer
        )

        if not operation:
            return self._uncertain(
                student_answer,
                previous_equation,
                (
                    "Aucune opération mathématique suffisamment "
                    "explicite n'a été identifiée dans la réponse."
                )
            )

        operation_type = operation.get(
            "type"
        )

        # ========================================================
        # ADDITION / SOUSTRACTION D'UNE EXPRESSION LINÉAIRE
        # ========================================================

        if operation_type in {
            "add",
            "subtract"
        }:
            return self._validate_add_subtract(
                student_answer=student_answer,
                previous_equation=previous_equation,
                equation_info=equation_info,
                operation=operation,
                last_teacher_question=(
                    last_teacher_question
                ),
            )

        # ========================================================
        # MULTIPLICATION / DIVISION PAR UN SCALAIRE
        # ========================================================

        if operation_type in {
            "multiply",
            "divide"
        }:
            return self._validate_multiply_divide(
                student_answer=student_answer,
                previous_equation=previous_equation,
                equation_info=equation_info,
                operation=operation,
                last_teacher_question=(
                    last_teacher_question
                ),
            )

        return self._uncertain(
            student_answer,
            previous_equation,
            (
                "Une opération a été détectée, mais le moteur "
                "ne dispose pas d'une preuve suffisante pour "
                "la classer."
            )
        )

    # ============================================================
    # VALIDATION ADDITION / SOUSTRACTION
    # ============================================================

    def _validate_add_subtract(
        self,
        student_answer,
        previous_equation,
        equation_info,
        operation,
        last_teacher_question,
    ):
        operand = operation.get(
            "operand"
        )

        if operand is None:
            return self._uncertain(
                student_answer,
                previous_equation,
                (
                    "L'addition ou la soustraction est annoncée "
                    "mais l'expression utilisée n'est pas "
                    "suffisamment explicite."
                )
            )

        operation_type = operation[
            "type"
        ]

        effective_operand = {
            "x": operand.get(
                "x",
                Fraction(0)
            ),

            "constant": operand.get(
                "constant",
                Fraction(0)
            ),
        }

        # --------------------------------------------------------
        # Soustraire E revient à ajouter -E.
        # --------------------------------------------------------

        if operation_type == "subtract":
            effective_operand = {
                "x": -effective_operand["x"],

                "constant": (
                    -effective_operand["constant"]
                ),
            }

        # --------------------------------------------------------
        # APPLICATION AUX DEUX MEMBRES
        # --------------------------------------------------------

        transformed = {
            "left_x": (
                equation_info["left_x"]
                + effective_operand["x"]
            ),

            "left_constant": (
                equation_info["left_constant"]
                + effective_operand["constant"]
            ),

            "right_x": (
                equation_info["right_x"]
                + effective_operand["x"]
            ),

            "right_constant": (
                equation_info["right_constant"]
                + effective_operand["constant"]
            ),
        }

        before_score = self._equation_complexity_score(
            equation_info
        )

        after_score = self._equation_complexity_score(
            transformed
        )

        transformed_text = (
            self._format_linear_equation(
                transformed
            )
        )

        # --------------------------------------------------------
        # L'opération élimine-t-elle un terme ?
        # --------------------------------------------------------

        eliminated_x_term = (
            (
                equation_info["left_x"] != 0
                and transformed["left_x"] == 0
            )
            or
            (
                equation_info["right_x"] != 0
                and transformed["right_x"] == 0
            )
        )

        eliminated_constant = (
            (
                equation_info["left_constant"] != 0
                and transformed["left_constant"] == 0
            )
            or
            (
                equation_info["right_constant"] != 0
                and transformed["right_constant"] == 0
            )
        )

        # --------------------------------------------------------
        # PROGRESSION DÉMONTRÉE
        # --------------------------------------------------------

        if (
            after_score < before_score
            or eliminated_x_term
            or eliminated_constant
        ):
            return ValidationResult(
                verdict="correct",
                confidence=1.0,
                method="reasoning_linear_transformation",

                normalized_student_answer=(
                    self.normalizer.normalize(
                        student_answer
                    )
                ),

                normalized_expected_answer=None,
                result_correct=None,
                reasoning_correct=True,
                error_type=None,

                reason=(
                    "L'opération proposée est mathématiquement "
                    "valide et fait progresser la résolution de "
                    "l'équation. Appliquée aux deux membres de "
                    f"{previous_equation}, elle conduit à "
                    f"{transformed_text}."
                ),

                requires_review=False,

                details={
                    "equation": (
                        previous_equation
                    ),

                    "operation_type": (
                        operation_type
                    ),

                    "operand": (
                        self._format_linear_operand(
                            operand
                        )
                    ),

                    "effective_operand": (
                        self._format_linear_operand(
                            effective_operand
                        )
                    ),

                    "transformed_equation": (
                        transformed_text
                    ),

                    "complexity_before": (
                        before_score
                    ),

                    "complexity_after": (
                        after_score
                    ),

                    "eliminated_x_term": (
                        eliminated_x_term
                    ),

                    "eliminated_constant": (
                        eliminated_constant
                    ),

                    "semantic_source": (
                        operation.get(
                            "semantic_source"
                        )
                    ),

                    "last_teacher_question": (
                        last_teacher_question
                    ),
                },
            )

        # --------------------------------------------------------
        # OPÉRATION MATHÉMATIQUEMENT LÉGALE MAIS PAS
        # CLAIREMENT UTILE
        # --------------------------------------------------------

        if self._teacher_is_asking_next_resolution_step(
            last_teacher_question
        ):
            return ValidationResult(
                verdict="incorrect",
                confidence=0.95,
                method="reasoning_linear_transformation",

                normalized_student_answer=(
                    self.normalizer.normalize(
                        student_answer
                    )
                ),

                normalized_expected_answer=None,
                result_correct=None,
                reasoning_correct=False,

                error_type="non_progressing_operation",

                reason=(
                    "L'opération proposée peut préserver "
                    "l'équivalence de l'équation, mais elle ne "
                    "fait pas progresser l'objectif demandé à "
                    "cette étape."
                ),

                requires_review=False,

                details={
                    "equation": (
                        previous_equation
                    ),

                    "operation_type": (
                        operation_type
                    ),

                    "operand": (
                        self._format_linear_operand(
                            operand
                        )
                    ),

                    "effective_operand": (
                        self._format_linear_operand(
                            effective_operand
                        )
                    ),

                    "transformed_equation": (
                        transformed_text
                    ),

                    "complexity_before": (
                        before_score
                    ),

                    "complexity_after": (
                        after_score
                    ),

                    "semantic_source": (
                        operation.get(
                            "semantic_source"
                        )
                    ),

                    "last_teacher_question": (
                        last_teacher_question
                    ),
                },
            )

        return self._uncertain(
            student_answer,
            previous_equation,
            (
                "L'opération conserve potentiellement "
                "l'équivalence de l'équation, mais le contexte "
                "ne permet pas de prouver qu'il s'agit de la "
                "progression pédagogique attendue."
            )
        )

    # ============================================================
    # VALIDATION MULTIPLICATION / DIVISION
    # ============================================================

    def _validate_multiply_divide(
        self,
        student_answer,
        previous_equation,
        equation_info,
        operation,
        last_teacher_question,
    ):
        operation_type = operation[
            "type"
        ]

        scalar = operation.get(
            "scalar"
        )

        if scalar is None:
            return self._uncertain(
                student_answer,
                previous_equation,
                (
                    "La multiplication ou la division est "
                    "annoncée mais la valeur utilisée n'est "
                    "pas suffisamment explicite."
                )
            )

        # --------------------------------------------------------
        # DIVISION PAR ZÉRO
        # --------------------------------------------------------

        if (
            operation_type == "divide"
            and scalar == 0
        ):
            return ValidationResult(
                verdict="incorrect",
                confidence=1.0,
                method="reasoning_linear_transformation",

                normalized_student_answer=(
                    self.normalizer.normalize(
                        student_answer
                    )
                ),

                normalized_expected_answer=None,
                result_correct=None,
                reasoning_correct=False,

                error_type="division_by_zero",

                reason=(
                    "Il est impossible de diviser les deux "
                    "membres d'une équation par zéro."
                ),

                requires_review=False,

                details={
                    "equation": (
                        previous_equation
                    ),

                    "operation_type": (
                        operation_type
                    ),

                    "operation_value": "0",
                },
            )

        # --------------------------------------------------------
        # MULTIPLICATION PAR ZÉRO
        # --------------------------------------------------------

        if (
            operation_type == "multiply"
            and scalar == 0
        ):
            return ValidationResult(
                verdict="incorrect",
                confidence=1.0,
                method="reasoning_linear_transformation",

                normalized_student_answer=(
                    self.normalizer.normalize(
                        student_answer
                    )
                ),

                normalized_expected_answer=None,
                result_correct=None,
                reasoning_correct=False,

                error_type="multiply_equation_by_zero",

                reason=(
                    "Multiplier les deux membres par zéro "
                    "détruit l'information nécessaire pour "
                    "conserver une équation équivalente."
                ),

                requires_review=False,

                details={
                    "equation": (
                        previous_equation
                    ),

                    "operation_type": (
                        operation_type
                    ),

                    "operation_value": "0",
                },
            )

        # --------------------------------------------------------
        # FACTEUR EFFECTIF
        # --------------------------------------------------------

        if operation_type == "divide":
            factor = (
                Fraction(1, 1)
                / scalar
            )

        else:
            factor = scalar

        transformed = {
            "left_x": (
                equation_info["left_x"]
                * factor
            ),

            "left_constant": (
                equation_info["left_constant"]
                * factor
            ),

            "right_x": (
                equation_info["right_x"]
                * factor
            ),

            "right_constant": (
                equation_info["right_constant"]
                * factor
            ),
        }

        before_score = self._equation_complexity_score(
            equation_info
        )

        after_score = self._equation_complexity_score(
            transformed
        )

        transformed_text = (
            self._format_linear_equation(
                transformed
            )
        )

        # --------------------------------------------------------
        # CAS SPÉCIAL : a*x = b
        # --------------------------------------------------------

        simple_ax_b = (
            equation_info["left_x"] != 0
            and equation_info["left_constant"] == 0
            and equation_info["right_x"] == 0
        )

        if simple_ax_b:
            coefficient = (
                equation_info["left_x"]
            )

            expected_factor = (
                Fraction(1, 1)
                / coefficient
            )

            if factor == expected_factor:
                solution = (
                    equation_info[
                        "right_constant"
                    ]
                    / coefficient
                )

                return ValidationResult(
                    verdict="correct",
                    confidence=1.0,
                    method="reasoning_operation",

                    normalized_student_answer=(
                        self.normalizer.normalize(
                            student_answer
                        )
                    ),

                    normalized_expected_answer=(
                        f"diviser les deux membres par "
                        f"{self._fraction_to_text(coefficient)}"
                    ),

                    result_correct=None,
                    reasoning_correct=True,
                    error_type=None,

                    reason=(
                        "L'opération proposée isole correctement "
                        "x dans l'équation "
                        f"{previous_equation}."
                    ),

                    requires_review=False,

                    details={
                        "equation": (
                            previous_equation
                        ),

                        "operation_type": (
                            operation_type
                        ),

                        "operation_value": (
                            self._fraction_to_text(
                                scalar
                            )
                        ),

                        "effective_factor": (
                            self._fraction_to_text(
                                factor
                            )
                        ),

                        "expected_result": (
                            self._fraction_to_text(
                                solution
                            )
                        ),

                        "transformed_equation": (
                            transformed_text
                        ),

                        "last_teacher_question": (
                            last_teacher_question
                        ),
                    },
                )

            if self._teacher_is_asking_to_isolate_x(
                last_teacher_question
            ):
                return ValidationResult(
                    verdict="incorrect",
                    confidence=1.0,
                    method="reasoning_operation",

                    normalized_student_answer=(
                        self.normalizer.normalize(
                            student_answer
                        )
                    ),

                    normalized_expected_answer=(
                        f"diviser les deux membres par "
                        f"{self._fraction_to_text(coefficient)}"
                    ),

                    result_correct=None,
                    reasoning_correct=False,

                    error_type="wrong_operation_value",

                    reason=(
                        "L'opération proposée ne supprime pas "
                        "correctement le coefficient de x. "
                        "Dans "
                        f"{previous_equation}, le coefficient de "
                        "x est "
                        f"{self._fraction_to_text(coefficient)}."
                    ),

                    requires_review=False,

                    details={
                        "equation": (
                            previous_equation
                        ),

                        "operation_type": (
                            operation_type
                        ),

                        "operation_value": (
                            self._fraction_to_text(
                                scalar
                            )
                        ),

                        "expected_divisor": (
                            self._fraction_to_text(
                                coefficient
                            )
                        ),

                        "equivalent_multiplier": (
                            self._fraction_to_text(
                                Fraction(1, 1)
                                / coefficient
                            )
                        ),

                        "last_teacher_question": (
                            last_teacher_question
                        ),
                    },
                )

        # --------------------------------------------------------
        # TRANSFORMATION GÉNÉRALE
        # --------------------------------------------------------

        if after_score < before_score:
            return ValidationResult(
                verdict="correct",
                confidence=1.0,
                method="reasoning_linear_transformation",

                normalized_student_answer=(
                    self.normalizer.normalize(
                        student_answer
                    )
                ),

                normalized_expected_answer=None,
                result_correct=None,
                reasoning_correct=True,
                error_type=None,

                reason=(
                    "La multiplication ou division proposée "
                    "préserve l'équivalence de l'équation et "
                    "simplifie sa résolution."
                ),

                requires_review=False,

                details={
                    "equation": (
                        previous_equation
                    ),

                    "operation_type": (
                        operation_type
                    ),

                    "operation_value": (
                        self._fraction_to_text(
                            scalar
                        )
                    ),

                    "effective_factor": (
                        self._fraction_to_text(
                            factor
                        )
                    ),

                    "transformed_equation": (
                        transformed_text
                    ),

                    "complexity_before": (
                        before_score
                    ),

                    "complexity_after": (
                        after_score
                    ),

                    "last_teacher_question": (
                        last_teacher_question
                    ),
                },
            )

        # --------------------------------------------------------
        # Opération valide mais progression non démontrée
        # --------------------------------------------------------

        return self._uncertain(
            student_answer,
            previous_equation,
            (
                "L'opération proposée peut conserver "
                "l'équivalence de l'équation, mais le moteur "
                "ne peut pas démontrer qu'elle constitue une "
                "progression utile à cette étape."
            )
        )

    # ============================================================
    # ANALYSE D'UNE ÉQUATION LINÉAIRE
    # ============================================================

    def _parse_linear_equation(
        self,
        equation
    ):
        text = self.normalizer.normalize(
            equation
        )

        text = (
            text
            .replace(" ", "")
            .replace("×", "*")
        )

        if text.count("=") != 1:
            return None

        left_text, right_text = (
            text.split(
                "=",
                1
            )
        )

        left = self._parse_linear_side(
            left_text
        )

        right = self._parse_linear_side(
            right_text
        )

        if (
            left is None
            or right is None
        ):
            return None

        return {
            "left_x": (
                left["x"]
            ),

            "left_constant": (
                left["constant"]
            ),

            "right_x": (
                right["x"]
            ),

            "right_constant": (
                right["constant"]
            ),
        }

    def _parse_linear_side(
        self,
        expression
    ):
        """
        Transforme une expression linéaire en :

            coefficient de x
            constante

        Exemples :

            7x-5
            -> x=7, constante=-5

            4x+3
            -> x=4, constante=3

            -x+2
            -> x=-1, constante=2

            8
            -> x=0, constante=8
        """

        text = str(
            expression or ""
        )

        text = (
            text
            .replace(" ", "")
            .replace("*", "")
            .replace("−", "-")
            .replace("–", "-")
        )

        if not text:
            return None

        # --------------------------------------------------------
        # Transformation en suite de termes signés
        # --------------------------------------------------------

        if text[0] not in "+-":
            text = "+" + text

        terms = re.findall(
            r"[+-][^+-]+",
            text
        )

        if not terms:
            return None

        coefficient_x = Fraction(0)
        constant = Fraction(0)

        for term in terms:

            sign = (
                Fraction(-1)
                if term[0] == "-"
                else Fraction(1)
            )

            body = term[1:]

            if not body:
                return None

            # ----------------------------------------------------
            # TERME EN x
            # ----------------------------------------------------

            if "x" in body.lower():

                if body.lower().count("x") != 1:
                    return None

                coefficient_text = (
                    body.lower()
                    .replace("x", "")
                )

                if coefficient_text == "":
                    coefficient = Fraction(1)

                else:
                    try:
                        coefficient = Fraction(
                            coefficient_text
                        )

                    except Exception:
                        return None

                coefficient_x += (
                    sign
                    * coefficient
                )

            # ----------------------------------------------------
            # CONSTANTE
            # ----------------------------------------------------

            else:
                try:
                    value = Fraction(
                        body
                    )

                except Exception:
                    return None

                constant += (
                    sign
                    * value
                )

        return {
            "x": coefficient_x,
            "constant": constant,
        }

    # ============================================================
    # NORMALISATION SÉMANTIQUE
    # ============================================================

    def _normalize_semantic_text(
        self,
        text
    ):
        """
        Normalisation destinée à reconnaître les formulations
        mathématiques exprimées en français.

        Exemples :

            "l'opposé de -5"
            -> "l'oppose de -5"

            "J’ajoute l’opposé de 4"
            -> "j'ajoute l'oppose de 4"

        Les accents sont supprimés uniquement pour faciliter
        la reconnaissance linguistique.
        """

        text = str(
            text or ""
        ).lower()

        text = (
            text
            .replace("’", "'")
            .replace("−", "-")
            .replace("–", "-")
        )

        text = unicodedata.normalize(
            "NFKD",
            text
        )

        text = "".join(
            character
            for character in text
            if not unicodedata.combining(
                character
            )
        )

        text = re.sub(
            r"\s+",
            " ",
            text
        ).strip()

        return text

    # ============================================================
    # EXTRACTION DES OPÉRATIONS VERBALES
    # ============================================================

    def _extract_operation(
        self,
        text
    ):
        semantic_text = (
            self._normalize_semantic_text(
                text
            )
        )

        # ========================================================
        # CAS PRIORITAIRE : OPPOSÉ DE ...
        # ========================================================
        #
        # Exemples :
        #
        # ajouter l'opposé de -5
        # -> ajouter +5
        #
        # ajouter l'opposé de 4
        # -> ajouter -4
        #
        # soustraire l'opposé de -5
        # -> soustraire +5
        #
        # Cette règle doit être évaluée AVANT l'extraction
        # ordinaire des nombres.
        # ========================================================

        opposite_match = re.search(
            (
                r"\boppose\s+de\s+"
                r"([+-]?\d+(?:[.,]\d+)?(?:/\d+)?)"
            ),
            semantic_text,
            flags=re.IGNORECASE
        )

        if opposite_match:

            raw_value = (
                opposite_match
                .group(1)
                .replace(",", ".")
            )

            try:
                original_value = Fraction(
                    raw_value
                )

                opposite_value = (
                    -original_value
                )

            except Exception:
                original_value = None
                opposite_value = None

            if opposite_value is not None:

                if self._contains_addition_signal(
                    semantic_text
                ):
                    return {
                        "type": "add",

                        "operand": {
                            "x": Fraction(0),
                            "constant": opposite_value,
                        },

                        "semantic_source": (
                            "opposite"
                        ),

                        "original_value": (
                            original_value
                        ),

                        "resolved_value": (
                            opposite_value
                        ),
                    }

                if self._contains_subtraction_signal(
                    semantic_text
                ):
                    return {
                        "type": "subtract",

                        "operand": {
                            "x": Fraction(0),
                            "constant": opposite_value,
                        },

                        "semantic_source": (
                            "opposite"
                        ),

                        "original_value": (
                            original_value
                        ),

                        "resolved_value": (
                            opposite_value
                        ),
                    }

        # ========================================================
        # DIVISION
        # ========================================================

        division_match = re.search(
            (
                r"\b(?:divis(?:e|er|ons|ez|ant)?|division)"
                r".*?\bpar\s+"
                r"([+-]?\d+(?:[.,]\d+)?(?:/\d+)?)"
            ),
            semantic_text,
            flags=re.IGNORECASE
        )

        if division_match:

            scalar = self._to_fraction(
                division_match.group(1)
            )

            return {
                "type": "divide",
                "scalar": scalar,
            }

        if any(
            signal in semantic_text
            for signal in [
                "divise",
                "diviser",
                "division",
                "divisant",
            ]
        ):
            return {
                "type": "divide",
                "scalar": None,
            }

        # ========================================================
        # MULTIPLICATION
        # ========================================================

        multiplication_match = re.search(
            (
                r"\bmultipli(?:e|er|ons|ez|ant)?"
                r".*?\bpar\s+"
                r"([+-]?\d+(?:[.,]\d+)?(?:/\d+)?)"
            ),
            semantic_text,
            flags=re.IGNORECASE
        )

        if multiplication_match:

            scalar = self._to_fraction(
                multiplication_match.group(1)
            )

            return {
                "type": "multiply",
                "scalar": scalar,
            }

        if any(
            signal in semantic_text
            for signal in [
                "multiplie",
                "multiplier",
                "multiplication",
            ]
        ):
            return {
                "type": "multiply",
                "scalar": None,
            }

        # ========================================================
        # ADDITION
        # ========================================================

        if self._contains_addition_signal(
            semantic_text
        ):
            operand = (
                self._extract_linear_operand_after_operation(
                    semantic_text,
                    operation="add"
                )
            )

            if operand is not None:
                return {
                    "type": "add",
                    "operand": operand,
                }

            return {
                "type": "add",
                "operand": None,
            }

        # ========================================================
        # SOUSTRACTION
        # ========================================================

        if self._contains_subtraction_signal(
            semantic_text
        ):
            operand = (
                self._extract_linear_operand_after_operation(
                    semantic_text,
                    operation="subtract"
                )
            )

            if operand is not None:
                return {
                    "type": "subtract",
                    "operand": operand,
                }

            return {
                "type": "subtract",
                "operand": None,
            }

        return None

    def _contains_addition_signal(
        self,
        text
    ):
        signals = [
            "ajoute",
            "ajouter",
            "ajoutons",
            "additionne",
            "additionner",
            "addition",
        ]

        return any(
            signal in text
            for signal in signals
        )

    def _contains_subtraction_signal(
        self,
        text
    ):
        signals = [
            "soustrais",
            "soustraire",
            "soustraction",
            "retranche",
            "retrancher",
            "enleve",
            "enlever",
        ]

        return any(
            signal in text
            for signal in signals
        )

    def _extract_linear_operand_after_operation(
        self,
        text,
        operation,
    ):
        """
        Extrait par exemple :

            ajouter -4x
            -> -4x

            ajouter 5
            -> 5

            soustraire 4x
            -> 4x
        """

        if operation == "add":
            verbs = (
                r"(?:"
                r"ajout(?:e|er|ons|ez|ant)?"
                r"|additionn(?:e|er|ons|ez|ant)?"
                r")"
            )

        else:
            verbs = (
                r"(?:"
                r"soustrai(?:s|re|t|sons|yez|ant)?"
                r"|retranch(?:e|er|ons|ez|ant)?"
                r"|enlev(?:e|er|ons|ez|ant)?"
                r")"
            )

        pattern = (
            verbs
            + r".*?"
            + r"("
            + r"[+-]?"
            + r"(?:\d+(?:[.,]\d+)?(?:/\d+)?)?"
            + r"x"
            + r"|"
            + r"[+-]?\d+(?:[.,]\d+)?(?:/\d+)?"
            + r")"
        )

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE
        )

        if not match:
            return None

        raw_operand = (
            match.group(1)
            .replace(",", ".")
        )

        return self._parse_linear_operand(
            raw_operand
        )

    def _parse_linear_operand(
        self,
        value
    ):
        value = str(
            value or ""
        ).strip()

        value = (
            value
            .replace(" ", "")
            .replace("*", "")
        )

        # --------------------------------------------------------
        # TERME EN x
        # --------------------------------------------------------

        if value.lower().endswith(
            "x"
        ):
            coefficient_text = (
                value[:-1]
            )

            if coefficient_text in (
                "",
                "+"
            ):
                coefficient = Fraction(1)

            elif coefficient_text == "-":
                coefficient = Fraction(-1)

            else:
                try:
                    coefficient = Fraction(
                        coefficient_text
                    )

                except Exception:
                    return None

            return {
                "x": coefficient,
                "constant": Fraction(0),
            }

        # --------------------------------------------------------
        # CONSTANTE
        # --------------------------------------------------------

        try:
            constant = Fraction(
                value
            )

        except Exception:
            return None

        return {
            "x": Fraction(0),
            "constant": constant,
        }

    # ============================================================
    # MESURE DE PROGRESSION
    # ============================================================

    def _equation_complexity_score(
        self,
        equation
    ):
        """
        Score simple servant à déterminer si une opération
        réduit effectivement la complexité structurelle
        d'une équation linéaire.

        Ce score n'est PAS un diagnostic de l'élève.

        Plus le score est petit, plus l'équation est proche
        d'une forme isolée x = valeur.
        """

        left_x = equation[
            "left_x"
        ]

        left_constant = equation[
            "left_constant"
        ]

        right_x = equation[
            "right_x"
        ]

        right_constant = equation[
            "right_constant"
        ]

        score = 0

        # --------------------------------------------------------
        # x présent des deux côtés
        # --------------------------------------------------------

        if (
            left_x != 0
            and right_x != 0
        ):
            score += 4

        # --------------------------------------------------------
        # On identifie le côté principal contenant x.
        # --------------------------------------------------------

        if (
            left_x != 0
            and right_x == 0
        ):
            active_x = left_x
            active_constant = (
                left_constant
            )

        elif (
            right_x != 0
            and left_x == 0
        ):
            active_x = right_x
            active_constant = (
                right_constant
            )

        else:
            active_x = None
            active_constant = None

        # --------------------------------------------------------
        # constante encore attachée au côté contenant x
        # --------------------------------------------------------

        if (
            active_constant is not None
            and active_constant != 0
        ):
            score += 2

        # --------------------------------------------------------
        # coefficient de x différent de ±1
        # --------------------------------------------------------

        if (
            active_x is not None
            and abs(active_x) != 1
        ):
            score += 1

        return score

    # ============================================================
    # CONTEXTE PÉDAGOGIQUE
    # ============================================================

    def _teacher_is_asking_to_isolate_x(
        self,
        question
    ):
        text = self._normalize_semantic_text(
            question
        )

        signals = [
            "isoler x",
            "isoler la variable",
            "eliminer le coefficient",
            "coefficient de x",
            "quelle operation",
            "quel operation",
            "deux membres",
        ]

        return any(
            signal in text
            for signal in signals
        )

    def _teacher_is_asking_next_resolution_step(
        self,
        question
    ):
        text = self._normalize_semantic_text(
            question
        )

        signals = [
            "quelle operation",
            "quel operation",
            "prochaine operation",
            "prochaine etape",
            "que faire",
            "faire ensuite",
            "faire en premier",
            "continuer",
            "isoler x",
            "isoler la variable",
            "rassembler les termes",
            "rassembler les termes en x",
            "eliminer",
            "deux membres",
        ]

        return any(
            signal in text
            for signal in signals
        )

    # ============================================================
    # FORMATAGE
    # ============================================================

    def _format_linear_equation(
        self,
        equation
    ):
        left = self._format_linear_side(
            equation["left_x"],
            equation["left_constant"]
        )

        right = self._format_linear_side(
            equation["right_x"],
            equation["right_constant"]
        )

        return (
            f"{left} = {right}"
        )

    def _format_linear_side(
        self,
        coefficient_x,
        constant,
    ):
        pieces = []

        # --------------------------------------------------------
        # TERME EN x
        # --------------------------------------------------------

        if coefficient_x != 0:

            if coefficient_x == 1:
                pieces.append(
                    "x"
                )

            elif coefficient_x == -1:
                pieces.append(
                    "-x"
                )

            else:
                pieces.append(
                    (
                        f"{self._fraction_to_text(coefficient_x)}"
                        "*x"
                    )
                )

        # --------------------------------------------------------
        # CONSTANTE
        # --------------------------------------------------------

        if constant != 0:

            constant_text = (
                self._fraction_to_text(
                    abs(constant)
                )
            )

            if pieces:

                if constant > 0:
                    pieces.append(
                        f"+ {constant_text}"
                    )

                else:
                    pieces.append(
                        f"- {constant_text}"
                    )

            else:
                pieces.append(
                    self._fraction_to_text(
                        constant
                    )
                )

        if not pieces:
            return "0"

        return " ".join(
            pieces
        )

    def _format_linear_operand(
        self,
        operand
    ):
        if not operand:
            return None

        coefficient_x = operand.get(
            "x",
            Fraction(0)
        )

        constant = operand.get(
            "constant",
            Fraction(0)
        )

        return self._format_linear_side(
            coefficient_x,
            constant
        )

    # ============================================================
    # OUTILS
    # ============================================================

    def _to_fraction(
        self,
        value
    ):
        try:
            value = str(
                value
            ).replace(
                ",",
                "."
            )

            return Fraction(
                value
            )

        except Exception:
            return None

    def _fraction_to_text(
        self,
        value
    ):
        if value is None:
            return None

        if not isinstance(
            value,
            Fraction
        ):
            try:
                value = Fraction(
                    value
                )

            except Exception:
                return str(
                    value
                )

        if value.denominator == 1:
            return str(
                value.numerator
            )

        return (
            f"{value.numerator}/"
            f"{value.denominator}"
        )

    # ============================================================
    # UNCERTAIN
    # ============================================================

    def _uncertain(
        self,
        student_answer,
        previous_equation,
        reason
    ):
        return ValidationResult(
            verdict="uncertain",
            confidence=0.0,
            method="reasoning_operation",

            normalized_student_answer=(
                self.normalizer.normalize(
                    student_answer
                )
            ),

            normalized_expected_answer=None,
            result_correct=None,
            reasoning_correct=None,
            error_type=None,
            reason=reason,
            requires_review=True,

            details={
                "equation": (
                    previous_equation
                ),
            },
        )