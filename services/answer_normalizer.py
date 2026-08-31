import re
import unicodedata


class AnswerNormalizer:
    """
    Normalisation prudente des réponses scolaires.

    IMPORTANT :
    normaliser ne signifie pas décider si une réponse
    est correcte.
    """

    REPLACEMENTS = {
        "−": "-",
        "–": "-",
        "—": "-",
        "×": "*",
        "·": "*",
        "÷": "/",
        "⁄": "/",
        "²": "**2",
        "³": "**3",
    }

    def normalize(self, answer):
        if answer is None:
            return ""

        text = str(answer).strip()

        for old, new in self.REPLACEMENTS.items():
            text = text.replace(old, new)

        # Virgule décimale simple :
        # 3,5 -> 3.5
        text = re.sub(
            r"(?<=\d),(?=\d)",
            ".",
            text
        )

        # Espaces multiples
        text = re.sub(
            r"\s+",
            " ",
            text
        ).strip()

        # Espaces autour de =
        text = re.sub(
            r"\s*=\s*",
            "=",
            text
        )

        # Espaces autour des opérateurs
        text = re.sub(
            r"\s*([+\-*/])\s*",
            r"\1",
            text
        )

        return text

    def normalize_text(self, answer):
        """
        Version textuelle utile pour les réponses
        non purement mathématiques.
        """

        text = self.normalize(answer).lower()

        text = "".join(
            char
            for char in unicodedata.normalize(
                "NFD",
                text
            )
            if unicodedata.category(char) != "Mn"
        )

        return text