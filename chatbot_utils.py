# chatbot_utils.py - Version multi-matières pour Naima
import nltk
import re
from nltk.chat.util import Chat, reflections

# Téléchargement une seule fois
nltk.download('punkt', quiet=True)

# ============================================================
# DÉTECTION DE LA MATIÈRE
# ============================================================

def detecter_matiere_simple(texte: str) -> str:
    """Détecte la matière d'une question pour adapter la réponse"""
    texte = texte.lower()
    
    patterns = {
        "maths": [
            "équation", "calcul", "fraction", "x=", "y=", "nombre", "addition", "soustraction",
            "multiplication", "division", "géométrie", "triangle", "angle", "pourcentage",
            "fonction", "dérivée", "intégrale", "algèbre", "puissance", "racine"
        ],
        "francais": [
            "grammaire", "conjugaison", "verbe", "phrase", "texte", "poème", "adjectif",
            "nom", "sujet", "complément", "ponctuation", "orthographe", "vocabulaire",
            "figure de style", "métaphore", "comparaison", "accord"
        ],
        "histoire": [
            "date", "guerre", "roi", "révolution", "siècle", "bataille", "empire",
            "civilisation", "préhistoire", "antiquité", "moyen Âge", "renaissance",
            "napoléon", "louis", "charlemagne", "clovis"
        ],
        "sciences": [
            "atome", "cellule", "force", "énergie", "vitesse", "masse", "volume",
            "réaction", "chimique", "physique", "biologie", "gravité", "électricité",
            "magnétisme", "photosynthèse", "respiration"
        ],
        "anglais": [
            "translate", "traduis", "vocabulary", "grammar", "verb", "tense",
            "sentence", "phrase", "word", "mot", "anglais", "english"
        ]
    }
    
    scores = {matiere: sum(1 for kw in mots if kw in texte) 
              for matiere, mots in patterns.items()}
    
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "maths"


# ============================================================
# RÉPONSES PAR MATIÈRE (format NLTK)
# ============================================================

def get_response_by_subject(subject: str, user_input: str) -> str:
    """Retourne une réponse adaptée à la matière détectée"""
    
    # Réponses pour les MATHS
    if subject == "maths":
        responses = {
            "equation": [
                "Pour résoudre une équation, on isole l'inconnue. Par exemple, pour ax + b = c :",
                "→ 1. Soustrais b des deux côtés : ax = c - b",
                "→ 2. Divise par a : x = (c - b)/a",
                "Quelle équation veux-tu résoudre ?"
            ],
            "fraction": [
                "Pour additionner des fractions, il faut un dénominateur commun.",
                "Exemple : 1/2 + 1/3 → dénominateur commun 6 → 3/6 + 2/6 = 5/6",
                "As-tu besoin d'aide avec une fraction particulière ?"
            ],
            "geometrie": [
                "En géométrie, pense toujours à :",
                "• Triangle : somme des angles = 180°",
                "• Cercle : périmètre = 2πr, aire = πr²",
                "• Théorème de Pythagore : a² + b² = c²",
                "Quelle figure géométrique te pose problème ?"
            ],
            "default": [
                "En mathématiques, il faut toujours commencer par bien lire l'énoncé.",
                "Peux-tu me dire ce que tu as déjà essayé ?"
            ]
        }
    
    # Réponses pour le FRANÇAIS
    elif subject == "francais":
        responses = {
            "conjugaison": [
                "Pour conjuguer un verbe :",
                "1. Identifie son groupe (-er, -ir, -re)",
                "2. Trouve le radical (infinitif sans terminaison)",
                "3. Ajoute la terminaison du temps demandé",
                "Quel verbe veux-tu conjuguer ?"
            ],
            "grammaire": [
                "Pour analyser une phrase :",
                "• Identifie le sujet (qui fait l'action ?)",
                "• Trouve le verbe (l'action ou l'état)",
                "• Cherche les compléments (COD, COI, etc.)",
                "Peux-tu me donner la phrase à analyser ?"
            ],
            "orthographe": [
                "Pour vérifier l'orthographe :",
                "• Relis-toi lentement",
                "• Cherche les accords (sujet-verbe, nom-adjectif)",
                "• Pense aux homophones (a/à, et/est, son/sont)",
                "Quel mot te pose problème ?"
            ],
            "default": [
                "En français, la pratique est essentielle.",
                "Peux-tu me donner la phrase ou le texte à étudier ?"
            ]
        }
    
    # Réponses pour l'HISTOIRE
    elif subject == "histoire":
        responses = {
            "date": [
                "Pour retenir une date, associe-la à un événement marquant.",
                "Exemple : 1789 → Révolution française",
                "Quelle période historique étudies-tu ?"
            ],
            "personnage": [
                "Pour comprendre un personnage historique :",
                "• Quand a-t-il vécu ?",
                "• Quel a été son rôle ?",
                "• Quelle est sa contribution majeure ?",
                "De qui veux-tu parler ?"
            ],
            "default": [
                "En histoire, il faut comprendre les causes et conséquences.",
                "Peux-tu me donner le contexte de ta question ?"
            ]
        }
    
    # Réponses pour les SCIENCES
    elif subject == "sciences":
        responses = {
            "physique": [
                "En physique, une formule n'est qu'un outil.",
                "Commence par identifier les données connues et l'inconnue.",
                "Quel phénomène physique veux-tu comprendre ?"
            ],
            "chimie": [
                "Pour équilibrer une équation chimique :",
                "• Compte les atomes de chaque côté",
                "• Ajuste les coefficients (jamais les indices)",
                "• Vérifie que tout est équilibré",
                "Quelle réaction chimique te pose problème ?"
            ],
            "biologie": [
                "En biologie, tout est une question de fonctionnement.",
                "• Quelle est la structure ?",
                "• Quelle est sa fonction ?",
                "• Comment s'intègre-t-elle dans le système ?",
                "Quel organe ou processus veux-tu comprendre ?"
            ],
            "default": [
                "En sciences, l'observation est la clé.",
                "Que vois-tu dans l'énoncé ? Qu'est-ce qu'on te demande ?"
            ]
        }
    
    # Réponses pour l'ANGLAIS
    elif subject == "anglais":
        responses = {
            "translate": [
                "Pour traduire, cherche d'abord le sens global de la phrase.",
                "• Identifie le sujet et le verbe principal",
                "• Traduis mot à mot, puis ajuste le sens",
                "Quelle phrase veux-tu traduire ?"
            ],
            "default": [
                "In English, practice makes perfect!",
                "What do you need help with? Grammar, vocabulary, or translation?"
            ]
        }
    
    else:
        responses = {"default": ["Je suis là pour t'aider dans toutes les matières. Pose ta question !"]}
    
    # Trouver le mot-clé le plus pertinent
    for keyword, response_list in responses.items():
        if keyword in user_input.lower() and keyword != "default":
            return "\n".join(response_list)
    
    return "\n".join(responses.get("default", ["Peux-tu reformuler ta question ?"]))


# ============================================================
# PAIRES NLTK MULTI-MATIÈRES
# ============================================================

pairs = [
    # Salutations - universelles
    [
        r"bonjour|salut|hello|hi|coucou",
        ["Bonjour ! Je suis Naima, ton assistant pédagogique. Je peux t'aider en maths, français, histoire, sciences, anglais... Quelle est ta question ?"]
    ],
    
    # Demande d'aide générale
    [
        r"aide(-)?moi|peux(-)?tu m'aider|j'ai besoin d'aide",
        ["Bien sûr ! Dis-moi dans quelle matière tu as besoin d'aide : maths, français, histoire, sciences, anglais ?"]
    ],
    
    # MATHÉMATIQUES
    [
        r"(équation|résoudre|calculer|x=|\+|\-|\*|/|=)",
        [lambda match: get_response_by_subject("maths", match.string)]
    ],
    [
        r"(fraction|dénominateur|numérateur|1/2|2/3)",
        [lambda match: get_response_by_subject("maths", match.string)]
    ],
    [
        r"(géométrie|triangle|cercle|périmètre|aire|pythagore|théorème)",
        [lambda match: get_response_by_subject("maths", match.string)]
    ],
    
    # FRANÇAIS
    [
        r"(conjugaison|verbe|terminaison|passé|présent|futur|imparfait)",
        [lambda match: get_response_by_subject("francais", match.string)]
    ],
    [
        r"(grammaire|phrase|sujet|complément|COD|COI|adjectif|nom)",
        [lambda match: get_response_by_subject("francais", match.string)]
    ],
    [
        r"(orthographe|faute|accorder|homophone|a à|et est|son sont)",
        [lambda match: get_response_by_subject("francais", match.string)]
    ],
    [
        r"(poème|figure de style|métaphore|comparaison|texte|dissertation|commentaire)",
        [lambda match: get_response_by_subject("francais", match.string)]
    ],
    
    # HISTOIRE
    [
        r"(date|siècle|année|avant J.-C.|ap. J.-C.)",
        [lambda match: get_response_by_subject("histoire", match.string)]
    ],
    [
        r"(guerre|bataille|révolution|empire|roi|reine|président|personnage historique)",
        [lambda match: get_response_by_subject("histoire", match.string)]
    ],
    [
        r"(civilisation|grec|romain|égyptien|moyen âge|renaissance|préhistoire|antiquité)",
        [lambda match: get_response_by_subject("histoire", match.string)]
    ],
    
    # SCIENCES
    [
        r"(physique|force|vitesse|énergie|gravité|mouvement|électricité|magnétisme)",
        [lambda match: get_response_by_subject("sciences", match.string)]
    ],
    [
        r"(chimie|réaction|molécule|atome|acide|base|équation chimique|tableau périodique)",
        [lambda match: get_response_by_subject("sciences", match.string)]
    ],
    [
        r"(biologie|cellule|organe|photosynthèse|respiration|système nerveux|cœur|ADN)",
        [lambda match: get_response_by_subject("sciences", match.string)]
    ],
    
    # ANGLAIS
    [
        r"(translate|traduis|traduction|comment dit-on)",
        [lambda match: get_response_by_subject("anglais", match.string)]
    ],
    [
        r"(english|anglais|vocabulary|grammar|verb|tense)",
        [lambda match: get_response_by_subject("anglais", match.string)]
    ],
    
    # Remerciements
    [
        r"merci|thanks|thank you|thx|merci beaucoup",
        ["Avec plaisir ! N'hésite pas si tu as d'autres questions. — Naima ✨"]
    ],
    
    # Au revoir
    [
        r"au revoir|quit|exit|bye|à plus tard",
        ["À bientôt ! Bon courage dans tes études. — Naima ✨"]
    ]
]


def chatbot():
    return Chat(pairs, reflections)


# chatbot_utils.py - Version améliorée

def get_chatbot_response(user_input: str) -> str:
    """
    Point d'entrée principal pour le fallback.
    Version améliorée qui comprend mieux les réponses mathématiques.
    """
    if not user_input or not user_input.strip():
        return "Bonjour ! Je suis Naima. Quelle est ta question ?"
    
    user_input_lower = user_input.lower().strip()
    
    # ✅ Détecter les réponses mathématiques
    math_patterns = {
        r'\d+\s*[+\-*/]\s*\d+': "Je vois que tu fais un calcul. Peux-tu m'expliquer ton raisonnement ?",
        r'\d+[xX]': "Tu utilises une variable x. C'est bien ! Continue.",
        r'[xX]\s*=\s*\d+': "Tu as trouvé une valeur pour x. Est-ce que tu peux vérifier si elle satisfait l'équation ?",
        r'\d+\s*\+\s*\d+': "Tu fais une addition. Pourquoi choisis-tu ces nombres ?",
    }
    
    for pattern, response in math_patterns.items():
        if re.search(pattern, user_input):
            return f"{response}\n\n— Naima ✨"
    
    # Détection de matière
    subject = detecter_matiere_simple(user_input)
    
    # Réponses personnalisées par matière
    if subject == "maths":
        return f"""Je vois que tu travailles sur un problème de maths.

**Peux-tu me dire quelle est la première étape selon toi ?**

N'oublie pas que je suis là pour te guider, pas pour te donner la réponse directement.

— Naima ✨"""
    
    elif subject == "francais":
        return f"""C'est une bonne question sur le français.

**Quelle règle de grammaire ou de conjugaison penses-tu appliquer ici ?**

— Naima ✨"""
    
    else:
        return f"""Merci pour ta réponse !

**Peux-tu m'expliquer comment tu es arrivé(e) à cette conclusion ?**

Je t'aiderai à avancer étape par étape.

— Naima ✨"""