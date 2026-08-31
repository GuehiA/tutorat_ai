from __future__ import annotations
from typing import Any, Dict, List, Optional
import re

_FINAL_ANSWER_PATTERNS_FR = [
    r"\bla réponse (?:finale )?est\b",
    r"\ble résultat (?:final )?est\b",
    r"\bdonc\s+x\s*=",
    r"\bsolution\s*:\s*x\s*=",
]
_FINAL_ANSWER_PATTERNS_EN = [
    r"\bthe (?:final )?answer is\b",
    r"\bthe (?:final )?result is\b",
    r"\btherefore\s+x\s*=",
    r"\bsolution\s*:\s*x\s*=",
]
_DIRECTIVE_NEXT_STEP_FR = [
    r"\btu peux commencer par\b",
    r"\bcommence par\b",
    r"\btu dois\b",
    r"\bil faut\b",
    r"\bajoute\b.*\baux deux\b",
    r"\bsoustrais\b.*\baux deux\b",
    r"\bdivise\b.*\bpar\b",
    r"\bmultiplie\b.*\bpar\b",
]
_DIRECTIVE_NEXT_STEP_EN = [
    r"\byou can start by\b",
    r"\bstart by\b",
    r"\byou should\b",
    r"\byou need to\b",
    r"\badd\b.*\bto both\b",
    r"\bsubtract\b.*\bfrom both\b",
    r"\bdivide\b.*\bby\b",
    r"\bmultiply\b.*\bby\b",
]

def _detect_solution_leakage(text: str, lang: str) -> bool:
    patterns = _FINAL_ANSWER_PATTERNS_EN if lang == "en" else _FINAL_ANSWER_PATTERNS_FR
    lowered = text.lower()
    if any(re.search(p, lowered, flags=re.IGNORECASE) for p in patterns):
        return True
    if re.search(r"(?<![\w])x\s*=\s*[-+]?\d+(?:[.,]\d+)?(?:/\d+)?", lowered):
        return True
    return False

def _detect_strategic_takeover(text: str, lang: str) -> bool:
    patterns = _DIRECTIVE_NEXT_STEP_EN if lang == "en" else _DIRECTIVE_NEXT_STEP_FR
    lowered = text.lower()
    return any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in patterns)

def verifier_reponse_naima(
    texte_naima: str,
    *,
    decision_pedagogique: Optional[Dict[str, Any]] = None,
    validation: Optional[Dict[str, Any]] = None,
    lang: str = "fr",
    max_questions: int = 1,
) -> Dict[str, Any]:
    texte = str(texte_naima or "").strip()
    decision = decision_pedagogique or {}
    validation = validation or {}
    problemes: List[str] = []

    if not texte:
        problemes.append("reponse_vide")

    question_count = texte.count("?")
    if max_questions is not None and question_count > max_questions:
        problemes.append("trop_de_questions")

    peut_reveler = bool(decision.get("peut_reveler_solution", False))
    fuite_solution = _detect_solution_leakage(texte, lang)
    if fuite_solution and not peut_reveler:
        problemes.append("solution_revelee")

    strategie = decision.get("strategie")
    prise_controle = False
    if strategie == "rendre_controle_a_eleve":
        prise_controle = _detect_strategic_takeover(texte, lang)
        if prise_controle:
            problemes.append("prise_controle_strategique")

    verdict = validation.get("verdict") or validation.get("validation_verdict")

    if verdict == "correct":
        negatives = (
            ["incorrect", "faux", "fausse", "ce n'est pas correct", "ce n’est pas correct"]
            if lang == "fr"
            else ["incorrect", "wrong", "not correct"]
        )
        if any(token in texte.lower() for token in negatives):
            problemes.append("contradiction_validation_correcte")

    if verdict == "uncertain":
        definitive_negative = (
            ["c'est faux", "c’est faux", "ta réponse est fausse", "incorrect"]
            if lang == "fr"
            else ["that's wrong", "your answer is wrong", "incorrect"]
        )
        if any(token in texte.lower() for token in definitive_negative):
            problemes.append("jugement_definitif_sur_incertain")

    conforme = len(problemes) == 0

    return {
        "conforme": conforme,
        "problemes": problemes,
        "question_count": question_count,
        "solution_leakage": fuite_solution,
        "prise_controle_strategique": prise_controle,
        "requires_regeneration": not conforme,
        "strategie": strategie,
        "validation_verdict": verdict,
    }

def construire_instruction_regeneration(
    resultat_guard: Dict[str, Any],
    *,
    lang: str = "fr",
) -> str:
    problemes = resultat_guard.get("problemes") or []

    if lang == "en":
        return (
            "Rewrite your previous answer. It failed the pedagogical guard for: "
            + ", ".join(problemes)
            + ". Keep the same teaching strategy, do not reveal the final answer, "
              "do not choose the next operation for the student when control must "
              "remain with the learner, and ask at most one question."
        )

    return (
        "Réécris ta réponse précédente. Elle a échoué au garde-fou pédagogique pour : "
        + ", ".join(problemes)
        + ". Garde la même stratégie pédagogique, ne révèle pas la solution finale, "
          "ne choisis pas la prochaine opération à la place de l'élève lorsque le "
          "contrôle doit lui être rendu, et pose au maximum une question."
    )
