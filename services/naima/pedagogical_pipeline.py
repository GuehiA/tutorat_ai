from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from services.behavioral_state_service import (
    diagnostiquer_etat_comportemental,
)

from services.cognitive_control_service import (
    detecter_controle_cognitif,
)

from services.pedagogical_policy_service import (
    choisir_intervention_pedagogique,
    construire_instruction_pedagogique,
)

from services.learning_recovery_service import (
    analyser_recuperation_apprentissage,
    resume_recuperation_apprentissage,
)


@dataclass
class PedagogicalPipelineResult:
    behavioral_state: Dict[str, Any]

    cognitive_control: Dict[str, Any]

    pedagogical_policy: Dict[str, Any]

    recovery_state: Dict[str, Any]

    recovery_summary: Dict[str, Any]

    pedagogical_instruction: str

    effective_validation: Dict[str, Any]

    recent_hint_count: int

    def to_dict(
        self,
    ) -> Dict[str, Any]:

        return {
            "behavioral_state": (
                self.behavioral_state
            ),
            "cognitive_control": (
                self.cognitive_control
            ),
            "pedagogical_policy": (
                self.pedagogical_policy
            ),
            "recovery_state": (
                self.recovery_state
            ),
            "recovery_summary": (
                self.recovery_summary
            ),
            "pedagogical_instruction": (
                self.pedagogical_instruction
            ),
            "effective_validation": (
                self.effective_validation
            ),
            "recent_hint_count": (
                self.recent_hint_count
            ),
        }


def validation_to_dict(
    validation: Any,
) -> Dict[str, Any]:
    """
    Normalise les différents formats de validation.

    Accepte :
    - ValidationResult ;
    - dict ;
    - objet possédant to_dict() ;
    - objet possédant les attributs usuels.
    """

    if validation is None:

        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "method": None,
            "reason": None,
            "error_type": None,
            "result_correct": None,
            "reasoning_correct": None,
        }

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
            pass

    return {
        "verdict": getattr(
            validation,
            "verdict",
            "uncertain",
        ),
        "confidence": getattr(
            validation,
            "confidence",
            0.0,
        ),
        "method": getattr(
            validation,
            "method",
            None,
        ),
        "reason": getattr(
            validation,
            "reason",
            None,
        ),
        "error_type": getattr(
            validation,
            "error_type",
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
    }


def build_behavior_history(
    conversation: Optional[
        List[Any]
    ],
    *,
    current_question: str = "",
) -> List[Dict[str, str]]:
    """
    Convertit l'historique de session :

        👤 Élève: ...
        🤖 Naima: ...

    vers le format attendu par
    behavioral_state_service.
    """

    history: List[
        Dict[str, str]
    ] = []

    for raw_message in (
        conversation
        or []
    )[-12:]:

        text = str(
            raw_message
            or ""
        ).strip()

        if (
            text.startswith(
                "👤 Élève:"
            )
            or text.startswith(
                "👤 Student:"
            )
        ):

            student_text = (
                text
                .replace(
                    "👤 Élève:",
                    "",
                    1,
                )
                .replace(
                    "👤 Student:",
                    "",
                    1,
                )
                .strip()
            )

            history.append({
                "role": "eleve",
                "texte": student_text,
            })

        elif text.startswith(
            "🤖 Naima:"
        ):

            naima_text = (
                text
                .replace(
                    "🤖 Naima:",
                    "",
                    1,
                )
                .strip()
            )

            history.append({
                "role": "naima",
                "texte": naima_text,
            })

    # Évite de dupliquer la question courante
    # si elle est déjà présente en fin d'historique.
    if (
        history
        and history[-1].get(
            "role"
        )
        == "eleve"
        and history[-1].get(
            "texte"
        )
        == current_question
    ):

        history = history[:-1]

    return history


def update_recent_hint_count(
    *,
    previous_count: int,
    intention: Dict[str, Any],
) -> int:
    """
    Met à jour le compteur récent d'indices.

    Une demande d'indice augmente le compteur.
    Une tentative de résolution le fait redescendre.
    """

    count = int(
        previous_count
        or 0
    )

    request_type = (
        intention.get(
            "type_demande"
        )
        or ""
    )

    if request_type == (
        "demande_indice"
    ):

        count += 1

    elif request_type in {
        "reponse_intermediaire",
        "reponse_finale",
        "probleme_a_resoudre",
    }:

        count = max(
            0,
            count - 1,
        )

    return min(
        count,
        10,
    )


def build_effective_validation(
    *,
    validation: Any,
    first_message: bool,
) -> Dict[str, Any]:
    """
    Produit le verdict utilisé par la politique pédagogique.

    Règle :
    - premier message : pas de verdict pédagogique ;
    - correct/incorrect seulement si confiance >= 0.95 ;
    - sinon : uncertain.
    """

    validation_dict = (
        validation_to_dict(
            validation
        )
    )

    verdict = (
        validation_dict.get(
            "verdict"
        )
    )

    confidence = float(
        validation_dict.get(
            "confidence"
        )
        or 0.0
    )

    if first_message:

        effective_verdict = None

    elif (
        verdict
        in {
            "correct",
            "incorrect",
        }
        and confidence >= 0.95
    ):

        effective_verdict = (
            verdict
        )

    else:

        effective_verdict = (
            "uncertain"
        )

    return {
        "verdict": (
            effective_verdict
        ),
        "confidence": (
            confidence
        ),
        "method": (
            validation_dict.get(
                "method"
            )
        ),
        "reason": (
            validation_dict.get(
                "reason"
            )
        ),
        "error_type": (
            validation_dict.get(
                "error_type"
            )
        ),
        "result_correct": (
            validation_dict.get(
                "result_correct"
            )
        ),
        "reasoning_correct": (
            validation_dict.get(
                "reasoning_correct"
            )
        ),
    }


def _is_recovery_sequence_active(
    previous_recovery_state: Optional[
        Dict[str, Any]
    ],
) -> bool:
    """
    Indique si une séquence d'erreur/blocage
    est actuellement active.
    """

    state = (
        previous_recovery_state
        or {}
    )

    return bool(
        state.get(
            "erreur_active"
        )
        or state.get(
            "blocage_actif"
        )
    )


def _apply_special_policy_guards(
    *,
    pedagogical_policy: Dict[str, Any],
    validation: Any,
    previous_recovery_state: Optional[
        Dict[str, Any]
    ],
) -> Dict[str, Any]:
    """
    Applique les gardes pédagogiques historiques.

    Elles ne modifient jamais le verdict mathématique.
    Elles empêchent seulement une stratégie pédagogique
    contradictoire avec l'état de récupération.
    """

    validation_dict = (
        validation_to_dict(
            validation
        )
    )

    validation_method = (
        validation_dict.get(
            "method"
        )
    )

    recovery_sequence_active = (
        _is_recovery_sequence_active(
            previous_recovery_state
        )
    )

    # ==========================================================
    # GARDE v1.3.1 :
    # RÉPÉTITION DE L'ÉQUATION COURANTE
    # ==========================================================

    if (
        validation_method
        == "equation_repetition_no_progress"
        and recovery_sequence_active
    ):

        return {
            "strategie": (
                "maintien_correction"
            ),
            "niveau_aide": 1,
            "peut_reveler_solution": False,
            "peut_declencher_remediation": False,
            "requires_review": False,
            "raison": (
                "L'élève rappelle correctement "
                "l'équation courante, mais n'a pas "
                "encore corrigé l'erreur ou le "
                "blocage précédent."
            ),
        }

    # ==========================================================
    # GARDE :
    # RÉSULTAT CORRECT MAIS RAISONNEMENT INCORRECT
    # ==========================================================

    result_correct = (
        validation_dict.get(
            "result_correct"
        )
    )

    reasoning_correct = (
        validation_dict.get(
            "reasoning_correct"
        )
    )

    if (
        result_correct is True
        and reasoning_correct is False
    ):

        return {
            "strategie": (
                "correction_raisonnement_resultat_correct"
            ),
            "niveau_aide": 1,
            "peut_reveler_solution": False,
            "peut_declencher_remediation": True,
            "requires_review": False,
            "raison": (
                "Le résultat final est correct, "
                "mais le raisonnement utilisé "
                "doit être corrigé."
            ),
        }

    return pedagogical_policy


def run_pedagogical_pipeline(
    *,
    question: str,

    validation: Any,

    intention: Dict[str, Any],

    conversation: Optional[
        List[Any]
    ] = None,

    previous_recovery_state: Optional[
        Dict[str, Any]
    ] = None,

    diagnostic: Optional[
        Dict[str, Any]
    ] = None,

    last_teacher_question: str = "",

    recent_hint_count: int = 0,

    first_message: bool = False,

    lang: str = "fr",

    validation_for_recovery: Any = None,
) -> PedagogicalPipelineResult:
    """
    Pipeline pédagogique autonome de Naima.

    Ordre :

        validation mathématique
                ↓
        historique comportemental
                ↓
        état comportemental
                ↓
        contrôle cognitif
                ↓
        verdict pédagogique effectif
                ↓
        politique pédagogique
                ↓
        gardes pédagogiques historiques
                ↓
        instruction pédagogique
                ↓
        Learning Recovery

    Ce service ne modifie jamais
    le verdict mathématique déterministe.
    """

    # ==========================================================
    # 1. VALIDATION NORMALISÉE
    # ==========================================================

    validation_dict = (
        validation_to_dict(
            validation
        )
    )

    validation_verdict = (
        validation_dict.get(
            "verdict"
        )
        or "uncertain"
    )

    # ==========================================================
    # 2. HISTORIQUE COMPORTEMENTAL
    # ==========================================================

    behavior_history = (
        build_behavior_history(
            conversation,
            current_question=(
                question
            ),
        )
    )

    request_type = (
        intention.get(
            "type_demande"
        )
        or ""
    )

    help_used = (
        request_type
        in {
            "demande_indice",
            "demande_explication",
        }
    )

    updated_hint_count = (
        update_recent_hint_count(
            previous_count=(
                recent_hint_count
            ),
            intention=(
                intention
            ),
        )
    )

    # ==========================================================
    # 3. ÉTAT COMPORTEMENTAL
    # ==========================================================

    behavioral_state = (
        diagnostiquer_etat_comportemental(
            question,

            historique=(
                behavior_history
            ),

            nb_tentatives_recentes=0,

            aide_utilisee=(
                help_used
            ),

            nb_indices_recentes=(
                updated_hint_count
            ),

            temps_depuis_derniere_aide=None,

            modification_apres_aide=None,

            verdict_validation=(
                validation_verdict
            ),
        )
    )

    # ==========================================================
    # 4. CONTRÔLE COGNITIF
    # ==========================================================

    cognitive_control = (
        detecter_controle_cognitif(
            question,

            derniere_question_naima=(
                last_teacher_question
                or ""
            ),

            intention_pedagogique=(
                intention
            ),
        )
    )

    # ==========================================================
    # 5. VERDICT PÉDAGOGIQUE EFFECTIF
    # ==========================================================

    effective_validation = (
        build_effective_validation(
            validation=(
                validation
            ),

            first_message=(
                first_message
            ),
        )
    )

    # ==========================================================
    # 6. POLITIQUE PÉDAGOGIQUE STANDARD
    # ==========================================================

    pedagogical_policy = (
        choisir_intervention_pedagogique(
            validation=(
                effective_validation
            ),

            intention=(
                intention
            ),

            etat_comportemental=(
                behavioral_state
            ),

            controle_cognitif=(
                cognitive_control
            ),

            diagnostic=(
                diagnostic
                or {}
            ),
        )
    )

    # ==========================================================
    # 7. GARDES PÉDAGOGIQUES HISTORIQUES
    # ==========================================================

    pedagogical_policy = (
        _apply_special_policy_guards(
            pedagogical_policy=(
                pedagogical_policy
            ),

            validation=(
                validation
            ),

            previous_recovery_state=(
                previous_recovery_state
            ),
        )
    )

    # Le premier message ne doit pas déclencher
    # une révision humaine simplement parce que
    # la validation mathématique est encore incertaine.
    if first_message:

        pedagogical_policy[
            "requires_review"
        ] = False

    # ==========================================================
    # 8. INSTRUCTION PÉDAGOGIQUE
    # ==========================================================

    pedagogical_instruction = (
        construire_instruction_pedagogique(
            pedagogical_policy,
            lang=(
                lang
            ),
        )
    )

    # ==========================================================
    # 9. LEARNING RECOVERY
    # ==========================================================

    recovery_validation = (
        validation_for_recovery
        if validation_for_recovery
        is not None
        else validation
    )

    recovery_state = (
        analyser_recuperation_apprentissage(
            etat_precedent=(
                previous_recovery_state
                or {}
            ),

            validation=(
                recovery_validation
            ),

            etat_comportemental=(
                behavioral_state
            ),

            controle_cognitif=(
                cognitive_control
            ),

            politique_pedagogique=(
                pedagogical_policy
            ),

            intention=(
                intention
            ),
        )
    )

    # ==========================================================
    # 10. RÉSUMÉ RECOVERY
    # ==========================================================

    recovery_summary = (
        resume_recuperation_apprentissage(
            recovery_state
        )
    )

    # ==========================================================
    # 11. RÉSULTAT
    # ==========================================================

    return PedagogicalPipelineResult(

        behavioral_state=(
            behavioral_state
        ),

        cognitive_control=(
            cognitive_control
        ),

        pedagogical_policy=(
            pedagogical_policy
        ),

        recovery_state=(
            recovery_state
        ),

        recovery_summary=(
            recovery_summary
        ),

        pedagogical_instruction=(
            pedagogical_instruction
        ),

        effective_validation=(
            effective_validation
        ),

        recent_hint_count=(
            updated_hint_count
        ),
    )