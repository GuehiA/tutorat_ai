from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class ProblemLifecycleDecision:
    """
    Décision générique sur le cycle de vie
    du problème courant.

    Cette structure ne connaît :
    - ni le domaine ;
    - ni le contenu de l'énoncé ;
    - ni le nom des objets ;
    - ni la variable utilisée.

    Elle s'appuie uniquement sur le niveau de preuve
    produit par le moteur de validation.
    """

    status: str

    keep_problem_open: bool
    objective_reached: bool

    exercise_closed: bool
    accept_new_problem: bool

    next_action: Optional[str]

    reason: str

    details: Dict[str, Any]

    def to_dict(
        self,
    ) -> Dict[str, Any]:

        return {
            "status": self.status,

            "keep_problem_open": (
                self.keep_problem_open
            ),

            "objective_reached": (
                self.objective_reached
            ),

            "exercise_closed": (
                self.exercise_closed
            ),

            "accept_new_problem": (
                self.accept_new_problem
            ),

            "next_action": (
                self.next_action
            ),

            "reason": self.reason,

            "details": dict(
                self.details
                or {}
            ),
        }


def resolve_problem_lifecycle(
    *,
    validation: Optional[
        Dict[str, Any]
    ],

    current_problem_active: bool,

    final_target_required: bool,
) -> ProblemLifecycleDecision:
    """
    Décide si le problème courant :

        - reste ouvert ;
        - a terminé un sous-objectif ;
        - est complètement résolu ;
        - accepte immédiatement un nouvel exercice.

    Principe fondamental :

        réponse correcte localement
                !=
        problème complètement terminé

    Lorsque final_target_required=True, une simple solution
    algébrique ne peut jamais fermer le problème.

    Exemple générique :

        problème verbal
            ↓
        modèle
            ↓
        solution algébrique
            ↓
        interprétation / cible finale
            ↓
        fermeture

    Aucune particularisation par domaine n'est utilisée.
    """

    validation = dict(
        validation
        or {}
    )

    verdict = (
        validation.get(
            "verdict"
        )
        or ""
    )

    method = (
        validation.get(
            "method"
        )
        or ""
    )

    result_correct = (
        validation.get(
            "result_correct"
        )
    )

    details = dict(
        validation.get(
            "details"
        )
        or {}
    )

    # ========================================================
    # 1. AUCUN PROBLÈME ACTIF
    # ========================================================

    if not current_problem_active:

        return ProblemLifecycleDecision(
            status="idle",

            keep_problem_open=False,

            objective_reached=False,

            exercise_closed=False,

            accept_new_problem=True,

            next_action=(
                "new_exercise"
            ),

            reason=(
                "no_active_problem"
            ),

            details={},
        )

    # ========================================================
    # 2. PREUVE EXPLICITE DE CIBLE FINALE
    # ========================================================
    #
    # Les validateurs futurs pourront poser directement :
    #
    #     details["final_target_proved"] = True
    #
    # Cela devient la règle générique privilégiée.
    # ========================================================

    explicit_final_target_proved = bool(
        verdict == "correct"
        and result_correct is True
        and details.get(
            "final_target_proved"
        )
        is True
    )

    if explicit_final_target_proved:

        return ProblemLifecycleDecision(
            status="closed",

            keep_problem_open=False,

            objective_reached=True,

            exercise_closed=True,

            accept_new_problem=True,

            next_action=(
                "new_exercise"
            ),

            reason=(
                "final_target_proved"
            ),

            details={
                "validation_method": method,
                "proof_source": (
                    "explicit_final_target"
                ),
            },
        )

    # ========================================================
    # 3. MÉTHODES FINALES DÉJÀ EXISTANTES
    # ========================================================
    #
    # Compatibilité avec l'architecture actuelle.
    #
    # À terme, tous ces validateurs pourront simplement poser :
    #
    #     final_target_proved = True
    #
    # et cette liste pourra disparaître.
    # ========================================================

    contextual_final_methods = {
        "direct_verbal_final_answer",
        "verbal_problem_final_answer",
    }

    algebraic_final_methods = {
        "equation_solution",
        "quadratic_solution_set",
        "inequality_solution",
        "final_solution",
    }

    # ========================================================
    # 4. PROBLÈME AVEC CIBLE FINALE CONTEXTUELLE
    # ========================================================
    #
    # Exemple :
    #
    # une solution algébrique x=...
    # peut être correcte sans répondre encore
    # à la question du problème.
    #
    # Dans ce contexte, seules les validations finales
    # contextuelles peuvent fermer le problème.
    # ========================================================

    if final_target_required:

        contextual_final_proof = bool(
            verdict == "correct"
            and result_correct is True
            and method
            in contextual_final_methods
        )

        if contextual_final_proof:

            return ProblemLifecycleDecision(
                status="closed",

                keep_problem_open=False,

                objective_reached=True,

                exercise_closed=True,

                accept_new_problem=True,

                next_action=(
                    "new_exercise"
                ),

                reason=(
                    "contextual_final_target_proved"
                ),

                details={
                    "validation_method": (
                        method
                    ),
                    "proof_source": (
                        "contextual_final_validation"
                    ),
                },
            )

        # ----------------------------------------------------
        # Solution algébrique obtenue mais problème verbal
        # toujours ouvert.
        # ----------------------------------------------------

        if (
            verdict == "correct"
            and result_correct is True
            and (
                method
                == "verbal_problem_intermediate_solution"
                or method
                in algebraic_final_methods
            )
        ):

            return ProblemLifecycleDecision(
                status=(
                    "algebraic_subgoal_completed"
                ),

                keep_problem_open=True,

                objective_reached=False,

                exercise_closed=False,

                accept_new_problem=False,

                next_action=None,

                reason=(
                    "algebraic_solution_proved_"
                    "but_final_target_pending"
                ),

                details={
                    "validation_method": (
                        method
                    ),
                },
            )

    # ========================================================
    # 5. PROBLÈME SANS CIBLE CONTEXTUELLE SUPPLÉMENTAIRE
    # ========================================================
    #
    # Une équation, inéquation, etc. peut être terminée
    # directement lorsque son résultat final est prouvé.
    # ========================================================

    else:

        algebraic_final_proof = bool(
            verdict == "correct"
            and result_correct is True
            and method
            in algebraic_final_methods
        )

        if algebraic_final_proof:

            return ProblemLifecycleDecision(
                status="closed",

                keep_problem_open=False,

                objective_reached=True,

                exercise_closed=True,

                accept_new_problem=True,

                next_action=(
                    "new_exercise"
                ),

                reason=(
                    "mathematical_final_target_proved"
                ),

                details={
                    "validation_method": (
                        method
                    ),
                    "proof_source": (
                        "mathematical_final_validation"
                    ),
                },
            )

    # ========================================================
    # 6. ÉTAPE CORRECTE MAIS NON FINALE
    # ========================================================

    if (
        verdict == "correct"
        and (
            result_correct is True
            or validation.get(
                "reasoning_correct"
            )
            is True
        )
    ):

        return ProblemLifecycleDecision(
            status="in_progress",

            keep_problem_open=True,

            objective_reached=False,

            exercise_closed=False,

            accept_new_problem=False,

            next_action=None,

            reason=(
                "correct_non_final_step"
            ),

            details={
                "validation_method": (
                    method
                ),
            },
        )

    # ========================================================
    # 7. INCERTITUDE OU ERREUR
    # ========================================================

    return ProblemLifecycleDecision(
        status="in_progress",

        keep_problem_open=True,

        objective_reached=False,

        exercise_closed=False,

        accept_new_problem=False,

        next_action=None,

        reason=(
            "problem_not_yet_proved_complete"
        ),

        details={
            "validation_method": method,
            "verdict": verdict,
        },
    )