# services/math_verification.py

from fractions import Fraction
import re


def verifier_expression_fractionnaire(texte):
    """
    Vérifie des égalités simples avec fractions.

    Exemples reconnus :
    - 2/20 = 2/10
    - 2/20 = 1/10
    - 13/3 * 1/2 = 13/6
    - 4 + 1/3 = 13/3

    Retourne un dictionnaire utilisable comme instruction interne pour Naima.
    """

    if not texte:
        return resultat_non_verifie()

    texte_normalise = normaliser_expression(texte)

    if "=" not in texte_normalise:
        return resultat_non_verifie()

    try:
        gauche, droite = texte_normalise.split("=", 1)

        gauche = nettoyer_expression(gauche)
        droite = nettoyer_expression(droite)

        if not gauche or not droite:
            return resultat_non_verifie()

        valeur_gauche = eval_fraction_securise(gauche)
        valeur_droite = eval_fraction_securise(droite)

        est_correct = valeur_gauche == valeur_droite

        return {
            "calcul_verifie": True,
            "est_correct": est_correct,
            "valeur_gauche": str(valeur_gauche),
            "valeur_droite": str(valeur_droite),
            "message_interne": construire_message_interne(
                est_correct=est_correct,
                gauche=gauche,
                droite=droite,
                valeur_gauche=valeur_gauche,
                valeur_droite=valeur_droite
            )
        }

    except Exception:
        return resultat_non_verifie()


def normaliser_expression(texte):
    texte = texte.lower().strip()

    remplacements = {
        " ": "",
        ",": ".",
        "×": "*",
        "÷": "/",
        "égal": "=",
        "egale": "=",
        "égale": "=",
        "estegaleà": "=",
        "estegalea": "=",
        "estégaleà": "=",
        "estégalà": "=",
        "estegala": "=",
        "revientà": "=",
        "revienta": "=",
        "donne": "=",
    }

    for ancien, nouveau in remplacements.items():
        texte = texte.replace(ancien, nouveau)

    texte = texte.replace("divisépar", "/")
    texte = texte.replace("divisepar", "/")
    texte = texte.replace("multipliépar", "*")
    texte = texte.replace("multipliepar", "*")

    return texte


def nettoyer_expression(expression):
    """
    Garde seulement la partie mathématique utile.
    Exemple :
    'oui2/20=1/10' devient traité par le split avant.
    Ici on retire les caractères non mathématiques autour.
    """

    expression = expression.strip()

    # Garde uniquement chiffres, opérateurs, parenthèses et points.
    morceaux = re.findall(r"[0-9+\-*/().]+", expression)

    if not morceaux:
        return ""

    return morceaux[-1] if len(morceaux) > 1 else morceaux[0]


def eval_fraction_securise(expression):
    """
    Évalue une expression fractionnaire simple avec Fraction.

    Autorisé :
    - nombres
    - + - * /
    - parenthèses
    - points décimaux simples
    """

    if not re.fullmatch(r"[0-9+\-*/().]+", expression):
        raise ValueError("Expression non autorisée")

    expression_fraction = re.sub(
        r"\b\d+(?:\.\d+)?\b",
        lambda m: f"Fraction('{m.group(0)}')",
        expression
    )

    return eval(
        expression_fraction,
        {"__builtins__": {}},
        {"Fraction": Fraction}
    )


def construire_message_interne(est_correct, gauche, droite, valeur_gauche, valeur_droite):
    if est_correct:
        return (
            "Vérification mathématique locale : l'égalité proposée par l'élève est correcte. "
            f"Le côté gauche ({gauche}) vaut {valeur_gauche}, "
            f"et le côté droit ({droite}) vaut {valeur_droite}. "
            "Naima doit reconnaître clairement que l'élève a raison avant de continuer."
        )

    return (
        "Vérification mathématique locale : l'égalité proposée par l'élève est incorrecte. "
        f"Le côté gauche ({gauche}) vaut {valeur_gauche}, "
        f"mais le côté droit ({droite}) vaut {valeur_droite}. "
        "Naima doit corriger doucement l'erreur et guider l'élève étape par étape."
    )


def resultat_non_verifie():
    return {
        "calcul_verifie": False,
        "est_correct": None,
        "message_interne": ""
    }