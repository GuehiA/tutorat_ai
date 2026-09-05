from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv


@dataclass
class NaimaLLMResponse:
    """
    Résultat normalisé d'un appel LLM Naima v2.
    """

    text: Optional[str]
    success: bool

    provider_used: str
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "success": self.success,
            "provider_used": self.provider_used,
            "reason": self.reason,
        }


def _clean_text(
    value: Any,
) -> str:
    """
    Convertit une valeur en texte propre.
    """

    if value is None:
        return ""

    return str(value).strip()


def _dict(
    value: Any,
) -> Dict[str, Any]:
    """
    Retourne un dictionnaire sûr.
    """

    if isinstance(
        value,
        dict,
    ):
        return dict(
            value
        )

    return {}


def _conversation_to_text(
    conversation: Optional[
        List[Any]
    ],
    limit: int = 10,
) -> str:
    """
    Transforme l'historique Naima en contexte texte.

    Compatible avec :
    - anciennes conversations sous forme de chaînes ;
    - conversations sous forme de dict {role, content}.
    """

    if not conversation:
        return ""

    lines: List[str] = []

    for item in conversation[
        -limit:
    ]:

        if isinstance(
            item,
            str,
        ):

            text = (
                item.strip()
            )

            if text:
                lines.append(
                    text
                )

            continue

        if isinstance(
            item,
            dict,
        ):

            role = (
                item.get(
                    "role"
                )
                or ""
            )

            content = (
                _clean_text(
                    item.get(
                        "content"
                    )
                )
            )

            if not content:
                continue

            if role == "user":

                prefix = (
                    "Élève"
                )

            elif role == "assistant":

                prefix = (
                    "Naima"
                )

            else:

                prefix = (
                    role
                    or "Message"
                )

            lines.append(
                f"{prefix}: {content}"
            )

    return "\n".join(
        lines
    )


def _ensure_signature(
    text: str,
    lang: str,
) -> str:
    """
    Garantit la signature Naima.
    """

    text = _clean_text(
        text
    )

    if not text:
        return text

    if lang == "en":

        if (
            "-- Naima"
            not in text
            and "— Naima"
            not in text
        ):

            text += (
                "\n\n-- Naima ✨"
            )

    else:

        if (
            "— Naima"
            not in text
        ):

            text += (
                "\n\n— Naima ✨"
            )

    return text


def _build_system_prompt(
    *,
    lang: str,
    context: Dict[str, Any],
    validation: Dict[str, Any],
    pedagogical: Dict[str, Any],
    response: Dict[str, Any],
) -> str:
    """
    Construit le garde-fou principal du fallback LLM.

    Le LLM ne décide PAS si l'élève a raison ou tort.
    Cette décision appartient aux moteurs déterministes.

    Si aucune preuve déterministe suffisante n'existe,
    le LLM doit rester strictement neutre :
    il peut guider et demander une vérification,
    mais ne peut jamais inventer un verdict mathématique.
    """

    current_equation = (
        _clean_text(
            context.get(
                "current_equation"
            )
        )
    )

    objective = (
        _clean_text(
            context.get(
                "objective"
            )
        )
    )

    verdict = (
        validation.get(
            "verdict"
        )
    )

    method = (
        _clean_text(
            validation.get(
                "method"
            )
        )
    )

    result_correct = (
        validation.get(
            "result_correct"
        )
    )

    reasoning_correct = (
        validation.get(
            "reasoning_correct"
        )
    )

    policy = (
        _dict(
            pedagogical.get(
                "pedagogical_policy"
            )
        )
    )

    pedagogical_instruction = (
        _clean_text(
            pedagogical.get(
                "pedagogical_instruction"
            )
        )
    )

    strategy = (
        _clean_text(
            policy.get(
                "strategie"
            )
        )
    )

    help_level = (
        policy.get(
            "niveau_aide"
        )
    )

    may_reveal_solution = bool(
        policy.get(
            "peut_reveler_solution",
            False,
        )
    )

    solution_leakage_blocked = bool(
        response.get(
            "solution_leakage_blocked",
            False,
        )
    )

    # ========================================================
    # STATUT DE PREUVE DÉTERMINISTE
    # ========================================================
    #
    # Le LLM ne doit jamais déduire lui-même :
    #
    #     correct
    #     incorrect
    #
    # à partir du texte de l'élève.
    #
    # Une conclusion déterministe existe uniquement lorsque
    # le moteur a produit explicitement un verdict correct
    # ou incorrect.
    # ========================================================

    deterministic_conclusion_available = (
        verdict
        in {
            "correct",
            "incorrect",
        }
    )

    validation_is_uncertain = (
        verdict
        in {
            "uncertain",
            None,
            "",
        }
        or not deterministic_conclusion_available
    )

    is_new_problem = bool(
        context.get(
            "is_new_problem",
            False,
        )
    )

    validation_method = (
        _clean_text(
            validation.get(
                "method"
            )
        )
    )

    fresh_problem = bool(
        is_new_problem
        or validation_method
        == "new_problem_presented"
    )

    # ========================================================
    # VERSION ANGLAISE
    # ========================================================

    if lang == "en":

        return f"""
You are Naima, a warm, supportive, and Socratic virtual teacher.

IMPORTANT ARCHITECTURE RULE:
A deterministic pedagogical and mathematical engine has already analyzed the student's message.

You MUST NEVER:
- override deterministic mathematical validation;
- change a correct answer into an incorrect answer;
- change an incorrect answer into a correct answer;
- invent a mathematical verdict;
- say an answer is correct unless the deterministic engine proved it correct;
- say the learner is right unless the deterministic engine proved it;
- say an answer is wrong unless the deterministic engine proved it incorrect;
- say there is a mathematical error unless the deterministic engine proved an error;
- infer correctness from fluency, confidence, plausibility, or the wording of the student's answer;
- reveal the final answer when forbidden;
- solve the exercise for the student.

Your role is ONLY to formulate the pedagogical response authorized by the deterministic system.

{"IMPORTANT: This is a NEW problem. Never say that the learner has already solved, worked on, or seen this exercise. Treat the current exercise as new and begin the guidance from the current statement." if fresh_problem else ""}

CURRENT CONTEXT:
- Objective: {objective or "not specified"}
- Current equation/problem: {current_equation or "not specified"}

DETERMINISTIC VALIDATION:
- Verdict: {verdict}
- Method: {method or "unknown"}
- Result correct: {result_correct}
- Reasoning correct: {reasoning_correct}

EVIDENCE STATUS:
- Deterministic conclusion available: {
    "yes"
    if deterministic_conclusion_available
    else "no"
}
- Validation uncertain: {
    "yes"
    if validation_is_uncertain
    else "no"
}

ABSOLUTE RULE WHEN VALIDATION IS UNCERTAIN:

If validation is uncertain or no deterministic conclusion is available,
you MUST remain mathematically neutral.

You MAY:
- rephrase the learner's idea;
- ask the learner to explain their reasoning;
- ask the learner to verify a step;
- ask the learner to substitute a proposed value into the equation;
- ask the learner to check whether both sides are equal;
- ask how an algebraic result connects to the original verbal problem;
- ask what a variable represents;
- ask one Socratic question that helps the learner verify the work.

You MUST NOT say or imply:
- "correct";
- "exactly";
- "that's right";
- "you are right";
- "good, your result is correct";
- "there is an error";
- "you made a mistake";
- "this result is wrong";
- "that equation is incorrect";
- or any equivalent mathematical judgment.

When validation is uncertain, never decide the mathematical status yourself.

If the learner gives a plausible answer but the engine has not proved it,
use neutral language such as:
- "Let's verify that."
- "How could you check this result?"
- "What happens if you substitute this value into the equation?"
- "How does this answer connect to the quantities in the original problem?"

PEDAGOGICAL POLICY:
- Strategy: {strategy or "light_guidance"}
- Help level: {help_level}
- May reveal final solution: {"yes" if may_reveal_solution else "no"}
- Leakage protection active: {"yes" if solution_leakage_blocked else "no"}

MANDATORY PEDAGOGICAL INSTRUCTION:
{pedagogical_instruction}

RESPONSE RULES:
1. Use at most 2 or 3 short sentences.
2. Ask only one useful question at a time.
3. Keep the learner active.
4. Do not give the final answer unless explicitly authorized.
5. Do not mention internal validation, policies, engines, confidence scores, evidence status, or technical systems.
6. Do not expose hidden expected results or transformed equations.
7. Stay focused on the current objective.
8. If deterministic validation is uncertain, remain neutral about correctness.
9. Never manufacture mathematical certainty merely to sound encouraging.
10. End with "-- Naima ✨".
""".strip()

    # ========================================================
    # VERSION FRANÇAISE
    # ========================================================

    return f"""
Tu es Naima, une enseignante virtuelle chaleureuse, bienveillante et socratique.

RÈGLE D'ARCHITECTURE IMPORTANTE :
Un moteur pédagogique et mathématique déterministe a déjà analysé le message de l'élève.

Tu ne dois JAMAIS :
- contredire une validation mathématique déterministe ;
- transformer une réponse correcte en réponse fausse ;
- transformer une réponse fausse en réponse correcte ;
- inventer toi-même un verdict mathématique ;
- déclarer qu'une réponse est correcte lorsque le moteur déterministe ne l'a pas prouvé ;
- dire que l'élève a raison lorsque le moteur déterministe ne l'a pas prouvé ;
- déclarer qu'une réponse est fausse lorsque le moteur déterministe ne l'a pas prouvé ;
- dire qu'il y a une erreur mathématique lorsque le moteur déterministe n'a pas prouvé cette erreur ;
- déduire la justesse d'une réponse simplement parce qu'elle paraît plausible, bien rédigée ou convaincante ;
- révéler la solution finale lorsque cela est interdit ;
- faire l'exercice à la place de l'élève.

Ton rôle est UNIQUEMENT de formuler la réponse pédagogique autorisée par le système déterministe.

{"IMPORTANT : il s'agit d'un NOUVEAU problème. Ne dis jamais que l'élève l'a déjà résolu, déjà travaillé ou déjà rencontré. Considère cet exercice comme nouveau et commence son accompagnement à partir de l'énoncé actuel." if fresh_problem else ""}

CONTEXTE COURANT :
- Objectif : {objective or "non précisé"}
- Équation/problème courant : {current_equation or "non précisé"}

VALIDATION DÉTERMINISTE :
- Verdict : {verdict}
- Méthode : {method or "inconnue"}
- Résultat correct : {result_correct}
- Raisonnement correct : {reasoning_correct}

STATUT DE PREUVE :
- Conclusion déterministe disponible : {
    "oui"
    if deterministic_conclusion_available
    else "non"
}
- Validation incertaine : {
    "oui"
    if validation_is_uncertain
    else "non"
}

RÈGLE ABSOLUE EN CAS D'INCERTITUDE :

Si la validation est incertaine ou si aucune conclusion déterministe
n'est disponible, tu dois rester mathématiquement NEUTRE.

Tu PEUX :
- reformuler l'idée de l'élève ;
- demander à l'élève d'expliquer son raisonnement ;
- demander une vérification ;
- demander à l'élève de remplacer une valeur proposée dans l'équation ;
- demander de vérifier si les deux membres sont égaux ;
- demander comment le résultat algébrique se relie à l'énoncé verbal ;
- demander ce que représente une variable ;
- poser une question socratique qui permet à l'élève de vérifier son travail.

Tu ne peux PAS dire ni laisser entendre :
- « c'est correct » ;
- « c'est exact » ;
- « tu as raison » ;
- « bravo, ton résultat est correct » ;
- « il y a une erreur » ;
- « tu as fait une erreur » ;
- « ce résultat est faux » ;
- « cette équation est incorrecte » ;
- ou toute formulation équivalente constituant un verdict mathématique.

Lorsque la validation est incertaine, ne décide JAMAIS toi-même
du statut mathématique de la réponse.

Si l'élève donne une réponse plausible mais que le moteur ne l'a pas
prouvée, utilise plutôt une formulation neutre comme :
- « Vérifions cette proposition. »
- « Comment pourrais-tu vérifier ce résultat ? »
- « Que se passe-t-il si tu remplaces cette valeur dans l'équation ? »
- « Comment cette réponse se relie-t-elle aux quantités de l'énoncé ? »

POLITIQUE PÉDAGOGIQUE :
- Stratégie : {strategy or "guidage_leger"}
- Niveau d'aide : {help_level}
- Peut révéler la solution finale : {"oui" if may_reveal_solution else "non"}
- Protection contre la fuite de solution : {"active" if solution_leakage_blocked else "non active"}

INSTRUCTION PÉDAGOGIQUE OBLIGATOIRE :
{pedagogical_instruction}

RÈGLES DE RÉPONSE :
1. Réponds en 2 ou 3 phrases courtes maximum.
2. Pose une seule question utile à la fois.
3. Garde l'élève actif dans son raisonnement.
4. Ne donne jamais la réponse finale sauf autorisation explicite.
5. Ne parle jamais de validation interne, politique, moteur, score de confiance, statut de preuve ou système technique.
6. Ne révèle jamais un résultat attendu caché ou une équation transformée interne.
7. Reste concentrée sur l'objectif courant.
8. Si la validation déterministe est incertaine, reste neutre sur la justesse mathématique.
9. N'invente jamais une certitude mathématique uniquement pour être encourageante.
10. Termine par "— Naima ✨".
""".strip()


def _build_user_prompt(
    *,
    message: str,
    conversation: Optional[
        List[Any]
    ],
    context: Dict[str, Any],
    last_teacher_question: str,
    lang: str,
) -> str:

    history = (
        _conversation_to_text(
            conversation
        )
    )

    objective = (
        _clean_text(
            context.get(
                "objective"
            )
        )
    )

    current_equation = (
        _clean_text(
            context.get(
                "current_equation"
            )
        )
    )

    last_teacher_question = (
        _clean_text(
            last_teacher_question
        )
    )

    if lang == "en":

        return f"""
Current learning objective:
{objective or "Help the learner progress without giving the answer."}

Current mathematical problem:
{current_equation or "Not specified"}

Recent conversation:
{history or "No previous conversation."}

Naima's previous question:
{last_teacher_question or "None"}

Student's new message:
{message}

Produce Naima's next pedagogical response.
""".strip()

    return f"""
Objectif pédagogique courant :
{objective or "Faire progresser l'élève sans lui donner la réponse."}

Problème mathématique courant :
{current_equation or "Non précisé"}

Conversation récente :
{history or "Aucun historique."}

Dernière question posée par Naima :
{last_teacher_question or "Aucune"}

Nouveau message de l'élève :
{message}

Produis maintenant la prochaine réponse pédagogique de Naima.
""".strip()


def generate_llm_response(
    *,
    message: str,
    context: Dict[str, Any],
    validation: Dict[str, Any],
    pedagogical: Dict[str, Any],
    response: Dict[str, Any],
    conversation: Optional[
        List[Any]
    ] = None,
    last_teacher_question: str = "",
    lang: str = "fr",
    matiere: str = "mathématiques",
    niveau: str = "secondaire",
) -> NaimaLLMResponse:
    """
    Génère uniquement les réponses que le moteur v2
    a explicitement déléguées au LLM.

    IMPORTANT :
    cette fonction ne valide jamais les mathématiques.

    En cas de validation incertaine :
    - le LLM peut guider ;
    - le LLM peut demander une vérification ;
    - le LLM ne peut jamais inventer un verdict.
    """

    context = (
        _dict(
            context
        )
    )

    validation = (
        _dict(
            validation
        )
    )

    pedagogical = (
        _dict(
            pedagogical
        )
    )

    response = (
        _dict(
            response
        )
    )

    system_prompt = (
        _build_system_prompt(
            lang=lang,
            context=context,
            validation=validation,
            pedagogical=pedagogical,
            response=response,
        )
    )

    # ==========================================================
    # NOUVEAU PROBLÈME : ISOLATION DE L'HISTORIQUE
    # ==========================================================
    #
    # Un nouveau problème ne doit pas hériter de l'historique
    # mathématique d'un exercice précédent pour la génération
    # de la première question socratique.
    # ==========================================================

    fresh_problem = bool(
        context.get(
            "is_new_problem",
            False,
        )
        or validation.get(
            "method"
        )
        == "new_problem_presented"
    )

    conversation_for_prompt = (
        []
        if fresh_problem
        else conversation
    )

    last_teacher_question_for_prompt = (
        ""
        if fresh_problem
        else last_teacher_question
    )

    user_prompt = (
        _build_user_prompt(
            message=message,
            conversation=(
                conversation_for_prompt
            ),
            context=context,
            last_teacher_question=(
                last_teacher_question_for_prompt
            ),
            lang=lang,
        )
    )

    messages = [
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": user_prompt,
        },
    ]

    # ==========================================================
    # CHARGEMENT ENVIRONNEMENT
    #
    # Flask CLI charge souvent automatiquement .env,
    # mais ce service doit également fonctionner
    # lorsqu'il est importé directement avec python -c,
    # dans les tests ou depuis un autre module.
    # ==========================================================

    load_dotenv()

    try:

        # ======================================================
        # IMPORT TARDIF VOLONTAIRE
        #
        # naima_router initialise actuellement certains
        # clients IA au moment de son import.
        #
        # On ne doit donc importer appel_ia qu'après
        # le chargement de .env.
        #
        # Cela évite notamment :
        #
        # OpenAIError:
        # Missing credentials
        # ======================================================

        from naima_router import (
            appel_ia,
        )

        text = appel_ia(
            messages,
            type_requete="chat",
            matiere=matiere,
            niveau=niveau,
            langue=lang,
            temperature=0.2,
            max_tokens=300,
        )

        text = (
            _ensure_signature(
                text,
                lang,
            )
        )

        if not text:

            return NaimaLLMResponse(
                text=None,
                success=False,
                provider_used=(
                    "naima_router"
                ),
                reason=(
                    "empty_llm_response"
                ),
            )

        return NaimaLLMResponse(
            text=text,
            success=True,
            provider_used=(
                "naima_router"
            ),
            reason=(
                "llm_response_generated"
            ),
        )

    except Exception as exc:

        print(
            "❌ Naima v2 LLM fallback:",
            type(
                exc
            ).__name__,
            str(
                exc
            ),
        )

        # ======================================================
        # FALLBACK BILINGUE
        # ======================================================

        if lang == "en":

            fallback_text = (
                "I’m having trouble generating the next hint. "
                "What first step would you try to move forward? "
                "-- Naima ✨"
            )

        else:

            fallback_text = (
                "J’ai une difficulté à générer le prochain indice. "
                "Quelle première étape essaierais-tu pour avancer ? "
                "— Naima ✨"
            )

        return NaimaLLMResponse(
            text=fallback_text,
            success=False,
            provider_used=(
                "local_fallback"
            ),
            reason=(
                f"llm_exception:"
                f"{type(exc).__name__}"
            ),
        )