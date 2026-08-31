from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Optional
import re

@dataclass
class BehavioralStateResult:
    etat: str
    score_dependance: float
    confiance: float
    nb_demandes_aide_consecutives: int
    nb_tentatives_recentes: int
    aide_repetee: bool
    modification_apres_aide: Optional[bool]
    temps_depuis_derniere_aide: Optional[int]
    signaux: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

_HELP_PATTERNS = [
    r"\baide[- ]?moi\b",
    r"\bje suis bloqu[ée]?\b",
    r"\bje ne sais pas\b",
    r"\bje sais pas\b",
    r"\bje ne comprends pas\b",
    r"\bje comprends pas\b",
    r"\bje ne comprend pas\b",
    r"\bje comprend pas\b",
    r"\bje ne comprends plus(?:\s+ta|\s+la|\s+le)?(?:\s+question)?\b",
    r"\bje comprends plus(?:\s+ta|\s+la|\s+le)?(?:\s+question)?\b",
    r"\bje ne comprend plus(?:\s+ta|\s+la|\s+le)?(?:\s+question)?\b",
    r"\bje comprend plus(?:\s+ta|\s+la|\s+le)?(?:\s+question)?\b",
    r"\bj['’]?ai pas compris\b",
    r"\bje n['’]?ai pas compris\b",
    r"\bje n['’]?arrive pas\b",
    r"\bj['’]?arrive pas\b",
    r"\bje suis perdu[e]?\b",
    r"\bje suis coinc[ée]?\b",
    r"\bquelle est la prochaine étape\b",
    r"\bdonne[- ]?moi la prochaine étape\b",
    r"\bque dois[- ]?je faire\b",
    r"\bqu['’]est[- ]?ce que je fais\b",
    r"\bdonne[- ]?moi un indice\b",
    r"\bun indice\b",
    r"\bhelp me\b",
    r"\bi(?:'| a)m stuck\b",
    r"\bwhat should i do\b",
    r"\bnext step\b",
    r"\bgive me a hint\b",
]

_DIRECT_DELEGATION_PATTERNS = [
    r"\bfais[- ]?le pour moi\b",
    r"\bfais l['’]?exercice\b",
    r"\bdonne[- ]?moi la réponse\b",
    r"\bdonne moi la reponse\b",
    r"\bdis[- ]?moi quoi faire\b",
    r"\bdonne[- ]?moi la prochaine étape\b",
    r"\bquelle est la prochaine étape\b",
    r"\brésous[- ]?le pour moi\b",
    r"\bresous[- ]?le pour moi\b",
    r"\bfais le calcul\b",
    r"\bsolve it for me\b",
    r"\bgive me the answer\b",
    r"\btell me exactly what to do\b",
    r"\bgive me the next step\b",
]

_INDEPENDENT_WORK_PATTERNS = [
    r"\bj['’]?essaie\b",
    r"\bje pense que\b",
    r"\bje vais\b",
    r"\bj['’]?obtiens\b",
    r"\bdonc\b",
    r"\bparce que\b",
    r"\bje vérifie\b",
    r"\bje verifie\b",
    r"\bje corrige\b",
    r"\bi think\b",
    r"\bi will\b",
    r"\bi get\b",
    r"\btherefore\b",
    r"\bbecause\b",
    r"\bi checked\b",
]

def _contains_pattern(text: str, patterns: Iterable[str]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)

def _normalize_history(historique: Optional[Iterable[Any]]) -> List[Dict[str, Any]]:
    result = []
    for item in historique or []:
        result.append(item if isinstance(item, dict) else {"texte": str(item)})
    return result

def _consecutive_help_requests(history: List[Dict[str, Any]], current_text: str) -> int:
    recent_texts = []
    for item in history[-8:]:
        role = str(item.get("role") or item.get("auteur") or "").lower()
        if role and role not in {"eleve", "élève", "student", "user"}:
            continue
        txt = str(
            item.get("texte")
            or item.get("message")
            or item.get("content")
            or item.get("reponse_eleve")
            or ""
        ).strip()
        if txt:
            recent_texts.append(txt)

    if current_text:
        recent_texts.append(current_text)

    count = 0
    for txt in reversed(recent_texts):
        normalized = txt.lower().strip()
        if (
            _contains_pattern(normalized, _HELP_PATTERNS)
            or _contains_pattern(normalized, _DIRECT_DELEGATION_PATTERNS)
        ):
            count += 1
            continue
        if _contains_pattern(normalized, _INDEPENDENT_WORK_PATTERNS):
            break
        if re.search(r"[=<>]|[-+]?\d", normalized):
            break
        break
    return count

def diagnostiquer_etat_comportemental(
    message_eleve: str,
    *,
    historique: Optional[Iterable[Any]] = None,
    nb_tentatives_recentes: int = 0,
    aide_utilisee: bool = False,
    nb_indices_recentes: int = 0,
    temps_depuis_derniere_aide: Optional[int] = None,
    modification_apres_aide: Optional[bool] = None,
    verdict_validation: Optional[str] = None,
) -> Dict[str, Any]:
    texte = str(message_eleve or "").strip().lower()
    history = _normalize_history(historique)
    signaux = []
    score = 0.0

    demande_aide = _contains_pattern(texte, _HELP_PATTERNS)
    delegation_directe = _contains_pattern(texte, _DIRECT_DELEGATION_PATTERNS)
    travail_independant = _contains_pattern(texte, _INDEPENDENT_WORK_PATTERNS)

    nb_demandes_consecutives = _consecutive_help_requests(
        history, str(message_eleve or "").strip()
    )

    if delegation_directe:
        score += 0.70
        signaux.append("delegation_directe")
    if demande_aide:
        score += 0.15
        signaux.append("demande_aide")
    if nb_demandes_consecutives >= 2:
        score += min(0.25, 0.08 * nb_demandes_consecutives)
        signaux.append(f"aide_consecutive_{nb_demandes_consecutives}")
    if nb_indices_recentes >= 2:
        score += min(0.20, 0.05 * nb_indices_recentes)
        signaux.append(f"indices_repetes_{nb_indices_recentes}")
    if aide_utilisee:
        signaux.append("aide_utilisee")
    if modification_apres_aide is False and (aide_utilisee or nb_indices_recentes > 0):
        score += 0.25
        signaux.append("pas_de_travail_apres_aide")
    if modification_apres_aide is True:
        score -= 0.20
        signaux.append("travail_apres_aide")
    if travail_independant:
        score -= 0.20
        signaux.append("initiative_eleve")
    if nb_tentatives_recentes >= 2 and not demande_aide:
        score -= 0.10
        signaux.append("tentatives_autonomes")
    if (
        temps_depuis_derniere_aide is not None
        and temps_depuis_derniere_aide >= 60
        and modification_apres_aide is True
    ):
        score -= 0.10
        signaux.append("temps_de_travail_independant")
    if verdict_validation == "uncertain":
        signaux.append("validation_incertaine_non_penalisante")

    score = max(0.0, min(1.0, score))

    if not texte:
        etat, confiance = "indetermine", 0.35
    elif delegation_directe:
        etat, confiance = "dependance_probable", 0.95
    elif score >= 0.65:
        etat = "dependance_probable"
        confiance = min(0.95, 0.60 + score * 0.35)
    elif (
        demande_aide
        or "pas_de_travail_apres_aide" in signaux
        or (verdict_validation == "incorrect" and nb_tentatives_recentes >= 2)
    ):
        etat, confiance = "blocage", 0.72
    else:
        etat = "travail_independant"
        confiance = 0.78 if travail_independant else 0.62

    return BehavioralStateResult(
        etat=etat,
        score_dependance=round(score, 3),
        confiance=round(confiance, 3),
        nb_demandes_aide_consecutives=nb_demandes_consecutives,
        nb_tentatives_recentes=max(0, int(nb_tentatives_recentes or 0)),
        aide_repetee=bool(nb_demandes_consecutives >= 2 or nb_indices_recentes >= 2),
        modification_apres_aide=modification_apres_aide,
        temps_depuis_derniere_aide=temps_depuis_derniere_aide,
        signaux=signaux,
    ).to_dict()
