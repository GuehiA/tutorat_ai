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

import re
import ast
from fractions import Fraction


def _normaliser_texte_math(texte):
    texte = texte or ""
    texte = texte.lower()

    remplacements = {
        "×": "*",
        "÷": "/",
        "−": "-",
        "–": "-",
        "²": "**2",
        "^": "**",
        ",": ".",
    }

    for ancien, nouveau in remplacements.items():
        texte = texte.replace(ancien, nouveau)

    # 3x -> 3*x
    texte = re.sub(r"(\d)(x)", r"\1*\2", texte)

    # )x -> )*x
    texte = re.sub(r"(\))(x)", r"\1*\2", texte)

    # x( -> x*(
    texte = re.sub(r"(x)(\()", r"\1*\2", texte)

    return texte


def _eval_expr_fraction(expr, x_value=None):
    """
    Évalue une expression mathématique simple avec Fraction.
    Autorise seulement :
    - nombres
    - x
    - +, -, *, /, **
    - parenthèses
    """

    expr = _normaliser_texte_math(expr)
    tree = ast.parse(expr, mode="eval")

    def eval_node(node):
        if isinstance(node, ast.Expression):
            return eval_node(node.body)

        if isinstance(node, ast.Constant):
            if isinstance(node.value, int):
                return Fraction(node.value, 1)
            if isinstance(node.value, float):
                return Fraction(str(node.value))
            raise ValueError("Constante non autorisée")

        if isinstance(node, ast.Name):
            if node.id == "x" and x_value is not None:
                return x_value
            raise ValueError("Variable non autorisée")

        if isinstance(node, ast.UnaryOp):
            value = eval_node(node.operand)
            if isinstance(node.op, ast.USub):
                return -value
            if isinstance(node.op, ast.UAdd):
                return value
            raise ValueError("Opérateur unaire non autorisé")

        if isinstance(node, ast.BinOp):
            left = eval_node(node.left)
            right = eval_node(node.right)

            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.Pow):
                if right.denominator != 1:
                    raise ValueError("Puissance non entière")
                return left ** right.numerator

            raise ValueError("Opérateur non autorisé")

        raise ValueError("Expression non autorisée")

    return eval_node(tree)


def _extraire_equation_depuis_texte(texte):
    """
    Extrait une équation contenant '=' depuis un texte.
    Exemple :
    'Résoudre x/4=3/16 ?' -> 'x/4=3/16'
    """

    texte = _normaliser_texte_math(texte)

    # On retire les mots fréquents avant l'équation
    texte = texte.replace("résoudre", "")
    texte = texte.replace("resoudre", "")
    texte = texte.replace("l'équation", "")
    texte = texte.replace("l’equation", "")
    texte = texte.replace("equation", "")
    texte = texte.replace("équation", "")
    texte = texte.replace("?", " ")
    texte = texte.replace(":", " ")

    # Cherche une partie avec =
    morceaux = re.findall(r"[a-z0-9\+\-\*/\.\(\)\s\*]+=[a-z0-9\+\-\*/\.\(\)\s\*]+", texte)

    if not morceaux:
        return None

    equation = morceaux[0].strip()

    # Nettoyage léger
    equation = re.sub(r"\s+", "", equation)

    return equation


def _extraire_valeur_x_depuis_reponse(reponse):
    """
    Extrait la valeur proposée pour x.
    Exemples :
    'x=3/4' -> '3/4'
    'je trouve x=(3*4)/16' -> '(3*4)/16'
    """

    texte = _normaliser_texte_math(reponse)

    match = re.search(r"x\s*=\s*([0-9x\+\-\*/\.\(\)\s\*]+)", texte)

    if not match:
        return None

    valeur = match.group(1).strip()

    # Arrêter la capture si la phrase continue
    valeur = re.split(r"( donc | alors | car | parce | après | apres | et |,|;|\.)", valeur)[0].strip()

    return valeur


def verifier_solution_equation_fractionnaire(equation_initiale, reponse_eleve):
    """
    Vérifie si une réponse du type x = ... satisfait l'équation initiale.

    Exemple :
    equation_initiale = 'Résoudre x/4=3/16 ?'
    reponse_eleve = 'je trouve x=3/4'

    Retour :
    {
        "verification_contextuelle": True,
        "est_correct": True,
        ...
    }
    """

    equation = _extraire_equation_depuis_texte(equation_initiale)
    valeur_x_txt = _extraire_valeur_x_depuis_reponse(reponse_eleve)

    if not equation or not valeur_x_txt:
        return {
            "verification_contextuelle": False,
            "est_correct": None,
            "message_interne": ""
        }

    try:
        gauche_txt, droite_txt = equation.split("=", 1)

        valeur_x = _eval_expr_fraction(valeur_x_txt)

        valeur_gauche = _eval_expr_fraction(gauche_txt, x_value=valeur_x)
        valeur_droite = _eval_expr_fraction(droite_txt, x_value=valeur_x)

        est_correct = valeur_gauche == valeur_droite

        if est_correct:
            message = (
                f"Vérification mathématique contextuelle : "
                f"l'équation initiale est {equation}. "
                f"L'élève propose x = {valeur_x_txt}. "
                f"En remplaçant x, on obtient gauche = {valeur_gauche} "
                f"et droite = {valeur_droite}. "
                f"Les deux valeurs sont égales. "
                f"La réponse de l'élève est donc correcte. "
                f"Tu dois la reconnaître clairement et passer à l'étape suivante. "
                f"Ne dis pas que cette réponse est fausse."
            )
        else:
            message = (
                f"Vérification mathématique contextuelle : "
                f"l'équation initiale est {equation}. "
                f"L'élève propose x = {valeur_x_txt}. "
                f"En remplaçant x, on obtient gauche = {valeur_gauche} "
                f"et droite = {valeur_droite}. "
                f"Les deux valeurs ne sont pas égales. "
                f"La réponse de l'élève est donc incorrecte. "
                f"Explique l'erreur avec douceur et guide l'élève."
            )

        return {
            "verification_contextuelle": True,
            "equation": equation,
            "valeur_x_proposee": valeur_x_txt,
            "valeur_x_calculee": str(valeur_x),
            "valeur_gauche": str(valeur_gauche),
            "valeur_droite": str(valeur_droite),
            "est_correct": est_correct,
            "message_interne": message
        }

    except Exception as e:
        return {
            "verification_contextuelle": False,
            "est_correct": None,
            "erreur": str(e),
            "message_interne": ""
        }