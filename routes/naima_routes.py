from __future__ import annotations

from typing import Any, Dict, Optional
from datetime import datetime
from html import escape

from flask import (
    Blueprint,
    jsonify,
    request,
    session,
)

from services.naima.orchestrator import (
    NaimaOrchestrator,
)

from services.naima.llm_response_service import (
    generate_llm_response,
)

from services.naima.math_parser_service import (
    extract_math_relation_from_text,
)


# ============================================================
# BLUEPRINT
# ============================================================

naima_v2_bp = Blueprint(
    "naima_v2",
    __name__,
    url_prefix="/api/naima/v2",
)


_orchestrator = NaimaOrchestrator()


# ============================================================
# OUTILS DE SESSION
# ============================================================

def _is_authenticated_student() -> bool:
    """
    Vérification minimale d'authentification.

    Cette route parallèle v2 ne vérifie pour l'instant
    que la présence de user_id en session.

    La vérification complète du rôle élève sera réalisée
    au moment de l'intégration finale avec /enseignant-virtuel.
    """

    return bool(
        session.get("user_id")
    )


def _json_error(
    message: str,
    status_code: int,
):
    """
    Réponse JSON d'erreur standardisée.
    """

    return (
        jsonify({
            "ok": False,
            "error": message,
        }),
        status_code,
    )


def _get_json_payload() -> Dict[str, Any]:
    """
    Lit le payload de manière tolérante.

    Accepte :
    - JSON pour /api/naima/v2/turn ;
    - formulaire HTML/AJAX historique pour /enseignant-virtuel.
    """

    payload = request.get_json(
        silent=True
    )

    if isinstance(
        payload,
        dict,
    ):
        return payload

    if request.form:
        return {
            key: request.form.get(key)
            for key in request.form.keys()
        }

    return {}


def _clean_message(
    value: Any,
) -> str:
    """
    Nettoyage minimal du message élève.
    """

    return str(
        value
        or ""
    ).strip()


# ============================================================
# CONVERSATION
# ============================================================

def _get_conversation() -> list:
    """
    Compatibilité temporaire entre :

        conversation_naima
        conversation

    Pendant la migration, les deux formats sont acceptés.
    """

    conversation = session.get(
        "conversation_naima"
    )

    if not isinstance(
        conversation,
        list,
    ):

        conversation = session.get(
            "conversation",
            [],
        )

    if not isinstance(
        conversation,
        list,
    ):
        conversation = []

    return list(
        conversation
    )


def _set_conversation(
    conversation: list,
) -> None:
    """
    Synchronise temporairement les deux clés
    de conversation pendant la migration.
    """

    conversation = list(
        conversation
        or []
    )

    session[
        "conversation_naima"
    ] = conversation

    session[
        "conversation"
    ] = conversation

    session.modified = True


# ============================================================
# QUESTION PRÉCÉDENTE
# ============================================================

def _get_last_teacher_question() -> str:
    """
    Compatibilité avec les différentes clés historiques.
    """

    return str(
        session.get(
            "derniere_question_naima"
        )
        or session.get(
            "derniere_question_ia_naima"
        )
        or session.get(
            "derniere_q_ia"
        )
        or ""
    )


# ============================================================
# PREMIER MESSAGE
# ============================================================

def _get_first_message() -> bool:
    """
    Si aucune clé n'existe encore, on considère
    qu'il s'agit du premier message.
    """

    return bool(
        session.get(
            "premier_message_naima",
            True,
        )
    )


# ============================================================
# RECOVERY
# ============================================================

def _get_recovery_state() -> Dict[str, Any]:
    """
    Récupère l'état longitudinal de récupération.
    """

    value = session.get(
        "recuperation_apprentissage_naima"
    )

    if not isinstance(
        value,
        dict,
    ):
        return {}

    return dict(
        value
    )


# ============================================================
# DIAGNOSTIC
# ============================================================

def _get_diagnostic(
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Pour cette première intégration :

    1. accepte un diagnostic fourni dans la requête ;
    2. sinon récupère un diagnostic déjà présent en session ;
    3. sinon retourne {}.

    Le diagnostic bayésien complet sera raccordé
    plus tard.
    """

    diagnostic = payload.get(
        "diagnostic"
    )

    if isinstance(
        diagnostic,
        dict,
    ):
        return diagnostic

    diagnostic = session.get(
        "diagnostic_naima"
    )

    if isinstance(
        diagnostic,
        dict,
    ):
        return diagnostic

    diagnostic = session.get(
        "diagnostic_bayesien"
    )

    if isinstance(
        diagnostic,
        dict,
    ):
        return diagnostic

    return {}


# ============================================================
# APPLICATION DU RÉSULTAT À LA SESSION
# ============================================================

def _apply_turn_to_session(
    *,
    message: str,
    turn_result,
) -> None:
    """
    Persiste le résultat de NaimaOrchestrator.

    Cette fonction ne décide rien mathématiquement.
    Elle ne fait que mémoriser les décisions déjà prises
    par les services v2.
    """

    result = (
        turn_result.to_dict()
    )

    context = (
        result.get(
            "context"
        )
        or {}
    )

    pedagogical = (
        result.get(
            "pedagogical"
        )
        or {}
    )

    response = (
        result.get(
            "response"
        )
        or {}
    )

    intent = (
        result.get(
            "intent"
        )
        or {}
    )

    # --------------------------------------------------------
    # INTENTION
    # --------------------------------------------------------

    session[
        "intention_pedagogique_naima_v2"
    ] = intent

    # --------------------------------------------------------
    # CONTEXTE MATHÉMATIQUE
    # --------------------------------------------------------

    current_equation = (
        context.get(
            "current_equation"
        )
    )

    initial_equation = (
        context.get(
            "initial_equation"
        )
    )

    if current_equation:

        session[
            "equation_courante_naima"
        ] = current_equation

    if initial_equation:

        session[
            "equation_initiale_naima"
        ] = initial_equation

    # --------------------------------------------------------
    # OBJECTIF
    # --------------------------------------------------------
    #
    # IMPORTANT : lorsqu'un nouveau problème est détecté,
    # l'objectif précédent ne doit jamais gagner sur le
    # nouveau message. Le contexte de l'orchestrateur peut
    # encore contenir l'ancien objectif au moment de la
    # transition entre deux exercices.
    #
    # Exemple :
    #   ancien objectif : resoudre 3x=5
    #   nouveau message : resoudre -2x>6
    #
    # Dans ce cas, on persiste le NOUVEAU message comme
    # objectif pédagogique de référence.
    # --------------------------------------------------------

    if context.get(
        "is_new_problem"
    ):

        session[
            "objectif_initial_naima"
        ] = message

    elif (
        not session.get(
            "objectif_initial_naima"
        )
        and current_equation
    ):

        session[
            "objectif_initial_naima"
        ] = (
            context.get(
                "objective"
            )
            or message
        )

    # --------------------------------------------------------
    # ÉTAT COMPORTEMENTAL
    # --------------------------------------------------------

    behavioral_state = (
        pedagogical.get(
            "behavioral_state"
        )
    )

    if isinstance(
        behavioral_state,
        dict,
    ):

        session[
            "etat_comportemental_naima"
        ] = behavioral_state

    # --------------------------------------------------------
    # CONTRÔLE COGNITIF
    # --------------------------------------------------------

    cognitive_control = (
        pedagogical.get(
            "cognitive_control"
        )
    )

    if isinstance(
        cognitive_control,
        dict,
    ):

        session[
            "controle_cognitif_naima"
        ] = cognitive_control

    # --------------------------------------------------------
    # POLITIQUE PÉDAGOGIQUE
    # --------------------------------------------------------

    pedagogical_policy = (
        pedagogical.get(
            "pedagogical_policy"
        )
    )

    if isinstance(
        pedagogical_policy,
        dict,
    ):

        session[
            "politique_pedagogique_naima"
        ] = pedagogical_policy

    # --------------------------------------------------------
    # RECOVERY
    # --------------------------------------------------------

    recovery_state = (
        pedagogical.get(
            "recovery_state"
        )
    )

    if isinstance(
        recovery_state,
        dict,
    ):

        session[
            "recuperation_apprentissage_naima"
        ] = recovery_state

    recovery_summary = (
        pedagogical.get(
            "recovery_summary"
        )
    )

    if isinstance(
        recovery_summary,
        dict,
    ):

        session[
            "resume_recuperation_naima"
        ] = recovery_summary

    # --------------------------------------------------------
    # INDICES
    # --------------------------------------------------------

    recent_hint_count = (
        pedagogical.get(
            "recent_hint_count"
        )
    )

    if recent_hint_count is not None:

        session[
            "nb_indices_recents_naima"
        ] = int(
            recent_hint_count
            or 0
        )

    # Compatibilité avec l'ancienne clé
    session[
        "naima_nb_indices_recents"
    ] = int(
        session.get(
            "nb_indices_recents_naima",
            0,
        )
        or 0
    )

    # --------------------------------------------------------
    # VALIDATION
    # --------------------------------------------------------

    session[
        "validation_naima_v2"
    ] = (
        result.get(
            "validation"
        )
        or {}
    )

    session[
        "response_decision_naima_v2"
    ] = response

    session[
        "equation_type_naima_v2"
    ] = result.get(
        "equation_type"
    )

    # --------------------------------------------------------
    # OBJECTIF TERMINÉ
    # --------------------------------------------------------

    session[
        "objectif_atteint_naima"
    ] = bool(
        result.get(
            "objective_reached"
        )
    )

    # --------------------------------------------------------
    # PREMIER MESSAGE
    # --------------------------------------------------------

    session[
        "premier_message_naima"
    ] = False

    session.modified = True


# ============================================================
# AJOUT À LA CONVERSATION
# ============================================================

def _append_response_to_conversation(
    *,
    student_message: str,
    assistant_message: Optional[str],
) -> None:
    """
    Ajoute le message élève et la réponse finale
    de Naima à l'historique.

    La réponse peut provenir :
    - du moteur déterministe local ;
    - du fallback LLM.
    """

    conversation = (
        _get_conversation()
    )

    conversation.append(
        f"👤 Élève: {student_message}"
    )

    if assistant_message:

        conversation.append(
            f"🤖 Naima: {assistant_message}"
        )

    conversation = (
        conversation[-40:]
    )

    _set_conversation(
        conversation
    )


# ============================================================
# RESET SESSION NAIMA V2
# ============================================================

def _reset_naima_v2_session() -> None:
    """
    Réinitialise uniquement le contexte Naima v2.

    Ne supprime jamais :
    - user_id ;
    - rôle ;
    - authentification ;
    - langue ;
    - autres données générales de l'élève.
    """

    keys = [
        "objectif_initial_naima",
        "objectif_atteint_naima",

        "equation_courante_naima",
        "equation_initiale_naima",

        "derniere_question_naima",
        "derniere_question_ia_naima",
        "derniere_q_ia",

        "premier_message_naima",

        "recuperation_apprentissage_naima",
        "resume_recuperation_naima",

        "nb_indices_recents_naima",
        "naima_nb_indices_recents",

        "etat_comportemental_naima",
        "controle_cognitif_naima",
        "politique_pedagogique_naima",

        "validation_naima_v2",
        "response_decision_naima_v2",
        "llm_response_naima_v2",
        "equation_type_naima_v2",

        "intention_pedagogique_naima_v2",
    ]

    for key in keys:

        session.pop(
            key,
            None,
        )

    session[
        "premier_message_naima"
    ] = True

    session.modified = True



# ============================================================
# ADAPTATEUR D'AFFICHAGE LEGACY
# ============================================================

def _format_legacy_messages(
    conversation: list,
) -> list:
    """
    Reproduit le format HTML attendu par
    templates/enseignant_virtuel.html.

    La migration v2 peut ainsi être activée sans
    modifier immédiatement le JavaScript historique.
    """

    time_str = datetime.now().strftime(
        "%H:%M"
    )

    html_messages = []

    for item in (
        conversation
        or []
    )[-10:]:

        text = str(
            item
            or ""
        )

        if (
            "👤 Élève:" in text
            or "👤 Student:" in text
        ):

            content = (
                text
                .replace(
                    "👤 Élève:",
                    "",
                )
                .replace(
                    "👤 Student:",
                    "",
                )
                .strip()
            )

            html_messages.append(
                '<div class="message user">'
                '<div class="message-avatar">'
                '<i class="fas fa-user-graduate"></i>'
                '</div>'
                '<div class="message-content">'
                f'{escape(content)}'
                '<div class="message-time">'
                f'{time_str}'
                '</div>'
                '</div>'
                '</div>'
            )

        elif "🤖 Naima:" in text:

            content = (
                text
                .replace(
                    "🤖 Naima:",
                    "",
                )
                .strip()
            )

            html_messages.append(
                '<div class="message naima">'
                '<div class="message-avatar">'
                '<i class="fas fa-robot"></i>'
                '</div>'
                '<div class="message-content">'
                f'{escape(content)}'
                '<div class="message-time">'
                f'{time_str}'
                '</div>'
                '</div>'
                '</div>'
            )

    return html_messages


def reset_naima_v2_state(
    *,
    preserve_conversation: bool = False,
) -> None:
    """
    Point d'entrée public utilisé pendant la migration
    par l'ancienne route /reset-chat.

    Ne touche jamais aux informations d'authentification.
    """

    conversation = (
        _get_conversation()
        if preserve_conversation
        else []
    )

    _reset_naima_v2_session()

    _set_conversation(
        conversation
    )


def naima_v2_legacy_ajax_response():
    """
    Adaptateur temporaire entre :

        POST /enseignant-virtuel

    et :

        moteur Naima v2

    Le moteur v2 traite le tour, puis cette fonction
    reformate uniquement la réponse HTTP afin de conserver
    le contrat JSON attendu par l'interface historique.

    Aucune décision mathématique n'est prise ici.
    """

    raw_response = (
        naima_v2_turn()
    )

    status_code = 200
    response_object = raw_response

    if isinstance(
        raw_response,
        tuple,
    ):

        response_object = (
            raw_response[0]
        )

        if len(
            raw_response
        ) > 1:
            status_code = int(
                raw_response[1]
                or 200
            )

    elif hasattr(
        raw_response,
        "status_code",
    ):

        status_code = int(
            raw_response.status_code
            or 200
        )

    try:
        data = (
            response_object.get_json()
            or {}
        )
    except Exception:
        data = {}

    if (
        status_code >= 400
        or not data.get(
            "ok",
            False,
        )
    ):
        return raw_response

    conversation = (
        _get_conversation()
    )

    messages_html = (
        _format_legacy_messages(
            conversation
        )
    )

    return jsonify({
        # --------------------------------------------------------
        # CONTRAT HISTORIQUE DE L'INTERFACE
        # --------------------------------------------------------
        "success": True,

        "messages": (
            messages_html
        ),

        "last_message": (
            messages_html[-1]
            if messages_html
            else ""
        ),

        "matiere": session.get(
            "matiere",
            "mathématiques",
        ),

        "termine": bool(
            data.get(
                "objective_reached",
                False,
            )
        ),

        "diagnostic_bayesien": session.get(
            "diagnostic_bayesien"
        ),

        "signaux_bayesiens": session.get(
            "signaux_bayesiens"
        ),

        "verification_calcul": session.get(
            "verification_calcul"
        ),

        "objectif_initial_naima": session.get(
            "objectif_initial_naima"
        ),

        "mode_pedagogique_naima": session.get(
            "mode_pedagogique_naima"
        ),

        "lecon_courante_naima": session.get(
            "lecon_courante_naima"
        ),

        "exercice_en_cours": session.get(
            "exercice_en_cours"
        ),

        "naima_processus_connecte": session.get(
            "naima_processus_connecte"
        ),

        # --------------------------------------------------------
        # DEBUG MIGRATION V2
        # --------------------------------------------------------
        "engine": "naima_v2",

        "naima_v2": {
            "reply": data.get(
                "reply"
            ),
            "requires_llm": data.get(
                "requires_llm",
                False,
            ),
            "llm_used": data.get(
                "llm_used",
                False,
            ),
            "handled_deterministically": data.get(
                "handled_deterministically",
                False,
            ),
            "objective_reached": data.get(
                "objective_reached",
                False,
            ),
            "intent": data.get(
                "intent"
            ),
            "context": data.get(
                "context"
            ),
            "validation": data.get(
                "validation"
            ),
            "response": data.get(
                "response"
            ),
        },
    })


# ============================================================
# POST /api/naima/v2/turn
# ============================================================

@naima_v2_bp.route(
    "/turn",
    methods=["POST"],
)
def naima_v2_turn():
    """
    Route parallèle de test Naima v2.

    Cette route ne remplace pas encore :

        /enseignant-virtuel

    Elle permet de vérifier la chaîne :

        Flask
        → Session
        → Intent
        → Context
        → MathRouter
        → Validation
        → PedagogicalPipeline
        → ResponseService
    """

    # --------------------------------------------------------
    # AUTHENTIFICATION
    # --------------------------------------------------------

    if not _is_authenticated_student():

        return _json_error(
            "Non authentifié",
            401,
        )

    # --------------------------------------------------------
    # PAYLOAD
    # --------------------------------------------------------

    payload = (
        _get_json_payload()
    )

    message = (
        _clean_message(
            payload.get(
                "message"
            )
            or payload.get(
                "question"
            )
        )
    )

    if not message:

        return _json_error(
            "Message vide",
            400,
        )

    # --------------------------------------------------------
    # RESET OPTIONNEL
    # --------------------------------------------------------

    if payload.get(
        "reset"
    ) is True:

        _reset_naima_v2_session()

        # Un reset demandé sur /turn représente
        # un nouveau contexte pédagogique propre.
        _set_conversation([])

    # --------------------------------------------------------
    # ÉTAT COURANT
    # --------------------------------------------------------

    conversation = (
        _get_conversation()
    )

    current_objective = (
        session.get(
            "objectif_initial_naima"
        )
    )

    current_equation = (
        session.get(
            "equation_courante_naima"
        )
    )

    initial_equation = (
        session.get(
            "equation_initiale_naima"
        )
    )

    # --------------------------------------------------------
    # GARDE DE NOUVEL OBJECTIF AVANT ORCHESTRATION
    # --------------------------------------------------------
    #
    # Le nouvel objectif doit être fourni à l'orchestrateur
    # AVANT un éventuel fallback LLM. Sinon le prompt du même
    # tour peut encore recevoir l'objectif de l'exercice
    # précédent.
    #
    # On ne considère ici comme nouveau problème qu'une
    # relation mathématique explicitement extraite du message
    # et différente de l'équation courante. Les réponses
    # finales du type "x=5/3" ou "x<-3" sont déjà protégées
    # par extract_math_relation_from_text(), qui ne les traite
    # pas comme de nouveaux énoncés.
    # --------------------------------------------------------

    try:
        relation_message = (
            extract_math_relation_from_text(
                message
            )
        )
    except Exception:
        relation_message = None

    new_problem_before_orchestration = bool(
        relation_message
        and (
            not current_equation
            or relation_message
            != current_equation
        )
    )

    if new_problem_before_orchestration:
        current_objective = message

    previous_recovery_state = (
        _get_recovery_state()
    )

    recent_hint_count = int(
        session.get(
            "nb_indices_recents_naima",
            session.get(
                "naima_nb_indices_recents",
                0,
            ),
        )
        or 0
    )

    first_message = (
        _get_first_message()
    )

    last_teacher_question = (
        _get_last_teacher_question()
    )

    current_lang = (
        session.get(
            "lang",
            "fr",
        )
        or "fr"
    )

    diagnostic = (
        _get_diagnostic(
            payload
        )
    )

    expected_answer = (
        payload.get(
            "expected_answer"
        )
    )

    # --------------------------------------------------------
    # ORCHESTRATEUR
    # --------------------------------------------------------

    try:

        turn_result = (
            _orchestrator.process_turn(

                message=(
                    message
                ),

                current_objective=(
                    current_objective
                ),

                current_equation=(
                    current_equation
                ),

                initial_equation=(
                    initial_equation
                ),

                last_teacher_question=(
                    last_teacher_question
                ),

                conversation=(
                    conversation
                ),

                previous_recovery_state=(
                    previous_recovery_state
                ),

                diagnostic=(
                    diagnostic
                ),

                recent_hint_count=(
                    recent_hint_count
                ),

                first_message=(
                    first_message
                ),

                expected_answer=(
                    expected_answer
                ),

                lang=(
                    current_lang
                ),
            )
        )

    except Exception as exc:

        return (
            jsonify({
                "ok": False,
                "error": (
                    "Erreur interne Naima v2"
                ),
                "error_type": (
                    type(
                        exc
                    ).__name__
                ),
                "detail": str(
                    exc
                ),
            }),
            500,
        )

    # --------------------------------------------------------
    # PERSISTANCE SESSION
    # --------------------------------------------------------

    _apply_turn_to_session(

        message=(
            message
        ),

        turn_result=(
            turn_result
        ),
    )

    result = (
        turn_result.to_dict()
    )

    response_data = (
        result.get(
            "response"
        )
        or {}
    )

    local_text = (
        response_data.get(
            "text"
        )
    )

    reply_text = (
        local_text
    )

    llm_data = None
    llm_used = False

    # --------------------------------------------------------
    # FALLBACK LLM
    # --------------------------------------------------------
    #
    # Le moteur déterministe garde toujours la priorité.
    #
    # Le LLM n'est appelé que lorsque l'orchestrateur
    # a explicitement décidé :
    #
    #     requires_llm = True
    #
    # Le LLM ne revalide jamais les mathématiques.
    # Il formule uniquement la réponse pédagogique.
    # --------------------------------------------------------

    if result.get(
        "requires_llm",
        False,
    ):

        llm_result = generate_llm_response(
            message=message,

            context=(
                result.get(
                    "context"
                )
                or {}
            ),

            validation=(
                result.get(
                    "validation"
                )
                or {}
            ),

            pedagogical=(
                result.get(
                    "pedagogical"
                )
                or {}
            ),

            response=(
                response_data
            ),

            conversation=(
                conversation
            ),

            last_teacher_question=(
                last_teacher_question
            ),

            lang=(
                current_lang
            ),

            matiere=(
                payload.get(
                    "matiere"
                )
                or "mathématiques"
            ),

            niveau=(
                payload.get(
                    "niveau"
                )
                or session.get(
                    "niveau"
                )
                or "secondaire"
            ),
        )

        llm_data = (
            llm_result.to_dict()
        )

        reply_text = (
            llm_result.text
        )

        llm_used = True

        session[
            "llm_response_naima_v2"
        ] = llm_data

    else:

        session.pop(
            "llm_response_naima_v2",
            None,
        )

    # --------------------------------------------------------
    # CONVERSATION
    # --------------------------------------------------------
    #
    # Le message élève et la réponse finale de Naima
    # sont ajoutés une seule fois, qu'elle soit locale
    # ou produite par le fallback LLM.
    # --------------------------------------------------------

    _append_response_to_conversation(
        student_message=(
            message
        ),
        assistant_message=(
            reply_text
        ),
    )

    # --------------------------------------------------------
    # DERNIÈRE QUESTION DE NAIMA
    # --------------------------------------------------------

    if (
        reply_text
        and "?" in reply_text
    ):

        session[
            "derniere_question_naima"
        ] = reply_text

        session[
            "derniere_question_ia_naima"
        ] = reply_text

        # Compatibilité historique
        session[
            "derniere_q_ia"
        ] = reply_text

    elif result.get(
        "objective_reached"
    ):

        session.pop(
            "derniere_question_naima",
            None,
        )

        session.pop(
            "derniere_question_ia_naima",
            None,
        )

        session.pop(
            "derniere_q_ia",
            None,
        )

    session.modified = True

    # --------------------------------------------------------
    # RÉPONSE HTTP
    # --------------------------------------------------------

    return jsonify({
        "ok": True,

        "engine": (
            "naima_v2"
        ),

        "message": (
            message
        ),

        "reply": (
            reply_text
        ),

        "llm_used": (
            llm_used
        ),

        "llm": (
            llm_data
        ),

        "requires_llm": (
            result.get(
                "requires_llm",
                False,
            )
        ),

        "handled_deterministically": (
            result.get(
                "handled_deterministically",
                False,
            )
        ),

        "objective_reached": (
            result.get(
                "objective_reached",
                False,
            )
        ),

        "intent": (
            result.get(
                "intent"
            )
        ),

        "context": (
            result.get(
                "context"
            )
        ),

        "validation": (
            result.get(
                "validation"
            )
        ),

        "pedagogical": (
            result.get(
                "pedagogical"
            )
        ),

        "response": (
            response_data
        ),
    })


# ============================================================
# GET /api/naima/v2/state
# ============================================================

@naima_v2_bp.route(
    "/state",
    methods=["GET"],
)
def naima_v2_state():
    """
    Retourne l'état courant de Naima v2.

    Cette route est uniquement destinée
    au debug et aux tests d'intégration
    pendant la migration.
    """

    if not _is_authenticated_student():

        return _json_error(
            "Non authentifié",
            401,
        )

    return jsonify({
        "ok": True,

        "engine": (
            "naima_v2"
        ),

        "objective": session.get(
            "objectif_initial_naima"
        ),

        "objective_reached": session.get(
            "objectif_atteint_naima",
            False,
        ),

        "current_equation": session.get(
            "equation_courante_naima"
        ),

        "initial_equation": session.get(
            "equation_initiale_naima"
        ),

        "equation_type": session.get(
            "equation_type_naima_v2"
        ),

        "first_message": (
            _get_first_message()
        ),

        "last_teacher_question": (
            _get_last_teacher_question()
        ),

        "recent_hint_count": int(
            session.get(
                "nb_indices_recents_naima",
                session.get(
                    "naima_nb_indices_recents",
                    0,
                ),
            )
            or 0
        ),

        "recovery_state": (
            _get_recovery_state()
        ),

        "behavioral_state": session.get(
            "etat_comportemental_naima"
        ),

        "cognitive_control": session.get(
            "controle_cognitif_naima"
        ),

        "pedagogical_policy": session.get(
            "politique_pedagogique_naima"
        ),

        "validation": session.get(
            "validation_naima_v2"
        ),

        "response_decision": session.get(
            "response_decision_naima_v2"
        ),

        "llm_response": session.get(
            "llm_response_naima_v2"
        ),

        "intent": session.get(
            "intention_pedagogique_naima_v2"
        ),

        "conversation": (
            _get_conversation()
        ),
    })


# ============================================================
# POST /api/naima/v2/reset
# ============================================================

@naima_v2_bp.route(
    "/reset",
    methods=["POST"],
)
def naima_v2_reset():
    """
    Réinitialise l'état Naima v2.

    Par défaut :
        la conversation est conservée.

    Pour supprimer également la conversation :

        {
            "preserve_conversation": false
        }
    """

    if not _is_authenticated_student():

        return _json_error(
            "Non authentifié",
            401,
        )

    payload = (
        _get_json_payload()
    )

    preserve_conversation = bool(
        payload.get(
            "preserve_conversation",
            True,
        )
    )

    if preserve_conversation:

        conversation = (
            _get_conversation()
        )

    else:

        conversation = []

    # --------------------------------------------------------
    # RESET DU CONTEXTE V2
    # --------------------------------------------------------

    _reset_naima_v2_session()

    # --------------------------------------------------------
    # CONVERSATION
    # --------------------------------------------------------

    if preserve_conversation:

        _set_conversation(
            conversation
        )

    else:

        _set_conversation(
            []
        )

    session.modified = True

    return jsonify({
        "ok": True,

        "engine": (
            "naima_v2"
        ),

        "reset": True,

        "conversation_preserved": (
            preserve_conversation
        ),

        "first_message": True,

        "current_equation": None,

        "initial_equation": None,

        "objective": None,
    })