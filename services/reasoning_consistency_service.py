"""
Détection conservatrice des cas :
    résultat final correct
    MAIS opération verbale incompatible avec l'équation courante.

Aucune conclusion n'est produite si le contexte n'est pas de la forme a*x=b.
"""

from __future__ import annotations

from fractions import Fraction
import re
from typing import Any, Dict, Optional


def _validation_dict(validation: Optional[Any]) -> Dict[str, Any]:
    if validation is None:
        return {}
    if isinstance(validation, dict):
        return validation
    if hasattr(validation, "to_dict"):
        try:
            return validation.to_dict()
        except Exception:
            return {}
    return {
        "verdict": getattr(validation, "verdict", None),
        "confidence": getattr(validation, "confidence", None),
        "method": getattr(validation, "method", None),
        "result_correct": getattr(validation, "result_correct", None),
    }


def _extraire_forme_ax_b(equation: str):
    eq = str(equation or "").replace(" ", "").replace("×", "*")
    m = re.fullmatch(
        r"([-+]?\d+(?:/\d+)?(?:\.\d+)?)\*?x="
        r"([-+]?\d+(?:/\d+)?(?:\.\d+)?)",
        eq,
        flags=re.IGNORECASE,
    )
    if not m:
        return None
    try:
        return {
            "coefficient": Fraction(m.group(1)),
            "droite": Fraction(m.group(2)),
        }
    except Exception:
        return None


def _extraire_division_verbalisee(message: str):
    texte = (
        str(message or "")
        .lower()
        .replace(",", ".")
        .replace("−", "-")
    )

    patterns = [
        r"\bdivis(?:e|er|ons|ant|é|ee|ée)?\b"
        r"(?:\s+les\s+deux\s+membres)?\s*"
        r"(?:par\s+)?([-+]?\d+(?:\.\d+)?(?:/\d+)?)",
        r"\bon\s+divise\b(?:\s+les\s+deux\s+membres)?\s*"
        r"(?:par\s+)?([-+]?\d+(?:\.\d+)?(?:/\d+)?)",
        r"\bje\s+divise\b(?:\s+les\s+deux\s+membres)?\s*"
        r"(?:par\s+)?([-+]?\d+(?:\.\d+)?(?:/\d+)?)",
    ]

    for pattern in patterns:
        m = re.search(pattern, texte, flags=re.IGNORECASE)
        if m:
            try:
                return Fraction(m.group(1))
            except Exception:
                pass
    return None


def verifier_coherence_resultat_raisonnement(
    *,
    message_eleve: str,
    equation_courante: str,
    validation: Optional[Any],
    lang: str = "fr",
) -> Dict[str, Any]:
    """
    Retour :
      conflit=False : aucune contradiction prouvée.
      conflit=True  : résultat validé, mais justification verbale fausse.
    """
    validation_d = _validation_dict(validation)

    if not (
        validation_d.get("verdict") == "correct"
        and float(validation_d.get("confidence") or 0.0) >= 0.95
        and validation_d.get("method") == "equation_solution"
        and validation_d.get("result_correct") is True
    ):
        return {"conflit": False}

    forme = _extraire_forme_ax_b(equation_courante)
    if not forme:
        return {"conflit": False}

    coefficient = forme["coefficient"]
    if coefficient in (0, 1):
        return {"conflit": False}

    diviseur_annonce = _extraire_division_verbalisee(message_eleve)
    if diviseur_annonce is None:
        return {"conflit": False}

    if diviseur_annonce == coefficient:
        return {
            "conflit": False,
            "operation_verbalisee": "divide",
            "valeur_verbalisee": str(diviseur_annonce),
            "valeur_attendue": str(coefficient),
        }

    if lang == "en":
        message_pedagogique = (
            "Your final result is correct, but there is a contradiction in the "
            "reasoning you wrote. From "
            f"**{str(equation_courante).replace('*', '')}**, you said to divide "
            f"by **{diviseur_annonce}**. Which number should you actually divide "
            "both sides by to remove the coefficient of x? — Naima ✨"
        )
    else:
        message_pedagogique = (
            "Ton résultat final est correct, mais il y a une contradiction dans "
            "le raisonnement écrit. À partir de "
            f"**{str(equation_courante).replace('*', '')}**, tu as indiqué qu'il "
            f"fallait diviser par **{diviseur_annonce}**. Par quel nombre faut-il "
            "réellement diviser les deux membres pour éliminer le coefficient de x ? "
            "— Naima ✨"
        )

    return {
        "conflit": True,
        "result_correct": True,
        "reasoning_correct": False,
        "error_type": "correct_result_wrong_reasoning_operation",
        "operation_verbalisee": "divide",
        "valeur_verbalisee": str(diviseur_annonce),
        "operation_attendue": "divide",
        "valeur_attendue": str(coefficient),
        "equation_courante": equation_courante,
        "message_pedagogique": message_pedagogique,
        "reason": (
            "Le résultat final est correct, mais l'opération verbalisée "
            "est incompatible avec le coefficient de l'équation courante."
        ),
    }
