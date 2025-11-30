import nltk
from nltk.chat.util import Chat, reflections

# Télécharger les données nécessaires une seule fois (au besoin)
nltk.download('punkt', quiet=True)

# Paires d'exemples simples avec des explications pédagogiques sans résoudre l'exercice de l'élève
pairs = [
    [
        r"bonjour|salut|hello|hi",
        ["Bonjour, je suis ton enseignant virtuel 🤖. Pose-moi une question sur un concept mathématique."]
    ],
    [
        r"(comment|quelle est la méthode pour|peux-tu m'expliquer) .* (équation|résolution|résoudre)",
        ["Bien sûr ! Pour résoudre une équation, on isole l'inconnue. Par exemple, pour ax + b = c, on commence par soustraire b, puis on divise par a."]
    ],
    [
        r"(équation|équations) (linéaire|du premier degré)",
        ["Une équation linéaire a la forme ax + b = c. On résout en isolant x. Exemple : 3x + 2 = 8 → x = 2."]
    ],
    [
        r"(équation|équations) quadratique|second degré",
        ["Une équation quadratique est de la forme ax² + bx + c = 0. On la résout avec le discriminant : Δ = b² - 4ac."]
    ],
    [
        r"(merci|thanks|thx|merci beaucoup)",
        ["Avec plaisir ! 😊 N’hésite pas à poser d’autres questions."]
    ],
    [
        r"(au revoir|quit|exit)",
        ["À bientôt et bon courage dans tes révisions ! 💪"]
    ]
]

def chatbot():
    return Chat(pairs, reflections)

def get_chatbot_response(user_input):
    bot = chatbot()
    response = bot.respond(user_input)
    if response:
        return response
    else:
        return "Je ne suis pas sûr de comprendre. Peux-tu reformuler ou préciser le concept mathématique ?"
