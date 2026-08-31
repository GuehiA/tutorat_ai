from fractions import Fraction
import re

from services.validation_result import (
    ValidationResult
)

from services.answer_normalizer import (
    AnswerNormalizer
)

from services.reasoning_validator import (
    ReasoningValidator
)

from services.math_verification import (
    verifier_expression_fractionnaire,
    verifier_solution_equation_fractionnaire,
    verifier_resultat_expression_contextuelle,
    verifier_chaine_egalites_fractionnaire,
    verifier_equation_intermediaire_equivalente,
)


class ValidationEngine:
    """
    Point d'entrée unique pour la validation.

    Cette version prend en charge :
    - normalisation ;
    - comparaison exacte ;
    - comparaison numérique simple ;
    - raisonnement verbal sur une opération ;
    - solutions d'équations ;
    - transformations d'équations ;
    - chaînes d'égalités numériques ;
    - expressions fractionnaires ;
    - réponses numériques contextuelles ;
    - retour UNCERTAIN si aucune preuve fiable
      n'est disponible.

    IMPORTANT :
    UNCERTAIN != INCORRECT.

    Un échec technique ou une absence de preuve
    ne doit jamais être transformé en erreur élève.
    """

    def __init__(self):
        self.normalizer = AnswerNormalizer()

        self.reasoning_validator = (
            ReasoningValidator()
        )

    # ============================================================
    # API PUBLIQUE
    # ============================================================

    def validate(
        self,
        student_answer,
        expected_answer=None,
        question=None,
        answer_type=None,
        previous_equation=None,
        last_teacher_question=None,
    ):
        """
        Valide une réponse élève.

        Principe de routage :

        1. réponse vide ;
        2. comparaison exacte ;
        3. comparaison numérique ;
        4. raisonnement verbal ;
        5. solution d'équation ;
        6. équation intermédiaire ;
        7. chaîne d'égalités ;
        8. expression numérique ;
        9. réponse contextuelle ;
        10. second essai du ReasoningValidator ;
        11. UNCERTAIN.

        IMPORTANT :
        UNCERTAIN != INCORRECT.
        """

        student = self.normalizer.normalize(
            student_answer
        )

        expected = self.normalizer.normalize(
            expected_answer
        )

        previous_equation_normalized = (
            self.normalizer.normalize(
                previous_equation
            )
        )

        question_normalized = (
            self.normalizer.normalize(
                question
            )
        )

        # --------------------------------------------------------
        # 1. RÉPONSE VIDE
        # --------------------------------------------------------

        if not student:
            return ValidationResult(
                verdict="uncertain",
                confidence=0.0,
                method="empty_answer",
                normalized_student_answer=student,
                normalized_expected_answer=expected,
                result_correct=None,
                reasoning_correct=None,
                reason="Réponse élève vide.",
                requires_review=True,
            )

        # --------------------------------------------------------
        # 2. COMPARAISON EXACTE
        # --------------------------------------------------------

        if expected and student == expected:
            return ValidationResult(
                verdict="correct",
                confidence=1.0,
                method="exact_match",
                normalized_student_answer=student,
                normalized_expected_answer=expected,
                result_correct=True,
                reasoning_correct=None,
                reason=(
                    "La réponse normalisée correspond "
                    "exactement à la réponse attendue."
                ),
                requires_review=False,
            )

        # --------------------------------------------------------
        # 3. COMPARAISON NUMÉRIQUE / FRACTIONNAIRE SIMPLE
        # --------------------------------------------------------

        if expected:
            numeric_result = (
                self._validate_numeric_equivalence(
                    student,
                    expected
                )
            )

            if numeric_result is not None:
                return numeric_result

        # --------------------------------------------------------
        # RÉFÉRENCE D'ÉQUATION
        # --------------------------------------------------------

        equation_reference = (
            previous_equation_normalized
            or question_normalized
            or expected
            or ""
        )

        reasoning_attempted = False

        # --------------------------------------------------------
        # 4. RAISONNEMENT VERBAL SUR UNE OPÉRATION
        # --------------------------------------------------------
        #
        # Exemple :
        #
        # équation précédente :
        #     3*x-5=-2*x+10
        #
        # élève :
        #     ajouter 2x aux deux membres
        #
        # On veut que ReasoningValidator puisse conclure
        # AVANT le LLM.
        # --------------------------------------------------------

        if (
            equation_reference
            and "=" in equation_reference
            and self._contains_variable(
                equation_reference
            )
            and self._looks_like_reasoning_operation(
                student_answer
            )
        ):
            reasoning_attempted = True

            try:
                reasoning_result = (
                    self.reasoning_validator.validate(
                        student_answer=student_answer,
                        previous_equation=(
                            equation_reference
                        ),
                        last_teacher_question=(
                            last_teacher_question
                        ),
                    )
                )

                if reasoning_result.verdict in {
                    "correct",
                    "incorrect"
                }:
                    return reasoning_result

            except Exception:
                # Une erreur interne du validateur de raisonnement
                # ne doit jamais être transformée en erreur élève.
                pass

        # --------------------------------------------------------
        # 5. SOLUTION D'ÉQUATION
        # --------------------------------------------------------

        if (
            equation_reference
            and "=" in equation_reference
            and self._contains_variable(
                equation_reference
            )
            and re.search(
                r"\bx\s*=",
                student,
                flags=re.IGNORECASE
            )
        ):
            try:
                result = (
                    verifier_solution_equation_fractionnaire(
                        equation_initiale=(
                            equation_reference
                        ),
                        reponse_eleve=student,
                    )
                )

                if result.get(
                    "verification_contextuelle"
                ):
                    return self._from_legacy_result(
                        result=result,
                        method="equation_solution",
                        student=student,
                        expected=expected,
                    )

            except Exception:
                # Une erreur technique ne devient jamais
                # une erreur de l'élève.
                pass

        # --------------------------------------------------------
        # 6. ÉQUATION INTERMÉDIAIRE
        # --------------------------------------------------------

        if (
            previous_equation_normalized
            and "=" in student
            and self._contains_variable(
                student
            )
        ):
            try:
                result = (
                    verifier_equation_intermediaire_equivalente(
                        equation_initiale=(
                            previous_equation_normalized
                        ),
                        reponse_eleve=student,
                    )
                )

                if result.get(
                    "verification_equation_intermediaire"
                ):
                    return self._from_legacy_result(
                        result=result,
                        method="equation_equivalence",
                        student=student,
                        expected=expected,
                    )

            except Exception:
                pass

        # --------------------------------------------------------
        # 7. CHAÎNE D'ÉGALITÉS NUMÉRIQUES
        # --------------------------------------------------------

        if (
            "=" in student
            and not self._contains_variable(
                student
            )
        ):
            try:
                result = (
                    verifier_chaine_egalites_fractionnaire(
                        texte=student,
                        objectif_initial=(
                            question or ""
                        ),
                    )
                )

                if result.get(
                    "verification_chaine"
                ):
                    return self._from_legacy_result(
                        result=result,
                        method="numeric_equality_chain",
                        student=student,
                        expected=expected,
                    )

            except Exception:
                pass

        # --------------------------------------------------------
        # 8. ÉGALITÉ NUMÉRIQUE SIMPLE
        # --------------------------------------------------------

        if (
            "=" in student
            and not self._contains_variable(
                student
            )
        ):
            try:
                result = (
                    verifier_expression_fractionnaire(
                        student
                    )
                )

                if result.get(
                    "calcul_verifie"
                ):
                    return self._from_legacy_result(
                        result=result,
                        method="fraction_expression",
                        student=student,
                        expected=expected,
                    )

            except Exception:
                pass

        # --------------------------------------------------------
        # 9. RÉPONSE NUMÉRIQUE CONTEXTUELLE
        # --------------------------------------------------------

        if (
            question
            and not self._contains_variable(
                question
            )
        ):
            try:
                result = (
                    verifier_resultat_expression_contextuelle(
                        objectif_initial=question,
                        reponse_eleve=student,
                    )
                )

                if result.get(
                    "verification_contextuelle"
                ):
                    return self._from_legacy_result(
                        result=result,
                        method="contextual_numeric",
                        student=student,
                        expected=expected,
                    )

            except Exception:
                pass

        # --------------------------------------------------------
        # 10. FALLBACK RAISONNEMENT
        # --------------------------------------------------------
        #
        # Même si la détection lexicale n'a pas reconnu
        # explicitement une opération, ReasoningValidator
        # peut encore tenter une dernière validation.
        #
        # Un verdict uncertain reste uncertain.
        # --------------------------------------------------------

        if (
            not reasoning_attempted
            and equation_reference
            and "=" in equation_reference
            and self._contains_variable(
                equation_reference
            )
        ):
            try:
                reasoning_result = (
                    self.reasoning_validator.validate(
                        student_answer=student_answer,
                        previous_equation=(
                            equation_reference
                        ),
                        last_teacher_question=(
                            last_teacher_question
                        ),
                    )
                )

                if reasoning_result.verdict in {
                    "correct",
                    "incorrect"
                }:
                    return reasoning_result

            except Exception:
                pass

        # --------------------------------------------------------
        # 11. AUCUNE PREUVE SUFFISANTE
        # --------------------------------------------------------

        return ValidationResult(
            verdict="uncertain",
            confidence=0.0,
            method="no_deterministic_conclusion",
            normalized_student_answer=student,
            normalized_expected_answer=expected,
            result_correct=None,
            reasoning_correct=None,
            reason=(
                "Aucun validateur déterministe n'a pu "
                "conclure avec suffisamment de certitude."
            ),
            requires_review=True,
        )

    # ============================================================
    # DÉTECTION D'UNE OPÉRATION VERBALE
    # ============================================================

    def _looks_like_reasoning_operation(
        self,
        text
    ):
        """
        Détecte prudemment si la réponse semble annoncer
        une opération algébrique.

        Cette méthode sert UNIQUEMENT au routage vers
        ReasoningValidator.

        Elle ne décide jamais si l'opération est correcte.

        Exemples :

            ajouter 2x aux deux membres

            je soustrais 4x

            diviser les deux côtés par 5

            multiplier chaque membre par 1/3

            ajouter l'opposé de -5
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

        operation_patterns = [

            # Addition
            r"\bajout(?:e|er|ons|ez|ant)?\b",
            r"\badditionn(?:e|er|ons|ez|ant)?\b",

            # Soustraction
            r"\bsoustrai(?:s|re|t|sons|yez|ant)?\b",
            r"\bretranch(?:e|er|ons|ez|ant)?\b",
            r"\benlev(?:e|er|ons|ez|ant)?\b",

            # Division
            r"\bdivis(?:e|er|ons|ez|ant|ion)?\b",

            # Multiplication
            r"\bmultipli(?:e|er|ons|ez|ant|cation)?\b",

            # Opposé
            r"\boppose\s+de\b",
            r"\bopposé\s+de\b",
        ]

        return any(
            re.search(
                pattern,
                text,
                flags=re.IGNORECASE
            )
            for pattern in operation_patterns
        )

    # ============================================================
    # DÉTECTION DE VARIABLE
    # ============================================================

    def _contains_variable(
        self,
        text
    ):
        """
        Détermine prudemment si une expression semble
        contenir une variable mathématique.

        Exemples :

            x=3

            2x+4=10

            3*y=12
        """

        text = str(
            text or ""
        )

        return bool(
            re.search(
                r"(?<![A-Za-zÀ-ÿ])[xyz](?![A-Za-zÀ-ÿ])",
                text,
                flags=re.IGNORECASE,
            )
            or re.search(
                r"\d\s*\*?\s*[xyz]\b",
                text,
                flags=re.IGNORECASE,
            )
        )

    # ============================================================
    # PARSING D'UN NOMBRE SIMPLE
    # ============================================================

    def _parse_simple_number(
        self,
        value
    ):
        """
        Convertit une représentation numérique simple
        en Fraction.

        Exemples :

            3
            -2
            0.5
            1/2
            -3/4

        Retourne None lorsque la chaîne n'est pas
        un nombre suffisamment simple.
        """

        value = str(
            value or ""
        ).strip()

        # --------------------------------------------------------
        # ENTIER OU DÉCIMAL
        # --------------------------------------------------------

        if re.fullmatch(
            r"[-+]?\d+(?:\.\d+)?",
            value
        ):
            try:
                return Fraction(
                    value
                )

            except Exception:
                return None

        # --------------------------------------------------------
        # FRACTION
        # --------------------------------------------------------

        if re.fullmatch(
            r"[-+]?\d+\s*/\s*[-+]?\d+",
            value
        ):
            try:
                numerator, denominator = (
                    value.split(
                        "/",
                        1
                    )
                )

                numerator_fraction = Fraction(
                    numerator.strip()
                )

                denominator_fraction = Fraction(
                    denominator.strip()
                )

                if denominator_fraction == 0:
                    return None

                return (
                    numerator_fraction
                    /
                    denominator_fraction
                )

            except Exception:
                return None

        return None

    # ============================================================
    # COMPARAISON NUMÉRIQUE
    # ============================================================

    def _validate_numeric_equivalence(
        self,
        student,
        expected,
    ):
        """
        Compare deux valeurs numériques simples
        de manière exacte.

        Exemple :

            1/2 == 0.5

            2/4 == 1/2

        Fraction permet d'éviter les erreurs
        d'arrondi flottant.
        """

        try:
            student_value = (
                self._parse_simple_number(
                    student
                )
            )

            expected_value = (
                self._parse_simple_number(
                    expected
                )
            )

            if (
                student_value is None
                or expected_value is None
            ):
                return None

            # ----------------------------------------------------
            # VALEURS ÉQUIVALENTES
            # ----------------------------------------------------

            if student_value == expected_value:
                return ValidationResult(
                    verdict="correct",
                    confidence=1.0,
                    method="numeric_equivalence",
                    normalized_student_answer=student,
                    normalized_expected_answer=expected,
                    result_correct=True,
                    reasoning_correct=None,
                    reason=(
                        "Les deux écritures représentent "
                        "exactement la même valeur."
                    ),
                    requires_review=False,
                    details={
                        "student_value": str(
                            student_value
                        ),
                        "expected_value": str(
                            expected_value
                        ),
                    },
                )

            # ----------------------------------------------------
            # VALEURS DIFFÉRENTES
            # ----------------------------------------------------

            return ValidationResult(
                verdict="incorrect",
                confidence=1.0,
                method="numeric_equivalence",
                normalized_student_answer=student,
                normalized_expected_answer=expected,
                result_correct=False,
                reasoning_correct=None,
                error_type="wrong_numeric_value",
                reason=(
                    "Les deux valeurs numériques sont "
                    "différentes."
                ),
                requires_review=False,
                details={
                    "student_value": str(
                        student_value
                    ),
                    "expected_value": str(
                        expected_value
                    ),
                },
            )

        except Exception:
            return None

    # ============================================================
    # CONVERSION DES ANCIENS VALIDATEURS
    # ============================================================

    def _from_legacy_result(
        self,
        result,
        method,
        student,
        expected,
    ):
        """
        Convertit les dictionnaires produits par
        math_verification.py en ValidationResult.
        """

        correct = result.get(
            "est_correct"
        )

        if correct is True:
            verdict = "correct"
            confidence = 1.0

        elif correct is False:
            verdict = "incorrect"
            confidence = 1.0

        else:
            verdict = "uncertain"
            confidence = 0.0

        return ValidationResult(
            verdict=verdict,
            confidence=confidence,
            method=method,
            normalized_student_answer=student,
            normalized_expected_answer=expected,
            result_correct=correct,
            reasoning_correct=None,
            error_type=(
                None
                if correct is not False
                else self._infer_legacy_error_type(
                    method
                )
            ),
            reason=result.get(
                "message_interne"
            ),
            requires_review=(
                verdict == "uncertain"
            ),
            details=result,
        )

    # ============================================================
    # TYPE D'ERREUR LEGACY
    # ============================================================

    def _infer_legacy_error_type(
        self,
        method
    ):
        """
        Fournit un type d'erreur minimal pour les anciens
        validateurs déterministes.
        """

        mapping = {
            "equation_solution":
                "wrong_equation_solution",

            "equation_equivalence":
                "non_equivalent_equation",

            "numeric_equality_chain":
                "wrong_equality_chain",

            "fraction_expression":
                "wrong_numeric_expression",

            "contextual_numeric":
                "wrong_contextual_result",
        }

        return mapping.get(
            method,
            "deterministic_math_error"
        )