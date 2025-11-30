import nltk
import re
from nltk.chat.util import Chat, reflections

# Ne télécharge punkt que si nécessaire
try:
    nltk.data.find("tokenizers/punkt")
except LookupError:
    nltk.download("punkt")

pairs = [
    [
        r"(?i)^(hi|hello|bonjour|salut)$",
        ["Bonjour, je suis ton enseignant virtuel. Pose-moi une question sur un concept mathématique."]
    ],
    [
        r"(?i).*méthode.*(résoudre|résolution|faire).*",
        ["Je peux t'expliquer une méthode générale. Pour quel concept ou type d'exercice as-tu besoin d’aide ?"]
    ],
    [
        r"(?i).*équation.*linéaire.*",
        ["Pour une équation linéaire ax + b = c, on isole x en deux étapes : soustraire b, puis diviser par a."]
    ],
    [
        r"(?i).*équation.*quadratique.*",
        ["Pour une équation quadratique ax² + bx + c = 0, on utilise la formule du discriminant : Δ = b² - 4ac."]
    ],
    [
        r"(?i)^merci|thanks$",
        ["Avec plaisir ! 😊 N’hésite pas si tu veux un autre exemple."]
    ],
    [
        r"(?i)^quit|exit$",
        ["À bientôt !"]
    ],
    # Fallback générique
    [
        r"(?i).*",
        ["Peux-tu reformuler ta question ? Je suis là pour t’aider avec des notions mathématiques."]
    ],
]

def chatbot():
    return Chat(pairs, reflections)

def get_chatbot_response(user_input):
    return chatbot().respond(user_input)
