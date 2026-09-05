from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from services.naima.context_service import (
    NaimaMathContext,
    build_math_context,
)

from services.naima.intent_service import (
    NaimaIntent,
    detect_intent,
    merge_intent,
)

from services.naima.math_router import (
    NaimaMathRouter,
)

from services.naima.pedagogical_pipeline import (
    PedagogicalPipelineResult,
    run_pedagogical_pipeline,
)

from services.naima.response_service import (
    NaimaResponseDecision,
    build_local_response,
)

from services.naima.verbal_problem_service import (
    extract_equations_from_text,
    extract_variable_meaning,
    targets_final_problem_objective,
    validate_direct_verbal_final_answer,
    validate_direct_verbal_modeling,
    validate_final_answer,
    validate_modeling_equation,
)

from services.naima.problem_lifecycle_service import (
    ProblemLifecycleDecision,
    resolve_problem_lifecycle,
)


@dataclass
class NaimaTurnResult:
    """
    Résultat complet d'un tour traité par Naima.
    """

    message: str

    intent: Dict[str, Any]

    context: Dict[str, Any]

    validation: Dict[str, Any]

    pedagogical: Dict[str, Any]

    response: Dict[str, Any]

    equation_type: str

    handled_deterministically: bool

    requires_llm: bool

    objective_reached: bool

    def to_dict(
        self,
    ) -> Dict[str, Any]:

        return {
            "message": self.message,
            "intent": self.intent,
            "context": self.context,
            "validation": self.validation,
            "pedagogical": self.pedagogical,
            "response": self.response,
            "equation_type": (
                self.equation_type
            ),
            "handled_deterministically": (
                self.handled_deterministically
            ),
            "requires_llm": (
                self.requires_llm
            ),
            "objective_reached": (
                self.objective_reached
            ),
        }


class NaimaOrchestrator:
    """
    Orchestrateur métier principal de Naima.

    Cette classe ne dépend volontairement pas de Flask.

    Elle ne lit directement :
    - ni request ;
    - ni session ;
    - ni base de données.

    Pipeline :

        message élève
              ↓
        détection intention
              ↓
        résolution contexte
              ↓
        routage mathématique / verbal
              ↓
        validation
              ↓
        pipeline pédagogique
              ↓
        décision de réponse
              ↓
        NaimaTurnResult

    L'intention peut être :
    - détectée automatiquement ;
    - fournie par l'ancien système ;
    - fusionnée avec l'intention déterministe.
    """

    def __init__(
        self,
        *,
        math_router: Optional[
            NaimaMathRouter
        ] = None,
    ):

        self.math_router = (
            math_router
            or NaimaMathRouter()
        )

    def process_turn(
        self,
        *,
        message: str,

        intention: Optional[
            Dict[str, Any]
        ] = None,

        current_objective: Optional[
            str
        ] = None,

        current_equation: Optional[
            str
        ] = None,

        initial_equation: Optional[
            str
        ] = None,

        extracted_equation: Optional[
            str
        ] = None,

        last_teacher_question: str = "",

        conversation: Optional[
            List[Any]
        ] = None,

        previous_recovery_state: Optional[
            Dict[str, Any]
        ] = None,

        diagnostic: Optional[
            Dict[str, Any]
        ] = None,

        recent_hint_count: int = 0,

        first_message: bool = False,

        expected_answer: Any = None,

        lang: str = "fr",

        validation_for_recovery: Any = None,

        verbal_problem_active: bool = False,

        verbal_problem_correction: Any = None,

        direct_verbal_variable_meaning: Optional[
            Dict[str, Any]
        ] = None,

        direct_verbal_algebraic_solution: Optional[
            Dict[str, Any]
        ] = None,

        direct_verbal_relations: Optional[
            List[Dict[str, Any]]
        ] = None,

        direct_verbal_constraints: Optional[
            List[Dict[str, Any]]
        ] = None,

    ) -> NaimaTurnResult:

        # ======================================================
        # 0. INTENTION
        # ======================================================

        has_active_problem = bool(
            current_equation
            or current_objective
        )

        deterministic_intent: NaimaIntent = (
            detect_intent(
                message,
                has_active_problem=(
                    has_active_problem
                ),
            )
        )

        resolved_intent: NaimaIntent = (
            merge_intent(
                deterministic_intent=(
                    deterministic_intent
                ),
                external_intent=(
                    intention
                ),
            )
        )

        intention_resolue = (
            resolved_intent.to_dict()
        )

        # ======================================================
        # 1. CONTEXTE
        # ======================================================

        context: NaimaMathContext = (
            build_math_context(
                message=message,

                current_objective=(
                    current_objective
                ),

                current_equation=(
                    current_equation
                ),

                initial_equation=(
                    initial_equation
                ),

                extracted_equation=(
                    extracted_equation
                ),
            )
        )

        equation = (
            context.current_equation
        )

        # ======================================================
        # 2. VALIDATION MATHÉMATIQUE / VERBALE
        # ======================================================
        #
        # IMPORTANT :
        #
        # Lorsqu'un élève présente un NOUVEAU problème :
        #
        #     "resoudre 3x=5"
        #
        # l'équation extraite ne constitue pas une réponse
        # de l'élève.
        #
        # On ne doit donc pas envoyer ce message au MathRouter
        # comme s'il s'agissait d'une transformation de 3*x=5.
        #
        # Sinon ValidationEngine peut conclure à tort :
        #
        #     equation_equivalence
        #     result_correct = True
        #
        # parce que l'équation de l'énoncé est évidemment
        # équivalente à elle-même.
        #
        # Dans ce cas on produit une validation neutre :
        #
        #     new_problem_presented
        #
        # Le pipeline pédagogique peut ensuite demander au LLM
        # de formuler la première question socratique.
        # ======================================================

        # ======================================================
        # 2A. PRIORITÉ PROBLÈME VERBAL
        # ======================================================
        #
        # Lorsqu'un exercice verbal est actif, une équation
        # proposée par l'élève peut constituer une MODÉLISATION
        # du problème et non un nouveau problème indépendant.
        #
        # Exemple :
        #
        #     problème :
        #         Marie a deux fois l'âge de Paul
        #         et leur somme vaut 30
        #
        #     élève :
        #         x+2x=30
        #
        # Cette équation doit être traitée comme tentative
        # de modélisation AVANT toute détection de réponse
        # finale.
        #
        # Ceci est particulièrement important lorsque le texte
        # de l'élève contient aussi des mots comme :
        #
        #     âge
        #     Paul
        #     Marie
        #
        # car targets_final_problem_objective() pourrait sinon
        # croire prématurément que l'élève répond déjà à la
        # question finale.
        #
        # Règle :
        #
        #     aucune équation active
        #     + équation explicite dans le message
        #
        #         ↓
        #
        #     priorité à validate_modeling_equation()
        #
        # ======================================================

        verbal_validation = None

        if (
            verbal_problem_active
            and not first_message
        ):

            verbal_final_target = (
                targets_final_problem_objective(
                    student_answer=(
                        message
                    ),

                    last_teacher_question=(
                        last_teacher_question
                    ),

                    objective=(
                        current_objective
                        or ""
                    ),
                )
            )

            intent_is_final = (
                intention_resolue.get(
                    "type_demande"
                )
                == "reponse_finale"
            )

            # --------------------------------------------------
            # EXTRACTION DES ÉQUATIONS DU MESSAGE
            # --------------------------------------------------
            #
            # Exemples :
            #
            #     x+2x=30
            #     3x=30
            #     x=10
            #
            # La présence d'une équation ne signifie pas
            # forcément qu'il s'agit d'une modélisation :
            #
            # si current_equation existe déjà, x=10 peut être
            # une réponse algébrique au sous-problème.
            # --------------------------------------------------

            student_equations = (
                extract_equations_from_text(
                    message
                )
            )

            student_has_explicit_equation = bool(
                student_equations
            )

            # --------------------------------------------------
            # A. ÉQUATION DE MODÉLISATION EN PRIORITÉ
            # --------------------------------------------------
            #
            # Ce chemin n'est utilisé que lorsqu'aucune équation
            # active n'existe encore.
            #
            # Si une correction de référence est disponible :
            #     la modélisation peut être prouvée.
            #
            # Si aucune correction n'existe :
            #     verdict = uncertain
            #     method = verbal_problem_modeling
            #
            # On conserve ainsi une politique prudente :
            #
            # absence de preuve != réponse fausse
            # --------------------------------------------------

            is_initial_modeling_attempt = bool(
                not current_equation
                and student_has_explicit_equation
            )

            if is_initial_modeling_attempt:

                # ----------------------------------------------
                # EXERCICE GÉNÉRÉ
                # ----------------------------------------------

                if verbal_problem_correction:

                    verbal_validation = (
                        validate_modeling_equation(
                            student_answer=(
                                message
                            ),

                            correction=(
                                verbal_problem_correction
                            ),
                        )
                    )

                # ----------------------------------------------
                # PROBLÈME VERBAL DIRECT
                # ----------------------------------------------
                #
                # Ici on essaie d'abord de reconstruire
                # déterministiquement le modèle attendu depuis :
                #
                # - la signification explicite de la variable ;
                # - les contraintes verbales de l'énoncé.
                #
                # Si ces éléments sont insuffisants, le service
                # retournera "uncertain".
                # ----------------------------------------------

                else:

                    # ----------------------------------------------
                    # SIGNIFICATION DE VARIABLE DU TOUR COURANT
                    # ----------------------------------------------
                    #
                    # Lors de la première modélisation, cette
                    # information n'est pas encore nécessairement
                    # persistée dans la session.
                    #
                    # Exemple :
                    #
                    #     Soit x l'âge de Paul...
                    #
                    # On l'extrait donc directement du message
                    # courant avant la validation déterministe.
                    # ----------------------------------------------

                    current_variable_meaning = (
                        direct_verbal_variable_meaning
                        or extract_variable_meaning(
                            message
                        )
                    )

                    verbal_validation = (
                        validate_direct_verbal_modeling(
                            student_answer=(
                                message
                            ),

                            variable_meaning=(
                                current_variable_meaning
                            ),

                            constraints=(
                                direct_verbal_constraints
                            ),
                        )
                    )

            # --------------------------------------------------
            # B. RÉPONSE FINALE CONTEXTUELLE
            # --------------------------------------------------
            #
            # IMPORTANT :
            #
            # Cette branche n'est examinée QUE si le message
            # n'était pas une tentative initiale de
            # modélisation.
            #
            # Cela empêche :
            #
            #     x+2x=30
            #
            # d'être interprété à la fois comme modélisation
            # et comme réponse finale.
            # --------------------------------------------------

            else:

                # ----------------------------------------------
                # MÉMOIRE DÉTERMINISTE DISPONIBLE POUR
                # UN PROBLÈME VERBAL DIRECT
                # ----------------------------------------------
                #
                # Quand l'élève a lui-même fourni le problème,
                # il n'existe aucune correction cachée.
                #
                # Mais après le travail pédagogique, nous
                # pouvons disposer de :
                #
                #     x = âge de Paul
                #     x = 10 prouvé
                #     Marie = 2 × Paul
                #
                # Dans ce cas une réponse contextuelle sans
                # équation explicite peut être soumise au
                # validateur déterministe même si IntentService
                # ne l'a pas explicitement étiquetée
                # "reponse_finale".
                # ----------------------------------------------

                # ----------------------------------------------
                # MÉMOIRE DÉTERMINISTE DIRECTE
                # ----------------------------------------------
                #
                # On distingue :
                #
                # 1. la mémoire historique actuellement comprise
                #    par validate_direct_verbal_final_answer()
                #    (ex. multiple_of pour les problèmes d'âge) ;
                #
                # 2. le contexte sémantique plus général, qui peut
                #    déjà contenir des contraintes comme
                #    product_offset_common_value.
                #
                # Le second peut désormais être transmis au
                # validateur final sémantique générique.
                # ----------------------------------------------

                direct_verbal_memory_available = bool(
                    not verbal_problem_correction
                    and direct_verbal_variable_meaning
                    and direct_verbal_algebraic_solution
                    and direct_verbal_relations
                )

                direct_verbal_semantic_context_available = bool(
                    not verbal_problem_correction
                    and direct_verbal_variable_meaning
                    and direct_verbal_algebraic_solution
                    and (
                        direct_verbal_relations
                        or direct_verbal_constraints
                    )
                )

                # ----------------------------------------------
                # IMPORTANT : UNE RÉPONSE FINALE PEUT CONTENIR
                # DES ÉQUATIONS
                # ----------------------------------------------
                #
                # Exemple :
                #
                #   5*17/5 = 17
                #   17 + 12 = 29
                #   donc j'ai 29 $.
                #
                # L'ancien garde :
                #
                #   not student_has_explicit_equation
                #
                # bloquait ce type de réponse contextuelle
                # pourtant complète.
                #
                # On autorise donc une réponse contenant des
                # équations UNIQUEMENT lorsqu'un signal
                # contextuel fort montre qu'elle vise le but
                # final du problème verbal.
                #
                # En revanche :
                #
                #   x = 10
                #
                # reste un sous-résultat algébrique si aucun
                # signal contextuel final n'est détecté.
                # ----------------------------------------------

                should_validate_verbal_final = bool(
                    verbal_final_target
                    or (
                        not student_has_explicit_equation
                        and (
                            intent_is_final
                            or direct_verbal_memory_available
                        )
                    )
                )

                # ----------------------------------------------
                # EXERCICE VERBAL GÉNÉRÉ
                # ----------------------------------------------

                if (
                    should_validate_verbal_final
                    and verbal_problem_correction
                ):

                    verbal_validation = (
                        validate_final_answer(
                            student_answer=(
                                message
                            ),

                            correction=(
                                verbal_problem_correction
                            ),
                        )
                    )

                # ----------------------------------------------
                # PROBLÈME VERBAL SAISI DIRECTEMENT
                # ----------------------------------------------
                #
                # Aucune correction n'est inventée.
                #
                # La validation repose exclusivement sur :
                #
                # - la signification explicite de la variable ;
                # - la solution algébrique prouvée ;
                # - les relations verbales extraites ;
                # - l'énoncé original ;
                # - les contraintes sémantiques structurées.
                #
                # IMPORTANT :
                #
                # statement et constraints sont transmis afin
                # que validate_direct_verbal_final_answer()
                # puisse utiliser le chemin sémantique générique.
                # ----------------------------------------------

                elif (
                    should_validate_verbal_final
                    and direct_verbal_memory_available
                ):

                    verbal_validation = (
                        validate_direct_verbal_final_answer(
                            student_answer=(
                                message
                            ),

                            variable_meaning=(
                                direct_verbal_variable_meaning
                            ),

                            algebraic_solution=(
                                direct_verbal_algebraic_solution
                            ),

                            verbal_relations=(
                                direct_verbal_relations
                            ),

                            statement=(
                                current_objective
                                or ""
                            ),

                            constraints=(
                                direct_verbal_constraints
                            ),
                        )
                    )

                # ----------------------------------------------
                # CAS VERBAL SANS MÉMOIRE DÉTERMINISTE COMPLÈTE
                # ----------------------------------------------
                #
                # Une correction peut être absente et la chaîne
                # de preuve historique encore incomplète.
                #
                # Mais si le contexte sémantique générique est
                # disponible, il peut être transmis au validateur
                # final sémantique.
                # ----------------------------------------------

                elif (
                    should_validate_verbal_final
                    and not verbal_problem_correction
                    and direct_verbal_semantic_context_available
                ):

                    # ------------------------------------------
                    # CONTEXTE DIRECT GÉNÉRIQUE DISPONIBLE
                    # ------------------------------------------
                    #
                    # Ici aussi nous transmettons :
                    #
                    #     statement
                    #     constraints
                    #
                    # afin d'autoriser une validation sémantique
                    # générale plutôt qu'un fallback immédiat
                    # vers le validateur historique.
                    # ------------------------------------------

                    verbal_validation = (
                        validate_direct_verbal_final_answer(
                            student_answer=(
                                message
                            ),

                            variable_meaning=(
                                direct_verbal_variable_meaning
                            ),

                            algebraic_solution=(
                                direct_verbal_algebraic_solution
                            ),

                            verbal_relations=(
                                direct_verbal_relations
                            ),

                            statement=(
                                current_objective
                                or ""
                            ),

                            constraints=(
                                direct_verbal_constraints
                            ),
                        )
                    )

        # ======================================================
        # 2B. ARBITRAGE DE VALIDATION
        # ======================================================

        if verbal_validation is not None:

            validation = (
                verbal_validation
            )

        elif (
            context.is_new_problem
            and intention_resolue.get(
                "type_demande"
            )
            == "probleme_a_resoudre"
        ):

            if equation:

                context.current_objective = (
                    f"resoudre {equation}"
                )

            validation = {
                "verdict": "uncertain",
                "confidence": 1.0,
                "method": (
                    "new_problem_presented"
                ),
                "result_correct": None,
                "reasoning_correct": None,
                "error_type": None,
                "requires_review": False,
                "reason": (
                    "L'élève vient de présenter un nouveau "
                    "problème. L'énoncé ne doit pas être "
                    "interprété comme une réponse ni comme "
                    "une transformation déjà effectuée."
                ),
                "details": {
                    "new_problem": True,
                    "equation": (
                        equation
                    ),
                    "equation_type": (
                        context.equation_type
                    ),
                },
            }

        elif equation:

            validation = (
                self.math_router.validate(
                    student_answer=(
                        message
                    ),

                    equation=equation,

                    teacher_question=(
                        last_teacher_question
                    ),

                    intent=(
                        intention_resolue.get(
                            "type_demande"
                        )
                    ),

                    expected_answer=(
                        expected_answer
                    ),
                )
            )

        else:

            validation = {
                "verdict": "uncertain",
                "confidence": 0.0,
                "method": (
                    "no_math_context"
                ),
                "result_correct": None,
                "reasoning_correct": None,
                "error_type": None,
                "requires_review": True,
                "reason": (
                    "Aucune équation courante "
                    "n'est disponible."
                ),
                "details": {},
            }

        # ======================================================
        # 2C. ÉQUATION RÉSOLUE À L'INTÉRIEUR
        #     D'UN PROBLÈME VERBAL
        # ======================================================
        #
        # MathRouter peut retourner :
        #
        # - un dictionnaire ;
        # - un objet de validation possédant to_dict().
        #
        # On normalise donc temporairement la validation avant
        # de décider si la résolution algébrique constitue
        # seulement un sous-objectif du problème verbal.
        # ======================================================

        validation_for_verbal_subgoal: Dict[
            str,
            Any,
        ] = {}

        if isinstance(
            validation,
            dict,
        ):

            validation_for_verbal_subgoal = dict(
                validation
            )

        elif hasattr(
            validation,
            "to_dict",
        ):

            try:

                validation_for_verbal_subgoal = (
                    validation.to_dict()
                )

            except Exception:

                validation_for_verbal_subgoal = {}

        # ------------------------------------------------------
        # Une solution algébrique correcte n'achève pas
        # automatiquement le problème verbal.
        #
        # Exemple :
        #
        #     x + 2x = 30
        #     x = 10
        #
        # x = 10 résout l'équation, mais l'élève doit encore
        # expliquer :
        #
        #     Paul a 10 ans
        #     Marie a 20 ans
        #
        # On transforme donc :
        #
        #     equation_solution
        #
        # en :
        #
        #     verbal_problem_intermediate_solution
        #
        # afin que ResponseService laisse le problème ouvert.
        # ------------------------------------------------------

        if (
            verbal_problem_active
            and validation_for_verbal_subgoal.get(
                "verdict"
            )
            == "correct"
            and validation_for_verbal_subgoal.get(
                "method"
            )
            == "equation_solution"
            and validation_for_verbal_subgoal.get(
                "result_correct"
            )
            is True
        ):

            original_validation = dict(
                validation_for_verbal_subgoal
            )

            original_details = dict(
                original_validation.get(
                    "details"
                )
                or {}
            )

            original_details[
                "algebraic_subgoal_completed"
            ] = True

            original_details[
                "original_validation_method"
            ] = (
                "equation_solution"
            )

            validation = {
                **original_validation,

                "method": (
                    "verbal_problem_intermediate_solution"
                ),

                "reason": (
                    "La résolution algébrique est correcte, "
                    "mais le problème verbal demande encore "
                    "une interprétation contextuelle du résultat."
                ),

                "details": (
                    original_details
                ),
            }

        # ======================================================
        # 2D. RÉPÉTITION DE L'ÉQUATION SANS PROGRESSION
        # ======================================================

        recovery_active = bool(
            (
                previous_recovery_state
                or {}
            ).get(
                "erreur_active"
            )
            or (
                previous_recovery_state
                or {}
            ).get(
                "blocage_actif"
            )
        )

        repeated_current_equation = bool(
            recovery_active
            and not context.is_new_problem
            and context.context_preserved
            and context.extracted_equation
            and context.current_equation
            and (
                context.extracted_equation
                == context.current_equation
            )
        )

        if repeated_current_equation:

            validation = {
                "verdict": "uncertain",
                "confidence": 0.0,
                "method": (
                    "equation_repetition_no_progress"
                ),
                "result_correct": None,
                "reasoning_correct": None,
                "error_type": None,
                "requires_review": False,
                "reason": (
                    "L'élève répète exactement "
                    "l'équation courante. Cette répétition "
                    "est mathématiquement cohérente mais "
                    "ne constitue pas une progression."
                ),
                "details": {
                    "repetition_equation_courante": True,
                    "equation_repetee": (
                        context.extracted_equation
                    ),
                    "equation_courante": (
                        context.current_equation
                    ),
                },
            }

        # ======================================================
        # 2E. CYCLE DE VIE DU PROBLÈME
        # ======================================================
        #
        # Le moteur de validation détermine la vérité
        # mathématique.
        #
        # ProblemLifecycleService détermine ensuite si cette
        # preuve suffit réellement à fermer le problème.
        #
        # IMPORTANT :
        #
        # verbal_problem_active=True signifie que la résolution
        # algébrique seule n'est pas nécessairement la cible
        # finale.
        # ======================================================

        if isinstance(
            validation,
            dict,
        ):

            lifecycle_validation = dict(
                validation
            )

        elif hasattr(
            validation,
            "to_dict",
        ):

            try:

                lifecycle_validation = (
                    validation.to_dict()
                )

            except Exception:

                lifecycle_validation = {}

        else:

            lifecycle_validation = {}

        problem_active = bool(
            current_objective
            or current_equation
            or verbal_problem_active
        )

        lifecycle: (
            ProblemLifecycleDecision
        ) = resolve_problem_lifecycle(
            validation=(
                lifecycle_validation
            ),

            current_problem_active=(
                problem_active
            ),

            final_target_required=(
                verbal_problem_active
            ),
        )

        # ======================================================
        # 3. PIPELINE PÉDAGOGIQUE
        # ======================================================

        pedagogical: (
            PedagogicalPipelineResult
        ) = run_pedagogical_pipeline(

            question=message,

            validation=validation,

            intention=(
                intention_resolue
            ),

            conversation=(
                conversation
            ),

            previous_recovery_state=(
                previous_recovery_state
            ),

            diagnostic=(
                diagnostic
                or {}
            ),

            last_teacher_question=(
                last_teacher_question
            ),

            recent_hint_count=(
                recent_hint_count
            ),

            first_message=(
                first_message
            ),

            lang=lang,

            validation_for_recovery=(
                validation_for_recovery
            ),
        )

        # ======================================================
        # 4. DÉCISION DE RÉPONSE
        # ======================================================

        response: (
            NaimaResponseDecision
        ) = build_local_response(

            validation=validation,

            pedagogical_policy=(
                pedagogical
                .pedagogical_policy
            ),

            equation=equation,

            student_answer=(
                message
            ),

            last_teacher_question=(
                last_teacher_question
            ),

            lifecycle=(
                lifecycle.to_dict()
            ),

            lang=lang,
        )

        # ======================================================
        # 5. NORMALISATION DU RÉSULTAT DE VALIDATION
        # ======================================================

        if isinstance(
            validation,
            dict,
        ):

            validation_dict = dict(
                validation
            )

        elif hasattr(
            validation,
            "to_dict",
        ):

            try:

                validation_dict = (
                    validation.to_dict()
                )

            except Exception:

                validation_dict = {}

        else:

            validation_dict = {}

        # ======================================================
        # 6. ÉTAT GLOBAL DU TOUR
        # ======================================================

        handled_deterministically = (
            response.use_local_response
            and not response.use_llm
        )

        # ======================================================
        # 7. RÉSULTAT FINAL
        # ======================================================

        return NaimaTurnResult(

            message=message,

            intent=(
                intention_resolue
            ),

            context=(
                context.to_dict()
            ),

            validation=(
                validation_dict
            ),

            pedagogical=(
                pedagogical.to_dict()
            ),

            response=(
                response.to_dict()
            ),

            equation_type=(
                context.equation_type
            ),

            handled_deterministically=(
                handled_deterministically
            ),

            requires_llm=(
                response.use_llm
            ),

            objective_reached=(
                response.objective_reached
            ),
        )