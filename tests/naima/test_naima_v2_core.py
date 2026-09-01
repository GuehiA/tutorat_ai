from services.naima.context_service import (
    build_math_context,
)

from services.naima.inequality_service import (
    detect_direction_rule_statement,
    validate_final_inequality,
)

from services.naima.math_parser_service import (
    extract_equation_from_text,
)

from services.naima.math_router import (
    NaimaMathRouter,
)

from services.naima.orchestrator import (
    NaimaOrchestrator,
)


def test_quadratic_parser_preserves_full_equation():

    extracted = extract_equation_from_text(
        "resoudre 3x²-5x+2=0"
    )

    assert extracted == (
        "3*x**2-5*x+2=0"
    )


def test_quadratic_final_answer_is_not_new_problem():

    extracted = extract_equation_from_text(
        "x=1 ou x=2/3"
    )

    assert extracted is None


def test_quadratic_context_preserves_active_problem():

    context = build_math_context(
        message="x=1 ou x=2/3",
        current_objective=(
            "resoudre 3x²-5x+2=0"
        ),
        current_equation=(
            "3*x**2-5*x+2=0"
        ),
        initial_equation=(
            "3*x**2-5*x+2=0"
        ),
        extracted_equation=None,
    )

    assert (
        context.current_equation
        == "3*x**2-5*x+2=0"
    )

    assert (
        context.equation_type
        == "quadratic"
    )

    assert (
        context.context_preserved
        is True
    )

    assert (
        context.is_new_problem
        is False
    )


def test_quadratic_final_solution_is_correct():

    router = NaimaMathRouter()

    result = router.validate(
        student_answer=(
            "x=1 ou x=2/3"
        ),
        equation=(
            "3*x**2-5*x+2=0"
        ),
        teacher_question=(
            "Quelles sont les solutions ?"
        ),
    )

    assert (
        result["verdict"]
        == "correct"
    )

    assert (
        result["method"]
        == "quadratic_solution_set"
    )

    assert (
        result["result_correct"]
        is True
    )


def test_quadratic_orchestrator_closes_correct_problem():

    orchestrator = (
        NaimaOrchestrator()
    )

    result = orchestrator.process_turn(
        message="x=1 ou x=2/3",
        current_objective=(
            "resoudre 3x²-5x+2=0"
        ),
        current_equation=(
            "3*x**2-5*x+2=0"
        ),
        initial_equation=(
            "3*x**2-5*x+2=0"
        ),
        last_teacher_question=(
            "Quelles sont les solutions ?"
        ),
        conversation=[],
        previous_recovery_state={},
        diagnostic={},
        first_message=False,
    )

    assert (
        result.intent[
            "type_demande"
        ]
        == "reponse_finale"
    )

    assert (
        result.validation[
            "method"
        ]
        == "quadratic_solution_set"
    )

    assert (
        result.response[
            "response_type"
        ]
        == "final_correct"
    )

    assert (
        result.objective_reached
        is True
    )

    assert (
        result.requires_llm
        is False
    )


def test_inequality_parser_extracts_new_problem():

    extracted = extract_equation_from_text(
        "resoudre -2x>6"
    )

    assert extracted == (
        "-2*x>6"
    )


def test_inequality_final_answer_is_not_new_problem():

    extracted = extract_equation_from_text(
        "x<-3"
    )

    assert extracted is None


def test_inequality_context_preserves_active_problem():

    context = build_math_context(
        message="x<-3",
        current_objective=(
            "resoudre -2x>6"
        ),
        current_equation=(
            "-2*x>6"
        ),
        initial_equation=(
            "-2*x>6"
        ),
        extracted_equation=None,
    )

    assert (
        context.current_equation
        == "-2*x>6"
    )

    assert (
        context.equation_type
        == "inequality"
    )

    assert (
        context.context_preserved
        is True
    )

    assert (
        context.is_new_problem
        is False
    )


def test_inequality_direction_rule_correct():

    result = (
        detect_direction_rule_statement(
            "je divise par -2 "
            "donc j inverse le sens "
            "de l inégalité"
        )
    )

    assert (
        result["detected"]
        is True
    )

    assert (
        result["reasoning_correct"]
        is True
    )

    assert (
        result["method"]
        == "inequality_direction_rule"
    )


def test_inequality_direction_rule_missing_flip():

    result = (
        detect_direction_rule_statement(
            "je divise par -2"
        )
    )

    assert (
        result["detected"]
        is True
    )

    assert (
        result["reasoning_correct"]
        is False
    )

    assert (
        result["error_type"]
        == (
            "missing_inequality_direction_flip"
        )
    )


def test_inequality_final_solution_correct():

    result = validate_final_inequality(
        "-2x>6",
        "x<-3",
    )

    assert (
        result["verdict"]
        == "correct"
    )

    assert (
        result["method"]
        == "inequality_solution"
    )

    assert (
        result["result_correct"]
        is True
    )


def test_inequality_final_solution_incorrect():

    result = validate_final_inequality(
        "-2x>6",
        "x>-3",
    )

    assert (
        result["verdict"]
        == "incorrect"
    )

    assert (
        result["result_correct"]
        is False
    )

    assert (
        result["error_type"]
        == "wrong_inequality_solution"
    )


def test_inequality_orchestrator_closes_correct_problem():

    orchestrator = (
        NaimaOrchestrator()
    )

    result = orchestrator.process_turn(
        message="x<-3",
        current_objective=(
            "resoudre -2x>6"
        ),
        current_equation=(
            "-2*x>6"
        ),
        initial_equation=(
            "-2*x>6"
        ),
        last_teacher_question=(
            "Quelle est la solution ?"
        ),
        conversation=[],
        previous_recovery_state={},
        diagnostic={},
        first_message=False,
    )

    assert (
        result.intent[
            "type_demande"
        ]
        == "reponse_finale"
    )

    assert (
        result.context[
            "current_equation"
        ]
        == "-2*x>6"
    )

    assert (
        result.validation[
            "method"
        ]
        == "inequality_solution"
    )

    assert (
        result.validation[
            "verdict"
        ]
        == "correct"
    )

    assert (
        result.response[
            "response_type"
        ]
        == "final_correct"
    )

    assert (
        result.objective_reached
        is True
    )

    assert (
        result.requires_llm
        is False
    )


def test_inequality_orchestrator_keeps_wrong_problem_open():

    orchestrator = (
        NaimaOrchestrator()
    )

    result = orchestrator.process_turn(
        message="x>-3",
        current_objective=(
            "resoudre -2x>6"
        ),
        current_equation=(
            "-2*x>6"
        ),
        initial_equation=(
            "-2*x>6"
        ),
        last_teacher_question=(
            "Quelle est la solution ?"
        ),
        conversation=[],
        previous_recovery_state={},
        diagnostic={},
        first_message=False,
    )

    assert (
        result.validation[
            "verdict"
        ]
        == "incorrect"
    )

    assert (
        result.validation[
            "error_type"
        ]
        == "wrong_inequality_solution"
    )

    assert (
        result.response[
            "response_type"
        ]
        == "inequality_solution_error"
    )

    assert (
        result.response[
            "keep_exercise_open"
        ]
        is True
    )

    assert (
        result.response[
            "solution_leakage_blocked"
        ]
        is True
    )

    assert (
        result.objective_reached
        is False
    )

    assert (
        result.requires_llm
        is False
    )

def test_linear_final_operation_remains_socratic():

    orchestrator = NaimaOrchestrator()

    result = orchestrator.process_turn(
        message=(
            "il faut diviser les deux membres par 3"
        ),
        current_objective=(
            "resoudre 3*x=5"
        ),
        current_equation=(
            "3*x=5"
        ),
        initial_equation=(
            "3*x=5"
        ),
        last_teacher_question=(
            "Quelle opération dois-tu appliquer "
            "aux deux membres pour isoler x ?"
        ),
        conversation=[],
        previous_recovery_state={},
        diagnostic={},
        first_message=False,
    )

    assert (
        result.validation[
            "verdict"
        ]
        == "correct"
    )

    assert (
        result.validation[
            "method"
        ]
        == "reasoning_operation"
    )

    assert (
        result.validation[
            "reasoning_correct"
        ]
        is True
    )

    assert (
        result.response[
            "use_local_response"
        ]
        is True
    )

    assert (
        result.response[
            "use_llm"
        ]
        is False
    )

    assert (
        result.response[
            "objective_reached"
        ]
        is False
    )

    assert (
        result.response[
            "keep_exercise_open"
        ]
        is True
    )

    response_text = (
        result.response[
            "text"
        ]
        or ""
    )

    assert "5/3" not in response_text

    assert (
        "quelle valeur"
        in response_text.lower()
        or "obtiens"
        in response_text.lower()
    )


def test_linear_correct_result_wrong_reasoning_conflict():

    orchestrator = NaimaOrchestrator()

    result = orchestrator.process_turn(
        message=(
            "je divise les deux membres par 2 "
            "et j'obtiens x=5/3"
        ),
        current_objective=(
            "resoudre 3*x=5"
        ),
        current_equation=(
            "3*x=5"
        ),
        initial_equation=(
            "3*x=5"
        ),
        last_teacher_question=(
            "Quelle opération dois-tu appliquer "
            "aux deux membres ?"
        ),
        conversation=[],
        previous_recovery_state={},
        diagnostic={},
        first_message=False,
    )

    assert (
        result.validation[
            "verdict"
        ]
        == "correct"
    )

    assert (
        result.validation[
            "method"
        ]
        == (
            "equation_solution_reasoning_conflict"
        )
    )

    assert (
        result.validation[
            "result_correct"
        ]
        is True
    )

    assert (
        result.validation[
            "reasoning_correct"
        ]
        is False
    )

    assert (
        result.response[
            "objective_reached"
        ]
        is False
    )

    assert (
        result.response[
            "keep_exercise_open"
        ]
        is True
    )

    assert (
        result.pedagogical[
            "recovery_state"
        ][
            "phase"
        ]
        != "reussite"
    )


def test_linear_context_continuity_after_reasoning_error():

    context = build_math_context(
        message=(
            "on divise plutot par 3 "
            "et on a x=5/3"
        ),
        current_objective=(
            "resoudre 3*x=5"
        ),
        current_equation=(
            "3*x=5"
        ),
        initial_equation=(
            "3*x=5"
        ),
        extracted_equation=None,
    )

    assert (
        context.current_equation
        == "3*x=5"
    )

    assert (
        context.initial_equation
        == "3*x=5"
    )

    assert (
        context.is_new_problem
        is False
    )

    assert (
        context.context_preserved
        is True
    )


def test_linear_repetition_does_not_close_exercise():

    orchestrator = NaimaOrchestrator()

    previous_recovery_state = {
        "phase": "erreur_active",
        "erreur_active": True,
        "blocage_actif": False,
        "derniere_erreur_type": (
            "wrong_operation_value"
        ),
        "derniere_validation_method": (
            "reasoning_operation"
        ),
        "aide_depuis_erreur": True,
        "aide_depuis_blocage": False,
        "niveau_aide_max": 1,
        "delegation_depuis_erreur": False,
        "delegation_depuis_blocage": False,
        "nb_erreurs_consecutives": 1,
        "nb_tentatives_depuis_erreur": 1,
        "nb_tentatives_depuis_aide": 0,
        "dernier_statut_recuperation": (
            "erreur_active"
        ),
        "confiance_recuperation": 1.0,
        "derniere_strategie_aide": (
            "localisation_erreur"
        ),
        "dernier_verdict": (
            "incorrect"
        ),
        "compteurs": {
            "recuperation_autonome": 0,
            "recuperation_apres_aide": 0,
            "reussite_assistee": 0,
            "sortie_blocage_apres_aide": 0,
            "blocage_observe": 0,
            "delegation_observee": 0,
            "raisonnement_a_corriger": 0,
        },
    }

    result = orchestrator.process_turn(
        message=(
            "Attention, on est ici 3x=5"
        ),
        current_objective=(
            "resoudre 3*x=5"
        ),
        current_equation=(
            "3*x=5"
        ),
        initial_equation=(
            "3*x=5"
        ),
        last_teacher_question=(
            "Quelle opération dois-tu appliquer "
            "aux deux membres ?"
        ),
        conversation=[],
        previous_recovery_state=(
            previous_recovery_state
        ),
        diagnostic={},
        first_message=False,
    )

    assert (
        result.context[
            "current_equation"
        ]
        == "3*x=5"
    )

    assert (
        result.objective_reached
        is False
    )

    assert (
        result.response[
            "keep_exercise_open"
        ]
        is True
    )

    assert (
        result.pedagogical[
            "pedagogical_policy"
        ][
            "strategie"
        ]
        != "felicitation_et_approfondissement"
    )


def test_behavioral_blockage_is_not_math_failure():

    orchestrator = NaimaOrchestrator()

    result = orchestrator.process_turn(
        message=(
            "Je ne comprend plus ta question"
        ),
        current_objective=(
            "resoudre 3*x=5"
        ),
        current_equation=(
            "3*x=5"
        ),
        initial_equation=(
            "3*x=5"
        ),
        last_teacher_question=(
            "Quelle opération dois-tu appliquer "
            "aux deux membres ?"
        ),
        conversation=[],
        previous_recovery_state={},
        diagnostic={},
        first_message=False,
    )

    behavioral_state = (
        result.pedagogical[
            "behavioral_state"
        ]
    )

    assert (
        behavioral_state[
            "etat"
        ]
        != "travail_independant"
        or behavioral_state[
            "signaux"
        ]
    )

    assert (
        result.validation[
            "result_correct"
        ]
        is not False
    )

    assert (
        result.objective_reached
        is False
    )

def test_linear_final_solution_closes_exercise():

    orchestrator = NaimaOrchestrator()

    # ==========================================================
    # 1. NOUVEAU PROBLÈME
    # ==========================================================

    first_turn = orchestrator.process_turn(
        message="resoudre 3x=5",
        current_objective=None,
        current_equation=None,
        initial_equation=None,
        last_teacher_question="",
        conversation=[],
        previous_recovery_state={},
        diagnostic={},
        first_message=True,
    )

    assert (
        first_turn.context["current_equation"]
        == "3*x=5"
    )

    assert (
        first_turn.context["initial_equation"]
        == "3*x=5"
    )

    assert (
        first_turn.context["is_new_problem"]
        is True
    )

    # ==========================================================
    # 2. OPÉRATION CORRECTE
    # ==========================================================

    second_turn = orchestrator.process_turn(
        message="je divise les deux membres par 3",

        current_objective="resoudre 3x=5",

        current_equation=(
            first_turn.context[
                "current_equation"
            ]
        ),

        initial_equation=(
            first_turn.context[
                "initial_equation"
            ]
        ),

        last_teacher_question=(
            "Quelle opération dois-tu appliquer "
            "aux deux membres pour isoler x ?"
        ),

        conversation=[
            {
                "role": "user",
                "content": "resoudre 3x=5",
            },
        ],

        previous_recovery_state=(
            first_turn.pedagogical[
                "recovery_state"
            ]
        ),

        diagnostic={},
        first_message=False,
    )

    assert (
        second_turn.validation["verdict"]
        == "correct"
    )

    assert (
        second_turn.validation["method"]
        == "reasoning_operation"
    )

    assert (
        second_turn.validation[
            "reasoning_correct"
        ]
        is True
    )

    assert (
        second_turn.response[
            "response_type"
        ]
        == "final_operation_socratic"
    )

    assert (
        second_turn.response[
            "keep_exercise_open"
        ]
        is True
    )

    assert (
        second_turn.response[
            "objective_reached"
        ]
        is False
    )

    assert (
        second_turn.response[
            "use_llm"
        ]
        is False
    )

    assert (
        second_turn.requires_llm
        is False
    )

    # Le moteur connaît 5/3,
    # mais Naima ne doit pas le révéler.
    response_text = (
        second_turn.response[
            "text"
        ]
        or ""
    )

    assert "5/3" not in response_text

    # ==========================================================
    # 3. RÉPONSE FINALE DE L'ÉLÈVE
    # ==========================================================

    third_turn = orchestrator.process_turn(
        message="x=5/3",

        current_objective="resoudre 3x=5",

        current_equation=(
            second_turn.context[
                "current_equation"
            ]
        ),

        initial_equation=(
            second_turn.context[
                "initial_equation"
            ]
        ),

        last_teacher_question=(
            second_turn.response[
                "text"
            ]
            or ""
        ),

        conversation=[
            {
                "role": "user",
                "content": "resoudre 3x=5",
            },
            {
                "role": "assistant",
                "content": (
                    second_turn.response[
                        "text"
                    ]
                    or ""
                ),
            },
            {
                "role": "user",
                "content": (
                    "je divise les deux membres par 3"
                ),
            },
        ],

        previous_recovery_state=(
            second_turn.pedagogical[
                "recovery_state"
            ]
        ),

        diagnostic={},
        first_message=False,
    )

    # ==========================================================
    # 4. VALIDATION MATHÉMATIQUE
    # ==========================================================

    assert (
        third_turn.validation["verdict"]
        == "correct"
    )

    assert (
        third_turn.validation["method"]
        == "equation_solution"
    )

    assert (
        third_turn.validation[
            "result_correct"
        ]
        is True
    )

    # ==========================================================
    # 5. RÉPONSE DÉTERMINISTE
    # ==========================================================

    assert (
        third_turn.handled_deterministically
        is True
    )

    assert (
        third_turn.requires_llm
        is False
    )

    # ==========================================================
    # 6. EXERCICE FERMÉ
    # ==========================================================

    assert (
        third_turn.response[
            "response_type"
        ]
        == "final_correct"
    )

    assert (
        third_turn.response[
            "use_local_response"
        ]
        is True
    )

    assert (
        third_turn.response[
            "use_llm"
        ]
        is False
    )

    assert (
        third_turn.response[
            "objective_reached"
        ]
        is True
    )

    assert (
        third_turn.response[
            "keep_exercise_open"
        ]
        is False
    )

    assert (
        third_turn.objective_reached
        is True
    )

def test_new_linear_problem_is_not_validated_as_equivalent_answer():

    orchestrator = NaimaOrchestrator()

    result = orchestrator.process_turn(
        message="resoudre 3x=5",
        current_objective=None,
        current_equation=None,
        initial_equation=None,
        last_teacher_question="",
        conversation=[],
        previous_recovery_state={},
        diagnostic={},
        first_message=True,
    )

    assert (
        result.context[
            "is_new_problem"
        ]
        is True
    )

    assert (
        result.context[
            "current_equation"
        ]
        == "3*x=5"
    )

    assert (
        result.validation[
            "method"
        ]
        == "new_problem_presented"
    )

    assert (
        result.validation[
            "result_correct"
        ]
        is None
    )

    assert (
        result.validation[
            "reasoning_correct"
        ]
        is None
    )

    assert (
        result.requires_llm
        is True
    )

    assert (
        result.objective_reached
        is False
    )

def test_quadratic_discriminant_expression_correct():

    router = NaimaMathRouter()

    result = router.validate(
        student_answer=(
            "delta = (-5)^2 - 4*3*2"
        ),
        equation=(
            "3*x**2-5*x+2=0"
        ),
        teacher_question=(
            "Quelle est l'expression du discriminant ?"
        ),
    )

    assert (
        result["verdict"]
        == "correct"
    )

    assert (
        result["method"]
        == "quadratic_discriminant_expression"
    )

    assert (
        result["reasoning_correct"]
        is True
    )

    assert (
        result["error_type"]
        is None
    )

    assert (
        result["requires_review"]
        is False
    )


def test_quadratic_discriminant_value_correct():

    router = NaimaMathRouter()

    result = router.validate(
        student_answer=(
            "delta = 1"
        ),
        equation=(
            "3*x**2-5*x+2=0"
        ),
        teacher_question=(
            "Quelle valeur obtiens-tu pour delta ?"
        ),
    )

    assert (
        result["verdict"]
        == "correct"
    )

    assert (
        result["method"]
        == "quadratic_discriminant_value"
    )

    assert (
        result["result_correct"]
        is True
    )

    assert (
        result["error_type"]
        is None
    )

    assert (
        result["requires_review"]
        is False
    )

    assert (
        result["details"][
            "expected_discriminant"
        ]
        == "1"
    )


def test_quadratic_discriminant_interpretation_correct():

    router = NaimaMathRouter()

    result = router.validate(
        student_answer=(
            "Comme le discriminant est positif, "
            "l'equation admet 2 solutions distinctes"
        ),
        equation=(
            "3*x**2-5*x+2=0"
        ),
        teacher_question=(
            "Que peux-tu déduire du signe de delta ?"
        ),
    )

    assert (
        result["verdict"]
        == "correct"
    )

    assert (
        result["method"]
        == (
            "quadratic_discriminant_interpretation"
        )
    )

    assert (
        result["reasoning_correct"]
        is True
    )

    assert (
        result["error_type"]
        is None
    )

    assert (
        result["requires_review"]
        is False
    )

    assert (
        result["details"][
            "expected_sign"
        ]
        == "positive"
    )

    assert (
        result["details"][
            "expected_solution_count"
        ]
        == 2
    )


def test_quadratic_discriminant_wrong_value_stays_open():

    orchestrator = NaimaOrchestrator()

    result = orchestrator.process_turn(
        message="delta = 2",

        current_objective=(
            "resoudre 3x²-5x+2=0"
        ),

        current_equation=(
            "3*x**2-5*x+2=0"
        ),

        initial_equation=(
            "3*x**2-5*x+2=0"
        ),

        last_teacher_question=(
            "Quelle valeur obtiens-tu pour Δ ?"
        ),

        conversation=[],

        previous_recovery_state={},

        diagnostic={},

        first_message=False,
    )

    # ==========================================================
    # VALIDATION MATHÉMATIQUE
    # ==========================================================

    assert (
        result.validation[
            "verdict"
        ]
        == "incorrect"
    )

    assert (
        result.validation[
            "method"
        ]
        == "quadratic_discriminant_value"
    )

    assert (
        result.validation[
            "result_correct"
        ]
        is False
    )

    assert (
        result.validation[
            "error_type"
        ]
        == (
            "wrong_quadratic_discriminant_value"
        )
    )

    # ==========================================================
    # RÉPONSE LOCALE
    # ==========================================================

    assert (
        result.response[
            "response_type"
        ]
        == "quadratic_discriminant_error"
    )

    assert (
        result.response[
            "use_local_response"
        ]
        is True
    )

    assert (
        result.response[
            "use_llm"
        ]
        is False
    )

    assert (
        result.requires_llm
        is False
    )

    # ==========================================================
    # L'EXERCICE RESTE OUVERT
    # ==========================================================

    assert (
        result.response[
            "keep_exercise_open"
        ]
        is True
    )

    assert (
        result.response[
            "objective_reached"
        ]
        is False
    )

    assert (
        result.objective_reached
        is False
    )

    # ==========================================================
    # PAS DE FUITE DE SOLUTION
    # ==========================================================

    assert (
        result.response[
            "solution_leakage_blocked"
        ]
        is True
    )

    response_text = (
        result.response[
            "text"
        ]
        or ""
    )

    assert "2/3" not in response_text
    assert "x=1" not in (
        response_text
        .replace(
            " ",
            ""
        )
        .lower()
    )


def test_quadratic_discriminant_value_remains_socratic():

    orchestrator = NaimaOrchestrator()

    result = orchestrator.process_turn(
        message="delta = 1",

        current_objective=(
            "resoudre 3x²-5x+2=0"
        ),

        current_equation=(
            "3*x**2-5*x+2=0"
        ),

        initial_equation=(
            "3*x**2-5*x+2=0"
        ),

        last_teacher_question=(
            "Quelle valeur obtiens-tu pour Δ ?"
        ),

        conversation=[],

        previous_recovery_state={},

        diagnostic={},

        first_message=False,
    )

    # ==========================================================
    # VALIDATION
    # ==========================================================

    assert (
        result.validation[
            "verdict"
        ]
        == "correct"
    )

    assert (
        result.validation[
            "method"
        ]
        == "quadratic_discriminant_value"
    )

    assert (
        result.validation[
            "result_correct"
        ]
        is True
    )

    # ==========================================================
    # RÉPONSE LOCALE
    # ==========================================================

    assert (
        result.response[
            "response_type"
        ]
        == (
            "quadratic_discriminant_value_correct"
        )
    )

    assert (
        result.response[
            "use_local_response"
        ]
        is True
    )

    assert (
        result.response[
            "use_llm"
        ]
        is False
    )

    assert (
        result.requires_llm
        is False
    )

    # ==========================================================
    # LE PARCOURS CONTINUE
    # ==========================================================

    assert (
        result.response[
            "objective_reached"
        ]
        is False
    )

    assert (
        result.response[
            "keep_exercise_open"
        ]
        is True
    )

    assert (
        result.objective_reached
        is False
    )

    # ==========================================================
    # LE MOTEUR CONNAÎT LES RACINES,
    # MAIS NAIMA NE DOIT PAS LES RÉVÉLER
    # ==========================================================

    assert (
        result.response[
            "solution_leakage_blocked"
        ]
        is True
    )

    response_text = (
        result.response[
            "text"
        ]
        or ""
    )

    assert "2/3" not in response_text

    assert "x=1" not in (
        response_text
        .replace(
            " ",
            ""
        )
        .lower()
    )

    assert (
        "nombre de solutions"
        in response_text.lower()
    )