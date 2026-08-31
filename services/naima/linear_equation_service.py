from __future__ import annotations

import re
from typing import Any, Dict, Optional

from services.reasoning_validator import (
    ReasoningValidator,
)

from services.validation_engine import (
    ValidationEngine,
)

from services.validation_result import (
    ValidationResult,
)


class LinearEquationService:
    """
    Adaptateur Naima v2 pour les équations linéaires.

    Ce service conserve ValidationEngine comme moteur
    déterministe principal.

    Il ajoute toutefois un arbitrage important entre :

        - le résultat mathématique final ;
        - le raisonnement verbal annoncé.

    Exemple :

        équation :
            3*x = 5

        élève :
            "je divise les deux membres par 2
             et j'obtiens x=5/3"

    Le résultat x=5/3 est correct.

    Mais la division par 2 est incorrecte.

    Le résultat global doit donc devenir :

        verdict = correct
        result_correct = True
        reasoning_correct = False
        method = equation_solution_reasoning_conflict

    L'exercice ne doit pas être considéré comme terminé
    pédagogiquement tant que le raisonnement n'est pas corrigé.
    """

    def __init__(
        self,
        *,
        validation_engine: Optional[
            ValidationEngine
        ] = None,
        reasoning_validator: Optional[
            ReasoningValidator
        ] = None,
    ):

        self.validation_engine = (
            validation_engine
            or ValidationEngine()
        )

        self.reasoning_validator = (
            reasoning_validator
            or ReasoningValidator()
        )

    # ==========================================================
    # UTILITAIRES DE LECTURE
    # ==========================================================

    @staticmethod
    def _validation_value(
        validation: Any,
        name: str,
        default: Any = None,
    ) -> Any:
        """
        Lit un champ depuis :

        - ValidationResult ;
        - dict ;
        - objet compatible.
        """

        if validation is None:
            return default

        if isinstance(
            validation,
            dict,
        ):
            return validation.get(
                name,
                default,
            )

        return getattr(
            validation,
            name,
            default,
        )

    @staticmethod
    def _validation_to_dict(
        validation: Any,
    ) -> Dict[str, Any]:
        """
        Convertit prudemment une validation
        en dictionnaire.
        """

        if validation is None:
            return {}

        if isinstance(
            validation,
            dict,
        ):
            return dict(
                validation
            )

        if hasattr(
            validation,
            "to_dict",
        ):
            try:
                return (
                    validation.to_dict()
                )
            except Exception:
                return {}

        return {
            "verdict": getattr(
                validation,
                "verdict",
                None,
            ),
            "confidence": getattr(
                validation,
                "confidence",
                None,
            ),
            "method": getattr(
                validation,
                "method",
                None,
            ),
            "result_correct": getattr(
                validation,
                "result_correct",
                None,
            ),
            "reasoning_correct": getattr(
                validation,
                "reasoning_correct",
                None,
            ),
            "error_type": getattr(
                validation,
                "error_type",
                None,
            ),
        }

    # ==========================================================
    # EXTRACTION DE x=...
    # ==========================================================

    def _extract_x_solution(
        self,
        student_answer: str,
    ) -> Optional[str]:
        """
        Extrait une solution finale explicite de type x=...

        Exemples :

            x=5/3
                -> x=5/3

            j'obtiens x=5/3
                -> x=5/3

            x=-7/4
                -> x=-7/4

            x=2
                -> x=2

            x=-1.5
                -> x=-1.5

        IMPORTANT :
        les fractions sont testées AVANT les nombres simples.

        Cela évite :

            x=5/3
                -> x=5     ❌

        et garantit :

            x=5/3
                -> x=5/3   ✅
        """

        if not student_answer:
            return None

        text = str(
            student_answer
        )

        text = (
            text
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
        )

        # ------------------------------------------------------
        # FRACTION AVANT DÉCIMAL / ENTIER
        # ------------------------------------------------------

        pattern = (
            r"\bx\s*=\s*"
            r"("
            r"[+\-]?"
            r"(?:"
            r"\d+\s*/\s*[+\-]?\d+"
            r"|"
            r"\d+(?:[.,]\d+)?"
            r")"
            r")"
        )

        matches = re.findall(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if not matches:
            return None

        value = (
            matches[-1]
            .replace(
                ",",
                ".",
            )
            .replace(
                " ",
                "",
            )
            .strip()
        )

        if not value:
            return None

        return (
            f"x={value}"
        )

    # ==========================================================
    # APPEL CENTRAL À VALIDATION ENGINE
    # ==========================================================

    def _validate_with_engine(
        self,
        *,
        student_answer: str,
        equation: str,
        teacher_question: str,
        expected_answer: Any,
        reference_question: str,
        answer_type: Optional[str],
    ):

        return (
            self.validation_engine.validate(

                student_answer=(
                    student_answer
                ),

                expected_answer=(
                    expected_answer
                ),

                question=(
                    reference_question
                ),

                answer_type=(
                    answer_type
                ),

                previous_equation=(
                    equation
                ),

                last_teacher_question=(
                    teacher_question
                ),
            )
        )

    # ==========================================================
    # VALIDATION INDÉPENDANTE DU RAISONNEMENT
    # ==========================================================

    def _validate_reasoning(
        self,
        *,
        student_answer: str,
        equation: str,
        teacher_question: str,
    ):

        try:

            return (
                self.reasoning_validator.validate(

                    student_answer=(
                        student_answer
                    ),

                    previous_equation=(
                        equation
                    ),

                    last_teacher_question=(
                        teacher_question
                    ),
                )
            )

        except Exception:

            # Une erreur technique ne devient jamais
            # une erreur de l'élève.
            return None

    # ==========================================================
    # CONSTRUCTION DU CONFLIT
    # ==========================================================

    def _build_reasoning_conflict_if_needed(
        self,
        *,
        student_answer: str,
        equation: str,
        extracted_solution: Optional[str],
        result_validation: Any,
        reasoning_validation: Any,
        main_validation: Any,
    ) -> Optional[ValidationResult]:
        """
        Construit :

            equation_solution_reasoning_conflict

        seulement si deux faits indépendants sont prouvés :

            1. résultat final correct ;
            2. raisonnement incorrect.
        """

        if not extracted_solution:
            return None

        # ======================================================
        # 1. PREUVE DU RÉSULTAT
        # ======================================================

        result_verdict = (
            self._validation_value(
                result_validation,
                "verdict",
                "uncertain",
            )
            or "uncertain"
        )

        result_confidence = float(
            self._validation_value(
                result_validation,
                "confidence",
                0.0,
            )
            or 0.0
        )

        result_correct_field = (
            self._validation_value(
                result_validation,
                "result_correct",
                None,
            )
        )

        result_is_proved_correct = bool(
            result_verdict
            == "correct"
            and result_confidence
            >= 0.95
            and result_correct_field
            is not False
        )

        if not result_is_proved_correct:

            return None

        # ======================================================
        # 2. PREUVE DU RAISONNEMENT INCORRECT
        # ======================================================

        reasoning_verdict = (
            self._validation_value(
                reasoning_validation,
                "verdict",
                "uncertain",
            )
            or "uncertain"
        )

        reasoning_confidence = float(
            self._validation_value(
                reasoning_validation,
                "confidence",
                0.0,
            )
            or 0.0
        )

        reasoning_correct_field = (
            self._validation_value(
                reasoning_validation,
                "reasoning_correct",
                None,
            )
        )

        reasoning_error_type = (
            self._validation_value(
                reasoning_validation,
                "error_type",
                None,
            )
        )

        reasoning_is_proved_wrong = bool(
            reasoning_verdict
            == "incorrect"
            and reasoning_confidence
            >= 0.95
            and reasoning_correct_field
            is False
        )

        # ======================================================
        # 3. SECOURS :
        # LA VALIDATION PRINCIPALE PEUT AUSSI PORTER LA PREUVE
        # ======================================================

        if not reasoning_is_proved_wrong:

            main_verdict = (
                self._validation_value(
                    main_validation,
                    "verdict",
                    "uncertain",
                )
                or "uncertain"
            )

            main_confidence = float(
                self._validation_value(
                    main_validation,
                    "confidence",
                    0.0,
                )
                or 0.0
            )

            main_reasoning_correct = (
                self._validation_value(
                    main_validation,
                    "reasoning_correct",
                    None,
                )
            )

            if (
                main_verdict
                == "incorrect"
                and main_confidence
                >= 0.95
                and main_reasoning_correct
                is False
            ):

                reasoning_is_proved_wrong = (
                    True
                )

                reasoning_error_type = (
                    self._validation_value(
                        main_validation,
                        "error_type",
                        reasoning_error_type,
                    )
                )

        if not reasoning_is_proved_wrong:

            return None

        # ======================================================
        # 4. CONFLIT DÉMONTRÉ
        # ======================================================

        return ValidationResult(

            verdict="correct",

            confidence=1.0,

            method=(
                "equation_solution_reasoning_conflict"
            ),

            normalized_student_answer=(
                student_answer
            ),

            normalized_expected_answer=(
                extracted_solution
            ),

            result_correct=True,

            reasoning_correct=False,

            error_type=(
                reasoning_error_type
                or (
                    "correct_result_wrong_reasoning_operation"
                )
            ),

            reason=(
                "La valeur finale proposée pour x est "
                "mathématiquement correcte, mais "
                "l'opération ou le raisonnement annoncé "
                "par l'élève est incorrect."
            ),

            requires_review=False,

            details={

                "equation": (
                    equation
                ),

                "solution_extraite": (
                    extracted_solution
                ),

                "resultat_correct_raisonnement_incorrect": (
                    True
                ),

                "validation_resultat": (
                    self._validation_to_dict(
                        result_validation
                    )
                ),

                "validation_raisonnement": (
                    self._validation_to_dict(
                        reasoning_validation
                    )
                ),

                "validation_principale": (
                    self._validation_to_dict(
                        main_validation
                    )
                ),
            },
        )

    # ==========================================================
    # API PUBLIQUE
    # ==========================================================

    def validate(
        self,
        *,
        student_answer: str,
        equation: str,
        teacher_question: str = "",
        expected_answer: Any = None,
        question: Optional[str] = None,
        answer_type: Optional[str] = None,
        **kwargs,
    ):
        """
        Validation complète d'une réponse linéaire.

        Ordre :

            1. validation de la phrase complète ;
            2. validation indépendante du raisonnement ;
            3. extraction éventuelle de x=... ;
            4. validation du résultat final isolé ;
            5. arbitrage résultat/raisonnement ;
            6. sinon retour de la meilleure preuve.
        """

        reference_question = (
            question
            if question is not None
            else equation
        )

        # ======================================================
        # 1. VALIDATION DE LA PHRASE COMPLÈTE
        # ======================================================

        main_validation = (
            self._validate_with_engine(

                student_answer=(
                    student_answer
                ),

                equation=(
                    equation
                ),

                teacher_question=(
                    teacher_question
                ),

                expected_answer=(
                    expected_answer
                ),

                reference_question=(
                    reference_question
                ),

                answer_type=(
                    answer_type
                ),
            )
        )

        # ======================================================
        # 2. VALIDATION DU RAISONNEMENT VERBAL
        # ======================================================

        reasoning_validation = (
            self._validate_reasoning(

                student_answer=(
                    student_answer
                ),

                equation=(
                    equation
                ),

                teacher_question=(
                    teacher_question
                ),
            )
        )

        # ======================================================
        # 3. EXTRACTION DE LA SOLUTION x=...
        # ======================================================

        extracted_solution = (
            self._extract_x_solution(
                student_answer
            )
        )

        # Pas de solution finale explicite :
        # le moteur historique reste l'autorité.
        if not extracted_solution:

            return (
                main_validation
            )

        # ======================================================
        # 4. VALIDATION DU RÉSULTAT SEUL
        # ======================================================

        result_validation = (
            self._validate_with_engine(

                student_answer=(
                    extracted_solution
                ),

                equation=(
                    equation
                ),

                teacher_question=(
                    teacher_question
                ),

                expected_answer=None,

                reference_question=(
                    reference_question
                ),

                answer_type=(
                    answer_type
                ),
            )
        )

        # ======================================================
        # 5. CONFLIT RÉSULTAT / RAISONNEMENT
        # ======================================================

        conflict_validation = (
            self._build_reasoning_conflict_if_needed(

                student_answer=(
                    student_answer
                ),

                equation=(
                    equation
                ),

                extracted_solution=(
                    extracted_solution
                ),

                result_validation=(
                    result_validation
                ),

                reasoning_validation=(
                    reasoning_validation
                ),

                main_validation=(
                    main_validation
                ),
            )
        )

        if conflict_validation is not None:

            return (
                conflict_validation
            )

        # ======================================================
        # 6. SOLUTION FINALE CORRECTE SANS CONFLIT
        # ======================================================

        result_verdict = (
            self._validation_value(
                result_validation,
                "verdict",
                "uncertain",
            )
            or "uncertain"
        )

        result_confidence = float(
            self._validation_value(
                result_validation,
                "confidence",
                0.0,
            )
            or 0.0
        )

        if (
            result_verdict
            == "correct"
            and result_confidence
            >= 0.95
        ):

            return (
                result_validation
            )

        # ======================================================
        # 7. SINON :
        # RETOUR DE LA VALIDATION PRINCIPALE
        # ======================================================

        return (
            main_validation
        )