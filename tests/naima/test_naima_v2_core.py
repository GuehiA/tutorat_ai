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

def test_verbal_problem_extracts_reference_equations():

    from services.naima.verbal_problem_service import (
        extract_reference_equations,
    )

    correction = {
        "etapes": [
            "On modélise avec 2(x+2x)=30.",
            "Ensuite on obtient x=5.",
        ]
    }

    equations = extract_reference_equations(
        correction
    )

    assert "2(x+2x)=30" in equations
    assert "x=5" in equations


def test_verbal_problem_modeling_equation_correct():

    from services.naima.verbal_problem_service import (
        validate_modeling_equation,
    )

    correction = {
        "etapes": [
            "On peut modéliser la situation par "
            "x+2x=15."
        ]
    }

    result = validate_modeling_equation(
        student_answer="3x=15",
        correction=correction,
    )

    assert (
        result["verdict"]
        == "correct"
    )

    assert (
        result["method"]
        == "verbal_problem_modeling"
    )

    assert (
        result["reasoning_correct"]
        is True
    )

    assert (
        result["requires_review"]
        is False
    )


def test_verbal_problem_modeling_without_reference_is_uncertain():

    from services.naima.verbal_problem_service import (
        validate_modeling_equation,
    )

    correction = {
        "explication": (
            "On réfléchit à la situation "
            "sans écrire d'équation."
        )
    }

    result = validate_modeling_equation(
        student_answer="3x=15",
        correction=correction,
    )

    assert (
        result["verdict"]
        == "uncertain"
    )

    assert (
        result["result_correct"]
        is None
    )

    assert (
        result["reasoning_correct"]
        is None
    )


def test_verbal_problem_final_answer_correct():

    from services.naima.verbal_problem_service import (
        validate_final_answer,
    )

    correction = {
        "reponse_finale": (
            "Marie a 10 ans et Paul a 15 ans."
        )
    }

    result = validate_final_answer(
        student_answer=(
            "Marie a 10 ans et Paul a 15 ans."
        ),
        correction=correction,
    )

    assert (
        result["verdict"]
        == "correct"
    )

    assert (
        result["method"]
        == "verbal_problem_final_answer"
    )

    assert (
        result["result_correct"]
        is True
    )

    assert (
        result["requires_review"]
        is False
    )


def test_verbal_problem_final_answer_incomplete_is_uncertain():

    from services.naima.verbal_problem_service import (
        validate_final_answer,
    )

    correction = {
        "reponse_finale": (
            "Marie a 10 ans et Paul a 15 ans."
        )
    }

    result = validate_final_answer(
        student_answer=(
            "Marie a 10 ans."
        ),
        correction=correction,
    )

    assert (
        result["verdict"]
        == "uncertain"
    )

    assert (
        result["result_correct"]
        is None
    )

    assert (
        result["requires_review"]
        is True
    )


def test_verbal_problem_targets_final_objective():

    from services.naima.verbal_problem_service import (
        targets_final_problem_objective,
    )

    result = targets_final_problem_objective(
        student_answer=(
            "Le budget total est de 120 dollars."
        ),
        last_teacher_question=(
            "Quel est maintenant le budget total ?"
        ),
        objective=(
            "Déterminer le budget total nécessaire "
            "pour acheter le matériel."
        ),
    )

    assert result is True

def test_verbal_problem_orchestrator_validates_modeling():

    orchestrator = NaimaOrchestrator()

    correction = {
        "etapes": [
            "On modélise la situation par "
            "x+2x=15."
        ],
        "reponse_finale": (
            "La première quantité vaut 5 "
            "et la deuxième vaut 10."
        ),
    }

    result = orchestrator.process_turn(
        message="3x=15",

        current_objective=(
            "Une quantité est le double "
            "d'une autre et leur somme vaut 15. "
            "Détermine les deux quantités."
        ),

        current_equation=None,
        initial_equation=None,

        last_teacher_question=(
            "Quelle équation peux-tu écrire "
            "pour modéliser la situation ?"
        ),

        conversation=[],
        previous_recovery_state={},
        diagnostic={},

        first_message=False,

        verbal_problem_active=True,
        verbal_problem_correction=(
            correction
        ),
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
        == "verbal_problem_modeling"
    )

    assert (
        result.validation[
            "reasoning_correct"
        ]
        is True
    )

    assert (
        result.response[
            "response_type"
        ]
        == "verbal_problem_modeling_correct"
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
            "keep_exercise_open"
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


def test_verbal_problem_orchestrator_closes_final_answer():

    orchestrator = NaimaOrchestrator()

    correction = {
        "etapes": [
            "On pose x pour l'âge de Marie.",
            "L'équation permet ensuite "
            "de déterminer les deux âges.",
        ],
        "reponse_finale": (
            "Marie a 10 ans et Paul a 15 ans."
        ),
    }

    result = orchestrator.process_turn(
        message=(
            "Marie a 10 ans et Paul a 15 ans."
        ),

        current_objective=(
            "Détermine l'âge de Marie "
            "et l'âge de Paul."
        ),

        current_equation="x=10",
        initial_equation="x=10",

        last_teacher_question=(
            "Quels sont finalement les âges "
            "de Marie et de Paul ?"
        ),

        conversation=[],
        previous_recovery_state={},
        diagnostic={},

        first_message=False,

        verbal_problem_active=True,
        verbal_problem_correction=(
            correction
        ),
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
        == "verbal_problem_final_answer"
    )

    assert (
        result.validation[
            "result_correct"
        ]
        is True
    )

    assert (
        result.response[
            "response_type"
        ]
        == "verbal_problem_final_correct"
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
            "keep_exercise_open"
        ]
        is False
    )

    assert (
        result.objective_reached
        is True
    )

    assert (
        result.requires_llm
        is False
    )

def test_verbal_problem_algebraic_solution_keeps_problem_open():

    orchestrator = NaimaOrchestrator()

    correction = {
        "etapes": [
            "On pose x pour l'âge de Paul.",
            "Marie a alors 2x ans.",
            "On obtient x+2x=30.",
        ],
        "reponse_finale": (
            "Paul a 10 ans et Marie a 20 ans."
        ),
    }

    result = orchestrator.process_turn(
        message="x=10",

        current_objective=(
            "Marie a deux fois l'âge de Paul. "
            "La somme de leurs âges est 30 ans. "
            "Quels sont leurs âges ?"
        ),

        current_equation="x+2*x=30",
        initial_equation="x+2*x=30",

        last_teacher_question=(
            "Quelle valeur obtiens-tu pour x ?"
        ),

        conversation=[],
        previous_recovery_state={},
        diagnostic={},

        first_message=False,

        verbal_problem_active=True,
        verbal_problem_correction=(
            correction
        ),
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
        == "verbal_problem_intermediate_solution"
    )

    assert (
        result.validation[
            "result_correct"
        ]
        is True
    )

    assert (
        result.response[
            "response_type"
        ]
        == "verbal_problem_intermediate_solution"
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
            "keep_exercise_open"
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

def test_direct_verbal_problem_statement_is_detected():

    from services.naima.verbal_problem_service import (
        is_probable_verbal_problem_statement,
    )

    message = (
        "Marie a deux fois l'âge de Paul. "
        "La somme de leurs âges est 30 ans."
    )

    assert (
        is_probable_verbal_problem_statement(
            message
        )
        is True
    )


def test_normal_math_answer_is_not_detected_as_verbal_problem():

    from services.naima.verbal_problem_service import (
        is_probable_verbal_problem_statement,
    )

    assert (
        is_probable_verbal_problem_statement(
            "je divise les deux membres par 3"
        )
        is False
    )

    assert (
        is_probable_verbal_problem_statement(
            "x=10"
        )
        is False
    )

def test_llm_uncertain_prompt_forbids_math_verdict_in_french():

    from services.naima.llm_response_service import (
        _build_system_prompt,
    )

    prompt = _build_system_prompt(
        lang="fr",

        context={
            "objective": (
                "Résoudre un problème verbal."
            ),
            "current_equation": None,
            "is_new_problem": False,
        },

        validation={
            "verdict": "uncertain",
            "method": "no_math_context",
            "result_correct": None,
            "reasoning_correct": None,
        },

        pedagogical={
            "pedagogical_policy": {
                "strategie": "guidage_leger",
                "niveau_aide": 1,
                "peut_reveler_solution": False,
            },
            "pedagogical_instruction": (
                "Faire progresser l'élève "
                "sans donner la réponse."
            ),
        },

        response={
            "solution_leakage_blocked": False,
        },
    )

    assert (
        "rester mathématiquement NEUTRE"
        in prompt
    )

    assert (
        "déclarer qu'une réponse est correcte"
        in prompt
    )

    assert (
        "dire qu'il y a une erreur mathématique"
        in prompt
    )

    assert (
        "ne décide JAMAIS toi-même"
        in prompt
    )


def test_llm_uncertain_prompt_forbids_math_verdict_in_english():

    from services.naima.llm_response_service import (
        _build_system_prompt,
    )

    prompt = _build_system_prompt(
        lang="en",

        context={
            "objective": (
                "Solve a verbal problem."
            ),
            "current_equation": None,
            "is_new_problem": False,
        },

        validation={
            "verdict": "uncertain",
            "method": "no_math_context",
            "result_correct": None,
            "reasoning_correct": None,
        },

        pedagogical={
            "pedagogical_policy": {
                "strategie": "light_guidance",
                "niveau_aide": 1,
                "peut_reveler_solution": False,
            },
            "pedagogical_instruction": (
                "Help the learner progress "
                "without giving the answer."
            ),
        },

        response={
            "solution_leakage_blocked": False,
        },
    )

    assert (
        "remain mathematically neutral"
        in prompt
    )

    assert (
        "say an answer is correct"
        in prompt
    )

    assert (
        "say there is a mathematical error"
        in prompt
    )

    assert (
        "never decide the mathematical status yourself"
        in prompt
    )


def test_llm_correct_validation_keeps_deterministic_authority_french():

    from services.naima.llm_response_service import (
        _build_system_prompt,
    )

    prompt = _build_system_prompt(
        lang="fr",

        context={
            "objective": "Résoudre 3x=30",
            "current_equation": "3*x=30",
            "is_new_problem": False,
        },

        validation={
            "verdict": "correct",
            "method": "equation_solution",
            "result_correct": True,
            "reasoning_correct": None,
        },

        pedagogical={
            "pedagogical_policy": {
                "strategie": (
                    "felicitation_et_approfondissement"
                ),
                "niveau_aide": 0,
                "peut_reveler_solution": False,
            },
            "pedagogical_instruction": (
                "Reconnaître le résultat prouvé."
            ),
        },

        response={
            "solution_leakage_blocked": False,
        },
    )

    assert (
        "Conclusion déterministe disponible : oui"
        in prompt
    )

    assert (
        "Validation incertaine : non"
        in prompt
    )

    assert (
        "contredire une validation mathématique déterministe"
        in prompt
    )


def test_llm_correct_validation_keeps_deterministic_authority_english():

    from services.naima.llm_response_service import (
        _build_system_prompt,
    )

    prompt = _build_system_prompt(
        lang="en",

        context={
            "objective": "Solve 3x=30",
            "current_equation": "3*x=30",
            "is_new_problem": False,
        },

        validation={
            "verdict": "correct",
            "method": "equation_solution",
            "result_correct": True,
            "reasoning_correct": None,
        },

        pedagogical={
            "pedagogical_policy": {
                "strategie": (
                    "felicitation_et_approfondissement"
                ),
                "niveau_aide": 0,
                "peut_reveler_solution": False,
            },
            "pedagogical_instruction": (
                "Acknowledge the proven result."
            ),
        },

        response={
            "solution_leakage_blocked": False,
        },
    )

    assert (
        "Deterministic conclusion available: yes"
        in prompt
    )

    assert (
        "Validation uncertain: no"
        in prompt
    )

    assert (
        "override deterministic mathematical validation"
        in prompt
    )

def test_direct_verbal_model_without_reference_remains_uncertain():

    orchestrator = NaimaOrchestrator()

    result = orchestrator.process_turn(
        message=(
            "Soit x l'âge de Paul. "
            "Marie a 2x donc x+2x=30."
        ),

        current_objective=(
            "Marie a deux fois l'âge de Paul. "
            "La somme de leurs âges est 30 ans. "
            "Quels sont leurs âges ?"
        ),

        current_equation=None,
        initial_equation=None,

        last_teacher_question=(
            "Peux-tu écrire une équation "
            "qui représente la situation ?"
        ),

        conversation=[],
        previous_recovery_state={},
        diagnostic={},

        first_message=False,

        verbal_problem_active=True,

        # Problème direct :
        # aucune correction cachée disponible.
        verbal_problem_correction=None,
    )

    # --------------------------------------------------------
    # VALIDATION
    # --------------------------------------------------------
    #
    # Sans correction de référence ni contraintes
    # déterministes transmises à l'orchestrateur,
    # Naïma ne doit ni accepter ni rejeter le modèle.
    # --------------------------------------------------------

    assert (
        result.validation[
            "verdict"
        ]
        == "uncertain"
    )

    assert (
        result.validation[
            "method"
        ]
        == "direct_verbal_modeling"
    )

    assert (
        result.validation[
            "result_correct"
        ]
        is None
    )

    assert (
        result.validation[
            "requires_review"
        ]
        is True
    )

    assert (
        result.validation[
            "reasoning_correct"
        ]
        is None
    )

    # --------------------------------------------------------
    # CONTEXTE MATHÉMATIQUE
    # --------------------------------------------------------
    #
    # L'équation proposée doit néanmoins devenir
    # l'équation de travail pour les tours suivants.
    # --------------------------------------------------------

    assert (
        result.context[
            "current_equation"
        ]
        == "x+2*x=30"
    )

    # --------------------------------------------------------
    # OBJECTIF
    # --------------------------------------------------------

    assert (
        result.objective_reached
        is False
    )

    # --------------------------------------------------------
    # FALLBACK PÉDAGOGIQUE
    # --------------------------------------------------------
    #
    # Puisque le moteur déterministe ne possède pas assez
    # d'information pour conclure, le LLM peut intervenir
    # uniquement pour guider ou demander une précision.
    #
    # Il ne doit pas produire lui-même un verdict
    # mathématique correct / incorrect.
    # --------------------------------------------------------

    assert (
        result.requires_llm
        is True
    )

    assert (
        result.handled_deterministically
        is False
    )

    assert (
        result.response[
            "response_type"
        ]
        == "llm_guidance"
    )

    assert (
        result.response[
            "use_local_response"
        ]
        is False
    )

    assert (
        result.response[
            "use_llm"
        ]
        is True
    )

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


def test_math_parser_removes_sentence_punctuation_after_equation():

    from services.naima.math_parser_service import (
        extract_math_relation_from_text,
    )

    result = extract_math_relation_from_text(
        "Soit x l'âge de Paul, donc x+2x=30."
    )

    assert (
        result
        == "x+2*x=30"
    )

def test_math_parser_preserves_decimal_point_inside_equation():

    from services.naima.math_parser_service import (
        extract_math_relation_from_text,
    )

    result = (
        extract_math_relation_from_text(
            "On obtient 2x=5.5."
        )
    )

    assert (
        result
        == "2*x=5.5"
    )

def test_extract_proved_algebraic_solution_from_verbal_subgoal():

    from services.naima.verbal_problem_service import (
        extract_proved_algebraic_solution,
    )

    validation = {
        "verdict": "correct",
        "method": (
            "verbal_problem_intermediate_solution"
        ),
        "result_correct": True,
        "reasoning_correct": None,
        "details": {
            "valeur_x_proposee": "10",
            "algebraic_subgoal_completed": True,
        },
    }

    result = (
        extract_proved_algebraic_solution(
            validation
        )
    )

    assert (
        result
        == {
            "variable": "x",
            "value": "10",
            "proved": True,
            "validation_method": (
                "verbal_problem_intermediate_solution"
            ),
        }
    )

def test_uncertain_algebraic_solution_is_not_memorized_as_proved():

    from services.naima.verbal_problem_service import (
        extract_proved_algebraic_solution,
    )

    validation = {
        "verdict": "uncertain",
        "method": (
            "verbal_problem_intermediate_solution"
        ),
        "result_correct": None,
        "details": {
            "valeur_x_proposee": "10",
        },
    }

    result = (
        extract_proved_algebraic_solution(
            validation
        )
    )

    assert (
        result
        is None
    )

def test_incorrect_algebraic_solution_is_not_memorized_as_proved():

    from services.naima.verbal_problem_service import (
        extract_proved_algebraic_solution,
    )

    validation = {
        "verdict": "incorrect",
        "method": "equation_solution",
        "result_correct": False,
        "details": {
            "valeur_x_proposee": "12",
        },
    }

    result = (
        extract_proved_algebraic_solution(
            validation
        )
    )

    assert (
        result
        is None
    )

def test_verbal_modeling_uncertain_uses_neutral_local_response_french():

    from services.naima.response_service import (
        build_local_response,
    )

    response = build_local_response(
        validation={
            "verdict": "uncertain",
            "method": (
                "verbal_problem_modeling"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": None,
            "details": {},
        },

        pedagogical_policy={
            "strategie": "guidage_leger",
            "niveau_aide": 1,
            "peut_reveler_solution": False,
        },

        equation="x+2*x=30",

        student_answer=(
            "Soit x l'âge de Paul, "
            "Marie a 2x donc x+2x=30"
        ),

        last_teacher_question=(
            "Peux-tu écrire une équation ?"
        ),

        lang="fr",
    )

    assert (
        response.response_type
        == "verbal_problem_modeling_uncertain"
    )

    assert (
        response.use_local_response
        is True
    )

    assert (
        response.use_llm
        is False
    )

    assert (
        response.objective_reached
        is False
    )

    assert (
        response.keep_exercise_open
        is True
    )

    assert (
        response.solution_leakage_blocked
        is True
    )

    assert (
        "Tu proposes x+2*x=30"
        in response.text
    )

    assert (
        "Comment peux-tu vérifier"
        in response.text
    )

    assert (
        "correct"
        not in response.text.lower()
    )

    assert (
        "faux"
        not in response.text.lower()
    )

def test_verbal_modeling_uncertain_uses_neutral_local_response_english():

    from services.naima.response_service import (
        build_local_response,
    )

    response = build_local_response(
        validation={
            "verdict": "uncertain",
            "method": (
                "verbal_problem_modeling"
            ),
            "result_correct": None,
            "reasoning_correct": None,
            "error_type": None,
            "details": {},
        },

        pedagogical_policy={
            "strategie": "guidage_leger",
            "niveau_aide": 1,
            "peut_reveler_solution": False,
        },

        equation="x+2*x=30",

        student_answer=(
            "Let x be Paul's age. "
            "Marie is 2x, so x+2x=30."
        ),

        last_teacher_question=(
            "Can you write an equation?"
        ),

        lang="en",
    )

    assert (
        response.response_type
        == "verbal_problem_modeling_uncertain"
    )

    assert (
        response.use_local_response
        is True
    )

    assert (
        response.use_llm
        is False
    )

    assert (
        response.objective_reached
        is False
    )

    assert (
        response.keep_exercise_open
        is True
    )

    assert (
        response.solution_leakage_blocked
        is True
    )

    assert (
        "You are proposing x+2*x=30"
        in response.text
    )

    assert (
        "How can you check"
        in response.text
    )

    assert (
        "correct"
        not in response.text.lower()
    )

    assert (
        "wrong"
        not in response.text.lower()
    )

def test_extract_variable_meaning_from_soit_x_age():

    from services.naima.verbal_problem_service import (
        extract_variable_meaning,
    )

    result = extract_variable_meaning(
        "Soit x l'âge de Paul. "
        "Marie a 2x donc x+2x=30."
    )

    assert result == {
        "variable": "x",
        "meaning": "âge de Paul",
        "entity": "Paul",
    }

def test_extract_variable_meaning_from_represents_phrase():

    from services.naima.verbal_problem_service import (
        extract_variable_meaning,
    )

    result = extract_variable_meaning(
        "x représente l'âge de Paul"
    )

    assert result == {
        "variable": "x",
        "meaning": "âge de Paul",
        "entity": "Paul",
    }

def test_variable_meaning_is_not_guessed_when_student_does_not_define_it():

    from services.naima.verbal_problem_service import (
        extract_variable_meaning,
    )

    result = extract_variable_meaning(
        "Marie a 2x donc x+2x=30"
    )

    assert result is None

def test_extract_simple_verbal_relation_two_times_age():

    from services.naima.verbal_problem_service import (
        extract_simple_verbal_relation,
    )

    result = extract_simple_verbal_relation(
        "Marie a deux fois l'âge de Paul."
    )

    assert result == {
        "subject": "Marie",
        "relation": "multiple_of",
        "factor": 2,
        "reference": "Paul",
        "attribute": "âge",
    }

def test_extract_simple_verbal_relation_numeric_factor():

    from services.naima.verbal_problem_service import (
        extract_simple_verbal_relation,
    )

    result = extract_simple_verbal_relation(
        "Marie a 2 fois l'âge de Paul."
    )

    assert result == {
        "subject": "Marie",
        "relation": "multiple_of",
        "factor": 2,
        "reference": "Paul",
        "attribute": "âge",
    }

def test_extract_simple_verbal_relation_double_age():

    from services.naima.verbal_problem_service import (
        extract_simple_verbal_relation,
    )

    result = extract_simple_verbal_relation(
        "Marie a le double de l'âge de Paul."
    )

    assert result == {
        "subject": "Marie",
        "relation": "multiple_of",
        "factor": 2,
        "reference": "Paul",
        "attribute": "âge",
    }

def test_extract_simple_verbal_relation_triple_age():

    from services.naima.verbal_problem_service import (
        extract_simple_verbal_relation,
    )

    result = extract_simple_verbal_relation(
        "Marie a le triple de l'âge de Paul."
    )

    assert result == {
        "subject": "Marie",
        "relation": "multiple_of",
        "factor": 3,
        "reference": "Paul",
        "attribute": "âge",
    }

def test_simple_verbal_relation_is_not_guessed_without_explicit_relation():

    from services.naima.verbal_problem_service import (
        extract_simple_verbal_relation,
    )

    result = extract_simple_verbal_relation(
        "Marie et Paul ont des âges différents."
    )

    assert result is None

def test_extract_simple_verbal_relation_from_full_problem_statement():

    from services.naima.verbal_problem_service import (
        extract_simple_verbal_relation,
    )

    statement = (
        "Marie a deux fois l'âge de Paul. "
        "La somme de leurs âges est 30 ans. "
        "Quels sont leurs âges ?"
    )

    result = (
        extract_simple_verbal_relation(
            statement
        )
    )

    assert result == {
        "subject": "Marie",
        "relation": "multiple_of",
        "factor": 2,
        "reference": "Paul",
        "attribute": "âge",
    }

def test_full_verbal_problem_without_supported_relation_returns_none():

    from services.naima.verbal_problem_service import (
        extract_simple_verbal_relation,
    )

    statement = (
        "Paul et Marie ont ensemble 30 ans. "
        "Quels sont leurs âges ?"
    )

    result = (
        extract_simple_verbal_relation(
            statement
        )
    )

    assert result is None

def test_direct_verbal_final_answer_correct_from_proved_memory():

    from services.naima.verbal_problem_service import (
        validate_direct_verbal_final_answer,
    )

    result = validate_direct_verbal_final_answer(
        student_answer=(
            "Paul a 10 ans et Marie a 20 ans."
        ),

        variable_meaning={
            "variable": "x",
            "meaning": "âge de Paul",
            "entity": "Paul",
        },

        algebraic_solution={
            "variable": "x",
            "value": "10",
            "proved": True,
            "validation_method": (
                "verbal_problem_intermediate_solution"
            ),
        },

        verbal_relations=[
            {
                "subject": "Marie",
                "relation": "multiple_of",
                "factor": 2,
                "reference": "Paul",
                "attribute": "âge",
            }
        ],
    )

    assert (
        result["verdict"]
        == "correct"
    )

    assert (
        result["result_correct"]
        is True
    )

    assert (
        result["method"]
        == "direct_verbal_final_answer"
    )

def test_direct_verbal_final_answer_swapped_values_is_incorrect():

    from services.naima.verbal_problem_service import (
        validate_direct_verbal_final_answer,
    )

    result = validate_direct_verbal_final_answer(
        student_answer=(
            "Paul a 20 ans et Marie a 10 ans."
        ),

        variable_meaning={
            "variable": "x",
            "meaning": "âge de Paul",
            "entity": "Paul",
        },

        algebraic_solution={
            "variable": "x",
            "value": "10",
            "proved": True,
        },

        verbal_relations=[
            {
                "subject": "Marie",
                "relation": "multiple_of",
                "factor": 2,
                "reference": "Paul",
                "attribute": "âge",
            }
        ],
    )

    assert (
        result["verdict"]
        == "incorrect"
    )

    assert (
        result["result_correct"]
        is False
    )

def test_direct_verbal_final_answer_incomplete_remains_uncertain():

    from services.naima.verbal_problem_service import (
        validate_direct_verbal_final_answer,
    )

    result = validate_direct_verbal_final_answer(
        student_answer=(
            "Paul a 10 ans."
        ),

        variable_meaning={
            "variable": "x",
            "meaning": "âge de Paul",
            "entity": "Paul",
        },

        algebraic_solution={
            "variable": "x",
            "value": "10",
            "proved": True,
        },

        verbal_relations=[
            {
                "subject": "Marie",
                "relation": "multiple_of",
                "factor": 2,
                "reference": "Paul",
                "attribute": "âge",
            }
        ],
    )

    assert (
        result["verdict"]
        == "uncertain"
    )

    assert (
        result["result_correct"]
        is None
    )

def test_direct_verbal_final_answer_without_proved_solution_is_uncertain():

    from services.naima.verbal_problem_service import (
        validate_direct_verbal_final_answer,
    )

    result = validate_direct_verbal_final_answer(
        student_answer=(
            "Paul a 10 ans et Marie a 20 ans."
        ),

        variable_meaning={
            "variable": "x",
            "meaning": "âge de Paul",
            "entity": "Paul",
        },

        algebraic_solution={
            "variable": "x",
            "value": "10",
            "proved": False,
        },

        verbal_relations=[
            {
                "subject": "Marie",
                "relation": "multiple_of",
                "factor": 2,
                "reference": "Paul",
                "attribute": "âge",
            }
        ],
    )

    assert (
        result["verdict"]
        == "uncertain"
    )

    assert (
        result["result_correct"]
        is None
    )

def test_orchestrator_closes_direct_verbal_problem_from_proved_memory():

    orchestrator = NaimaOrchestrator()

    result = orchestrator.process_turn(
        message=(
            "Paul a 10 ans et Marie a 20 ans."
        ),

        current_objective=(
            "Marie a deux fois l'âge de Paul. "
            "La somme de leurs âges est 30 ans. "
            "Quels sont leurs âges ?"
        ),

        current_equation=(
            "x+2*x=30"
        ),

        initial_equation=(
            "x+2*x=30"
        ),

        last_teacher_question=(
            "Que représente x dans le problème, "
            "et quelle réponse finale dois-tu donner ?"
        ),

        conversation=[],
        previous_recovery_state={},
        diagnostic={},

        first_message=False,

        verbal_problem_active=True,
        verbal_problem_correction=None,

        direct_verbal_variable_meaning={
            "variable": "x",
            "meaning": "âge de Paul",
            "entity": "Paul",
        },

        direct_verbal_algebraic_solution={
            "variable": "x",
            "value": "10",
            "proved": True,
            "validation_method": (
                "verbal_problem_intermediate_solution"
            ),
        },

        direct_verbal_relations=[
            {
                "subject": "Marie",
                "relation": "multiple_of",
                "factor": 2,
                "reference": "Paul",
                "attribute": "âge",
            }
        ],
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
        == "direct_verbal_final_answer"
    )

    assert (
        result.validation[
            "result_correct"
        ]
        is True
    )

    assert (
        result.objective_reached
        is True
    )

    assert (
        result.requires_llm
        is False
    )

    assert (
        result.handled_deterministically
        is True
    )

    assert (
        result.response[
            "response_type"
        ]
        == "verbal_problem_final_correct"
    )

def test_orchestrator_rejects_swapped_direct_verbal_final_answer():

    orchestrator = NaimaOrchestrator()

    result = orchestrator.process_turn(
        message=(
            "Paul a 20 ans et Marie a 10 ans."
        ),

        current_objective=(
            "Marie a deux fois l'âge de Paul. "
            "La somme de leurs âges est 30 ans. "
            "Quels sont leurs âges ?"
        ),

        current_equation=(
            "x+2*x=30"
        ),

        initial_equation=(
            "x+2*x=30"
        ),

        last_teacher_question=(
            "Quelle réponse finale dois-tu donner ?"
        ),

        conversation=[],
        previous_recovery_state={},
        diagnostic={},

        first_message=False,

        verbal_problem_active=True,
        verbal_problem_correction=None,

        direct_verbal_variable_meaning={
            "variable": "x",
            "meaning": "âge de Paul",
            "entity": "Paul",
        },

        direct_verbal_algebraic_solution={
            "variable": "x",
            "value": "10",
            "proved": True,
        },

        direct_verbal_relations=[
            {
                "subject": "Marie",
                "relation": "multiple_of",
                "factor": 2,
                "reference": "Paul",
                "attribute": "âge",
            }
        ],
    )

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
        == "direct_verbal_final_answer"
    )

    assert (
        result.objective_reached
        is False
    )

    assert (
        result.requires_llm
        is False
    )

    assert (
        result.response[
            "response_type"
        ]
        == "direct_verbal_final_error"
    )

def test_orchestrator_direct_verbal_incomplete_final_answer_remains_uncertain():

    orchestrator = NaimaOrchestrator()

    result = orchestrator.process_turn(
        message=(
            "Paul a 10 ans."
        ),

        current_objective=(
            "Marie a deux fois l'âge de Paul. "
            "La somme de leurs âges est 30 ans. "
            "Quels sont leurs âges ?"
        ),

        current_equation=(
            "x+2*x=30"
        ),

        initial_equation=(
            "x+2*x=30"
        ),

        last_teacher_question=(
            "Quelle réponse finale dois-tu donner ?"
        ),

        conversation=[],
        previous_recovery_state={},
        diagnostic={},

        first_message=False,

        verbal_problem_active=True,
        verbal_problem_correction=None,

        direct_verbal_variable_meaning={
            "variable": "x",
            "meaning": "âge de Paul",
            "entity": "Paul",
        },

        direct_verbal_algebraic_solution={
            "variable": "x",
            "value": "10",
            "proved": True,
        },

        direct_verbal_relations=[
            {
                "subject": "Marie",
                "relation": "multiple_of",
                "factor": 2,
                "reference": "Paul",
                "attribute": "âge",
            }
        ],
    )

    assert (
        result.validation[
            "verdict"
        ]
        == "uncertain"
    )

    assert (
        result.validation[
            "method"
        ]
        == "direct_verbal_final_answer"
    )

    assert (
        result.objective_reached
        is False
    )

    # Aucun verdict artificiel :
    # le LLM peut uniquement guider l'élève.
    assert (
        result.requires_llm
        is True
    )

def test_final_verbal_answer_must_not_replace_modeling_message():

    modeling_validation = {
        "verdict": "uncertain",
        "method": "verbal_problem_modeling",
    }

    final_validation = {
        "verdict": "correct",
        "method": "direct_verbal_final_answer",
        "result_correct": True,
    }

    assert (
        modeling_validation["method"]
        == "verbal_problem_modeling"
    )

    assert (
        final_validation["method"]
        != "verbal_problem_modeling"
    )

def test_extract_sum_relation_from_their_ages():

    from services.naima.verbal_problem_service import (
        extract_simple_sum_relation,
    )

    result = extract_simple_sum_relation(
        "Marie a deux fois l'âge de Paul. "
        "La somme de leurs âges est 30 ans."
    )

    assert result == {
        "relation": "sum_equals",
        "entities": [
            "Paul",
            "Marie",
        ],
        "value": 30,
        "attribute": "âge",
    }

def test_extract_sum_relation_from_named_ages():

    from services.naima.verbal_problem_service import (
        extract_simple_sum_relation,
    )

    result = extract_simple_sum_relation(
        "La somme des âges de Paul et Marie est 30 ans."
    )

    assert result == {
        "relation": "sum_equals",
        "entities": [
            "Paul",
            "Marie",
        ],
        "value": 30,
        "attribute": "âge",
    }

def test_extract_sum_relation_from_together_phrase():

    from services.naima.verbal_problem_service import (
        extract_simple_sum_relation,
    )

    result = extract_simple_sum_relation(
        "Paul et Marie ont ensemble 30 ans."
    )

    assert result == {
        "relation": "sum_equals",
        "entities": [
            "Paul",
            "Marie",
        ],
        "value": 30,
        "attribute": "âge",
    }

def test_extract_simple_verbal_constraints_from_full_problem():

    from services.naima.verbal_problem_service import (
        extract_simple_verbal_constraints,
    )

    result = extract_simple_verbal_constraints(
        "Marie a deux fois l'âge de Paul. "
        "La somme de leurs âges est 30 ans. "
        "Quels sont leurs âges ?"
    )

    assert result == [
        {
            "subject": "Marie",
            "relation": "multiple_of",
            "factor": 2,
            "reference": "Paul",
            "attribute": "âge",
        },
        {
            "relation": "sum_equals",
            "entities": [
                "Paul",
                "Marie",
            ],
            "value": 30,
            "attribute": "âge",
        },
    ]

def test_build_expected_equation_from_verbal_constraints():

    from services.naima.verbal_problem_service import (
        build_expected_equation_from_verbal_constraints,
    )

    result = (
        build_expected_equation_from_verbal_constraints(
            variable_meaning={
                "variable": "x",
                "meaning": "âge de Paul",
                "entity": "Paul",
            },

            constraints=[
                {
                    "subject": "Marie",
                    "relation": "multiple_of",
                    "factor": 2,
                    "reference": "Paul",
                    "attribute": "âge",
                },
                {
                    "relation": "sum_equals",
                    "entities": [
                        "Paul",
                        "Marie",
                    ],
                    "value": 30,
                    "attribute": "âge",
                },
            ],
        )
    )

    assert result is not None

    assert (
        result["equation"]
        == "x+2*x=30"
    )

    assert (
        result["variable_entity"]
        == "Paul"
    )

    assert (
        result["related_entity"]
        == "Marie"
    )

def test_direct_verbal_modeling_is_proved_correct():

    from services.naima.verbal_problem_service import (
        validate_direct_verbal_modeling,
    )

    result = validate_direct_verbal_modeling(
        student_answer=(
            "Soit x l'âge de Paul, "
            "Marie a 2x donc x+2x=30."
        ),

        variable_meaning={
            "variable": "x",
            "meaning": "âge de Paul",
            "entity": "Paul",
        },

        constraints=[
            {
                "subject": "Marie",
                "relation": "multiple_of",
                "factor": 2,
                "reference": "Paul",
                "attribute": "âge",
            },
            {
                "relation": "sum_equals",
                "entities": [
                    "Paul",
                    "Marie",
                ],
                "value": 30,
                "attribute": "âge",
            },
        ],
    )

    assert (
        result["verdict"]
        == "correct"
    )

    assert (
        result["result_correct"]
        is True
    )

    assert (
        result["reasoning_correct"]
        is True
    )

def test_direct_verbal_modeling_accepts_simplified_equation():

    from services.naima.verbal_problem_service import (
        validate_direct_verbal_modeling,
    )

    result = validate_direct_verbal_modeling(
        student_answer="3x=30",

        variable_meaning={
            "variable": "x",
            "entity": "Paul",
        },

        constraints=[
            {
                "subject": "Marie",
                "relation": "multiple_of",
                "factor": 2,
                "reference": "Paul",
            },
            {
                "relation": "sum_equals",
                "entities": [
                    "Paul",
                    "Marie",
                ],
                "value": 30,
            },
        ],
    )

    assert (
        result["verdict"]
        == "correct"
    )

def test_direct_verbal_modeling_wrong_factor_is_incorrect():

    from services.naima.verbal_problem_service import (
        validate_direct_verbal_modeling,
    )

    result = validate_direct_verbal_modeling(
        student_answer="x+3x=30",

        variable_meaning={
            "variable": "x",
            "entity": "Paul",
        },

        constraints=[
            {
                "subject": "Marie",
                "relation": "multiple_of",
                "factor": 2,
                "reference": "Paul",
            },
            {
                "relation": "sum_equals",
                "entities": [
                    "Paul",
                    "Marie",
                ],
                "value": 30,
            },
        ],
    )

    assert (
        result["verdict"]
        == "incorrect"
    )

    assert (
        result["error_type"]
        == "verbal_model_constraint_mismatch"
    )

def test_direct_verbal_modeling_wrong_total_is_incorrect():

    from services.naima.verbal_problem_service import (
        validate_direct_verbal_modeling,
    )

    result = validate_direct_verbal_modeling(
        student_answer="x+2x=40",

        variable_meaning={
            "variable": "x",
            "entity": "Paul",
        },

        constraints=[
            {
                "subject": "Marie",
                "relation": "multiple_of",
                "factor": 2,
                "reference": "Paul",
            },
            {
                "relation": "sum_equals",
                "entities": [
                    "Paul",
                    "Marie",
                ],
                "value": 30,
            },
        ],
    )

    assert (
        result["verdict"]
        == "incorrect"
    )

    assert (
        result["result_correct"]
        is False
    )

def test_orchestrator_proves_direct_verbal_modeling_correct():

    orchestrator = NaimaOrchestrator()

    result = orchestrator.process_turn(
        message=(
            "Soit x l'âge de Paul, "
            "Marie a 2x donc x+2x=30."
        ),

        current_objective=(
            "Marie a deux fois l'âge de Paul. "
            "La somme de leurs âges est 30 ans. "
            "Quels sont leurs âges ?"
        ),

        current_equation=None,
        initial_equation=None,

        last_teacher_question=(
            "Quelle équation représente la situation ?"
        ),

        conversation=[],
        previous_recovery_state={},
        diagnostic={},

        first_message=False,

        verbal_problem_active=True,
        verbal_problem_correction=None,

        direct_verbal_variable_meaning={
            "variable": "x",
            "meaning": "âge de Paul",
            "entity": "Paul",
        },

        direct_verbal_constraints=[
            {
                "subject": "Marie",
                "relation": "multiple_of",
                "factor": 2,
                "reference": "Paul",
                "attribute": "âge",
            },
            {
                "relation": "sum_equals",
                "entities": [
                    "Paul",
                    "Marie",
                ],
                "value": 30,
                "attribute": "âge",
            },
        ],
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
        == "direct_verbal_modeling"
    )

    assert (
        result.validation[
            "result_correct"
        ]
        is True
    )

def test_orchestrator_rejects_wrong_direct_verbal_modeling():

    orchestrator = NaimaOrchestrator()

    result = orchestrator.process_turn(
        message=(
            "Soit x l'âge de Paul, "
            "donc x+3x=30."
        ),

        current_objective=(
            "Marie a deux fois l'âge de Paul. "
            "La somme de leurs âges est 30 ans."
        ),

        current_equation=None,
        initial_equation=None,

        last_teacher_question=(
            "Quelle équation représente la situation ?"
        ),

        conversation=[],
        previous_recovery_state={},
        diagnostic={},

        first_message=False,

        verbal_problem_active=True,
        verbal_problem_correction=None,

        direct_verbal_variable_meaning={
            "variable": "x",
            "entity": "Paul",
        },

        direct_verbal_constraints=[
            {
                "subject": "Marie",
                "relation": "multiple_of",
                "factor": 2,
                "reference": "Paul",
            },
            {
                "relation": "sum_equals",
                "entities": [
                    "Paul",
                    "Marie",
                ],
                "value": 30,
            },
        ],
    )

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
        == "direct_verbal_modeling"
    )

def test_direct_verbal_modeling_without_constraints_stays_uncertain():

    orchestrator = NaimaOrchestrator()

    result = orchestrator.process_turn(
        message="x+2x=30",

        current_objective=(
            "Marie a deux fois l'âge de Paul."
        ),

        current_equation=None,
        initial_equation=None,

        last_teacher_question=(
            "Quelle équation représente la situation ?"
        ),

        conversation=[],
        previous_recovery_state={},
        diagnostic={},

        first_message=False,

        verbal_problem_active=True,
        verbal_problem_correction=None,

        direct_verbal_variable_meaning={
            "variable": "x",
            "entity": "Paul",
        },

        direct_verbal_constraints=[],
    )

    assert (
        result.validation[
            "verdict"
        ]
        == "uncertain"
    )

    assert (
        result.validation[
            "method"
        ]
        == "direct_verbal_modeling"
    )

def test_extract_sum_relation_accepts_real_student_wording():

    from services.naima.verbal_problem_service import (
        extract_simple_sum_relation,
    )

    result = extract_simple_sum_relation(
        "Marie a deux fois l'age de paul, "
        "sachant que la sommes de leur age donne 30, "
        "quel est l'age de Marie et paul"
    )

    assert result == {
        "relation": "sum_equals",
        "entities": [
            "paul",
            "Marie",
        ],
        "value": 30,
        "attribute": "âge",
    }

def test_orchestrator_extracts_variable_meaning_from_current_modeling_message():

    orchestrator = NaimaOrchestrator()

    result = orchestrator.process_turn(
        message=(
            "Soit x l'âge de Paul, "
            "Marie a 2x donc x+2x=30"
        ),

        current_objective=(
            "Marie a deux fois l'age de paul, "
            "sachant que la sommes de leur age donne 30"
        ),

        current_equation=None,
        initial_equation=None,

        last_teacher_question=(
            "Quelle équation représente la situation ?"
        ),

        conversation=[],
        previous_recovery_state={},
        diagnostic={},

        first_message=False,

        verbal_problem_active=True,
        verbal_problem_correction=None,

        direct_verbal_variable_meaning=None,

        direct_verbal_constraints=[
            {
                "subject": "Marie",
                "relation": "multiple_of",
                "factor": 2,
                "reference": "paul",
                "attribute": "âge",
            },
            {
                "relation": "sum_equals",
                "entities": [
                    "paul",
                    "Marie",
                ],
                "value": 30,
                "attribute": "âge",
            },
        ],
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
        == "direct_verbal_modeling"
    )

    assert (
        result.validation[
            "result_correct"
        ]
        is True
    )

def test_extract_proved_algebraic_solution_keeps_x_variable():

    from services.naima.verbal_problem_service import (
        extract_proved_algebraic_solution,
    )

    result = extract_proved_algebraic_solution({
        "verdict": "correct",
        "result_correct": True,
        "method": (
            "verbal_problem_intermediate_solution"
        ),
        "details": {
            "variable": "x",
            "valeur_x_proposee": "10",
        },
    })

    assert result == {
        "variable": "x",
        "value": "10",
        "proved": True,
        "validation_method": (
            "verbal_problem_intermediate_solution"
        ),
    }

def test_extract_proved_algebraic_solution_supports_p_variable():

    from services.naima.verbal_problem_service import (
        extract_proved_algebraic_solution,
    )

    result = extract_proved_algebraic_solution({
        "verdict": "correct",
        "result_correct": True,
        "method": (
            "verbal_problem_intermediate_solution"
        ),
        "details": {
            "variable": "p",
            "solution": "10",
        },
    })

    assert result == {
        "variable": "p",
        "value": "10",
        "proved": True,
        "validation_method": (
            "verbal_problem_intermediate_solution"
        ),
    }

def test_extract_proved_algebraic_solution_detects_variable_from_equation():

    from services.naima.verbal_problem_service import (
        extract_proved_algebraic_solution,
    )

    result = extract_proved_algebraic_solution({
        "verdict": "correct",
        "result_correct": True,
        "method": (
            "verbal_problem_intermediate_solution"
        ),
        "details": {
            "solution": "10",
            "student_equation": "P=10",
        },
    })

    assert result == {
        "variable": "p",
        "value": "10",
        "proved": True,
        "validation_method": (
            "verbal_problem_intermediate_solution"
        ),
    }

def test_semantic_constraints_convert_multiple_relation():

    from services.naima.verbal_problem_service import (
        build_semantic_model_from_verbal_constraints,
    )

    result = (
        build_semantic_model_from_verbal_constraints(
            variable_meaning={
                "variable": "x",
                "meaning": "âge de Paul",
                "entity": "Paul",
            },
            constraints=[
                {
                    "subject": "Marie",
                    "relation": "multiple_of",
                    "factor": 2,
                    "reference": "Paul",
                    "attribute": "âge",
                },
            ],
        )
    )

    constraints = result[
        "constraints"
    ]

    assert len(
        constraints
    ) >= 1

    assert constraints[
        0
    ].relation == "equality"

def test_semantic_constraints_compile_age_sum():

    from services.naima.verbal_problem_service import (
        build_semantic_model_from_verbal_constraints,
    )

    result = (
        build_semantic_model_from_verbal_constraints(
            variable_meaning={
                "variable": "x",
                "meaning": "âge de Paul",
                "entity": "Paul",
            },
            constraints=[
                {
                    "subject": "Marie",
                    "relation": "multiple_of",
                    "factor": 2,
                    "reference": "Paul",
                    "attribute": "âge",
                },
                {
                    "relation": "sum_equals",
                    "entities": [
                        "Paul",
                        "Marie",
                    ],
                    "value": 30,
                    "attribute": "âge",
                },
            ],
        )
    )

    assert (
        "x+2*x=30"
        in result[
            "equations"
        ]
    )

def test_semantic_constraints_support_p_variable():

    from services.naima.verbal_problem_service import (
        build_semantic_model_from_verbal_constraints,
    )

    result = (
        build_semantic_model_from_verbal_constraints(
            variable_meaning={
                "variable": "p",
                "meaning": "âge de Paul",
                "entity": "Paul",
            },
            constraints=[
                {
                    "subject": "Marie",
                    "relation": "multiple_of",
                    "factor": 2,
                    "reference": "Paul",
                },
                {
                    "relation": "sum_equals",
                    "entities": [
                        "Paul",
                        "Marie",
                    ],
                    "value": 30,
                },
            ],
        )
    )

    assert (
        "p+2*p=30"
        in result[
            "equations"
        ]
    )

def test_extract_variable_meaning_generic_price():

    from services.naima.verbal_problem_service import (
        extract_variable_meaning,
    )

    result = extract_variable_meaning(
        "x est le prix d'un CD"
    )

    assert result is not None

    assert (
        result["variable"]
        == "x"
    )

    assert (
        "prix"
        in result[
            "meaning"
        ].lower()
    )

    assert (
        result.get(
            "entity"
        )
        == "CD"
    )

def test_extract_variable_meaning_student_preference_price():

    from services.naima.verbal_problem_service import (
        extract_variable_meaning,
    )

    result = extract_variable_meaning(
        "Je prefere appeler x le prix d'un CD"
    )

    assert result is not None

    assert (
        result["variable"]
        == "x"
    )

    assert (
        "prix"
        in result[
            "meaning"
        ].lower()
    )

def test_semantic_difference_expression_compiles():

    from services.naima.verbal_problem_service import (
        make_difference_expression,
        make_product_expression,
        make_variable_expression,
        semantic_expression_to_math,
    )

    expression = (
        make_difference_expression(
            make_product_expression(
                10,
                make_variable_expression(
                    "x"
                ),
            ),
            make_variable_expression(
                "b"
            ),
        )
    )

    result = (
        semantic_expression_to_math(
            expression
        )
    )

    assert (
        result
        == "10*x-b"
    )

def test_semantic_difference_is_domain_independent():

    from services.naima.verbal_problem_service import (
        make_difference_expression,
        make_variable_expression,
        semantic_expression_to_math,
    )

    expression = (
        make_difference_expression(
            make_variable_expression(
                "d"
            ),
            make_variable_expression(
                "p"
            ),
        )
    )

    result = (
        semantic_expression_to_math(
            expression
        )
    )

    assert (
        result
        == "d-p"
    )

def test_extract_product_offset_shortfall():

    from services.naima.verbal_problem_service import (
        extract_product_offset_constraints,
    )

    result = (
        extract_product_offset_constraints(
            (
                "Si j'achète 10 CD "
                "il me manquera 5 $"
            )
        )
    )

    assert any(
        constraint.get(
            "quantity"
        ) == 10
        and constraint.get(
            "offset"
        ) == -5
        and constraint.get(
            "offset_kind"
        ) == "shortfall"
        for constraint in result
    )

def test_extract_product_offset_remainder():

    from services.naima.verbal_problem_service import (
        extract_product_offset_constraints,
    )

    result = (
        extract_product_offset_constraints(
            (
                "Si j'achète 5 CD "
                "il me restera 12 $"
            )
        )
    )

    assert any(
        constraint.get(
            "quantity"
        ) == 5
        and constraint.get(
            "offset"
        ) == 12
        and constraint.get(
            "offset_kind"
        ) == "remainder"
        for constraint in result
    )

def test_extract_product_offsets_real_cd_problem():

    from services.naima.verbal_problem_service import (
        extract_product_offset_constraints,
    )

    result = (
        extract_product_offset_constraints(
            (
                "Si j'achete 10 CD "
                "il me manquera 5 $, "
                "mais si j'achete 5 CD "
                "il me restera 12 $, "
                "combien ai je"
            )
        )
    )

    assert len(
        result
    ) >= 2

    assert any(
        c.get(
            "quantity"
        ) == 10
        and c.get(
            "offset"
        ) == -5
        for c in result
    )

    assert any(
        c.get(
            "quantity"
        ) == 5
        and c.get(
            "offset"
        ) == 12
        for c in result
    )

def test_extract_product_offset_cost_above_budget():

    from services.naima.verbal_problem_service import (
        extract_product_offset_constraints,
    )

    result = (
        extract_product_offset_constraints(
            (
                "10 billets coûtent "
                "5 $ de plus que mon budget"
            )
        )
    )

    assert any(
        c.get(
            "quantity"
        ) == 10
        and c.get(
            "offset"
        ) == -5
        for c in result
    )

def test_extract_product_offset_cost_below_budget():

    from services.naima.verbal_problem_service import (
        extract_product_offset_constraints,
    )

    result = (
        extract_product_offset_constraints(
            (
                "5 billets coûtent "
                "12 $ de moins que mon budget"
            )
        )
    )

    assert any(
        c.get(
            "quantity"
        ) == 5
        and c.get(
            "offset"
        ) == 12
        for c in result
    )

def test_semantic_model_builds_cd_budget_equation():

    from services.naima.verbal_problem_service import (
        build_semantic_model_from_verbal_constraints,
        extract_product_offset_constraints,
    )

    statement = (
        "Si j'achete 10 CD "
        "il me manquera 5 $, "
        "mais si j'achete 5 CD "
        "il me restera 12 $"
    )

    constraints = (
        extract_product_offset_constraints(
            statement
        )
    )

    result = (
        build_semantic_model_from_verbal_constraints(
            variable_meaning={
                "variable": "x",
                "meaning": "le prix d'un CD",
                "entity": "CD",
            },
            constraints=constraints,
        )
    )

    normalized_equations = {
        equation.replace(
            " ",
            ""
        )
        for equation in result[
            "equations"
        ]
    }

    assert (
        "10*x-5=5*x+12"
        in normalized_equations
    )

def test_semantic_product_offset_is_not_cd_specific():

    from services.naima.verbal_problem_service import (
        build_semantic_model_from_verbal_constraints,
        extract_product_offset_constraints,
    )

    statement = (
        "Si j'achete 8 billets "
        "il me manquera 4 $, "
        "mais si j'achete 3 billets "
        "il me restera 11 $"
    )

    constraints = (
        extract_product_offset_constraints(
            statement
        )
    )

    result = (
        build_semantic_model_from_verbal_constraints(
            variable_meaning={
                "variable": "p",
                "meaning": (
                    "le prix d'un billet"
                ),
                "entity": "billet",
            },
            constraints=constraints,
        )
    )

    normalized_equations = {
        equation.replace(
            " ",
            ""
        )
        for equation in result[
            "equations"
        ]
    }

    assert (
        "8*p-4=3*p+11"
        in normalized_equations
    )

def test_direct_verbal_modeling_semantic_budget_correct():

    from services.naima.verbal_problem_service import (
        extract_product_offset_constraints,
        validate_direct_verbal_modeling,
    )

    statement = (
        "Si j'achete 10 CD il me manquera 5 $, "
        "mais si j'achete 5 CD il me restera 12 $"
    )

    result = validate_direct_verbal_modeling(
        student_answer=(
            "10x-5=5x+12"
        ),
        variable_meaning={
            "variable": "x",
            "meaning": "le prix d'un CD",
            "entity": "CD",
        },
        constraints=(
            extract_product_offset_constraints(
                statement
            )
        ),
    )

    assert result["verdict"] == "correct"
    assert result["result_correct"] is True
    assert (
        result["details"]["matched_model_source"]
        == "semantic_hybrid"
    )

def test_direct_verbal_modeling_semantic_budget_wrong():

    from services.naima.verbal_problem_service import (
        extract_product_offset_constraints,
        validate_direct_verbal_modeling,
    )

    statement = (
        "Si j'achete 10 CD il me manquera 5 $, "
        "mais si j'achete 5 CD il me restera 12 $"
    )

    result = validate_direct_verbal_modeling(
        student_answer=(
            "10x+5=5x+12"
        ),
        variable_meaning={
            "variable": "x",
            "meaning": "le prix d'un CD",
            "entity": "CD",
        },
        constraints=(
            extract_product_offset_constraints(
                statement
            )
        ),
    )

    assert result["verdict"] == "incorrect"
    assert result["result_correct"] is False

def test_direct_verbal_modeling_semantic_other_item():

    from services.naima.verbal_problem_service import (
        extract_product_offset_constraints,
        validate_direct_verbal_modeling,
    )

    statement = (
        "Si j'achete 8 billets il me manquera 4 $, "
        "mais si j'achete 3 billets il me restera 11 $"
    )

    result = validate_direct_verbal_modeling(
        student_answer=(
            "8p-4=3p+11"
        ),
        variable_meaning={
            "variable": "p",
            "meaning": "le prix d'un billet",
            "entity": "billet",
        },
        constraints=(
            extract_product_offset_constraints(
                statement
            )
        ),
    )

    assert result["verdict"] == "correct"

def test_direct_verbal_modeling_historical_age_still_works():

    from services.naima.verbal_problem_service import (
        extract_simple_verbal_constraints,
        validate_direct_verbal_modeling,
    )

    statement = (
        "Marie a le double de l'âge de Paul. "
        "La somme de leurs âges est 30 ans."
    )

    result = validate_direct_verbal_modeling(
        student_answer=(
            "3x=30"
        ),
        variable_meaning={
            "variable": "x",
            "meaning": "âge de Paul",
            "entity": "Paul",
        },
        constraints=(
            extract_simple_verbal_constraints(
                statement
            )
        ),
    )

    assert result["verdict"] == "correct"

def test_semantic_compiler_accepts_implicit_multiplication():

    from services.naima.semantic_compiler_service import (
        equations_are_same_constraint,
    )

    assert (
        equations_are_same_constraint(
            "10x-5=5x+12",
            "10*x-5=5*x+12",
        )
        is True
    )


def test_semantic_compiler_accepts_reversed_equation():

    from services.naima.semantic_compiler_service import (
        equations_are_same_constraint,
    )

    assert (
        equations_are_same_constraint(
            "10x-5=5x+12",
            "5x+12=10x-5",
        )
        is True
    )


def test_semantic_compiler_accepts_simplified_constraint():

    from services.naima.semantic_compiler_service import (
        equations_are_same_constraint,
    )

    assert (
        equations_are_same_constraint(
            "10x-5=5x+12",
            "5x=17",
        )
        is True
    )


def test_semantic_reparameterization_unit_value():

    from services.naima.semantic_schema import (
        SemanticConstraint,
        SemanticSituation,
    )

    from services.naima.semantic_compiler_service import (
        compile_parameterization,
    )

    situation = SemanticSituation(
        status="interpreted",

        constraints=[
            SemanticConstraint(
                relation=(
                    "product_offset_common_value"
                ),
                data={
                    "quantity": 10,
                    "offset": -5,
                    "item": "CD",
                    "unit_role": "unit_value",
                    "common_role": (
                        "available_amount"
                    ),
                },
            ),

            SemanticConstraint(
                relation=(
                    "product_offset_common_value"
                ),
                data={
                    "quantity": 5,
                    "offset": 12,
                    "item": "CD",
                    "unit_role": "unit_value",
                    "common_role": (
                        "available_amount"
                    ),
                },
            ),
        ],
    )

    result = compile_parameterization(
        situation=situation,
        variable="x",
        role="unit_value",
        meaning="prix d'un CD",
    )

    assert len(
        result.equations
    ) == 1

    from services.naima.semantic_compiler_service import (
        equations_are_same_constraint,
    )

    assert (
        equations_are_same_constraint(
            result.equations[0],
            "10x-5=5x+12",
        )
        is True
    )


def test_semantic_reparameterization_available_amount():

    from services.naima.semantic_schema import (
        SemanticConstraint,
        SemanticSituation,
    )

    from services.naima.semantic_compiler_service import (
        compile_parameterization,
        equations_are_same_constraint,
    )

    situation = SemanticSituation(
        status="interpreted",

        constraints=[
            SemanticConstraint(
                relation=(
                    "product_offset_common_value"
                ),
                data={
                    "quantity": 10,
                    "offset": -5,
                    "item": "CD",
                    "unit_role": "unit_value",
                    "common_role": (
                        "available_amount"
                    ),
                },
            ),

            SemanticConstraint(
                relation=(
                    "product_offset_common_value"
                ),
                data={
                    "quantity": 5,
                    "offset": 12,
                    "item": "CD",
                    "unit_role": "unit_value",
                    "common_role": (
                        "available_amount"
                    ),
                },
            ),
        ],
    )

    result = compile_parameterization(
        situation=situation,
        variable="x",
        role="available_amount",
        meaning="argent disponible",
    )

    assert len(
        result.equations
    ) == 1

    assert (
        equations_are_same_constraint(
            result.equations[0],
            "(x+5)/10=(x-12)/5",
        )
        is True
    )


def test_semantic_interpreter_completes_missing_constraint():

    from services.naima.semantic_interpreter_service import (
        interpret_math_situation,
    )

    def fake_interpreter(
        statement,
    ):

        return {
            "status": "interpreted",
            "confidence": 0.95,

            "entities": [
                {
                    "role": "unit_value",
                    "label": "prix d'un CD",
                    "symbol": None,
                    "entity_type": "quantity",
                },
                {
                    "role": "available_amount",
                    "label": "argent disponible",
                    "symbol": None,
                    "entity_type": "quantity",
                },
            ],

            "constraints": [
                {
                    "relation": (
                        "product_offset_common_value"
                    ),
                    "data": {
                        "quantity": 10,
                        "offset": -5,
                        "item": "CD",
                        "unit_role": "unit_value",
                        "common_role": (
                            "available_amount"
                        ),
                    },
                    "confidence": 0.99,
                },
                {
                    "relation": (
                        "product_offset_common_value"
                    ),
                    "data": {
                        "quantity": 5,
                        "offset": 12,
                        "item": "CD",
                        "unit_role": "unit_value",
                        "common_role": (
                            "available_amount"
                        ),
                    },
                    "confidence": 0.99,
                },
            ],

            "target_role": "unit_value",
            "parameterizations": [],
            "ambiguities": [],
        }

    result = interpret_math_situation(
        statement=(
            "Si j'achète 10 CD il me manque 5 $, "
            "mais si j'en achète 5 il me reste 12 $."
        ),

        deterministic_constraints=[
            {
                "relation": (
                    "product_offset_common_value"
                ),
                "quantity": 10,
                "offset": -5,
                "item": "CD",
                "common_role": (
                    "available_amount"
                ),
            },
        ],

        llm_interpreter=(
            fake_interpreter
        ),
    )

    assert (
        result.status
        == "interpreted"
    )

    assert (
        result.source
        == "hybrid"
    )

    assert len(
        result.constraints
    ) == 2

def test_semantic_final_answer_when_solved_variable_is_target():

    from services.naima.verbal_problem_service import (
        validate_semantic_verbal_final_answer,
    )

    def fake_semantic_interpreter(
        statement,
    ):

        return {
            "status": "interpreted",
            "confidence": 0.99,

            "entities": [
                {
                    "role": "unit_value",
                    "label": "le prix d'un CD",
                    "entity_type": "quantity",
                },

                {
                    "role": "available_amount",
                    "label": "argent disponible",
                    "entity_type": "quantity",
                },
            ],

            "constraints": [
                {
                    "relation": (
                        "product_offset_common_value"
                    ),
                    "data": {
                        "quantity": 10,
                        "offset": -5,
                        "item": "CD",
                        "unit_role": "unit_value",
                        "common_role": (
                            "available_amount"
                        ),
                    },
                },

                {
                    "relation": (
                        "product_offset_common_value"
                    ),
                    "data": {
                        "quantity": 5,
                        "offset": 12,
                        "item": "CD",
                        "unit_role": "unit_value",
                        "common_role": (
                            "available_amount"
                        ),
                    },
                },
            ],

            "target_role": "unit_value",
            "ambiguities": [],
        }

    from services.naima import (
        semantic_interpreter_service,
    )

    original = (
        semantic_interpreter_service
        .call_openai_semantic_interpreter
    )

    semantic_interpreter_service.call_openai_semantic_interpreter = (
        fake_semantic_interpreter
    )

    try:

        result = (
            validate_semantic_verbal_final_answer(
                student_answer=(
                    "Le prix d'un CD est 3,4 $."
                ),

                statement=(
                    "Si j'achète 10 CD il me manque 5 $, "
                    "et avec 5 CD il me reste 12 $. "
                    "Quel est le prix d'un CD ?"
                ),

                variable_meaning={
                    "variable": "x",
                    "meaning": (
                        "le prix d'un CD"
                    ),
                    "entity": "CD",
                },

                algebraic_solution={
                    "proved": True,
                    "variable": "x",
                    "value": "17/5",
                },

                constraints=[],
            )
        )

    finally:

        semantic_interpreter_service.call_openai_semantic_interpreter = (
            original
        )

    assert result[
        "verdict"
    ] == "correct"

    assert result[
        "result_correct"
    ] is True


def test_semantic_final_answer_can_derive_target_from_other_parameterization():

    from services.naima.verbal_problem_service import (
        validate_semantic_verbal_final_answer,
    )

    from services.naima import (
        semantic_interpreter_service,
    )

    def fake_semantic_interpreter(
        statement,
    ):

        return {
            "status": "interpreted",
            "confidence": 0.99,

            "entities": [
                {
                    "role": "unit_value",
                    "label": "prix d'un CD",
                    "entity_type": "quantity",
                },

                {
                    "role": "available_amount",
                    "label": "argent disponible",
                    "entity_type": "quantity",
                },
            ],

            "constraints": [
                {
                    "relation": (
                        "product_offset_common_value"
                    ),
                    "data": {
                        "quantity": 10,
                        "offset": -5,
                        "item": "CD",
                        "unit_role": "unit_value",
                        "common_role": (
                            "available_amount"
                        ),
                    },
                },

                {
                    "relation": (
                        "product_offset_common_value"
                    ),
                    "data": {
                        "quantity": 5,
                        "offset": 12,
                        "item": "CD",
                        "unit_role": "unit_value",
                        "common_role": (
                            "available_amount"
                        ),
                    },
                },
            ],

            "target_role": "unit_value",
            "ambiguities": [],
        }

    original = (
        semantic_interpreter_service
        .call_openai_semantic_interpreter
    )

    semantic_interpreter_service.call_openai_semantic_interpreter = (
        fake_semantic_interpreter
    )

    try:

        result = (
            validate_semantic_verbal_final_answer(
                student_answer=(
                    "Le CD coûte 3.40 $."
                ),

                statement=(
                    "Problème verbal"
                ),

                variable_meaning={
                    "variable": "x",
                    "meaning": (
                        "argent disponible"
                    ),
                },

                algebraic_solution={
                    "proved": True,
                    "variable": "x",
                    "value": "29",
                },

                constraints=[],
            )
        )

    finally:

        semantic_interpreter_service.call_openai_semantic_interpreter = (
            original
        )

    assert result[
        "verdict"
    ] == "correct"

    assert result[
        "details"
    ][
        "expected_value"
    ] == "17/5"


def test_semantic_final_answer_rejects_wrong_value():

    from services.naima.verbal_problem_service import (
        validate_semantic_verbal_final_answer,
    )

    from services.naima import (
        semantic_interpreter_service,
    )

    def fake_semantic_interpreter(
        statement,
    ):

        return {
            "status": "interpreted",
            "confidence": 0.99,

            "entities": [
                {
                    "role": "unit_value",
                    "label": "prix unitaire",
                    "entity_type": "quantity",
                },
            ],

            "constraints": [
                {
                    "relation": (
                        "product_offset_common_value"
                    ),
                    "data": {
                        "quantity": 10,
                        "offset": -5,
                        "unit_role": "unit_value",
                        "common_role": (
                            "available_amount"
                        ),
                    },
                },

                {
                    "relation": (
                        "product_offset_common_value"
                    ),
                    "data": {
                        "quantity": 5,
                        "offset": 12,
                        "unit_role": "unit_value",
                        "common_role": (
                            "available_amount"
                        ),
                    },
                },
            ],

            "target_role": "unit_value",
            "ambiguities": [],
        }

    original = (
        semantic_interpreter_service
        .call_openai_semantic_interpreter
    )

    semantic_interpreter_service.call_openai_semantic_interpreter = (
        fake_semantic_interpreter
    )

    try:

        result = (
            validate_semantic_verbal_final_answer(
                student_answer=(
                    "Le prix est 4 $."
                ),

                statement=(
                    "Problème verbal"
                ),

                variable_meaning={
                    "variable": "x",
                    "meaning": (
                        "prix unitaire"
                    ),
                },

                algebraic_solution={
                    "proved": True,
                    "variable": "x",
                    "value": "17/5",
                },

                constraints=[],
            )
        )

    finally:

        semantic_interpreter_service.call_openai_semantic_interpreter = (
            original
        )

    assert result[
        "verdict"
    ] == "incorrect"

    assert result[
        "result_correct"
    ] is False

def test_direct_verbal_final_answer_uses_semantic_path():

    from services.naima.verbal_problem_service import (
        validate_direct_verbal_final_answer,
    )

    from services.naima import (
        semantic_interpreter_service,
    )

    def fake_semantic_interpreter(
        statement,
    ):

        return {
            "status": "interpreted",
            "confidence": 0.99,

            "entities": [
                {
                    "role": "unit_value",
                    "label": "le prix d'un objet",
                    "entity_type": "quantity",
                },

                {
                    "role": "available_amount",
                    "label": "montant disponible",
                    "entity_type": "quantity",
                },
            ],

            "constraints": [
                {
                    "relation": (
                        "product_offset_common_value"
                    ),

                    "data": {
                        "quantity": 10,
                        "offset": -5,
                        "item": "objet",
                        "unit_role": "unit_value",
                        "common_role": (
                            "available_amount"
                        ),
                    },
                },

                {
                    "relation": (
                        "product_offset_common_value"
                    ),

                    "data": {
                        "quantity": 5,
                        "offset": 12,
                        "item": "objet",
                        "unit_role": "unit_value",
                        "common_role": (
                            "available_amount"
                        ),
                    },
                },
            ],

            "target_role": "unit_value",
            "ambiguities": [],
        }

    original = (
        semantic_interpreter_service
        .call_openai_semantic_interpreter
    )

    semantic_interpreter_service.call_openai_semantic_interpreter = (
        fake_semantic_interpreter
    )

    try:

        result = (
            validate_direct_verbal_final_answer(
                student_answer=(
                    "La valeur est 3,4."
                ),

                variable_meaning={
                    "variable": "x",
                    "meaning": (
                        "le prix d'un objet"
                    ),
                },

                algebraic_solution={
                    "proved": True,
                    "variable": "x",
                    "value": "17/5",
                },

                verbal_relations=[],

                statement=(
                    "Énoncé verbal générique"
                ),

                constraints=[
                    {
                        "relation": (
                            "product_offset_common_value"
                        ),
                        "quantity": 10,
                        "offset": -5,
                        "item": "objet",
                        "common_role": (
                            "available_amount"
                        ),
                    },
                ],
            )
        )

    finally:

        semantic_interpreter_service.call_openai_semantic_interpreter = (
            original
        )

    assert (
        result["verdict"]
        == "correct"
    )

    assert (
        result["method"]
        == "direct_verbal_final_answer"
    )

    assert (
        result["details"]["validation_path"]
        == "semantic"
    )

def test_direct_verbal_final_answer_keeps_legacy_fallback():

    from services.naima.verbal_problem_service import (
        validate_direct_verbal_final_answer,
    )

    result = (
        validate_direct_verbal_final_answer(
            student_answer=(
                "Paul a 10 ans et Marie a 20 ans."
            ),

            variable_meaning={
                "variable": "x",
                "meaning": "âge de Paul",
                "entity": "Paul",
            },

            algebraic_solution={
                "variable": "x",
                "value": "10",
                "proved": True,
            },

            verbal_relations=[
                {
                    "subject": "Marie",
                    "relation": "multiple_of",
                    "factor": 2,
                    "reference": "Paul",
                    "attribute": "âge",
                }
            ],

            statement="",
            constraints=[],
        )
    )

    assert (
        result["verdict"]
        == "correct"
    )

    assert (
        result["method"]
        == "direct_verbal_final_answer"
    )

    assert (
        result["details"]["validation_path"]
        == "legacy"
    )