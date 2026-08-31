from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional
import re

@dataclass
class CognitiveControlResult:
    niveau: str
    confiance: float
    raison: str
    strategie_recommandee: str
    def to_dict(self): return asdict(self)

_VALIDATION=[r"\best[- ]?ce correct\b",r"\bvérifie\b",r"\bverifie\b",r"\bai[- ]?je raison\b",r"\bis this correct\b",r"\bcheck my answer\b"]
_HINT=[r"\bdonne[- ]?moi un indice\b",r"\bun indice\b",r"\baide[- ]?moi sans donner la réponse\b",r"\bgive me a hint\b",r"\bhint\b"]
_DELEGATION=[r"\bque dois[- ]?je faire maintenant\b",r"\bdis[- ]?moi quoi faire\b",r"\bdonne[- ]?moi la prochaine étape\b",r"\bfais[- ]?le pour moi\b",r"\bfais l['’]?exercice\b",r"\bdonne[- ]?moi la réponse\b",r"\bwhat should i do now\b",r"\btell me what to do\b",r"\bgive me the next step\b",r"\bsolve it for me\b",r"\bgive me the answer\b"]
_AUTONOMY=[r"\bje vais\b",r"\bj['’]?essaie\b",r"\bje pense que\b",r"\bdonc\b",r"\bparce que\b",r"\bj['’]?obtiens\b",r"\bje vérifie\b",r"\bi will\b",r"\bi think\b",r"\btherefore\b",r"\bbecause\b"]
def _matches(text, patterns): return any(re.search(p,text,re.I) for p in patterns)

def detecter_controle_cognitif(message_eleve: str, *, derniere_question_naima: Optional[str]=None,
    intention_pedagogique: Optional[Dict[str,Any]]=None) -> Dict[str,Any]:
    texte=str(message_eleve or "").strip().lower()
    if not texte:
        return CognitiveControlResult("indetermine",0.35,"Message vide ou insuffisant.","observer").to_dict()
    intention_type=str((intention_pedagogique or {}).get("type_demande") or "").strip()
    if _matches(texte,_DELEGATION):
        return CognitiveControlResult("delegation_strategique",0.96,"L'élève demande à Naïma de choisir ou exécuter la prochaine étape.","rendre_controle_a_eleve").to_dict()
    if intention_type=="demande_indice" or _matches(texte,_HINT):
        return CognitiveControlResult("demande_indice",0.92,"L'élève demande une aide ponctuelle.","indice_minimal").to_dict()
    if intention_type=="demande_verification" or _matches(texte,_VALIDATION):
        return CognitiveControlResult("demande_validation",0.92,"L'élève propose une démarche et demande une validation.","valider_sans_prendre_controle").to_dict()
    if _matches(texte,_AUTONOMY) or re.search(r"[=<>]|[-+]?\d",texte):
        return CognitiveControlResult("autonome",0.82,"L'élève produit une proposition, un calcul ou une justification.","laisser_eleve_planifier").to_dict()
    if derniere_question_naima:
        return CognitiveControlResult("partage",0.58,"Interaction guidée sans délégation claire.","guidage_leger").to_dict()
    return CognitiveControlResult("partage",0.50,"Niveau de contrôle peu clair.","guidage_leger").to_dict()
