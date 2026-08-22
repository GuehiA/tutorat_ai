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
    Extrait proprement une équation contenant '=' depuis un texte.

    Exemples :
        "Résoudre x/4=3/16 ?" -> "x/4=3/16"
        "aide moi à résoudre 3x-2=5x+4" -> "3*x-2=5*x+4"

    Important :
    - les mots précédant l'équation ne doivent jamais être intégrés
      à l'expression mathématique ;
    - le signe négatif d'un terme est conservé.
    """

    texte = _normaliser_texte_math(texte or "")

    # On recherche uniquement une vraie zone mathématique autour de "=".
    # Les mots comme "aide", "résoudre", etc. ne peuvent donc pas être
    # absorbés dans l'équation.
    candidats = re.findall(
        r"(?<![a-zà-ÿ])"
        r"[-+]?[0-9x\.\(\)\+\-\*/\s]+"
        r"="
        r"[-+]?[0-9x\.\(\)\+\-\*/\s]+"
        r"(?![a-zà-ÿ])",
        texte,
        flags=re.IGNORECASE
    )

    equations_valides = []

    for candidat in candidats:
        equation = re.sub(r"\s+", "", candidat).strip()

        # Ne retirer que les caractères parasites de fin.
        # Ne jamais retirer le signe '-' du début.
        equation = equation.rstrip("+-*/.")

        if not equation or equation.count("=") != 1:
            continue

        gauche, droite = equation.split("=", 1)

        if not gauche or not droite:
            continue

        if not re.fullmatch(r"[0-9x+\-*/().]+", gauche):
            continue

        if not re.fullmatch(r"[0-9x+\-*/().]+", droite):
            continue

        equations_valides.append(equation)

    if not equations_valides:
        return None

    # La dernière équation explicite est généralement celle que l'utilisateur
    # veut réellement traiter.
    return equations_valides[-1]

def _extraire_valeur_x_depuis_reponse(reponse):
    """
    Extrait la valeur proposée pour x.
    Exemples :
    'x=3/4' -> '3/4'
    'je trouve x=(3*4)/16' -> '(3*4)/16'
    """

    texte = _normaliser_texte_math(reponse)

    match = re.search(
        r"(?<![0-9a-z*])x\s*=\s*([0-9x\+\-\*/\.\(\)\s\*]+)",
        texte
    )

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

def verifier_resultat_expression_contextuelle(objectif_initial, reponse_eleve):
    """
    Vérifie une réponse numérique/fractionnaire donnée en langage naturel
    par rapport à une expression arithmétique présente dans l'objectif initial.

    Exemple :
        objectif_initial = "Aide moi a effectuer 1/3+1/4"
        reponse_eleve = "le résultat est 7/12"

    Retour :
        {
            "verification_contextuelle": True,
            "est_correct": True,
            "expression_initiale": "1/3+1/4",
            "valeur_attendue": "7/12",
            "valeur_proposee": "7/12",
            "message_interne": "..."
        }

    Sécurité :
    - aucune variable n'est autorisée ;
    - seules les opérations numériques simples sont évaluées ;
    - si l'extraction est ambiguë, on retourne NON VÉRIFIÉ ;
    - non vérifié ne signifie jamais incorrect.
    """

    objectif = objectif_initial or ""
    reponse = reponse_eleve or ""

    if not objectif.strip() or not reponse.strip():
        return {
            "verification_contextuelle": False,
            "est_correct": None,
            "message_interne": ""
        }

    # ------------------------------------------------------------
    # 1. NORMALISER L'OBJECTIF
    # ------------------------------------------------------------

    objectif_normalise = _normaliser_texte_math(objectif)

    # ------------------------------------------------------------
    # 2. EXTRAIRE UNE EXPRESSION ARITHMÉTIQUE NUMÉRIQUE
    # ------------------------------------------------------------
    #
    # Exemples visés :
    #   1/3+1/4
    #   2+3/5
    #   (1/2)*4
    #   5-2/3
    #
    # On exige au moins un véritable opérateur arithmétique.
    # ------------------------------------------------------------

    candidats = re.findall(
        r"(?<![\w.])"
        r"[-+]?"
        r"(?:\d+(?:\.\d+)?|\(\s*[-+]?\d+(?:\.\d+)?\s*\))"
        r"(?:\s*[+\-*/]\s*"
        r"(?:\d+(?:\.\d+)?|\(\s*[-+]?\d+(?:\.\d+)?\s*\))"
        r")+",
        objectif_normalise
    )

    # Le motif précédent peut être trop restrictif pour des fractions
    # comme 1/3+1/4. On utilise donc un second extracteur contrôlé.
    if not candidats:
        candidats = re.findall(
            r"(?<![\w.])"
            r"[0-9.\s()+\-*/]+"
            r"(?![\w.])",
            objectif_normalise
        )

    expressions_valides = []

    for candidat in candidats:
        candidat = candidat.strip()

        if not candidat:
            continue

        # Retirer les espaces.
        candidat = re.sub(r"\s+", "", candidat)

        # Un candidat doit contenir au moins une opération.
        if not any(op in candidat for op in ["+", "-", "*", "/"]):
            continue

        # Pas de lettres.
        if re.search(r"[a-zA-Z]", candidat):
            continue

        # Seulement les caractères mathématiques autorisés.
        if not re.fullmatch(r"[0-9+\-*/().]+", candidat):
            continue

        try:
            valeur = _eval_expr_fraction(candidat)
            expressions_valides.append((candidat, valeur))
        except Exception:
            continue

    if not expressions_valides:
        return {
            "verification_contextuelle": False,
            "est_correct": None,
            "message_interne": ""
        }

    # On prend la dernière expression mathématique valide de l'objectif.
    expression_initiale, valeur_attendue = expressions_valides[-1]

    # ------------------------------------------------------------
    # 3. EXTRAIRE LA VALEUR PROPOSÉE PAR L'ÉLÈVE
    # ------------------------------------------------------------

    texte_reponse = _normaliser_texte_math(reponse).strip()

    valeur_proposee_txt = None

    # Cas A : réponse constituée uniquement d'une valeur.
    #
    # Exemples :
    #   7/12
    #   0.5
    #   -3
    #
    match_valeur_seule = re.fullmatch(
        r"\s*([-+]?\d+(?:\.\d+)?(?:\s*/\s*[-+]?\d+(?:\.\d+)?)?)\s*",
        texte_reponse
    )

    if match_valeur_seule:
        valeur_proposee_txt = match_valeur_seule.group(1)

    # Cas B : formulation explicite d'une réponse finale.
    #
    # Exemples :
    #   le résultat est 7/12
    #   la réponse est 7/12
    #   j'obtiens 7/12
    #   donc 7/12
    #   ça donne 7/12
    #
    if not valeur_proposee_txt:
        patterns_reponse = [
            r"(?:le\s+)?r[eé]sultat\s+(?:est|=)\s*"
            r"([-+]?\d+(?:\.\d+)?(?:\s*/\s*[-+]?\d+(?:\.\d+)?)?)",

            r"(?:la\s+)?r[eé]ponse\s+(?:est|=)\s*"
            r"([-+]?\d+(?:\.\d+)?(?:\s*/\s*[-+]?\d+(?:\.\d+)?)?)",

            r"j['’]?\s*obtiens\s*"
            r"([-+]?\d+(?:\.\d+)?(?:\s*/\s*[-+]?\d+(?:\.\d+)?)?)",

            r"on\s+obtient\s*"
            r"([-+]?\d+(?:\.\d+)?(?:\s*/\s*[-+]?\d+(?:\.\d+)?)?)",

            r"(?:donc|alors)\s*"
            r"([-+]?\d+(?:\.\d+)?(?:\s*/\s*[-+]?\d+(?:\.\d+)?)?)",

            r"(?:[cç]a|cela)\s+donne\s*"
            r"([-+]?\d+(?:\.\d+)?(?:\s*/\s*[-+]?\d+(?:\.\d+)?)?)",
        ]

        for pattern in patterns_reponse:
            match = re.search(
                pattern,
                texte_reponse,
                flags=re.IGNORECASE
            )

            if match:
                valeur_proposee_txt = match.group(1)
                break

    if not valeur_proposee_txt:
        return {
            "verification_contextuelle": False,
            "est_correct": None,
            "expression_initiale": expression_initiale,
            "valeur_attendue": str(valeur_attendue),
            "message_interne": ""
        }

    valeur_proposee_txt = re.sub(
        r"\s+",
        "",
        valeur_proposee_txt
    )

    # ------------------------------------------------------------
    # 4. ÉVALUATION EXACTE AVEC FRACTION
    # ------------------------------------------------------------

    try:
        valeur_proposee = _eval_expr_fraction(
            valeur_proposee_txt
        )
    except Exception:
        return {
            "verification_contextuelle": False,
            "est_correct": None,
            "expression_initiale": expression_initiale,
            "valeur_attendue": str(valeur_attendue),
            "message_interne": ""
        }

    est_correct = valeur_proposee == valeur_attendue

    # ------------------------------------------------------------
    # 5. MESSAGE PRIORITAIRE POUR NAIMA
    # ------------------------------------------------------------

    if est_correct:

        message_interne = (
            "Vérification mathématique contextuelle prioritaire : "
            f"l'objectif initial contient l'expression "
            f"{expression_initiale}. "
            f"Cette expression vaut exactement {valeur_attendue}. "
            f"L'élève propose {valeur_proposee}. "
            "La réponse de l'élève est donc mathématiquement correcte. "
            "Naima doit reconnaître clairement que cette réponse est correcte. "
            "Naima ne doit pas dire que cette réponse est fausse. "
            "Elle peut ensuite conclure l'exercice ou vérifier brièvement "
            "la compréhension si cela est pédagogiquement nécessaire."
        )

    else:

        message_interne = (
            "Vérification mathématique contextuelle : "
            f"l'objectif initial contient l'expression "
            f"{expression_initiale}, qui vaut exactement "
            f"{valeur_attendue}. "
            f"L'élève propose {valeur_proposee}. "
            "Ces valeurs ne sont pas égales. "
            "La réponse proposée est donc incorrecte pour cette expression. "
            "Naima doit corriger avec bienveillance et guider l'élève "
            "sans inventer une autre valeur."
        )

    return {
        "verification_contextuelle": True,
        "est_correct": est_correct,
        "expression_initiale": expression_initiale,
        "valeur_attendue": str(valeur_attendue),
        "valeur_proposee": str(valeur_proposee),
        "message_interne": message_interne
    }


def verifier_chaine_egalites_fractionnaire(texte, objectif_initial=""):
    """
    Vérifie une chaîne d'égalités numériques/fractionnaires contenue dans
    une phrase de l'élève.

    Exemples :
        "on a 1/2+1/3=3/6+2/6=5/6"
        "donc 1/2+1/3 = 5/6"

    Principes de sécurité :
    - seules des expressions numériques sont évaluées ;
    - aucune lettre/variable n'est évaluée ;
    - chaque membre de la chaîne doit avoir exactement la même valeur ;
    - si l'analyse est ambiguë, on retourne NON VÉRIFIÉ ;
    - NON VÉRIFIÉ ne signifie jamais incorrect.

    Si un objectif initial numérique est disponible, la fonction indique
    aussi si la chaîne correspond réellement à cet objectif et si le
    dernier membre constitue un résultat final explicite.
    """

    texte = texte or ""

    if "=" not in texte:
        return {
            "verification_chaine": False,
            "calcul_verifie": False,
            "est_correct": None,
            "message_interne": ""
        }

    texte_normalise = _normaliser_texte_math(texte)

    # ------------------------------------------------------------
    # EXTRACTION D'UNE CHAÎNE MATHÉMATIQUE CONTENANT AU MOINS "="
    # ------------------------------------------------------------
    #
    # On récupère uniquement des blocs composés de chiffres,
    # opérateurs, parenthèses, points et signes "=".
    # Les mots autour ("on a", "donc", etc.) sont ignorés.
    # ------------------------------------------------------------

    candidats = re.findall(
        r"[0-9\.\s\+\-\*/\(\)=]+",
        texte_normalise
    )

    chaines_valides = []

    for candidat in candidats:
        candidat = re.sub(r"\s+", "", candidat).strip()

        if not candidat or "=" not in candidat:
            continue

        candidat = candidat.strip("=+-*/.")

        if "=" not in candidat:
            continue

        if not re.fullmatch(r"[0-9+\-*/().=]+", candidat):
            continue

        membres = [m.strip() for m in candidat.split("=")]

        if len(membres) < 2 or any(not m for m in membres):
            continue

        valeurs = []

        try:
            for membre in membres:
                valeurs.append(_eval_expr_fraction(membre))
        except Exception:
            continue

        chaines_valides.append(
            {
                "chaine": candidat,
                "membres": membres,
                "valeurs": valeurs
            }
        )

    if not chaines_valides:
        return {
            "verification_chaine": False,
            "calcul_verifie": False,
            "est_correct": None,
            "message_interne": ""
        }

    # On privilégie la chaîne la plus riche, puis la dernière trouvée.
    chaine_info = sorted(
        chaines_valides,
        key=lambda item: (len(item["membres"]), len(item["chaine"]))
    )[-1]

    chaine = chaine_info["chaine"]
    membres = chaine_info["membres"]
    valeurs = chaine_info["valeurs"]

    valeur_reference = valeurs[0]
    est_correct = all(
        valeur == valeur_reference
        for valeur in valeurs[1:]
    )

    # ------------------------------------------------------------
    # LE DERNIER MEMBRE EST-IL UN RÉSULTAT FINAL EXPLICITE ?
    # ------------------------------------------------------------
    #
    # On considère comme final :
    # - un entier : 5
    # - un décimal : 0.5
    # - une fraction simple : 5/6
    # - un nombre négatif : -23/35
    #
    # Une expression comme 3/6+2/6 n'est pas encore considérée
    # comme un résultat final explicite.
    # ------------------------------------------------------------

    dernier_membre = membres[-1]

    resultat_final_explicite = bool(
        re.fullmatch(
            r"[-+]?\d+(?:\.\d+)?(?:/[-+]?\d+(?:\.\d+)?)?",
            dernier_membre
        )
    )

    # ------------------------------------------------------------
    # COMPARAISON AVEC L'OBJECTIF INITIAL
    # ------------------------------------------------------------

    correspond_objectif = False
    valeur_objectif = None
    expression_objectif = None

    objectif = objectif_initial or ""

    if objectif.strip():
        objectif_normalise = _normaliser_texte_math(objectif)

        candidats_objectif = re.findall(
            r"[0-9\.\s\+\-\*/\(\)]+",
            objectif_normalise
        )

        expressions_objectif = []

        for candidat in candidats_objectif:
            candidat = re.sub(r"\s+", "", candidat).strip()

            if not candidat:
                continue

            if not any(op in candidat for op in ["+", "-", "*", "/"]):
                continue

            if not re.fullmatch(r"[0-9+\-*/().]+", candidat):
                continue

            try:
                valeur = _eval_expr_fraction(candidat)
                expressions_objectif.append((candidat, valeur))
            except Exception:
                continue

        if expressions_objectif:
            expression_objectif, valeur_objectif = expressions_objectif[-1]

            correspond_objectif = (
                valeur_reference == valeur_objectif
            )

    # ------------------------------------------------------------
    # MESSAGE INTERNE PRIORITAIRE
    # ------------------------------------------------------------

    if est_correct:
        message = (
            "Vérification mathématique locale d'une chaîne d'égalités : "
            f"la chaîne « {chaine} » est correcte. "
            f"Tous ses membres valent exactement {valeur_reference}. "
        )

        if correspond_objectif:
            message += (
                f"Elle correspond à l'objectif initial "
                f"« {expression_objectif} », qui vaut aussi "
                f"{valeur_objectif}. "
            )

        if resultat_final_explicite and correspond_objectif:
            message += (
                f"Le dernier membre ({dernier_membre}) est un résultat "
                "final explicite et correct pour l'objectif initial. "
                "Naima doit reconnaître que l'objectif est atteint. "
                "Elle ne doit pas revenir à une étape déjà validée "
                "et ne doit pas poser une nouvelle question sur cet exercice."
            )
        else:
            message += (
                "Naima doit reconnaître clairement que cette étape est "
                "correcte et poursuivre uniquement vers l'étape suivante. "
                "Elle ne doit pas revenir sur une étape déjà validée."
            )

    else:
        details = ", ".join(
            f"{membre}={valeur}"
            for membre, valeur in zip(membres, valeurs)
        )

        message = (
            "Vérification mathématique locale d'une chaîne d'égalités : "
            f"la chaîne « {chaine} » n'est pas entièrement correcte. "
            f"Valeurs calculées : {details}. "
            "Naima doit corriger uniquement la première rupture d'égalité "
            "et ne pas inventer une autre erreur."
        )

    return {
        "verification_chaine": True,
        "calcul_verifie": True,
        "est_correct": est_correct,
        "chaine": chaine,
        "membres": membres,
        "valeurs": [str(v) for v in valeurs],
        "valeur_commune": str(valeur_reference) if est_correct else None,
        "resultat_final_explicite": resultat_final_explicite,
        "resultat_final": str(valeurs[-1]) if resultat_final_explicite else None,
        "correspond_objectif": correspond_objectif,
        "expression_objectif": expression_objectif,
        "valeur_objectif": (
            str(valeur_objectif)
            if valeur_objectif is not None
            else None
        ),
        "message_interne": message
    }


# ================================================================
# VÉRIFICATION D'UNE ÉQUATION INTERMÉDIAIRE ÉQUIVALENTE
# ================================================================

def _extraire_equation_math_depuis_reponse(texte):
    """
    Extrait une équation mathématique contenant x depuis une réponse
    en langage naturel.

    Exemples :
        "je trouve 2x=11" -> "2*x=11"
        "cela donne -2x-2=4" -> "-2*x-2=4"
        "on ajoute 5 : 2x-5+5=6+5" -> "2*x-5+5=6+5"

    Le signe négatif placé devant le premier terme est conservé.
    """

    texte = _normaliser_texte_math(texte or "")

    candidats = re.findall(
        r"(?<![a-zà-ÿ])"
        r"[-+]?[0-9x\.\(\)\+\-\*/\s]+"
        r"="
        r"[-+]?[0-9x\.\(\)\+\-\*/\s]+"
        r"(?![a-zà-ÿ])",
        texte,
        flags=re.IGNORECASE
    )

    equations = []

    for candidat in candidats:
        equation = re.sub(r"\s+", "", candidat).strip()

        # IMPORTANT : ne pas utiliser strip("+-*/.")
        # car cela transformerait "-2*x-2=4" en "2*x-2=4".
        equation = equation.rstrip("+-*/.")

        if not equation or equation.count("=") != 1:
            continue

        gauche, droite = equation.split("=", 1)

        if not gauche or not droite:
            continue

        if "x" not in gauche and "x" not in droite:
            continue

        if not re.fullmatch(r"[0-9x+\-*/().=]+", equation):
            continue

        equations.append(equation)

    if not equations:
        return None

    return equations[-1]

def _analyser_equation_lineaire(equation):
    """
    Analyse une équation simple en x par évaluation exacte avec Fraction.

    On pose :
        f(x) = membre_gauche - membre_droit

    Pour une équation linéaire :
        f(x) = a*x + b

    On détermine a et b avec x=0 et x=1 puis on vérifie avec x=2
    que l'expression est réellement linéaire.

    Retour :
        {
            "analyse_reussie": True,
            "type_solution": "unique" | "toutes" | "aucune",
            "solution": Fraction(...) ou None,
            ...
        }

    Si l'équation n'est pas reconnue comme linéaire, on retourne
    analyse_reussie=False. Cela ne signifie jamais que l'équation
    de l'élève est incorrecte.
    """

    if not equation or equation.count("=") != 1:
        return {
            "analyse_reussie": False,
            "raison": "equation_absente_ou_ambigue"
        }

    try:
        gauche, droite = equation.split("=", 1)

        if not gauche or not droite:
            return {
                "analyse_reussie": False,
                "raison": "membre_equation_manquant"
            }

        def f(x_value):
            return (
                _eval_expr_fraction(
                    gauche,
                    x_value=x_value
                )
                -
                _eval_expr_fraction(
                    droite,
                    x_value=x_value
                )
            )

        f0 = f(Fraction(0, 1))
        f1 = f(Fraction(1, 1))
        f2 = f(Fraction(2, 1))

        b = f0
        a = f1 - f0

        # Vérification de linéarité.
        if f2 != b + 2 * a:
            return {
                "analyse_reussie": False,
                "raison": "equation_non_lineaire_ou_non_supportee"
            }

        if a == 0:
            if b == 0:
                return {
                    "analyse_reussie": True,
                    "type_solution": "toutes",
                    "solution": None,
                    "coefficient_a": str(a),
                    "coefficient_b": str(b)
                }

            return {
                "analyse_reussie": True,
                "type_solution": "aucune",
                "solution": None,
                "coefficient_a": str(a),
                "coefficient_b": str(b)
            }

        solution = -b / a

        return {
            "analyse_reussie": True,
            "type_solution": "unique",
            "solution": solution,
            "coefficient_a": str(a),
            "coefficient_b": str(b)
        }

    except Exception as e:
        return {
            "analyse_reussie": False,
            "raison": "erreur_analyse_equation",
            "erreur": str(e)
        }


def verifier_equation_intermediaire_equivalente(
    equation_initiale,
    reponse_eleve
):
    """
    Vérifie qu'une équation intermédiaire proposée par l'élève est
    équivalente à l'équation initiale.

    Exemples :
        initiale : 2x - 5 = 6
        élève     : 2x = 11
        -> correct

        initiale : 2x - 5 = 6
        élève     : 2x = 1
        -> incorrect

        initiale : 3x = 9
        élève     : x = 3
        -> correct

    Principe :
    - on extrait l'équation initiale ;
    - on extrait l'équation proposée par l'élève ;
    - on calcule exactement leur ensemble de solutions lorsqu'elles
      sont linéaires ;
    - mêmes ensembles de solutions = transformation équivalente.

    Sécurité :
    - si l'analyse locale n'est pas possible, retourne NON VÉRIFIÉ ;
    - NON VÉRIFIÉ ne signifie jamais incorrect.
    """

    equation_depart = _extraire_equation_depuis_texte(
        equation_initiale
    )

    equation_eleve = _extraire_equation_math_depuis_reponse(
        reponse_eleve
    )

    if not equation_depart or not equation_eleve:
        return {
            "verification_equation_intermediaire": False,
            "verification_contextuelle": False,
            "est_correct": None,
            "message_interne": ""
        }

    analyse_depart = _analyser_equation_lineaire(
        equation_depart
    )

    analyse_eleve = _analyser_equation_lineaire(
        equation_eleve
    )

    if (
        not analyse_depart.get("analyse_reussie")
        or not analyse_eleve.get("analyse_reussie")
    ):
        return {
            "verification_equation_intermediaire": False,
            "verification_contextuelle": False,
            "est_correct": None,
            "equation_initiale": equation_depart,
            "equation_eleve": equation_eleve,
            "analyse_initiale": analyse_depart,
            "analyse_eleve": analyse_eleve,
            "message_interne": ""
        }

    type_depart = analyse_depart.get("type_solution")
    type_eleve = analyse_eleve.get("type_solution")

    est_equivalente = False

    if type_depart == type_eleve:
        if type_depart == "unique":
            est_equivalente = (
                analyse_depart.get("solution")
                ==
                analyse_eleve.get("solution")
            )
        else:
            # "toutes" avec "toutes", ou "aucune" avec "aucune".
            est_equivalente = True

    solution_depart = analyse_depart.get("solution")
    solution_eleve = analyse_eleve.get("solution")

    if est_equivalente:
        message = (
            "Vérification déterministe prioritaire d'une transformation "
            "d'équation : "
            f"l'équation initiale est « {equation_depart} » et l'élève "
            f"propose « {equation_eleve} ». "
        )

        if type_depart == "unique":
            message += (
                f"Les deux équations ont exactement la même solution "
                f"x = {solution_depart}. "
            )
        elif type_depart == "toutes":
            message += (
                "Les deux équations sont vraies pour toutes les valeurs de x. "
            )
        else:
            message += (
                "Les deux équations n'ont aucune solution. "
            )

        message += (
            "L'étape de l'élève est donc mathématiquement correcte et "
            "équivalente à l'équation précédente. "
            "Naima doit reconnaître explicitement que cette étape est correcte, "
            "la considérer comme acquise et poursuivre à partir de cette "
            "nouvelle équation. "
            "Naima ne doit pas demander à l'élève de refaire une opération "
            "déjà correctement effectuée."
        )

    else:
        message = (
            "Vérification déterministe d'une transformation d'équation : "
            f"l'équation initiale est « {equation_depart} » tandis que "
            f"l'élève propose « {equation_eleve} ». "
        )

        if (
            type_depart == "unique"
            and type_eleve == "unique"
        ):
            message += (
                f"La première a pour solution x = {solution_depart}, "
                f"alors que la seconde a pour solution x = {solution_eleve}. "
            )

        message += (
            "Les deux équations ne sont donc pas équivalentes. "
            "Naima doit signaler doucement l'erreur dans cette transformation "
            "et guider l'élève sans inventer une autre erreur."
        )

    return {
        "verification_equation_intermediaire": True,
        "verification_contextuelle": True,
        "est_correct": est_equivalente,
        "equation_initiale": equation_depart,
        "equation_eleve": equation_eleve,
        "type_solution_initiale": type_depart,
        "type_solution_eleve": type_eleve,
        "solution_initiale": (
            str(solution_depart)
            if solution_depart is not None
            else None
        ),
        "solution_eleve": (
            str(solution_eleve)
            if solution_eleve is not None
            else None
        ),
        "message_interne": message
    }

