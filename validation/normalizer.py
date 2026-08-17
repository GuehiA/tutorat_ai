import re
import unicodedata
from typing import Optional


class AnswerNormalizer:
    """
    Normalise une réponse d'élève ou une réponse attendue
    sans essayer de décider si elle est correcte.
    """

    def normalize(self, answer: Optional[str]) -> str:
        if answer is None:
            return ""

        text = str(answer)

        # Normalisation Unicode
        text = unicodedata.normalize("NFKC", text)

        # Retirer les espaces inutiles en début et fin
        text = text.strip()

        if not text:
            return ""

        # Uniformiser les espaces multiples
        text = re.sub(r"\s+", " ", text)

        # Uniformiser certains symboles mathématiques
        replacements = {
            "×": "*",
            "·": "*",
            "÷": "/",
            "−": "-",
            "–": "-",
            "—": "-",
            "＝": "=",
        }

        for old, new in replacements.items():
            text = text.replace(old, new)

        # Virgule décimale simple :
        # 3,5 -> 3.5
        # mais on évite de modifier arbitrairement une liste comme 2, 3, 5
        text = re.sub(
            r"(?<=\d),(?=\d)",
            ".",
            text
        )

        # Retirer les espaces autour de certains opérateurs
        text = re.sub(r"\s*=\s*", "=", text)
        text = re.sub(r"\s*\+\s*", "+", text)
        text = re.sub(r"\s*-\s*", "-", text)
        text = re.sub(r"\s*\*\s*", "*", text)
        text = re.sub(r"\s*/\s*", "/", text)
        text = re.sub(r"\s*\^\s*", "^", text)

        return text