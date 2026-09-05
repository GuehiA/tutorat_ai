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

from services.naima.verbal_problem_service import (
    extract_proved_algebraic_solution,
    extract_simple_verbal_relation,
    extract_simple_verbal_constraints,
    extract_variable_meaning,
    is_probable_verbal_problem_statement,
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
# PROBLÈME VERBAL SAISI DIRECTEMENT
# ============================================================

def _get_direct_verbal_problem() -> Dict[str, Any]:
    """
    Retourne le problème verbal éventuellement mémorisé
    depuis un message direct de l'élève.

    IMPORTANT :

    L'énoncé original est la source canonique du problème.

    La mémoire structurée peut avoir été créée :
        - avec une ancienne version de l'extracteur ;
        - à partir d'une extraction partielle ;
        - avant qu'une nouvelle relation déterministe
          soit reconnue.

    À chaque lecture, on ré-extrait donc prudemment les
    contraintes depuis l'énoncé canonique puis on les
    FUSIONNE avec les contraintes déjà mémorisées.

    On ne supprime jamais une contrainte existante ici.

    Cela permet notamment de réparer automatiquement une
    ancienne session contenant une représentation partielle.

    Aucune relation n'est inventée :
    seules les relations reconnues déterministiquement
    depuis l'énoncé original peuvent être ajoutées.
    """

    value = session.get(
        "probleme_verbal_naima_v2"
    )

    if not isinstance(
        value,
        dict,
    ):
        return {}

    if not value.get(
        "active"
    ):
        return {}

    problem = dict(
        value
    )

    # ========================================================
    # 1. ÉNONCÉ CANONIQUE
    # ========================================================

    statement = str(
        problem.get(
            "statement"
        )
        or ""
    ).strip()

    if not statement:

        return problem

    changed = False

    # ========================================================
    # 2. RÉ-EXTRACTION DES CONTRAINTES
    # ========================================================
    #
    # L'extraction est déterministe.
    #
    # Elle peut maintenant reconnaître des informations
    # qu'une version précédente du moteur avait manquées.
    # ========================================================

    try:

        extracted_constraints = (
            extract_simple_verbal_constraints(
                statement
            )
        )

    except Exception:

        extracted_constraints = []

    existing_constraints = list(
        problem.get(
            "verbal_constraints",
            [],
        )
        or []
    )

    merged_constraints = list(
        existing_constraints
    )

    for constraint in (
        extracted_constraints
    ):

        if not isinstance(
            constraint,
            dict,
        ):
            continue

        if (
            constraint
            not in merged_constraints
        ):

            merged_constraints.append(
                constraint
            )

            changed = True

    if (
        merged_constraints
        != existing_constraints
    ):

        problem[
            "verbal_constraints"
        ] = (
            merged_constraints
        )

        changed = True

    # ========================================================
    # 3. RÉ-EXTRACTION DE LA RELATION HISTORIQUE EXPLICITE
    # ========================================================
    #
    # Cette structure reste utile au moteur legacy.
    #
    # Elle ne remplace pas le nouveau modèle sémantique.
    # ========================================================

    try:

        extracted_relation = (
            extract_simple_verbal_relation(
                statement
            )
        )

    except Exception:

        extracted_relation = None

    existing_relations = list(
        problem.get(
            "verbal_relations",
            [],
        )
        or []
    )

    merged_relations = list(
        existing_relations
    )

    if (
        isinstance(
            extracted_relation,
            dict,
        )
        and extracted_relation
        not in merged_relations
    ):

        merged_relations.append(
            extracted_relation
        )

        changed = True

    if (
        merged_relations
        != existing_relations
    ):

        problem[
            "verbal_relations"
        ] = (
            merged_relations
        )

        changed = True

    # ========================================================
    # 4. AUTO-RÉPARATION DE LA SESSION
    # ========================================================
    #
    # On ne réécrit la session que si son contenu a réellement
    # changé, afin d'éviter des écritures inutiles.
    # ========================================================

    if changed:

        session[
            "probleme_verbal_naima_v2"
        ] = problem

        session.modified = True

    return problem

def _store_direct_verbal_problem(
    statement: str,
) -> None:
    """
    Mémorise un énoncé verbal présenté directement
    par l'élève.

    IMPORTANT :
    aucune correction de référence n'est inventée.

    Les relations verbales explicitement détectées dans
    l'énoncé peuvent être mémorisées comme faits structurés,
    mais uniquement lorsqu'elles sont reconnues de manière
    déterministe.
    """

    statement = str(
        statement
        or ""
    ).strip()

    # --------------------------------------------------------
    # EXTRACTION D'UNE RELATION VERBALE EXPLICITE
    # --------------------------------------------------------
    #
    # Exemple :
    #
    #     Marie a deux fois l'âge de Paul.
    #
    # devient :
    #
    #     {
    #         "subject": "Marie",
    #         "relation": "multiple_of",
    #         "factor": 2,
    #         "reference": "Paul",
    #         "attribute": "âge",
    #     }
    #
    # Si aucune relation explicite n'est reconnue,
    # aucune relation n'est inventée.
    # --------------------------------------------------------

    verbal_relation = (
        extract_simple_verbal_relation(
            statement
        )
    )

    verbal_relations = []

    if verbal_relation:

        verbal_relations.append(
            verbal_relation
        )

    # --------------------------------------------------------
    # CONTRAINTES VERBALES COMPLÈTES
    # --------------------------------------------------------

    verbal_constraints = (
        extract_simple_verbal_constraints(
            statement
        )
    )

    session[
        "probleme_verbal_naima_v2"
    ] = {
        "active": True,

        "statement": statement,

        "correction": None,

        "source": (
            "student_message"
        ),

        # ----------------------------------------------------
        # MODÉLISATION
        # ----------------------------------------------------

        "model_equation": None,

        "modeling_message": None,

        "variable_meaning": None,

        "model_status": None,

        "model_validation_method": None,

        "model_validation_verdict": None,

        "model_proved_correct": False,

        # ----------------------------------------------------
        # RELATIONS VERBALES EXPLICITES
        # ----------------------------------------------------

        "verbal_relations": (
            verbal_relations
        ),

        "verbal_constraints": (
            verbal_constraints
        ),

        # ----------------------------------------------------
        # RÉSOLUTION ALGÉBRIQUE
        # ----------------------------------------------------

        "algebraic_solution": None,
    }

    session.modified = True



def _update_direct_verbal_problem_variable_meaning(
    *,
    message: str,
) -> None:
    """
    Mémorise la signification explicite d'une variable
    dans un problème verbal direct.

    La recherche se fait d'abord dans le message courant.

    Si le message courant ne contient pas la définition,
    on examine également les derniers messages de l'élève
    afin de récupérer une définition récente comme :

        "Soit x l'âge de Paul"

    Cette récupération reste déterministe :
    aucune signification de variable n'est inventée.
    """

    message = str(
        message
        or ""
    ).strip()

    problem = (
        _get_direct_verbal_problem()
    )

    if not problem:
        return

    if (
        problem.get(
            "source"
        )
        != "student_message"
    ):
        return

    if problem.get(
        "correction"
    ):
        return

    # --------------------------------------------------------
    # NE PAS ÉCRASER UNE SIGNIFICATION DÉJÀ MÉMORISÉE
    # --------------------------------------------------------

    existing_meaning = (
        problem.get(
            "variable_meaning"
        )
    )

    if isinstance(
        existing_meaning,
        dict,
    ) and existing_meaning.get(
        "variable"
    ):

        return

    # --------------------------------------------------------
    # 1. MESSAGE COURANT
    # --------------------------------------------------------

    variable_meaning = None

    if message:

        variable_meaning = (
            extract_variable_meaning(
                message
            )
        )

    # --------------------------------------------------------
    # 2. HISTORIQUE RÉCENT DE L'ÉLÈVE
    # --------------------------------------------------------
    #
    # Exemple :
    #
    # tour précédent :
    #
    #   Soit x l'âge de Paul...
    #
    # tour courant :
    #
    #   x+2x=30
    #
    # --------------------------------------------------------

    if not variable_meaning:

        conversation = (
            _get_conversation()
        )

        for item in reversed(
            conversation[-12:]
        ):

            text = str(
                item
                or ""
            ).strip()

            if not (
                text.startswith(
                    "👤 Élève:"
                )
                or text.startswith(
                    "👤 Student:"
                )
            ):
                continue

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

            if not student_text:
                continue

            variable_meaning = (
                extract_variable_meaning(
                    student_text
                )
            )

            if variable_meaning:
                break

    if not variable_meaning:
        return

    problem[
        "variable_meaning"
    ] = variable_meaning

    session[
        "probleme_verbal_naima_v2"
    ] = problem

    session.modified = True


def _update_direct_verbal_problem_model(
    *,
    equation: Optional[str],
    modeling_message: str = "",
    validation: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Mémorise l'équation proposée par l'élève comme
    modèle de travail d'un problème verbal direct.

    IMPORTANT :
    cette fonction ne déclare jamais la modélisation correcte
    par elle-même.

    La vérité mathématique provient exclusivement de la
    validation reçue.

    Lorsqu'une modélisation est prouvée par le moteur
    sémantique générique, le rôle sémantique associé à la
    variable peut également être mémorisé.

    Exemple générique :

        variable :
            x

        équation proposée :
            ...

        validation :
            matched_role = "unit_value"

    devient dans la mémoire :

        variable_meaning = {
            "variable": "x",
            "meaning": "...",
            "semantic_role": "unit_value",
        }

    IMPORTANT :

    Le rôle n'est jamais déduit ici à partir du vocabulaire
    métier.

    Il est uniquement mémorisé lorsqu'il a déjà été établi
    par le moteur de validation déterministe.
    """

    if not equation:
        return

    problem = (
        _get_direct_verbal_problem()
    )

    if not problem:
        return

    # Un exercice généré possédant une correction de référence
    # ne relève pas de cette mémoire "directe".
    if problem.get(
        "correction"
    ):
        return

    validation = dict(
        validation
        or {}
    )

    # ========================================================
    # MÉTHODE DE VALIDATION COURANTE
    # ========================================================

    validation_method = (
        validation.get(
            "method"
        )
    )

    # ========================================================
    # NE MODIFIER LE MODÈLE QUE LORS D'UNE VALIDATION
    # DE MODÉLISATION
    # ========================================================
    #
    # Une validation ultérieure comme :
    #
    #     equation_solution
    #     verbal_problem_intermediate_solution
    #     direct_verbal_final_answer
    #
    # ne doit jamais écraser l'état du modèle.
    # ========================================================

    if validation_method not in {
        "verbal_problem_modeling",
        "direct_verbal_modeling",
    }:
        return

    # ========================================================
    # 1. ÉQUATION DE MODÈLE
    # ========================================================

    problem[
        "model_equation"
    ] = str(
        equation
    ).strip()

    modeling_message = str(
        modeling_message
        or ""
    ).strip()

    # ========================================================
    # 2. MESSAGE DE MODÉLISATION
    # ========================================================
    #
    # IMPORTANT :
    # le dernier message de l'élève ne doit pas remplacer
    # arbitrairement le message ayant réellement défini
    # la modélisation.
    # ========================================================

    if (
        modeling_message
        and validation_method
        in {
            "verbal_problem_modeling",
            "direct_verbal_modeling",
        }
    ):

        problem[
            "modeling_message"
        ] = modeling_message

        # ----------------------------------------------------
        # EXTRACTION EXPLICITE DE LA SIGNIFICATION
        # ----------------------------------------------------
        #
        # Cette extraction ne fournit que ce que l'élève
        # a réellement exprimé.
        # ----------------------------------------------------

        extracted_variable_meaning = (
            extract_variable_meaning(
                modeling_message
            )
        )

        if extracted_variable_meaning:

            # ------------------------------------------------
            # PRÉSERVER LES INFORMATIONS DÉJÀ MÉMORISÉES
            # ------------------------------------------------
            #
            # Exemple :
            #
            # semantic_role peut avoir été prouvé auparavant.
            # ------------------------------------------------

            existing_variable_meaning = (
                problem.get(
                    "variable_meaning"
                )
            )

            if not isinstance(
                existing_variable_meaning,
                dict,
            ):

                existing_variable_meaning = {}

            merged_variable_meaning = {
                **existing_variable_meaning,
                **extracted_variable_meaning,
            }

            problem[
                "variable_meaning"
            ] = (
                merged_variable_meaning
            )

    # ========================================================
    # 3. ÉTAT DE MODÉLISATION
    # ========================================================

    problem[
        "model_status"
    ] = (
        "learner_proposed"
    )

    problem[
        "model_validation_method"
    ] = (
        validation_method
    )

    problem[
        "model_validation_verdict"
    ] = (
        validation.get(
            "verdict"
        )
    )

    # ========================================================
    # 4. MODÉLISATION PROUVÉE
    # ========================================================
    #
    # Une modélisation directe n'est prouvée correcte que si
    # le moteur déterministe direct_verbal_modeling l'a
    # explicitement validée.
    # ========================================================

    model_proved_correct = bool(
        validation_method
        == "direct_verbal_modeling"
        and validation.get(
            "verdict"
        )
        == "correct"
        and validation.get(
            "result_correct"
        )
        is True
    )

    problem[
        "model_proved_correct"
    ] = (
        model_proved_correct
    )

    # ========================================================
    # 5. MÉMORISER LE RÔLE SÉMANTIQUE PROUVÉ
    # ========================================================
    #
    # validate_direct_verbal_modeling() peut retourner :
    #
    #     details["matched_role"]
    #
    # uniquement lorsqu'une paramétrisation déterministe
    # correspond réellement à l'équation de l'élève.
    #
    # On peut donc conserver ce rôle comme preuve de la
    # signification mathématique de la variable.
    #
    # IMPORTANT :
    #
    # Le rôle ne provient pas d'un mot-clé métier.
    # Il provient de la paramétrisation mathématique qui
    # correspond à l'équation validée.
    # ========================================================

    if model_proved_correct:

        validation_details = (
            validation.get(
                "details"
            )
            or {}
        )

        if isinstance(
            validation_details,
            dict,
        ):

            matched_role = str(
                validation_details.get(
                    "matched_role"
                )
                or ""
            ).strip()

            if matched_role:

                variable_meaning = (
                    problem.get(
                        "variable_meaning"
                    )
                )

                if not isinstance(
                    variable_meaning,
                    dict,
                ):

                    variable_meaning = {}

                variable_meaning = dict(
                    variable_meaning
                )

                # --------------------------------------------
                # VÉRIFICATION DU SYMBOLE SI DISPONIBLE
                # --------------------------------------------

                student_variable = str(
                    validation_details.get(
                        "student_variable"
                    )
                    or ""
                ).strip()

                remembered_variable = str(
                    variable_meaning.get(
                        "variable"
                    )
                    or ""
                ).strip()

                # Si les deux symboles existent et diffèrent,
                # on ne persiste pas le rôle.
                #
                # Cela évite d'associer le rôle d'une variable
                # à une autre variable par erreur.
                can_store_role = bool(
                    not student_variable
                    or not remembered_variable
                    or (
                        student_variable.lower()
                        == remembered_variable.lower()
                    )
                )

                if can_store_role:

                    variable_meaning[
                        "semantic_role"
                    ] = (
                        matched_role
                    )

                    problem[
                        "variable_meaning"
                    ] = (
                        variable_meaning
                    )

                    # ----------------------------------------
                    # TRACE DU MODÈLE PROUVÉ
                    # ----------------------------------------

                    problem[
                        "model_semantic_role"
                    ] = (
                        matched_role
                    )

    # ========================================================
    # 6. PERSISTANCE
    # ========================================================

    session[
        "probleme_verbal_naima_v2"
    ] = problem

    session.modified = True
    

def _update_direct_verbal_problem_algebraic_solution(
    *,
    validation: Any,
) -> None:
    """
    Mémorise une solution algébrique uniquement lorsque
    le moteur déterministe l'a prouvée.

    Exemple :

        x+2*x=30
        x=10

    La résolution x=10 peut être prouvée même si la
    modélisation initiale reste seulement
    "learner_proposed".
    """

    problem = (
        _get_direct_verbal_problem()
    )

    if not problem:
        return

    if (
        problem.get(
            "source"
        )
        != "student_message"
    ):
        return

    # Les exercices générés utilisent leur correction
    # de référence et ne relèvent pas de cette mémoire.
    if problem.get(
        "correction"
    ):
        return

    algebraic_solution = (
        extract_proved_algebraic_solution(
            validation
        )
    )

    if not algebraic_solution:
        return

    problem[
        "algebraic_solution"
    ] = (
        algebraic_solution
    )

    session[
        "probleme_verbal_naima_v2"
    ] = problem

    session.modified = True

# ============================================================
# PROBLÈME VERBAL GÉNÉRÉ
# ============================================================

def _get_generated_verbal_problem_context(
    *,
    current_message: str = "",
) -> tuple:
    """
    Résout le contexte verbal actif.

    PRIORITÉ :

        1. exercice généré avec correction ;
        2. problème verbal direct déjà actif ;
        3. nouvel énoncé verbal du message courant,
           uniquement lorsqu'aucun problème verbal direct
           n'est déjà actif.

    Principe fondamental :

    Une fois qu'un problème verbal est actif, les messages
    ultérieurs de l'élève sont considérés comme appartenant
    à ce problème :

        - définition / redéfinition d'une variable ;
        - modélisation ;
        - transformation algébrique ;
        - justification ;
        - réponse intermédiaire ;
        - réponse finale.

    Ils ne doivent donc jamais remplacer automatiquement
    l'énoncé canonique du problème.

    Le remplacement d'un problème actif doit être effectué
    par une véritable transition de contexte :

        - reset ;
        - exercice explicitement remplacé par l'application ;
        - futur arbitre générique de transition.

    Retour :

        (
            verbal_problem_active,
            statement,
            correction,
        )
    """

    current_message = str(
        current_message
        or ""
    ).strip()

    # ========================================================
    # 1. EXERCICE GÉNÉRÉ AVEC CORRECTION
    # ========================================================

    exercise = (
        session.get(
            "exercice_en_cours"
        )
        or {}
    )

    if isinstance(
        exercise,
        dict,
    ):

        statement = str(
            exercise.get(
                "enonce"
            )
            or ""
        ).strip()

        correction = (
            exercise.get(
                "correction"
            )
        )

        if (
            statement
            and correction
        ):

            try:

                statement_relation = (
                    extract_math_relation_from_text(
                        statement
                    )
                )

            except Exception:

                statement_relation = None

            # ------------------------------------------------
            # Un exercice généré réellement verbal conserve
            # sa priorité.
            # ------------------------------------------------

            if not statement_relation:

                return (
                    True,
                    statement,
                    correction,
                )

    # ========================================================
    # 2. PROBLÈME VERBAL DIRECT DÉJÀ ACTIF
    # ========================================================
    #
    # IMPORTANT :
    #
    # Cette vérification doit précéder toute tentative
    # de détection d'un "nouvel énoncé" dans le message
    # courant.
    #
    # Sinon :
    #
    #     problème actif :
    #         énoncé initial
    #
    #     élève :
    #         x représente ...
    #
    # peut être faussement détecté comme nouvel énoncé,
    # ce qui détruit :
    #
    #     statement
    #     verbal_constraints
    #     model_equation
    #     algebraic_solution
    #     variable_meaning
    #
    # --------------------------------------------------------

    direct_problem = (
        _get_direct_verbal_problem()
    )

    if direct_problem:

        statement = str(
            direct_problem.get(
                "statement"
            )
            or ""
        ).strip()

        if statement:

            return (
                True,
                statement,
                None,
            )

    # ========================================================
    # 3. AUCUN PROBLÈME DIRECT ACTIF :
    #    LE MESSAGE COURANT PEUT EN CRÉER UN
    # ========================================================

    if (
        current_message
        and is_probable_verbal_problem_statement(
            current_message
        )
    ):

        _store_direct_verbal_problem(
            current_message
        )

        direct_problem = (
            _get_direct_verbal_problem()
        )

        statement = str(
            direct_problem.get(
                "statement"
            )
            if direct_problem
            else current_message
        ).strip()

        return (
            True,
            statement,
            None,
        )

    # ========================================================
    # 4. AUCUN CONTEXTE VERBAL
    # ========================================================

    return (
        False,
        "",
        None,
    )


# ============================================================
# CONVERSATION
# ============================================================

def _get_conversation():
    """
    Retourne la conversation Naima.

    conversation_naima est désormais la clé canonique.
    L'ancienne clé conversation reste uniquement un fallback
    de migration.
    """

    conversation = session.get(
        "conversation_naima"
    )

    if isinstance(
        conversation,
        list,
    ):
        return conversation

    legacy_conversation = session.get(
        "conversation"
    )

    if isinstance(
        legacy_conversation,
        list,
    ):
        return legacy_conversation

    return []


def _set_conversation(
    conversation,
):
    """
    Stocke la conversation Naima dans une seule clé canonique.

    IMPORTANT :
    Flask stocke actuellement la session dans un cookie signé.
    Dupliquer toute la conversation dans deux clés peut faire
    dépasser la limite navigateur d'environ 4 Ko.
    """

    safe_conversation = list(
        conversation
        or []
    )

    # Limiter également l'historique conservé côté session.
    # Les derniers tours suffisent au contexte immédiat.
    safe_conversation = (
        safe_conversation[-8:]
    )

    session[
        "conversation_naima"
    ] = safe_conversation

    # Ne plus dupliquer le contenu complet.
    session.pop(
        "conversation",
        None,
    )

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

    validation = (
        result.get(
            "validation"
        )
        or {}
    )

    validation_method = (
        validation.get(
            "method"
        )
        or ""
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

    # --------------------------------------------------------
    # ÉQUATION DE TRAVAIL / MODÉLISATION
    # --------------------------------------------------------
    #
    # Pour certaines variables contextuelles comme P,
    # le ContextService général peut ne pas encore fournir
    # current_equation.
    #
    # En revanche, le validateur déterministe du problème
    # verbal direct peut déjà avoir extrait et validé
    # l'équation dans :
    #
    #     validation["details"]["student_equation"]
    #
    # On utilise donc cette équation comme fallback fiable
    # uniquement lorsque la méthode de validation correspond
    # réellement à une modélisation verbale.
    # --------------------------------------------------------

    model_equation = (
        current_equation
    )

    if (
        not model_equation
        and validation_method
        in {
            "verbal_problem_modeling",
            "direct_verbal_modeling",
        }
    ):

        validation_details = (
            validation.get(
                "details"
            )
            or {}
        )

        if isinstance(
            validation_details,
            dict,
        ):

            model_equation = str(
                validation_details.get(
                    "student_equation"
                )
                or ""
            ).strip()

    if model_equation:

        session[
            "equation_courante_naima"
        ] = model_equation

        # --------------------------------------------------------
        # PROBLÈME VERBAL DIRECT :
        # MÉMOIRE DE LA MODÉLISATION
        # --------------------------------------------------------

        direct_problem = (
            _get_direct_verbal_problem()
        )

        if (
            direct_problem
            and direct_problem.get(
                "source"
            )
            == "student_message"
            and not direct_problem.get(
                "correction"
            )
            and validation_method
            in {
                "verbal_problem_modeling",
                "direct_verbal_modeling",
            }
        ):

            _update_direct_verbal_problem_model(
                equation=(
                    model_equation
                ),
                modeling_message=(
                    message
                ),
                validation=(
                    validation
                ),
            )

    # --------------------------------------------------------
    # SOLUTION ALGÉBRIQUE PROUVÉE
    # --------------------------------------------------------
    #
    # Cette étape est distincte de la modélisation.
    #
    # Exemple :
    #
    #     modèle proposé :
    #         x+2*x=30
    #
    #     solution algébrique prouvée :
    #         x=10
    #
    # Le modèle peut rester :
    #
    #     model_proved_correct = False
    #
    # tandis que la résolution de cette équation peut être
    # déterministiquement prouvée :
    #
    #     algebraic_solution.proved = True
    #
    # Si aucune preuve positive n'existe, le helper ne fait
    # simplement rien.
    # --------------------------------------------------------

    _update_direct_verbal_problem_algebraic_solution(
        validation=(
            validation
        ),
    )

    # --------------------------------------------------------
    # ÉQUATION INITIALE
    # --------------------------------------------------------

    if initial_equation:

        session[
            "equation_initiale_naima"
        ] = initial_equation

    # --------------------------------------------------------
    # OBJECTIF
    # --------------------------------------------------------
    #
    # IMPORTANT :
    #
    # Dans le cas standard :
    #
    #     resoudre 3x=5
    #
    # un nouveau problème détecté doit remplacer l'ancien
    # objectif par le nouveau message.
    #
    # MAIS :
    #
    # dans un problème verbal actif, si l'élève écrit :
    #
    #     3x=15
    #
    # et que cette équation vient d'être validée comme
    # modélisation correcte, cette équation ne doit PAS
    # remplacer l'énoncé verbal comme objectif pédagogique.
    #
    # On garde donc :
    #
    #     objectif_initial_naima = énoncé verbal
    #
    # et :
    #
    #     equation_courante_naima = 3x=15
    #
    # ========================================================

    if context.get(
        "is_new_problem"
    ):

        if (
            validation_method
            in {
                "verbal_problem_modeling",
                "direct_verbal_modeling",
            }
        ):

            # Ne pas écraser l'objectif verbal.
            #
            # L'équation extraite a déjà été mémorisée
            # ci-dessus dans equation_courante_naima.
            pass

        else:

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
    ] = validation

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

    objective_reached = bool(
        result.get(
            "objective_reached"
        )
    )

    session[
        "objectif_atteint_naima"
    ] = objective_reached

    # Compatibilité avec le fonctionnement historique
    # de l'exercice généré.
    if objective_reached:

        session[
            "exercice_termine"
        ] = True

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
        "probleme_verbal_naima_v2",

        # Compatibilité avec le statut de fin d'exercice.
        "exercice_termine",

        "naima_next_action",
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

def _prepare_closed_exercise_for_new_problem() -> None:
    """
    Libère immédiatement le contexte de l'exercice terminé
    SANS supprimer la conversation affichée.

    État obtenu :

        ancien exercice :
            supprimé

        mémoire mathématique :
            supprimée

        problème verbal :
            supprimé

        conversation :
            conservée

        interface :
            next_action = "new_exercise"

    Le clic ultérieur sur "Nouvel exercice" effectuera
    le reset complet et supprimera alors la conversation.
    """

    # --------------------------------------------------------
    # CONSERVER LA CONVERSATION VISIBLE
    # --------------------------------------------------------

    conversation = (
        _get_conversation()
    )

    # --------------------------------------------------------
    # CONSERVER LA DERNIÈRE PREUVE POUR LE DEBUG
    # --------------------------------------------------------

    final_validation = session.get(
        "validation_naima_v2"
    )

    final_response = session.get(
        "response_decision_naima_v2"
    )

    # --------------------------------------------------------
    # LIBÉRER LE CONTEXTE NAIMA
    # --------------------------------------------------------

    _reset_naima_v2_session()

    # --------------------------------------------------------
    # UN EXERCICE GÉNÉRÉ TERMINÉ NE DOIT PLUS RESTER ACTIF
    # --------------------------------------------------------

    session.pop(
        "exercice_en_cours",
        None,
    )

    # --------------------------------------------------------
    # RESTAURER UNIQUEMENT L'HISTORIQUE VISUEL
    # --------------------------------------------------------

    _set_conversation(
        conversation
    )

    # --------------------------------------------------------
    # ÉTAT DE TRANSITION
    # --------------------------------------------------------

    session[
        "objectif_atteint_naima"
    ] = True

    session[
        "exercice_termine"
    ] = True

    session[
        "naima_next_action"
    ] = (
        "new_exercise"
    )

    # Le prochain vrai exercice sera traité comme
    # un premier message.
    session[
        "premier_message_naima"
    ] = True

    # --------------------------------------------------------
    # CONSERVER LE RÉSULTAT FINAL POUR /state
    # --------------------------------------------------------

    if final_validation is not None:

        session[
            "validation_naima_v2"
        ] = final_validation

    if final_response is not None:

        session[
            "response_decision_naima_v2"
        ] = final_response

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
            "verbal_problem_active": data.get(
                "verbal_problem_active",
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
            "exercise_closed": bool(
            data.get(
                "response",
                {},
            ).get(
                "exercise_closed",
                False,
            )
        ),

        "next_action": (
            data.get(
                "response",
                {}
            ).get(
                "next_action"
            )
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
        → MathRouter / VerbalProblemService
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
    # CONTEXTE D'UN PROBLÈME VERBAL GÉNÉRÉ
    # --------------------------------------------------------
    #
    # Si exercice_en_cours contient un véritable problème
    # verbal généré, son énoncé devient l'objectif pédagogique
    # prioritaire.
    #
    # La correction est envoyée uniquement à l'orchestrateur
    # déterministe. Elle n'est pas directement affichée à
    # l'élève.
    # --------------------------------------------------------

    (
        verbal_problem_active,
        verbal_problem_statement,
        verbal_problem_correction,
    ) = _get_generated_verbal_problem_context(
        current_message=(
            message
        ),
    )

    if verbal_problem_active:

        current_objective = (
            verbal_problem_statement
        )

        # Si aucun objectif n'a encore été mémorisé ou qu'un
        # ancien objectif mathématique est toujours présent,
        # on rattache explicitement Naima à l'énoncé généré.
        session[
            "objectif_initial_naima"
        ] = verbal_problem_statement

        session.modified = True

    # --------------------------------------------------------
    # SIGNIFICATION DE VARIABLE DU TOUR COURANT
    # --------------------------------------------------------
    #
    # Une définition comme :
    #
    #     "Si P est l'âge de Paul..."
    #
    # peut être donnée un tour avant l'équation :
    #
    #     P+2P=30
    #
    # On la mémorise donc avant de construire les arguments
    # transmis à l'orchestrateur.
    # --------------------------------------------------------

    if verbal_problem_active:

        current_direct_problem = (
            _get_direct_verbal_problem()
        )

        if (
            current_direct_problem
            and current_direct_problem.get(
                "source"
            )
            == "student_message"
            and not current_direct_problem.get(
                "correction"
            )
        ):

            _update_direct_verbal_problem_variable_meaning(
                message=(
                    message
                ),
            )

    # --------------------------------------------------------
    # MÉMOIRE DÉTERMINISTE DU PROBLÈME VERBAL DIRECT
    # --------------------------------------------------------

    direct_verbal_problem = (
        _get_direct_verbal_problem()
    )

    direct_verbal_variable_meaning = None
    direct_verbal_algebraic_solution = None
    direct_verbal_relations = []
    direct_verbal_constraints = []

    if (
        direct_verbal_problem
        and direct_verbal_problem.get(
            "source"
        )
        == "student_message"
        and not direct_verbal_problem.get(
            "correction"
        )
    ):

        direct_verbal_variable_meaning = (
            direct_verbal_problem.get(
                "variable_meaning"
            )
        )

        direct_verbal_algebraic_solution = (
            direct_verbal_problem.get(
                "algebraic_solution"
            )
        )

        direct_verbal_relations = list(
            direct_verbal_problem.get(
                "verbal_relations",
                [],
            )
            or []
        )

        direct_verbal_constraints = list(
            direct_verbal_problem.get(
                "verbal_constraints",
                [],
            )
            or []
        )

    # --------------------------------------------------------
    # GARDE DE NOUVEL OBJECTIF AVANT ORCHESTRATION
    # --------------------------------------------------------
    #
    # Pour les problèmes purement mathématiques :
    #
    #     resoudre 3x=5
    #
    # une nouvelle relation différente peut devenir un nouvel
    # objectif.
    #
    # MAIS pour un problème verbal généré :
    #
    #     élève : 3x=15
    #
    # peut être une équation de MODÉLISATION.
    #
    # Dans ce cas elle ne doit surtout pas remplacer l'énoncé
    # verbal avant que VerbalProblemService ait pu la vérifier.
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
        and not verbal_problem_active
        and (
            not current_equation
            or relation_message
            != current_equation
        )
    )

    if new_problem_before_orchestration:

        current_objective = (
            message
        )

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

                # ==============================================
                # PROBLÈME VERBAL V2
                # ==============================================

                verbal_problem_active=(
                    verbal_problem_active
                ),

                verbal_problem_correction=(
                    verbal_problem_correction
                ),

                direct_verbal_variable_meaning=(
                    direct_verbal_variable_meaning
                ),

                direct_verbal_algebraic_solution=(
                    direct_verbal_algebraic_solution
                ),

                direct_verbal_relations=(
                    direct_verbal_relations
                ),

                direct_verbal_constraints=(
                    direct_verbal_constraints
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

    # ========================================================
    # EXERCICE TERMINÉ
    # ========================================================
    #
    # La conversation reste affichée.
    #
    # En revanche l'ancien contexte pédagogique/mathématique
    # est immédiatement libéré.
    # ========================================================

    response_decision = dict(
        result.get(
            "response"
        )
        or {}
    )

    if (
        response_decision.get(
            "exercise_closed"
        )
        is True
        and response_decision.get(
            "next_action"
        )
        == "new_exercise"
    ):

        _prepare_closed_exercise_for_new_problem()

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

        # Ne plus stocker trois fois le même texte.
        session.pop(
            "derniere_question_ia_naima",
            None,
        )

        session.pop(
            "derniere_q_ia",
            None,
        )

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

        # ----------------------------------------------------
        # DEBUG PROBLÈME VERBAL
        # ----------------------------------------------------

        "verbal_problem_active": (
            verbal_problem_active
        ),

        "verbal_problem_statement": (
            verbal_problem_statement
            if verbal_problem_active
            else None
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

    IMPORTANT :

    Lorsqu'un exercice vient d'être terminé :

        exercise_closed = True
        next_action = "new_exercise"

    la conversation peut encore être visible,
    mais l'ancien contexte mathématique ne doit
    plus être considéré comme actif.
    """

    if not _is_authenticated_student():

        return _json_error(
            "Non authentifié",
            401,
        )

    # ========================================================
    # ÉTAT DE FERMETURE
    # ========================================================

    exercise_closed = bool(
        session.get(
            "exercice_termine",
            False,
        )
    )

    next_action = session.get(
        "naima_next_action"
    )

    # ========================================================
    # CONTEXTE VERBAL
    # ========================================================
    #
    # Un exercice fermé ne doit plus redevenir actif
    # simplement parce qu'un ancien contexte subsiste
    # quelque part dans la session.
    # ========================================================

    if exercise_closed:

        verbal_problem_active = False
        verbal_problem_statement = ""

        direct_verbal_problem = None

    else:

        (
            verbal_problem_active,
            verbal_problem_statement,
            _verbal_problem_correction,
        ) = _get_generated_verbal_problem_context()

        direct_verbal_problem = (
            _get_direct_verbal_problem()
        )

    # ========================================================
    # RÉPONSE DEBUG
    # ========================================================

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

        # ----------------------------------------------------
        # CYCLE DE VIE DE L'EXERCICE
        # ----------------------------------------------------

        "exercise_closed": (
            exercise_closed
        ),

        "next_action": (
            next_action
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

        # ----------------------------------------------------
        # PROBLÈME VERBAL
        # ----------------------------------------------------

        "verbal_problem_active": (
            verbal_problem_active
        ),

        "verbal_problem_statement": (
            verbal_problem_statement
            if verbal_problem_active
            else None
        ),

        "verbal_problem_source": (
            direct_verbal_problem.get(
                "source"
            )
            if direct_verbal_problem
            else None
        ),

        "verbal_problem_model_equation": (
            direct_verbal_problem.get(
                "model_equation"
            )
            if direct_verbal_problem
            else None
        ),

        "verbal_problem_modeling_message": (
            direct_verbal_problem.get(
                "modeling_message"
            )
            if direct_verbal_problem
            else None
        ),

        "verbal_problem_variable_meaning": (
            direct_verbal_problem.get(
                "variable_meaning"
            )
            if direct_verbal_problem
            else None
        ),

        # ----------------------------------------------------
        # RELATIONS VERBALES EXPLICITES
        # ----------------------------------------------------

        "verbal_problem_relations": (
            direct_verbal_problem.get(
                "verbal_relations",
                [],
            )
            if direct_verbal_problem
            else []
        ),

        "verbal_problem_constraints": (
            direct_verbal_problem.get(
                "verbal_constraints",
                [],
            )
            if direct_verbal_problem
            else []
        ),

        "verbal_problem_model_status": (
            direct_verbal_problem.get(
                "model_status"
            )
            if direct_verbal_problem
            else None
        ),

        "verbal_problem_model_proved_correct": (
            bool(
                direct_verbal_problem.get(
                    "model_proved_correct",
                    False,
                )
            )
            if direct_verbal_problem
            else False
        ),

        # ----------------------------------------------------
        # SOLUTION ALGÉBRIQUE PROUVÉE
        # ----------------------------------------------------
        #
        # Cette valeur indique uniquement que la résolution
        # de l'équation proposée a été prouvée par le moteur
        # déterministe.
        #
        # Elle ne signifie PAS automatiquement que la
        # modélisation représente correctement l'énoncé.
        # ----------------------------------------------------

        "verbal_problem_algebraic_solution": (
            direct_verbal_problem.get(
                "algebraic_solution"
            )
            if direct_verbal_problem
            else None
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

        # ----------------------------------------------------
        # HISTORIQUE VISUEL
        # ----------------------------------------------------
        #
        # Même lorsque exercise_closed=True,
        # cette conversation reste visible jusqu'au clic
        # sur "Nouvel exercice".
        # ----------------------------------------------------

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