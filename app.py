import os
import time
import logging
import uuid
import re
import warnings
from sqlalchemy.exc import SAWarning
warnings.filterwarnings('ignore', category=SAWarning)

import datetime
import stripe
import traceback
from flask import (
    Flask, request, jsonify, render_template, make_response,
    redirect, session, url_for, g, flash, get_flashed_messages
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
from sqlalchemy.orm import joinedload
from urllib.parse import urlencode
from openai import OpenAI
from dotenv import load_dotenv
import pdfkit
import random
import json
from chatbot_utils import get_chatbot_response
from flask_migrate import Migrate
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from datetime import datetime  # Pour le timestamp

# 🧠 Modèles et config
from models import (
    db, User, Exercice, StudentResponse, Parent, ParentEleve,
    RemediationSuggestion, Enseignant, Niveau, Matiere, Unite,
    Lecon, TestSommatif, TestResponse
)
from config import OPENAI_API_KEY

# 🚀 Initialisation de l'app Flask
app = Flask(__name__)
load_dotenv()

# --- Clé secrète ---
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-key-change-me')

# ====================================================================
# 🔧 CONFIGURATION INTELLIGENTE DE LA BASE DE DONNÉES
# ====================================================================

def get_database_url():
    """
    Détermine l'URL de la base de données selon l'environnement.
    Priorité : 
    1. PostgreSQL sur Render (RENDER_POSTGRES_URL)
    2. PostgreSQL standard (DATABASE_URL) 
    3. PostgreSQL externe (POSTGRES_URL)
    4. SQLite local (développement)
    """
    # 1. PostgreSQL intégré Render (service web + base)
    render_postgres_url = os.getenv('RENDER_POSTGRES_URL')
    if render_postgres_url:
        print("🎯 Configuration: PostgreSQL Render (RENDER_POSTGRES_URL)")
        db_url = render_postgres_url
    
    # 2. Base de données Render dédiée
    elif os.getenv('DATABASE_URL'):
        print("🎯 Configuration: Base de données Render dédiée (DATABASE_URL)")
        db_url = os.getenv('DATABASE_URL')
    
    # 3. PostgreSQL externe
    elif os.getenv('POSTGRES_URL'):
        print("🎯 Configuration: PostgreSQL externe (POSTGRES_URL)")
        db_url = os.getenv('POSTGRES_URL')
    
    # 4. Développement local - SQLite
    else:
        print("💻 Configuration: SQLite local (développement)")
        db_url = 'sqlite:///tutorat_ai.db'
    
    # Correction pour SQLAlchemy 2.0+ (postgres:// → postgresql://)
    if isinstance(db_url, str) and db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
        print("🔧 Correction: postgres:// → postgresql://")
    
    return db_url

# Application de la configuration
DB_URL = get_database_url()
app.config['SQLALCHEMY_DATABASE_URI'] = DB_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Options avancées pour PostgreSQL
if 'postgresql' in DB_URL:
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        "pool_pre_ping": True,          # Vérifie la connexion avant utilisation
        "pool_recycle": 280,            # Recycle les connexions après 280s
        "pool_size": 5,                 # Nombre de connexions permanentes
        "max_overflow": 10,             # Connexions supplémentaires temporaires
        "connect_args": {
            "connect_timeout": 10,      # Timeout de connexion de 10s
            "keepalives": 1,            # Keepalive TCP
            "keepalives_idle": 30,      # Attente avant keepalive
            "keepalives_interval": 10,  # Intervalle entre keepalives
        }
    }
    print(f"⚙️ Options PostgreSQL activées")
else:
    # SQLite - options minimales
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        "pool_pre_ping": False,
        "pool_recycle": -1,
    }
    print(f"⚙️ Options SQLite (développement)")

# Log de l'URL (masquée pour sécurité)
if DB_URL and len(DB_URL) > 20:
    masked_url = DB_URL[:20] + "..." + DB_URL[-20:] if len(DB_URL) > 40 else DB_URL[:40] + "..."
    print(f"🔗 URL Base de données: {masked_url}")

# ====================================================================
# FIN CONFIGURATION BASE DE DONNÉES
# ====================================================================

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 🔌 Initialisation des extensions
db.init_app(app)
migrate = Migrate(app, db)

# ✅ CONFIGURATION STRIPE CORRECTE - CLÉ VALIDE
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")

# Debug Stripe
print(f"🎯 Stripe configuré: {bool(stripe.api_key)}")
print(f"🔑 Clé utilisée: {stripe.api_key[:20]}..." if stripe.api_key else "❌ Pas de clé Stripe")

# 📁 Configuration des uploads
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads", "tests")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 Mo par requête

# 🔌 Initialisation OpenAI
client = OpenAI(api_key=OPENAI_API_KEY)

# --- Optimisations pour PostgreSQL ---
@app.before_request
def _enable_foreign_keys():
    """Active les clés étrangères pour SQLite (ignoré par PostgreSQL)"""
    if hasattr(db, 'engine') and 'sqlite' in str(db.engine.url):
        db.session.execute(text('PRAGMA foreign_keys=ON'))

@app.before_request
def log_start_time():
    request.start_time = time.time()

@app.after_request
def log_end_time(response):
    if hasattr(request, 'start_time'):
        duration = time.time() - request.start_time
        if duration > 0.5:  # Seuil d'alerte à 500ms
            logger.warning(f"Requête longue: {request.path} a pris {duration:.2f}s")
    return response

def execute_with_retry(func, max_retries=3):
    """Exécute une fonction avec des retries en cas d'erreur de concurrence SQLite."""
    for attempt in range(max_retries):
        try:
            return func()
        except OperationalError as e:
            if "locked" in str(e) and attempt < max_retries - 1:
                time.sleep(0.1 * (attempt + 1))
                continue
            raise

# --- Vos fonctions existantes ---
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("login_admin"))
        return f(*args, **kwargs)
    return decorated_function

@app.template_filter('replace_latex')
def replace_latex_filter(text):
    """
    Remplace les expressions LaTeX simples par un format plus convivial
    """
    if not text:
        return text
    
    import re
    
    # Nettoyage initial
    text = str(text)
    
    # Échappement HTML pour sécurité
    from markupsafe import Markup
    
    # Fractions: \frac{a}{b} → a/b
    text = re.sub(r'\\frac{([^}]+)}{([^}]+)}', r'\1/\2', text)
    
    # Racines carrées: \sqrt{x} → √x, \sqrt[n]{x} → ⁿ√x
    text = re.sub(r'\\sqrt\[([^]]+)\]{(.+?)}', r'\1√\2', text)
    text = re.sub(r'\\sqrt{(.+?)}', r'√\1', text)
    
    # Exposants: x^{2} → x², x^{n} → xⁿ
    text = re.sub(r'(\w+)\^{2}', r'\1²', text)
    text = re.sub(r'(\w+)\^{3}', r'\1³', text)
    text = re.sub(r'(\w+)\^{(\w+)}', r'\1^\2', text)
    
    # Indices: x_{2} → x₂, x_{n} → xₙ
    text = re.sub(r'(\w+)_{2}', r'\1₂', text)
    text = re.sub(r'(\w+)_{3}', r'\1₃', text)
    text = re.sub(r'(\w+)_{(\w+)}', r'\1_\2', text)
    
    # Symboles grecs étendus
    greek_symbols = {
        '\\alpha': 'α', '\\beta': 'β', '\\gamma': 'γ', '\\delta': 'δ',
        '\\epsilon': 'ε', '\\zeta': 'ζ', '\\eta': 'η', '\\theta': 'θ',
        '\\iota': 'ι', '\\kappa': 'κ', '\\lambda': 'λ', '\\mu': 'μ',
        '\\nu': 'ν', '\\xi': 'ξ', '\\pi': 'π', '\\rho': 'ρ',
        '\\sigma': 'σ', '\\tau': 'τ', '\\upsilon': 'υ', '\\phi': 'φ',
        '\\chi': 'χ', '\\psi': 'ψ', '\\omega': 'ω',
        '\\Gamma': 'Γ', '\\Delta': 'Δ', '\\Theta': 'Θ', '\\Lambda': 'Λ',
        '\\Xi': 'Ξ', '\\Pi': 'Π', '\\Sigma': 'Σ', '\\Phi': 'Φ',
        '\\Psi': 'Ψ', '\\Omega': 'Ω'
    }
    
    for latex, symbol in greek_symbols.items():
        text = text.replace(latex, symbol)
    
    # Opérateurs mathématiques
    operators = {
        '\\times': '×', '\\cdot': '·', '\\div': '÷', '\\pm': '±',
        '\\mp': '∓', '\\leq': '≤', '\\geq': '≥', '\\neq': '≠',
        '\\approx': '≈', '\\equiv': '≡', '\\propto': '∝', '\\infty': '∞',
        '\\partial': '∂', '\\nabla': '∇', '\\forall': '∀', '\\exists': '∃',
        '\\in': '∈', '\\notin': '∉', '\\subset': '⊂', '\\subseteq': '⊆',
        '\\cup': '∪', '\\cap': '∩', '\\wedge': '∧', '\\vee': '∨',
        '\\neg': '¬', '\\Rightarrow': '⇒', '\\Leftrightarrow': '⇔',
        '\\rightarrow': '→', '\\leftarrow': '←'
    }
    
    for latex, symbol in operators.items():
        text = text.replace(latex, symbol)
    
    # Ensembles
    text = text.replace('\\mathbb{R}', 'ℝ')
    text = text.replace('\\mathbb{N}', 'ℕ')
    text = text.replace('\\mathbb{Z}', 'ℤ')
    text = text.replace('\\mathbb{Q}', 'ℚ')
    text = text.replace('\\mathbb{C}', 'ℂ')
    
    # Accents et symboles divers
    text = text.replace('\\hat', '̂')
    text = text.replace('\\bar', '̄')
    text = text.replace('\\vec', '⃗')
    text = text.replace('\\dot', '̇')
    
    # Équations en display (supprimer les $$)
    text = re.sub(r'\$\$(.*?)\$\$', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'\$(.*?)\$', r'\1', text)
    
    # Nettoyage des doubles backslashes et espaces
    text = text.replace('\\\\', ' ')
    text = re.sub(r'\s+', ' ', text)  # Normaliser les espaces
    
    return Markup(text.strip())


# ... ensuite vos routes commencent ici ...
@app.route("/eleve/remediations")
def eleve_remediations():
    username = request.args.get("username")
    lang = request.args.get("lang", "fr")

    eleve = User.query.filter_by(username=username).first()
    if not eleve:
        return "Élève introuvable", 404

    remediations = RemediationSuggestion.query.filter_by(
        user_id=eleve.id,
        statut="valide"
    ).order_by(RemediationSuggestion.timestamp.desc()).all()

    # Toutes les remédiations sont marquées comme vues ici :
    for r in remediations:
        if not r.vue_par_eleve:
            r.vue_par_eleve = True
    db.session.commit()

    return render_template(
        "remediations_eleve.html",
        eleve=eleve,
        remediations=remediations,
        lang=lang
    )

def generer_reponse_guide_math(question, niveau_eleve, langue="fr", mode_examen=False, historique=None):
    """
    Génère une réponse pédagogique POUR UNE QUESTION DE MATHÉMATIQUES
    """
    try:
        from openai import OpenAI
        import os
        
        client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        
        # Construire le système prompt
        if langue == "fr":
            system_content = f"""Tu es un enseignant de mathématiques pour un élève de {niveau_eleve}.

RÈGLES STRICTES :
1. Tu dois GUIDER l'élève, PAS donner la réponse directement
2. Pose des QUESTIONS pour vérifier sa compréhension
3. Divise le problème en ÉTAPES simples
4. Donne UNE ÉTAPE à la fois, attends la réponse de l'élève
5. Utilise des exemples CONCRETS adaptés au niveau
6. Sois ENCOURAGEANT et PATIENT
7. Utilise LaTeX pour les formules : \\(formule\\) pour inline, \\[formule\\] pour display

{"⚠️ MODE EXAMEN : Tu ne dois donner que des INDICATIONS, pas la solution. Pose des questions pour guider." if mode_examen else ""}

FORMAT DE RÉPONSE :
- Commence par saluer et reformuler le problème
- Identifie les concepts mathématiques en jeu
- Propose la PREMIÈRE ÉTAPE seulement
- Pose une question pour vérifier la compréhension
- Termine par une invitation à continuer"""
        else:
            system_content = f"""You are a mathematics teacher for a {niveau_eleve} student.

STRICT RULES:
1. You must GUIDE the student, NOT give the answer directly
2. Ask QUESTIONS to check understanding
3. Break the problem into SIMPLE STEPS
4. Give ONE STEP at a time, wait for student response
5. Use CONCRETE examples adapted to the level
6. Be ENCOURAGING and PATIENT
7. Use LaTeX for formulas: \\(formula\\) for inline, \\[formula\\] for display

{"⚠️ EXAM MODE: You must only give HINTS, not the solution. Ask guiding questions." if mode_examen else ""}

RESPONSE FORMAT:
- Start by greeting and rephrasing the problem
- Identify mathematical concepts involved
- Propose ONLY the FIRST STEP
- Ask a question to check understanding
- End with an invitation to continue"""
        
        # Construire le message utilisateur avec historique
        user_content = f"Question de l'élève : {question}"
        if historique:
            user_content += f"\n\nHistorique récent :\n" + "\n".join([f"- {msg[:100]}..." for msg in historique[-3:]])
        
        # Appel à OpenAI
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",  # Plus rapide et moins cher que GPT-4
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content}
            ],
            temperature=0.7,
            max_tokens=800  # Limiter la longueur
        )
        
        reponse = response.choices[0].message.content.strip()
        
        # Formater la réponse
        return f"""
<div class="reponse-ia">
{reponse}
</div>
"""
        
    except Exception as e:
        print(f"Erreur OpenAI: {e}")
        
        # Fallback simple
        if langue == "fr":
            return f"""
<div class="reponse-ia">
<h4>👨‍🏫 Enseignant de Mathématiques</h4>
<p>Je vais t'aider à résoudre ce problème <strong>étape par étape</strong>.</p>

<p><strong>Première étape :</strong> Reformule le problème dans tes propres mots.</p>
<p><em>Qu'est-ce que tu comprends de l'énoncé ? Peux-tu me le redire avec tes mots ?</em></p>

<p>Une fois que tu auras fait ça, je te guiderai pour l'étape suivante !</p>
</div>
"""
        else:
            return f"""
<div class="reponse-ia">
<h4>👨‍🏫 Mathematics Teacher</h4>
<p>I'll help you solve this problem <strong>step by step</strong>.</p>

<p><strong>First step:</strong> Rephrase the problem in your own words.</p>
<p><em>What do you understand from the statement? Can you tell me in your own words?</em></p>

<p>Once you've done that, I'll guide you to the next step!</p>
</div>
"""
            
# chatbot_routes.py
# ============ FONCTIONS UTILITAIRES MATIÈRES ============
def obtenir_matiere_exercice(exercice):
    """Obtenir la matière d'un exercice"""
    if not exercice:
        return None
    
    try:
        # Parcourir la hiérarchie pédagogique
        if exercice.lecon and exercice.lecon.unite and exercice.lecon.unite.matiere:
            return exercice.lecon.unite.matiere
    except AttributeError as e:
        print(f"Erreur d'attribut: {e}")
        return None
    
    return None


def obtenir_matiere_test_exercice(test_exercice):
    """Obtenir la matière d'un exercice de test"""
    if not test_exercice:
        return None
    
    try:
        if test_exercice.test and test_exercice.test.unite and test_exercice.test.unite.matiere:
            return test_exercice.test.unite.matiere
    except AttributeError as e:
        print(f"Erreur d'attribut: {e}")
        return None
    
    return None


def obtenir_nom_matiere_objet(matiere_obj, lang="fr"):
    """Obtenir le nom de la matière dans la bonne langue depuis un objet Matiere"""
    if not matiere_obj:
        return "mathématiques" if lang == "fr" else "mathematics"
    
    if lang == "fr":
        return matiere_obj.nom.lower()
    else:
        # Retourner le nom anglais s'il existe, sinon le nom français
        nom = matiere_obj.nom_en.lower() if matiere_obj.nom_en else matiere_obj.nom.lower()
        
        # Mapping pour les noms courants
        mapping = {
            "mathématiques": "mathematics",
            "français": "french",
            "histoire": "history", 
            "sciences": "science",
            "géographie": "geography",
            "anglais": "english",
            "espagnol": "spanish",
            "physique": "physics",
            "chimie": "chemistry",
            "biologie": "biology"
        }
        return mapping.get(nom, nom)


# ============ ROUTE ADAPTÉE ============
@app.route("/enseignant-virtuel", methods=['GET', 'POST'])
def enseignant_virtuel():
    """Route pour l'enseignant virtuel - Accès libre - BILINGUE"""
    from datetime import datetime
    
    if "eleve_id" not in session:
        return redirect(url_for("login_eleve"))

    eleve = User.query.options(joinedload(User.niveau)).get(session["eleve_id"])
    if not eleve or eleve.role != "élève":
        return redirect(url_for("login_eleve"))
    
    # Vérifier l'accès (essai gratuit uniquement)
    lang = session.get("lang", "fr")
    if eleve.essai_est_expire() and eleve.statut_paiement != "paye":
        session.clear()
        flash(get_message("essai_termine", lang), "error")
        return redirect(url_for('login_eleve'))

    # Initialiser la conversation si elle n'existe pas
    if "conversation" not in session:
        session["conversation"] = []
    
    # Récupérer la matière sélectionnée ou par défaut
    matiere = "mathématiques" if lang == "fr" else "mathematics"
    
    # TRAITEMENT POST
    if request.method == 'POST':
        question = request.form.get("question", "").strip()
        matiere_form = request.form.get("matiere", "")
        
        if matiere_form:
            matiere = matiere_form
        
        if question and len(question) >= 3:
            conversation = session.get("conversation", [])
            derniere_q_ia = session.get('derniere_q_ia')
            
            # Si c'est une nouvelle conversation, ajouter un message de bienvenue
            if not conversation:
                bienvenue_msg = get_message("bienvenue_enseignant", lang)
                enseignant_label = "🤖 Teacher:" if lang == "en" else "🤖 Enseignant:"
                conversation.append(f"{enseignant_label} {bienvenue_msg}")
            
            # Format simple pour l'historique
            eleve_label = "👤 Student:" if lang == "en" else "👤 Élève:"
            conversation.append(f"{eleve_label} {question}")
            
            try:
                if derniere_q_ia:
                    # Réponse à une question précédente
                    reponse = generer_suite_conversation(
                        derniere_q=derniere_q_ia,
                        reponse=question,
                        historique=conversation,
                        niveau=eleve.niveau.nom if eleve.niveau else ("6th grade" if lang == "en" else "6ème"),
                        langue=lang,
                        mode_examen=session.get("mode_examen", False),
                        exercice_context="",
                        matiere=matiere
                    )
                    session.pop('derniere_q_ia', None)
                else:
                    # Nouvelle question
                    reponse = generer_debut_conversation(
                        question=question,
                        niveau=eleve.niveau.nom if eleve.niveau else ("6th grade" if lang == "en" else "6ème"),
                        langue=lang,
                        mode_examen=session.get("mode_examen", False),
                        matiere=matiere
                    )
                
                # Ajouter la réponse de l'IA
                enseignant_label = "🤖 Teacher:" if lang == "en" else "🤖 Enseignant:"
                conversation.append(f"{enseignant_label} {reponse}")
                
                # Limiter à 15 messages
                if len(conversation) > 15:
                    conversation = conversation[-15:]
                
                session["conversation"] = conversation
                
                # Extraire la nouvelle question
                nouvelle_q = extraire_question(reponse, lang)
                if nouvelle_q:
                    session['derniere_q_ia'] = nouvelle_q
                
                flash(get_message("je_te_guide", lang), "success")
                
            except Exception as e:
                print(f"Erreur lors de la génération de réponse: {e}")
                # Message d'erreur bilingue
                if lang == "fr":
                    fallback_msg = "Je suis désolé, j'ai rencontré une erreur. Pourrais-tu reformuler ta question ?"
                else:
                    fallback_msg = "I'm sorry, I encountered an error. Could you rephrase your question?"
                
                enseignant_label = "🤖 Teacher:" if lang == "en" else "🤖 Enseignant:"
                conversation.append(f"{enseignant_label} {fallback_msg}")
                session["conversation"] = conversation
                flash(get_message("erreur_traitement", lang), "warning")
    
    # Récupérer la conversation
    conversation = session.get("conversation", [])
    
    return render_template(
        "enseignant_virtuel.html",
        lang=lang,
        eleve=eleve,
        conversation=conversation,
        exercice_remediation=None,
        access_count=0,
        date_du_jour=datetime.utcnow(),
        matiere=matiere
    )


def get_message(key, lang="fr"):
    """Système de messages bilingues"""
    messages = {
        "fr": {
            "essai_termine": "Essai gratuit terminé. Abonne-toi pour continuer.",
            "je_te_guide": "Je te guide étape par étape !",
            "erreur_traitement": "Erreur lors du traitement de la question",
            "bienvenue_enseignant": "👋 Bonjour ! Je suis ton enseignant virtuel. Pose-moi n'importe quelle question sur n'importe quelle matière !",
            "nouveau_dialogue": "Nouvelle conversation commencée. Pose ta question !",
            "acces_enseignant": "Accès à l'enseignant virtuel activé !"
        },
        "en": {
            "essai_termine": "Free trial ended. Subscribe to continue.",
            "je_te_guide": "I'll guide you step by step!",
            "erreur_traitement": "Error processing the question",
            "bienvenue_enseignant": "👋 Hello! I'm your virtual teacher. Ask me any question about any subject!",
            "nouveau_dialogue": "New conversation started. Ask your question!",
            "acces_enseignant": "Virtual teacher access activated!"
        }
    }
    return messages.get(lang, messages["fr"]).get(key, key)


def extraire_question(reponse, lang="fr"):
    """Extrait la question posée par l'IA - version bilingue"""
    import re
    
    # Patterns FRANÇAIS
    patterns_fr = [
        r'[Pp]eux-tu\s+(.*?)\?',
        r'[Qq]u\'est-ce que\s+(.*?)\?',
        r'[Cc]alcule\s+(.*?)\?',
        r'[Tt]rouve\s+(.*?)\?',
        r'[Dd]is-moi\s+(.*?)\?',
        r'[Qq]uelle\s+(.*?)\?',
        r'[Cc]ombien\s+(.*?)\?',
        r'[Cc]omment\s+(.*?)\?',
        r'[Pp]ourquoi\s+(.*?)\?',
        r'[Éé]cris\s+(.*?)\?',
        r'[Aa]nalyse\s+(.*?)\?',
        r'[Ee]xplique\s+(.*?)\?',
        r'[Rr]eformule\s+(.*?)\?'
    ]
    
    # Patterns ANGLAIS
    patterns_en = [
        r'[Cc]an you\s+(.*?)\?',
        r'[Ww]hat is\s+(.*?)\?',
        r'[Cc]alculate\s+(.*?)\?',
        r'[Ff]ind\s+(.*?)\?',
        r'[Tt]ell me\s+(.*?)\?',
        r'[Ww]hich\s+(.*?)\?',
        r'[Hh]ow many\s+(.*?)\?',
        r'[Hh]ow\s+(.*?)\?',
        r'[Ww]hy\s+(.*?)\?',
        r'[Ww]rite\s+(.*?)\?',
        r'[Aa]nalyze\s+(.*?)\?',
        r'[Ee]xplain\s+(.*?)\?',
        r'[Dd]escribe\s+(.*?)\?',
        r'[Rr]ephrase\s+(.*?)\?'
    ]
    
    patterns = patterns_fr if lang == "fr" else patterns_en
    
    for pattern in patterns:
        match = re.search(pattern, reponse)
        if match:
            question = match.group(1).strip()
            if len(question) > 5:  # Minimum 5 caractères
                return question
    
    return None


def get_system_prompt(matiere="mathématiques", lang="fr", mode_examen=False):
    """Prompt optimisé par matière et par langue"""
    
    # Dictionnaire des prompts FRANÇAIS
    prompts_fr = {
        "mathématiques": """Tu es un enseignant de mathématiques expert en pédagogie.
        **RÈGLES STRICTES :**
        1. TU NE DONNES JAMAIS LA RÉPONSE DIRECTEMENT
        2. Tu guides vers la méthode appropriée
        3. Tu fais réfléchir sur les concepts
        4. Tu encourages le raisonnement logique
        **EXEMPLES DE QUESTIONS :**
        - "Quelle opération utiliserais-tu ici ?"
        - "Comment formulerais-tu cette équation ?"
        - "Peux-tu dessiner un schéma pour comprendre ?"
        - "Quelle est la première étape selon toi ?"
        """,
        
        "français": """Tu es un professeur de français expert en pédagogie.
        **RÈGLES STRICTES :**
        1. TU NE DONNES JAMAIS LA RÉPONSE DIRECTEMENT
        2. Pour la grammaire : guide pour trouver les règles
        3. Pour l'analyse de texte : aide à identifier les procédés littéraires
        4. Pour la conjugaison : fais pratiquer les terminaisons
        5. Pour l'orthographe : aide à mémoriser les règles
        6. Pour la rédaction : aide à structurer les idées sans écrire à la place
        **EXEMPLES DE QUESTIONS :**
        - "Quel est le sujet de cette phrase ?"
        - "Peux-tu identifier la figure de style ?"
        - "Comment conjuguerais-tu ce verbe au passé simple ?"
        - "Quelle serait ta première phrase pour introduire ce sujet ?"
        """,
        
        "histoire": """Tu es un professeur d'histoire expert en pédagogie.
        **RÈGLES STRICTES :**
        1. TU NE DONNES JAMAIS LES DATES/ÉVÉNEMENTS DIRECTEMENT
        2. Guide pour comprendre les causes et conséquences
        3. Aide à analyser les documents historiques
        4. Fais faire des liens entre les événements
        5. Encourage la réflexion critique
        **EXEMPLES DE QUESTIONS :**
        - "Quelles étaient les causes possibles de cet événement ?"
        - "Que peut-on déduire de ce document historique ?"
        - "Quels liens fais-tu avec d'autres périodes ?"
        - "Quelle était la conséquence principale ?"
        """,
        
        "sciences": """Tu es un professeur de sciences expert en pédagogie.
        **RÈGLES STRICTES :**
        1. TU NE DONNES JAMAIS LES RÉPONSES DIRECTEMENT
        2. Guide pour la démarche scientifique
        3. Aide à formuler des hypothèses
        4. Fais analyser les résultats
        5. Encourage l'expérimentation mentale
        **EXEMPLES DE QUESTIONS :**
        - "Quelle hypothèse pourrais-tu formuler ?"
        - "Comment vérifierais-tu cette hypothèse ?"
        - "Que signifie ce résultat selon toi ?"
        - "Quelle serait la prochaine étape de l'expérience ?"
        """,
        
        "géographie": """Tu es un professeur de géographie expert en pédagogie.
        **RÈGLES STRICTES :**
        1. TU NE DONNES JAMAIS LES RÉPONSES DIRECTEMENT
        2. Guide pour lire et interpréter les cartes
        3. Aide à comprendre les phénomènes géographiques
        4. Fais faire des liens entre climat, relief et activités humaines
        5. Encourage l'observation et l'analyse spatiale
        **EXEMPLES DE QUESTIONS :**
        - "Que peux-tu observer sur cette carte ?"
        - "Quels liens fais-tu entre le climat et l'agriculture ici ?"
        - "Comment expliquerais-tu cette répartition de population ?"
        - "Quelles sont les caractéristiques principales de ce type de paysage ?"
        """
    }
    
    # Dictionnaire des prompts ANGLAIS
    prompts_en = {
        "mathematics": """You are a mathematics teacher expert in pedagogy.
        **STRICT RULES:**
        1. YOU NEVER GIVE THE ANSWER DIRECTLY
        2. You guide to the appropriate method
        3. You encourage thinking about concepts
        4. You promote logical reasoning
        **EXAMPLE QUESTIONS:**
        - "What operation would you use here?"
        - "How would you formulate this equation?"
        - "Can you draw a diagram to understand?"
        - "What is the first step in your opinion?"
        """,
        
        "french": """You are a French teacher expert in pedagogy.
        **STRICT RULES:**
        1. YOU NEVER GIVE THE ANSWER DIRECTELY
        2. For grammar: guide to find the rules
        3. For text analysis: help identify literary devices
        4. For conjugation: practice verb endings
        5. For spelling: help memorize rules
        6. For writing: help structure ideas without writing for them
        **EXAMPLE QUESTIONS:**
        - "What is the subject of this sentence?"
        - "Can you identify the figure of speech?"
        - "How would you conjugate this verb in the simple past?"
        - "What would be your first sentence to introduce this topic?"
        """,
        
        "history": """You are a history teacher expert in pedagogy.
        **STRICT RULES:**
        1. YOU NEVER GIVE DATES/EVENTS DIRECTLY
        2. Guide to understand causes and consequences
        3. Help analyze historical documents
        4. Make connections between events
        5. Encourage critical thinking
        **EXAMPLE QUESTIONS:**
        - "What were the possible causes of this event?"
        - "What can we deduce from this historical document?"
        - "What connections do you make with other periods?"
        - "What was the main consequence?"
        """,
        
        "science": """You are a science teacher expert in pedagogy.
        **STRICT RULES:**
        1. YOU NEVER GIVE ANSWERS DIRECTLY
        2. Guide through the scientific method
        3. Help formulate hypotheses
        4. Help analyze results
        5. Encourage mental experimentation
        **EXAMPLE QUESTIONS:**
        - "What hypothesis could you formulate?"
        - "How would you verify this hypothesis?"
        - "What does this result mean to you?"
        - "What would be the next step of the experiment?"
        """,
        
        "geography": """You are a geography teacher expert in pedagogy.
        **STRICT RULES:**
        1. YOU NEVER GIVE ANSWERS DIRECTLY
        2. Guide to read and interpret maps
        3. Help understand geographical phenomena
        4. Make connections between climate, terrain and human activities
        5. Encourage observation and spatial analysis
        **EXAMPLE QUESTIONS:**
        - "What can you observe on this map?"
        - "What connections do you make between climate and agriculture here?"
        - "How would you explain this population distribution?"
        - "What are the main characteristics of this type of landscape?"
        """
    }
    
    # Choisir le bon dictionnaire
    prompts_dict = prompts_fr if lang == "fr" else prompts_en
    
    # Normaliser le nom de la matière
    matiere_normalisee = matiere.lower()
    if lang == "en":
        # Mapper les noms français aux noms anglais
        matieres_map = {
            "mathématiques": "mathematics",
            "français": "french", 
            "histoire": "history",
            "sciences": "science",
            "géographie": "geography"
        }
        matiere_normalisee = matieres_map.get(matiere_normalisee, matiere_normalisee)
    
    # Récupérer le prompt spécifique ou utiliser les mathématiques comme défaut
    prompt_base = prompts_dict.get(matiere_normalisee, prompts_dict.get("mathematics" if lang == "en" else "mathématiques"))
    
    # Ajouter les règles communes dans la bonne langue
    if lang == "fr":
        regles_communes = f"""
        **MÉTHODOLOGIE PÉDAGOGIQUE :**
        1. Reformuler le problème dans tes mots
        2. Identifier la compétence concernée
        3. Guider étape par étape
        4. Poser UNE question précise à la fois
        5. Attendre la réponse avant de continuer
        6. Vérifier la compréhension à chaque étape
        7. Féliciter les progrès et efforts
        8. Corriger doucement les erreurs
        9. Adapter le langage au niveau de l'élève
        10. Utiliser des exemples concrets et familiers
        
        {"⚠️ MODE EXAMEN : Guide avec des indices seulement, ne donne pas les étapes complètes." if mode_examen else ""}
        """
    else:
        regles_communes = f"""
        **PEDAGOGICAL METHODOLOGY:**
        1. Rephrase the problem in your words
        2. Identify the relevant skill
        3. Guide step by step
        4. Ask ONE specific question at a time
        5. Wait for answer before continuing
        6. Check understanding at each step
        7. Praise progress and efforts
        8. Gently correct mistakes
        9. Adapt language to student's level
        10. Use concrete and familiar examples
        
        {"⚠️ EXAM MODE: Guide with hints only, do not give complete steps." if mode_examen else ""}
        """
    
    return prompt_base + regles_communes


def generer_debut_conversation(question, niveau, langue="fr", mode_examen=False, matiere="mathématiques"):
    """Début de conversation bilingue adapté à la matière"""
    from openai import OpenAI
    import os
    
    client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
    
    if langue == "fr":
        prompt = f"""Élève de {niveau} en {matiere.upper()} pose la question suivante : "{question}"

Ton rôle : Commencer le dialogue pédagogique SPÉCIFIQUE À LA MATIÈRE.

**Instructions :**
1. Reformule la question dans tes mots pour vérifier la compréhension
2. Identifie la compétence de {matiere} concernée
3. Propose une stratégie générale adaptée à {matiere}
4. Pose la PREMIÈRE QUESTION qui guide vers la première étape

**Format :**
- Accueil chaleureux et reformulation
- Indication de la méthode adaptée à {matiere}
- QUESTION PRÉCISE pour l'élève
- Indication de ce qu'il doit faire ensuite

{"Mode examen : reste au niveau des indices généraux." if mode_examen else ""}

**Important :** Sois encourageant et pédagogue !"""
    else:
        prompt = f"""{niveau} student in {matiere.upper()} asks the following question: "{question}"

Your role: Start the pedagogical dialogue SPECIFIC TO THE SUBJECT.

**Instructions:**
1. Rephrase the question in your words to check understanding
2. Identify the relevant {matiere} skill
3. Propose a general strategy adapted to {matiere}
4. Ask the FIRST QUESTION that guides to the first step

**Format:**
- Warm welcome and rephrasing
- Indication of method adapted to {matiere}
- SPECIFIC QUESTION for the student
- Indication of what they should do next

{"Exam mode: stay at general hint level." if mode_examen else ""}

**Important:** Be encouraging and pedagogical!"""
    
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": get_system_prompt(matiere, langue, mode_examen)},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=400
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        # Fallback bilingue
        if langue == "fr":
            return f"""Excellent ! On va travailler sur cette question de {matiere} ensemble.

**Question :** {question}

Je vais te guider étape par étape sans te donner la réponse directement.

**Première étape :** Comprendre exactement ce qu'on te demande.

**Question 1 :** Peux-tu reformuler ce problème dans tes propres mots ? Qu'est-ce qu'on cherche à comprendre ou résoudre ?

Écris ta reformulation, et je te guiderai vers la méthode à utiliser !

💡 *Astuce : Commence par expliquer ce que tu as déjà compris.*"""
        else:
            return f"""Excellent! Let's work on this {matiere} question together.

**Question:** {question}

I'll guide you step by step without giving you the answer directly.

**First step:** Understand exactly what you're being asked.

**Question 1:** Can you rephrase this problem in your own words? What are we trying to understand or solve?

Write your rephrasing, and I'll guide you to the method to use!

💡 *Tip: Start by explaining what you already understand.*"""


def generer_suite_conversation(derniere_q, reponse, historique, niveau, langue="fr", mode_examen=False, exercice_context="", matiere="mathématiques"):
    """Continue la conversation bilingue avec contexte de matière"""
    from openai import OpenAI
    import os
    
    client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
    
    # Préparer l'historique contextuel
    historique_contextuel = []
    
    # Ajouter les 10 derniers messages maximum
    for msg in historique[-10:]:
        historique_contextuel.append(msg)
    
    historique_text = "\n".join(historique_contextuel)
    
    if langue == "fr":
        prompt = f"""Élève de {niveau} en {matiere.upper()}

**HISTORIQUE DE CONVERSATION :**
{historique_text}

**Dernière question que j'ai posée :** {derniere_q}
**Réponse de l'élève :** {reponse}

**Ta tâche ({matiere}) :**
1. Analyser la réponse de l'élève dans le contexte de {matiere}
2. Valider ce qui est correct selon les règles de {matiere}
3. Corriger doucement ce qui est erroné (sans critiquer)
4. Poser la PROCHAINE QUESTION qui avance vers la compréhension/solution
5. Toujours encourager et féliciter les efforts

**Règles pédagogiques strictes :**
- Ne jamais donner la réponse directement
- Guider avec des questions spécifiques
- Adapter le langage au niveau scolaire
- Être patient et bienveillant
- Utiliser des exemples concrets si nécessaire

{"Mode examen : guide avec des indices, ne révèle pas les étapes." if mode_examen else ""}"""
    else:
        prompt = f"""{niveau} student in {matiere.upper()}

**CONVERSATION HISTORY:**
{historique_text}

**Last question I asked:** {derniere_q}
**Student's answer:** {reponse}

**Your task ({matiere}):**
1. Analyze the student's response in the context of {matiere}
2. Validate what is correct according to {matiere} rules
3. Gently correct what is wrong (without criticism)
4. Ask the NEXT QUESTION that moves toward understanding/solution
5. Always encourage and praise efforts

**Strict pedagogical rules:**
- Never give the answer directly
- Guide with specific questions
- Adapt language to school level
- Be patient and supportive
- Use concrete examples if needed

{"Exam mode: guide with hints, do not reveal steps." if mode_examen else ""}"""
    
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": get_system_prompt(matiere, langue, mode_examen)},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=450
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        # Fallback bilingue
        if langue == "fr":
            return f"""Merci pour ta réponse ! C'est un bon début.

Pour continuer notre exploration de cette question de {matiere}, j'ai besoin de comprendre un peu mieux ta pensée.

**Nouvelle question :** Quelle est la prochaine étape logique selon toi ? Si tu hésites, dis-moi simplement ce que tu comprends jusqu'à présent.

Je suis là pour t'aider à avancer pas à pas !

✨ *N'oublie pas : chaque erreur est une occasion d'apprendre !*"""
        else:
            return f"""Thank you for your answer! That's a good start.

To continue our exploration of this {matiere} question, I need to understand your thinking a bit better.

**New question:** What is the next logical step in your opinion? If you hesitate, just tell me what you understand so far.

I'm here to help you move forward step by step!

✨ *Remember: every mistake is a learning opportunity!*"""


@app.after_request
def add_header(response):
    """Ajouter des headers pour empêcher la mise en cache et les rechargements"""
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

@app.route("/chat", methods=["POST"])
def chat():
    from chatbot_utils import get_chatbot_response  # chemin selon ton organisation
    user_input = request.json.get("message", "")
    response = get_chatbot_response(user_input)
    return jsonify({"response": response})

@app.route("/nouvel-exercice", methods=["POST"])
def nouvel_exercice():
    """Nouvel exercice - réinitialise COMPLÈTEMENT"""
    if "eleve_id" not in session:
        return redirect(url_for("login_eleve"))
    
    # Vider TOUTE la session liée à la conversation
    session_keys_to_remove = [
        "conversation", 
        "derniere_q_ia", 
        "exercice_en_cours",
        "mode_examen"  # Au cas où
    ]
    
    for key in session_keys_to_remove:
        session.pop(key, None)
    
    # Flash message clair
    flash("🎯 Nouvel exercice prêt ! Pose ta question.", "success")
    
    # Rediriger avec un timestamp pour éviter le cache
    import time
    return redirect(url_for("enseignant_virtuel") + f"?t={int(time.time())}")

@app.after_request
def add_headers(response):
    """Headers anti-cache"""
    response.headers['Cache-Control'] = 'no-store, no-cache'
    response.headers['Pragma'] = 'no-cache'
    return response

@app.after_request
def after_request(response):
    """Ajouter des headers pour empêcher la mise en cache"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.route("/matiere-par-niveau/<int:niveau_id>")
def matiere_par_niveau(niveau_id):
    matieres = Matiere.query.filter_by(niveau_id=niveau_id).all()
    return jsonify([{"id": m.id, "nom": m.nom} for m in matieres])

@app.route("/unites-par-matiere/<int:matiere_id>")
def unites_par_matiere(matiere_id):
    unites = Unite.query.filter_by(matiere_id=matiere_id).all()
    return jsonify([{"id": u.id, "nom": u.nom} for u in unites])

@app.route("/admin/contenus", methods=["GET"])
@admin_required
def contenus_admin():
    niveaux = Niveau.query.all()
    return render_template("admin_contenus.html", niveaux=niveaux)

@app.route("/contenus-eleve")
def contenus_eleve():
    username = request.args.get("username")
    lang = request.args.get("lang", "fr")

    eleve = User.query.options(
        joinedload(User.niveau)
        .joinedload(Niveau.matieres)
        .joinedload(Matiere.unites)
        .joinedload(Unite.lecons)
        .joinedload(Lecon.exercices),
        joinedload(User.niveau)
        .joinedload(Niveau.matieres)
        .joinedload(Matiere.unites)
        .joinedload(Unite.tests)
    ).filter_by(username=username).first_or_404()

    # Réponses aux exercices simples
    responses = StudentResponse.query.filter_by(user_id=eleve.id).all()
    exercices_faits = {r.exercice_id: r for r in responses}

    # Réponses aux tests sommatifs
    tests_reponses = {tr.test_id: tr for tr in TestResponse.query.filter_by(user_id=eleve.id).all()}

    return render_template(
        "contenus_eleve.html",
        eleve=eleve,
        lang=lang,
        niveaux=[eleve.niveau],
        exercices_faits=exercices_faits,
        tests_faits=tests_reponses
    )


@app.route("/admin/creer-exercice-ia", methods=["GET", "POST"])
def creer_exercice_ia():
    # 🔒 Vérification d'accès - maintenant pour enseignants aussi
    if not session.get("enseignant_id") and not session.get("is_admin"):
        return redirect("/login-enseignant")

    # Déterminer le tableau de bord de retour
    if session.get("is_admin"):
        dashboard_url = "/admin/dashboard"
    elif session.get("enseignant_id"):
        dashboard_url = "/dashboard-enseignant"
    else:
        dashboard_url = "/"

    import json, re

    niveaux = Niveau.query.all()
    matieres = Matiere.query.all()
    unites = Unite.query.all()
    lecons = Lecon.query.all()

    if request.method == "POST":
        niveau_id = request.form.get("niveau_id")
        matiere_id = request.form.get("matiere_id")
        unite_id = request.form.get("unite_id")
        lecon_id = request.form.get("lecon_id")
        objectif = request.form.get("objectif")
        difficulte = request.form.get("difficulte")
        nb_exercices = int(request.form.get("nb_exercices", 1))
        exemple = request.form.get("exemple", "").strip()

        # Vérification des champs requis
        if not all([niveau_id, matiere_id, unite_id, lecon_id, objectif, difficulte]):
            return "Tous les champs obligatoires ne sont pas remplis.", 400
        
        # ✅ Validation du nombre d'exercices (1 à 5)
        if nb_exercices < 1 or nb_exercices > 5:
            return "Le nombre d'exercices doit être entre 1 et 5.", 400

        niveau = Niveau.query.get(niveau_id)
        matiere = Matiere.query.get(matiere_id)
        unite = Unite.query.get(unite_id)
        lecon = Lecon.query.get(lecon_id)

        # ✅ Prompt amélioré avec spécification claire du nombre
        prompt = f"""
Tu es un générateur d'exercices pédagogiques.

Contexte pédagogique :
- Niveau : {niveau.nom}
- Matière : {matiere.nom}
- Unité : {unite.nom}
- Leçon : {lecon.titre_fr}
- Objectif pédagogique : {objectif}
- Difficulté : {difficulte}

Consigne :
Génère exactement {nb_exercices} exercices distincts, clairs, variés et bien structurés, adaptés au niveau donné.
Les exercices doivent être diversifiés (types différents, approches différentes).
Si un exemple est fourni, inspire-toi du style mais ne le copie pas.

⚠️ Important :
- Si tu écris des formules mathématiques, encadre-les avec des dollars `$...$` ou `$$...$$` (compatibilité LaTeX).
- Réponds uniquement avec un JSON **valide**, sans texte avant ni après.
- Ne jamais échapper les dollars ni les backslashes (\\) dans les formules.

Format strict attendu :
[
  {{
    "question_fr": "Question en français ici...",
    "question_en": "Question in English here...",
    "reponse_fr": "Réponse en français ici...",
    "reponse_en": "Answer in English here...",
    "explication_fr": "Explication détaillée en français...",
    "explication_en": "Detailed explanation in English..."
  }},
  ... (exactement {nb_exercices} exercices)
]

{f"Exemple à titre d'inspiration : {exemple}" if exemple else ""}

💡 Astuce : Crée des exercices complémentaires qui couvrent différents aspects de l'objectif pédagogique.
"""

        # 🧠 Appel à l'API OpenAI
        try:
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "Tu es un générateur d'exercices pédagogiques JSON pur. Génère toujours le nombre exact d'exercices demandé."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=3500,  # Augmenté pour plusieurs exercices
                temperature=0.7,
            )
        except Exception as e:
            return f"Erreur lors de l'appel OpenAI : {e}", 500

        contenu = response.choices[0].message.content.strip()
        print("📘 Réponse brute GPT :\n", contenu)

        # 🔍 Extraction du JSON pur
        try:
            match = re.search(r"\[.*\]", contenu, re.DOTALL)
            if not match:
                raise ValueError("Aucun tableau JSON détecté dans la réponse.")
            json_text = match.group(0)

            # 🧹 Étape critique : corriger les antislashs invalides
            json_text = re.sub(r'(?<!\\)\\(?!["\\/bfnrtu])', r'\\\\', json_text)

            # 🧩 Parsing JSON
            data = json.loads(json_text)
            
            # ✅ Vérification du nombre d'exercices générés
            if len(data) != nb_exercices:
                print(f"⚠️ GPT a généré {len(data)} exercices au lieu de {nb_exercices}")

        except Exception as e:
            print("❌ Erreur JSON :", e)
            return f"Erreur de parsing JSON : {e}<br><br>Réponse brute de l'IA :<pre>{contenu}</pre>", 500

        # 💾 Enregistrement des exercices générés
        exercices_crees = []
        for ex in data:
            exercice = Exercice(
                lecon_id=lecon.id,
                question_fr=ex.get("question_fr", "").strip(),
                question_en=ex.get("question_en", "").strip(),
                reponse_fr=ex.get("reponse_fr", "").strip(),
                reponse_en=ex.get("reponse_en", "").strip(),
                explication_fr=ex.get("explication_fr", "").strip(),
                explication_en=ex.get("explication_en", "").strip(),
                temps=60
            )
            db.session.add(exercice)
            db.session.flush()  # Pour obtenir l'ID
            exercices_crees.append(exercice)

        db.session.commit()

        # ✅ Afficher la page de confirmation
        return render_template(
            "exercices_crees.html",
            nombre=len(exercices_crees),
            lecon=lecon,
            exercices=exercices_crees,  # Passer les exercices pour affichage
            lang=session.get("lang", "fr"),
            dashboard_url=dashboard_url
        )

    # Si GET → afficher le formulaire
    return render_template(
        "form_creer_exercice_ia.html",
        niveaux=niveaux,
        matieres=matieres,
        unites=unites,
        lecons=lecons,
        lang=session.get("lang", "fr"),
        dashboard_url=dashboard_url
    )


@app.route("/admin/creer-test-sommatif-ia", methods=["GET", "POST"])
def creer_test_sommatif_ia():
    # 🔒 Vérification d'accès - maintenant pour enseignants aussi
    if not session.get("enseignant_id") and not session.get("is_admin"):
        return redirect("/login-enseignant")

    # Déterminer la page de retour
    if session.get("is_admin"):
        dashboard_url = "/admin/dashboard"
    elif session.get("enseignant_id"):
        dashboard_url = "/dashboard-enseignant"
    else:
        dashboard_url = "/"

    import json, re

    niveaux = Niveau.query.all()
    matieres = Matiere.query.all()
    unites = Unite.query.all()

    if request.method == "POST":
        niveau_id = request.form.get("niveau_id")
        matiere_id = request.form.get("matiere_id")
        unite_id = request.form.get("unite_id")
        nb_questions = int(request.form.get("nb_questions", 1))
        difficulte = request.form.get("difficulte", "moyenne")
        exemple = request.form.get("exemple", "").strip()
        temps = int(request.form.get("temps", 600))

        if not all([niveau_id, matiere_id, unite_id, nb_questions]):
            return "Tous les champs obligatoires ne sont pas remplis.", 400

        niveau = Niveau.query.get(niveau_id)
        matiere = Matiere.query.get(matiere_id)
        unite = Unite.query.get(unite_id)

        # ✅ Prompt amélioré avec instructions PLUS STRICTES
        prompt = f"""
Tu es un générateur de tests sommatifs pédagogiques.

CONTEXTE PÉDAGOGIQUE :
- Niveau : {niveau.nom}
- Matière : {matiere.nom}
- Unité : {unite.nom}
- Difficulté : {difficulte}
- Nombre de questions : {nb_questions} (EXACTEMENT {nb_questions} QUESTIONS)

CONSIGNES STRICTES :
1. Génère EXACTEMENT {nb_questions} questions - PAS PLUS, PAS MOINS
2. Chaque question doit être en français et en anglais
3. Format de réponse EXCLUSIVEMENT en JSON valide
4. Pas de texte avant ou après le JSON
5. Pour les formules mathématiques, utilise $$...$$ pour l'affichage et $...$ pour l'inline
6. STOP après {nb_questions} questions

FORMAT JSON OBLIGATOIRE :
[
  {{
    "question_fr": "Question en français...",
    "question_en": "Question in English...",
    "reponse_fr": "Réponse en français...",
    "reponse_en": "Answer in English...",
    "explication_fr": "Explication en français...",
    "explication_en": "Explanation in English..."
  }}
]

{f"EXEMPLE D'INSPIRATION (ne pas copier) : {exemple}" if exemple else ""}

IMPORTANT : 
- Réponds UNIQUEMENT avec le JSON, sans commentaires
- EXACTEMENT {nb_questions} questions
- STOP après {nb_questions} questions
"""

        try:
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": f"Tu es un assistant qui génère EXCLUSIVEMENT du JSON valide pour des tests pédagogiques. Tu génères EXACTEMENT le nombre de questions demandé. Tu ne réponds qu'avec du JSON, sans texte avant ni après."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=4000,
                temperature=0.7,
            )
        except Exception as e:
            return f"Erreur lors de l'appel OpenAI : {e}", 500

        contenu = response.choices[0].message.content.strip()
        print("📘 Réponse brute GPT :\n", contenu)
        
        # Vérifier si la réponse est tronquée
        if "..." in contenu and not contenu.strip().endswith("]"):
            print("⚠️ Réponse GPT tronquée détectée")
            return f"Erreur : La réponse de l'IA est tronquée. Essayez avec moins de questions ou réessayez.<br><br>Réponse partielle :<pre>{contenu}</pre>", 500

        # 🔍 Extraction et nettoyage du JSON - APPROCHE SIMPLIFIÉE
        try:
            # Nettoyer d'abord la réponse
            contenu_clean = contenu.strip()
            
            # Supprimer les éventuels backticks de code
            if contenu_clean.startswith("```json"):
                contenu_clean = contenu_clean[7:]
            elif contenu_clean.startswith("```"):
                contenu_clean = contenu_clean[3:]
            if contenu_clean.endswith("```"):
                contenu_clean = contenu_clean[:-3]
            contenu_clean = contenu_clean.strip()
            
            print("🔧 Contenu après nettoyage initial :\n", contenu_clean)
            
            # APPROCHE DIRECTE - Essayer de parser directement d'abord
            try:
                data = json.loads(contenu_clean)
                print("✅ JSON parsé directement sans extraction")
            except json.JSONDecodeError as first_error:
                print("⚠️ Premier parsing échoué, tentative d'extraction...")
                
                # Si le parsing direct échoue, essayer d'extraire le JSON
                match = re.search(r'\[\s*\{.*\}\s*\]', contenu_clean, re.DOTALL)
                if not match:
                    match = re.search(r'\[.*\]', contenu_clean, re.DOTALL)
                    if not match:
                        # Dernière tentative : chercher un début de JSON
                        start_idx = contenu_clean.find('[')
                        end_idx = contenu_clean.rfind(']')
                        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                            json_text = contenu_clean[start_idx:end_idx+1]
                            print("📄 JSON extrait par indices :\n", json_text)
                        else:
                            raise ValueError("Aucun tableau JSON détecté dans la réponse de l'IA.")
                    else:
                        json_text = match.group(0)
                else:
                    json_text = match.group(0)
                
                print("📄 JSON extrait :\n", json_text)
                
                # CORRECTION CRITIQUE : Déséchapper les guillemets si nécessaire
                if '\\"' in json_text:
                    json_text = json_text.replace('\\"', '"')
                    print("🔧 Guillemets déséchappés")
                
                # Essayer de parser le JSON extrait
                data = json.loads(json_text)
                print("✅ JSON extrait parsé avec succès")

        except json.JSONDecodeError as e:
            print("❌ Erreur de décodage JSON :", e)
            print("📄 Dernier texte essayé :", contenu_clean if 'data' not in locals() else json_text)
            
            # Dernière tentative : essayer avec ast.literal_eval
            try:
                import ast
                data = ast.literal_eval(contenu_clean)
                print("✅ JSON parsé avec ast.literal_eval")
            except:
                # Afficher un message d'erreur plus utile
                error_msg = f"""
                Erreur de parsing JSON : {e}

                La réponse de l'IA ne respecte pas le format JSON attendu.

                Suggestions :
                - Réduisez le nombre de questions (essayez avec 3-5 questions)
                - Vérifiez que l'IA génère exactement le nombre demandé
                - Réessayez l'opération

                Réponse brute de l'IA :
                <pre>{contenu}</pre>
                """
                return error_msg, 500
                
        except Exception as e:
            print("❌ Erreur générale JSON :", e)
            return f"Erreur de traitement JSON : {e}<br><br>Réponse brute de l'IA :<pre>{contenu}</pre>", 500

        # Vérifier que nous avons des données
        if not data or not isinstance(data, list):
            return "Aucune donnée valide trouvée dans la réponse de l'IA.", 500

        # Vérifier que nous avons le bon nombre de questions
        questions_recues = len(data)
        if questions_recues != nb_questions:
            print(f"⚠️ Nombre de questions générées ({questions_recues}) différent de celui demandé ({nb_questions})")
            # On continue quand même avec le nombre reçu, mais on avertit
            # Vous pourriez aussi choisir de retourner une erreur ici

        # 💾 Création du test sommatif principal
        try:
            # Créer le test sommatif avec uniquement les champs existants
            test = TestSommatif(
                unite_id=unite.id, 
                temps=temps
            )
            db.session.add(test)
            db.session.flush()

            # 💾 Ajout de chaque question générée comme TestExercice
            questions_ajoutees = 0
            for i, q in enumerate(data):
                # Vérifier que les champs requis existent
                if q.get("question_fr") and q.get("question_en"):
                    test_exercice = TestExercice(
                        test_id=test.id,
                        question_fr=q.get("question_fr", "").strip(),
                        question_en=q.get("question_en", "").strip(),
                        reponse_fr=q.get("reponse_fr", "").strip(),
                        reponse_en=q.get("reponse_en", "").strip(),
                        explication_fr=q.get("explication_fr", "").strip(),
                        explication_en=q.get("explication_en", "").strip()
                    )
                    db.session.add(test_exercice)
                    questions_ajoutees += 1

            db.session.commit()
            
            print(f"✅ Test créé avec {questions_ajoutees} questions sur {questions_recues} reçues")

            # Si aucune question n'a été ajoutée
            if questions_ajoutees == 0:
                return "Aucune question valide n'a pu être créée à partir de la réponse de l'IA.", 500

        except Exception as e:
            db.session.rollback()
            print("❌ Erreur base de données :", e)
            return f"Erreur lors de l'enregistrement en base de données : {e}", 500

        # ✅ REDIRECTION VERS LA VISUALISATION après création
        return render_template(
            "test_sommatif_cree.html",
            nombre=questions_ajoutees,
            test=test,
            lang=session.get("lang", "fr"),
            dashboard_url=dashboard_url
        )

    # 🧩 Page GET : formulaire
    return render_template(
        "form_creer_test_sommatif_ia.html",
        niveaux=niveaux,
        matieres=matieres,
        unites=unites,
        lang=session.get("lang", "fr"),
        dashboard_url=dashboard_url
    )
    


@app.route("/admin/visualiser-test-sommatif/<int:test_id>")
def visualiser_test_sommatif(test_id):
    # 🔒 Vérification d'accès - pour enseignants et admin
    if not session.get("enseignant_id") and not session.get("is_admin"):
        return redirect("/login-enseignant")
    
    # Déterminer le dashboard de retour
    if session.get("is_admin"):
        dashboard_url = "/admin/dashboard"
    elif session.get("enseignant_id"):
        dashboard_url = "/dashboard-enseignant"
    else:
        dashboard_url = "/"

    test = TestSommatif.query.get_or_404(test_id)
    exercices = TestExercice.query.filter_by(test_id=test.id).all()

    return render_template(
        "visualiser_test_sommatif.html",
        test=test,
        exercices=exercices,
        lang=session.get("lang", "fr"),
        dashboard_url=dashboard_url
    )

@app.route("/admin/supprimer-exercice/<int:exercice_id>", methods=["POST"])
@admin_required
def supprimer_exercice(exercice_id):
    exercice = Exercice.query.get_or_404(exercice_id)
    lecon_id = exercice.lecon_id
    db.session.delete(exercice)
    db.session.commit()
    flash("✅ Exercice supprimé avec succès" if session.get("lang") != "en" else "✅ Exercise successfully deleted", "success")
    return redirect(url_for("admin_dashboard", lecon_id=lecon_id))


@app.route("/eleve/remediation/<int:id>", methods=["GET", "POST"])
def faire_remediation(id):
    from datetime import datetime
    eleve_id = session.get("eleve_id")

    if not eleve_id:
        return redirect("/login-eleve")

    remediation = RemediationSuggestion.query.get_or_404(id)
    eleve = User.query.get_or_404(eleve_id)

    if remediation.user_id != eleve.id:
        return "Accès non autorisé", 403

    lang = eleve.langue if hasattr(eleve, "langue") and eleve.langue == "en" else "fr"

    if remediation.statut != "valide":
        return render_template("remediation_non_validee.html", lang=lang)

    if request.method == "POST":
        reponse_texte = request.form.get("reponse_eleve") or request.form.get("reponse", "")
        reponse_texte = reponse_texte.strip()
        if not reponse_texte:
            return "Réponse vide", 400

        question = ""
        reponse_attendue = ""
        if remediation.exercice_suggere:
            for ligne in remediation.exercice_suggere.splitlines():
                if not question and ("Question :" in ligne or "Question:" in ligne):
                    question = ligne.split(":", 1)[1].strip()
                elif not reponse_attendue and ("Réponse attendue" in ligne or "Expected answer" in ligne):
                    reponse_attendue = ligne.split(":", 1)[1].strip()

        # ✅ NOUVEAU PROMPT avec barème sur 5
        if lang == "en":
            prompt = f"""
You are a rigorous and expert math teacher. You must evaluate a student's solution.

📘 Problem:
{question}

📜 Student's Response:
{reponse_texte}

🌟 Expected Final Answer (provided by human expert):
{reponse_attendue}

🔍 Instructions:
- Solve the problem yourself and make sure your final answer matches the expert-provided one.
- Compare each line of the student's reasoning with your own.
- Accept steps that are logically and mathematically correct, even if expressed differently.
- Do not claim something is wrong if it is correct but differently presented.
- Be pedagogical and constructive in your feedback.
- Use the informal "you" to address the student directly for a more familiar tone.
- Give priority to reasoning over final result.
- Award partial credit for correct steps.
- ❗ Important: Do not contradict yourself. If the final answer is correct and the reasoning is valid, do not say otherwise.

⭐ SCORING SCALE (5 POINTS MAXIMUM):
- 5/5: Excellent reasoning, complete methodology, correct result
- 4/5: Very good reasoning, appropriate method, minor calculation error  
- 3/5: Good overall approach, method understood but imperfect application
- 2/5: Partial reasoning, some relevant elements but incomplete
- 1/5: Fragmented approach, very limited correct elements
- 0/5: Off-topic or no answer

🎯 IMPORTANT: 
- You MUST use the 5-point scale above
- ALWAYS write "Score: X/5" in your response

📤 Output format:
Analysis:
[...]
Score: X/5
Correction:
- Expert resolution: [...]
- Final answer: [...]
"""
        else:
            prompt = f"""
Tu es un professeur de mathématiques expert et rigoureux. Tu dois évaluer la réponse d'un élève.

📘 Énoncé :
{question}

📜 Réponse de l'élève :
{reponse_texte}

🌟 Réponse finale attendue (imposée) :
{reponse_attendue}

🔍 Ce que tu dois faire :
- Résous l'exercice toi-même pour vérifier que tu obtiens la même réponse que celle attendue.
- Compare chaque ligne du raisonnement de l'élève avec ta propre résolution.
- Si chaque transformation est correcte même si elle est formulée autrement, accepte-la.
- Sois cohérent : ne dis pas qu'il y a une erreur si la réponse est bonne et la méthode correcte.
- Sois pédagogique, clair et bienveillant.
- Tutoie l'élève pour plus de familiarité en t'adressant directement à lui.
- Privilégie le raisonnement sur le résultat final.
- Accordez des points partiels pour les étapes correctes.
- ❗ Important : ne te contredit pas. Si la réponse finale est correcte et que le raisonnement est valide, ne dit pas le contraire.

⭐ BARÈME (5 POINTS MAXIMUM) :
- 5/5 : Raisonnement excellent, méthodologie complète, résultat correct
- 4/5 : Très bon raisonnement, méthode appropriée, erreur mineure de calcul
- 3/5 : Bonne démarche globale, méthode comprise mais application imparfaite
- 2/5 : Raisonnement partiel, éléments pertinents mais incomplets
- 1/5 : Démarche ébauchée, éléments corrects très limités
- 0/5 : Hors sujet ou absence de réponse

🎯 IMPORTANT :
- Vous DEVEZ utiliser le barème sur 5 points ci-dessus
- Écrivez TOUJOURS "Note : X/5" dans votre réponse

📤 Format attendu :
Analyse :
[Ligne par ligne : ce qui est correct ou faux, justification, remarque]
Note : X/5

Correction :
- Résolution experte : [...]
- Résultat final : [...]
"""

        try:
            chat_completion = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
            )
            analyse_ia = chat_completion.choices[0].message.content.strip()
        except Exception as e:
            return f"Erreur IA : {e}", 500

        # ✅ EXTRACTION DE NOTE SUR 5
        etoiles = 0
        match = re.search(r"(Note|Score)\s*:\s*(\d)/5", analyse_ia, re.IGNORECASE)
        if match:
            etoiles = int(match.group(2))
            print(f"⭐ Note remédiation extraite: {etoiles}/5")
        else:
            # Fallback pour l'ancien format
            match = re.search(r"(Note|Score)\s*:\s*(\d)", analyse_ia, re.IGNORECASE)
            if match:
                etoiles = min(int(match.group(2)), 5)  # Limite à 5 maximum
                print(f"⭐ Note remédiation extraite (sans /5): {etoiles}/5")
            else:
                print("⚠️ Impossible d'extraire la note de l'analyse IA")

        reponse = StudentResponse(
            user_id=eleve.id,
            exercice_id=None,
            reponse_eleve=reponse_texte,
            analyse_ia=analyse_ia,
            etoiles=etoiles,
            timestamp=datetime.utcnow()
        )
        db.session.add(reponse)

        remediation.reponse_eleve = reponse_texte
        remediation.analyse_ia = analyse_ia
        remediation.etoiles = etoiles

        # ✅ Mise à jour du statut selon la note sur 5
        if etoiles >= 3:  # Si note ≥ 3/5, la remédiation est réussie
            remediation.statut = "reussie"
        else:
            remediation.statut = "en_attente"  # Doit retravailler

        db.session.commit()

        return render_template(
            "feedback_exercice.html",
            reponse=reponse_texte,
            analyse=analyse_ia,
            etoiles=etoiles,
            redirect_url=f"/eleve/remediations?username={eleve.username}&lang={lang}",
            lang=lang,
            is_remediation=True
        )

    return render_template(
        "faire_remediation.html",
        remediation=remediation,
        eleve=eleve,
        lang=lang,
        feedback=None,
        etoiles=0
    )

@app.route("/close-remediation-access", methods=["POST"])
def close_remediation_access():
    """Ferme l'accès à l'enseignant virtuel après réussite"""
    if "eleve_id" not in session:
        return redirect(url_for("login_eleve"))
    
    # Supprimer les clés de session
    session.pop('remediation_access_granted', None)
    session.pop('remediation_exercice_id', None)
    session.pop('remediation_access_count', None)
    session.pop('conversation', None)
    session.pop('derniere_q_ia', None)
    
    flash("🎉 Félicitations ! Tu as terminé la rémédiation.", "success")
    return redirect(url_for('dashboard_eleve'))

@app.context_processor
def inject_lang():
    return {"lang": session.get("lang", "fr")}

@app.route("/sequence-unite")
def sequence_unite():
    username = request.args.get("username")
    ids = request.args.get("ids", "").split(",")
    lang = request.args.get("lang", "fr")

    eleve = User.query.filter_by(username=username).first_or_404()
    ids = [int(i) for i in ids if i.isdigit()]
    exercices = Exercice.query.filter(Exercice.id.in_(ids)).all()

    if not exercices:
        return "Aucun exercice trouvé", 404

    index = int(request.args.get("index", 0))
    if index >= len(exercices):
        return redirect(url_for("dashboard_eleve", username=username, lang=lang))

    exercice = exercices[index]

    return render_template(
        "sequence_exercice.html",
        eleve=eleve,
        exercice=exercice,
        total=len(exercices),
        index=index,
        lang=lang
    )


@app.before_request
def set_language():
    lang = request.args.get("lang")
    if lang:
        session["lang"] = lang
    g.lang = session.get("lang", "fr")

@app.route("/exercice/<int:ex_id>", methods=["GET", "POST"])
def faire_exercice(ex_id):
    username = request.args.get("username")
    lang = request.args.get("lang", "fr")

    eleve = User.query.filter_by(username=username).first_or_404()
    exercice = Exercice.query.get_or_404(ex_id)

    # Vérifier si l'exercice est déjà fait
    reponse_existante = StudentResponse.query.filter_by(
        user_id=eleve.id, 
        exercice_id=exercice.id
    ).first()

    # Si POST et exercice non fait, soumettre normalement
    if request.method == "POST" and not reponse_existante:
        reponse_eleve = request.form.get("reponse_eleve", "").strip()
        if not reponse_eleve:
            flash("Veuillez saisir une réponse" if lang == "fr" else "Please enter an answer", "error")
            return render_template(
                "exercice_detail.html",
                eleve=eleve,
                exercice=exercice,
                lang=lang,
                reponse=None,
                show_feedback=False,
                already_completed=False
            )

        # Utiliser directement la route soumettre-reponse avec les bons paramètres
        return redirect(url_for(
            'soumettre_reponse',
            student_id=eleve.id,
            exercice_id=exercice.id,
            reponse_eleve=reponse_eleve,
            redirect_url=f"/exercice/{ex_id}?username={eleve.username}&lang={lang}&submitted=1"
        ))

    # Si GET ou exercice déjà fait, afficher la page
    return render_template(
        "exercice_detail.html",
        eleve=eleve,
        exercice=exercice,
        lang=lang,
        reponse=reponse_existante,  # Inclure la réponse existante si elle existe
        show_feedback=bool(reponse_existante),  # Afficher la rétroaction si exercice déjà fait
        already_completed=bool(reponse_existante)  # Indiquer que l'exercice est déjà terminé
    )

@app.route("/soumettre-reponse", methods=["POST"])
def soumettre_reponse():
    from datetime import datetime
    import re

    print("=== 📝 SOUMISSION RÉPONSE SIMPLE ===")
    
    # DEBUG: Afficher tous les champs reçus
    print("📦 Données reçues:", dict(request.form))
    
    # Récupération des données
    student_id = request.form.get("student_id")
    exercice_id = request.form.get("exercice_id")
    reponse_eleve = request.form.get("reponse_eleve", "").strip()
    redirect_url = request.form.get("redirect_url", "/")

    print(f"Student ID: {student_id}")
    print(f"Exercice ID: {exercice_id}")
    print(f"Réponse: {reponse_eleve}")

    # Validation détaillée
    missing_fields = []
    if not student_id:
        missing_fields.append("student_id")
    if not exercice_id:
        missing_fields.append("exercice_id")
    if not reponse_eleve:
        missing_fields.append("reponse_eleve")
    
    if missing_fields:
        print(f"❌ Champs manquants: {missing_fields}")
        return f"Données manquantes: {', '.join(missing_fields)}", 400

    eleve = User.query.get(student_id)
    exercice = Exercice.query.get(exercice_id)

    if not eleve:
        print("❌ Élève non trouvé")
        return "Élève non trouvé", 404
        
    if not exercice:
        print("❌ Exercice non trouvé")
        return "Exercice non trouvé", 404

    lang = eleve.langue if hasattr(eleve, "langue") and eleve.langue == "en" else "fr"
    question = exercice.question_en if lang == "en" else exercice.question_fr

    # ✅ NOUVEAU PROMPT avec barème sur 5
    if lang == "en":
        prompt = f"""
Correct the student's answer to a school exercise.

📘 Problem statement:
{question}

📜 Student's answer:
{reponse_eleve}

⭐ SCORING SCALE (5 POINTS MAXIMUM):
- 5/5: Excellent reasoning, complete methodology, correct result
- 4/5: Very good reasoning, appropriate method, minor calculation error  
- 3/5: Good overall approach, method understood but imperfect application
- 2/5: Partial reasoning, some relevant elements but incomplete
- 1/5: Fragmented approach, very limited correct elements
- 0/5: Off-topic or no answer

🎯 IMPORTANT: 
- Give priority to reasoning over final result
- Award partial credit for correct steps
- You MUST use the 5-point scale above
- ALWAYS write "Score: X/5" in your response

📤 Expected format:
Analysis:
[...]
Score: X/5
Correction:
- Expert resolution: [...]
- Final answer: [...]
""".strip()
    else:
        prompt = f"""
Corrige la réponse d'un élève à un exercice scolaire.

📘 Énoncé :
{question}

📜 Réponse de l'élève :
{reponse_eleve}

⭐ BARÈME (5 POINTS MAXIMUM) :
- 5/5 : Raisonnement excellent, méthodologie complète, résultat correct
- 4/5 : Très bon raisonnement, méthode appropriée, erreur mineure de calcul
- 3/5 : Bonne démarche globale, méthode comprise mais application imparfaite
- 2/5 : Raisonnement partiel, éléments pertinents mais incomplets
- 1/5 : Démarche ébauchée, éléments corrects très limités
- 0/5 : Hors sujet ou absence de réponse

🎯 IMPORTANT :
- Privilégiez le raisonnement sur le résultat final
- Accordez des points partiels pour les étapes correctes
- Vous DEVEZ utiliser le barème sur 5 points ci-dessus
- Écrivez TOUJOURS "Note : X/5" dans votre réponse

📤 Format attendu :
Analyse :
[...]
Note : X/5
Correction :
- Résolution experte : [...]
- Résultat final : [...]
""".strip()

    try:
        print("🤖 Appel à l'API OpenAI...")
        chat_completion = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
        )
        analyse_ia = chat_completion.choices[0].message.content.strip()
        print("✅ Analyse IA reçue avec succès")
    except Exception as e:
        analyse_ia = f"Erreur IA : {e}"
        print(f"❌ Erreur lors de l'appel IA: {e}")

    # ✅ EXTRACTION DE NOTE SUR 5
    etoiles = 0
    match = re.search(r"(Note|Score)\s*:\s*(\d)/5", analyse_ia, re.IGNORECASE)
    if match:
        etoiles = int(match.group(2))
        print(f"⭐ Note extraite: {etoiles}/5")
    else:
        # Fallback si le format /5 n'est pas respecté
        match = re.search(r"(Note|Score)\s*:\s*(\d)", analyse_ia, re.IGNORECASE)
        if match:
            etoiles = min(int(match.group(2)), 5)  # Limite à 5 maximum
            print(f"⭐ Note extraite (sans /5): {etoiles}/5")
        else:
            print("⚠️ Impossible d'extraire la note de l'analyse IA")

    # ✅ GÉNÉRATION DE REMÉDIATION si note < 3/5
    if etoiles < 3:
        print(f"🔄 Génération remédiation (note: {etoiles}/5)")
        if lang == "en":
            remediation_prompt = f"""
Generate a new math remediation exercise for a student who scored {etoiles}/5 on the previous exercise.

🧩 Context:
- Original question: {question}
- Student's answer: {reponse_eleve}
- Student's score: {etoiles}/5

✍️ Instructions:
- Create an exercise with equivalent difficulty focusing on the same concepts
- Adapt the exercise to address the specific difficulties shown in the student's answer
- Write clear instructions
- Provide the expected final answer
- Provide a short hint to guide the student

🎯 Output format:
Question: ...
Expected answer: ...
Hint: ...
""".strip()
        else:
            remediation_prompt = f"""
Génère un nouvel exercice de remédiation en mathématiques pour un élève qui a obtenu {etoiles}/5 sur l'exercice précédent.

🧩 Contexte :
- Énoncé initial : {question}
- Réponse de l'élève : {reponse_eleve}
- Note de l'élève : {etoiles}/5

✍️ Consignes :
- Crée un exercice de difficulté équivalente ciblant les mêmes concepts
- Adapte l'exercice pour adresser les difficultés spécifiques montrées dans la réponse de l'élève
- Rédige un énoncé clair
- Donne la réponse attendue
- Fournis un court indice pour aider l'élève

🎯 Format attendu :
Question : ...
Réponse attendue : ...
Indice : ...
""".strip()

        try:
            remediation_completion = client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": remediation_prompt}],
            )
            remediation_content = remediation_completion.choices[0].message.content.strip()
            print("✅ Remédiation générée")
            
            # Création de la suggestion de remédiation
            nouvelle_suggestion = RemediationSuggestion(
                user_id=eleve.id,
                theme=exercice.theme,
                lecon=exercice.lecon.titre_fr if exercice.lecon else "Général",
                message=f"Exercice de remédiation proposé automatiquement (note: {etoiles}/5).",
                exercice_suggere=remediation_content,
                statut="en_attente",
                timestamp=datetime.utcnow()
            )
            db.session.add(nouvelle_suggestion)
            print("✅ Suggestion de remédiation sauvegardée")
            
            # 🆕 IMPORTANT: Autoriser l'accès à l'enseignant virtuel pour cette rémédiation
            session['remediation_access'] = {
                'exercice_id': exercice.id,
                'note': etoiles,
                'access_count': 0,
                'first_access': datetime.utcnow().isoformat()
            }
            print(f"✅ Accès à l'enseignant virtuel autorisé (note: {etoiles}/5)")
            
        except Exception as e:
            print(f"❌ Erreur génération remédiation: {e}")

    # Sauvegarde réponse
    try:
        nouvelle = StudentResponse(
            user_id=eleve.id,
            exercice_id=exercice.id,
            reponse_eleve=reponse_eleve,
            analyse_ia=analyse_ia,
            etoiles=etoiles,
            timestamp=datetime.utcnow()
        )
        db.session.add(nouvelle)
        db.session.commit()
        print("✅ Réponse sauvegardée en base de données")
    except Exception as e:
        print(f"❌ Erreur lors de la sauvegarde: {e}")
        return f"Erreur base de données: {e}", 500

    print("=== ✅ RÉPONSE SAUVEGARDÉE ===")

    # ✅ Afficher la rétroaction au lieu de rediriger
    return render_template(
        "exercice_detail.html",
        exercice=exercice,
        eleve=eleve,
        lang=lang,
        reponse=nouvelle,  # ✅ Rétroaction incluse
        show_feedback=True,  # ✅ Flag pour afficher la rétroaction
        already_completed=True,  # ✅ Marquer comme déjà complété
        show_teacher_button=(etoiles < 3)  # 🆕 Afficher bouton enseignant virtuel si note < 3
    )


from sqlalchemy import func
from sqlalchemy.orm import joinedload

@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    lang = request.args.get("lang") or session.get("lang", "fr")

    # Charger la structure complète du contenu
    niveaux = Niveau.query.options(
        joinedload(Niveau.matieres)
        .joinedload(Matiere.unites)
        .joinedload(Unite.lecons)
        .joinedload(Lecon.exercices)
    ).all()

    # Statistiques principales
    stats = {
        'enseignants_count': Enseignant.query.count(),
        'eleves_count': User.query.filter_by(role="élève").count(),
        'lecons_count': Lecon.query.count(),
        'tests_count': TestSommatif.query.count(),
        'exercices_count': Exercice.query.count(),
        'matieres_count': Matiere.query.count(),
        'unites_count': Unite.query.count(),
        'niveaux_count': Niveau.query.count(),
        'parents_count': Parent.query.count()
    }

    # Nombre d’élèves par niveau (pour le graphique)
    eleves_par_niveau = (
        db.session.query(Niveau.nom, func.count(User.id))
        .join(User, Niveau.id == User.niveau_id)
        .filter(User.role == "élève")
        .group_by(Niveau.nom)
        .all()
    )

    # Debug console
    print(f"✅ DEBUG - Statistiques calculées : {stats}")
    print(f"✅ DEBUG - Élèves par niveau : {eleves_par_niveau}")

    return render_template(
        "admin_dashboard.html",
        niveaux=niveaux,
        stats=stats,
        eleves_par_niveau=eleves_par_niveau,
        lang=lang
    )




@app.route("/admin/tests")
@admin_required
def liste_tests():
    tests = TestSommatif.query.all()
    return render_template("liste_tests.html", tests=tests, lang=session.get("lang", "fr"))

def generer_description_auto(exercice_id):
    """Génère automatiquement les descriptions d'image pour un exercice"""
    exercice = db.session.get(Exercice, exercice_id)
    
    if not exercice or not exercice.chemin_image:
        return False
    
    try:
        prompt = f"""
Tu es un expert en pédagogie. Analyse cet exercice scolaire et génère une description concise de l'image qui aidera une IA à comprendre les éléments visuels importants.

CONTEXTE:
- Question FR: {exercice.question_fr}
- Question EN: {exercice.question_en}
- Thème: {exercice.theme}
- Niveau: {exercice.niveau}

Génère une description concise (1 phrase) qui capture les éléments visuels essentiels pour résoudre l'exercice.

FORMAT EXACT:
DESC_FR: [description en français]
DESC_EN: [description en anglais]
KEYWORDS: [mots-clés en anglais séparés par des virgules]
"""
        
        response = client.chat.completions.create(
            model="gpt-4",  # ou "gpt-3.5-turbo" pour économiser
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.3
        )
        
        content = response.choices[0].message.content.strip()
        
        # Extraction des valeurs
        def extract_value(text, key):
            for line in text.split('\n'):
                if line.startswith(key + ':'):
                    return line.replace(key + ':', '').strip()
            return None
        
        desc_fr = extract_value(content, "DESC_FR")
        desc_en = extract_value(content, "DESC_EN") 
        keywords = extract_value(content, "KEYWORDS")
        
        # Valeurs par défaut si extraction échoue
        if not desc_fr:
            desc_fr = f"Graphique illustrant l'exercice sur {exercice.theme}"
        if not desc_en:
            desc_en = f"Graph illustrating the exercise about {exercice.theme}"
        if not keywords:
            keywords = "math, graph, exercise"
        
        # Mise à jour de l'exercice
        exercice.image_description_fr = desc_fr
        exercice.image_description_en = desc_en
        exercice.image_keywords = keywords
        
        db.session.commit()
        print(f"✅ Description générée pour l'exercice {exercice_id}: {desc_fr[:50]}...")
        return True
        
    except Exception as e:
        print(f"❌ Erreur génération description pour {exercice_id}: {e}")
        # Valeurs par défaut en cas d'erreur
        exercice.image_description_fr = f"Élément visuel pour l'exercice de {exercice.theme}"
        exercice.image_description_en = f"Visual element for {exercice.theme} exercise"
        exercice.image_keywords = "math, visual"
        db.session.commit()
        return False
    
@app.route("/admin/migration-descriptions")
@admin_required
def migration_descriptions():
    """Génère les descriptions pour tous les exercices existants avec images"""
    exercices_avec_images = Exercice.query.filter(
        Exercice.chemin_image.isnot(None)
    ).all()
    
    results = {
        "total": len(exercices_avec_images),
        "success": 0,
        "errors": []
    }
    
    for exercice in exercices_avec_images:
        try:
            if generer_description_auto(exercice.id):
                results["success"] += 1
                print(f"✅ Traité: {exercice.id}")
            else:
                results["errors"].append(f"Exercice {exercice.id}")
        except Exception as e:
            results["errors"].append(f"Exercice {exercice.id}: {e}")
    
    return f"""
    <h1>Migration terminée</h1>
    <p>Total exercices avec images: {results['total']}</p>
    <p>Descriptions générées avec succès: {results['success']}</p>
    <p>Erreurs: {len(results['errors'])}</p>
    <p><a href="/admin/dashboard">Retour au dashboard</a></p>
    """

@app.route("/admin/modifier-exercice/<int:id>", methods=["GET", "POST"])
@admin_required
def modifier_exercice(id):
    exercice = Exercice.query.get_or_404(id)

    if request.method == "POST":
        # Vérifier si une nouvelle image est uploadée
        fichier = request.files.get("image_exercice")
        nouvelle_image = False
        
        if fichier and fichier.filename:
            # 🖼️ Nouvelle image uploadée
            nom_fichier = secure_filename(fichier.filename)
            dossier = os.path.join("static", "uploads", "images")
            os.makedirs(dossier, exist_ok=True)
            chemin_absolu = os.path.join(dossier, nom_fichier)
            fichier.save(chemin_absolu)
            exercice.chemin_image = f"uploads/images/{nom_fichier}"
            nouvelle_image = True

        # Mise à jour des champs texte
        exercice.question_fr = request.form["question_fr"]
        exercice.reponse_fr = request.form["reponse_fr"]
        exercice.explication_fr = request.form.get("explication_fr", "")
        exercice.question_en = request.form["question_en"]
        exercice.reponse_en = request.form["reponse_en"]
        exercice.explication_en = request.form.get("explication_en", "")
        exercice.temps = int(request.form.get("temps", 60))

        db.session.commit()

        # ✅ GÉNÉRATION AUTOMATIQUE SI NOUVELLE IMAGE OU SI DESCRIPTION MANQUANTE
        if nouvelle_image or not exercice.image_description_fr:
            try:
                generer_description_auto(exercice.id)
                print(f"✅ Description (re)générée pour l'exercice {exercice.id}")
            except Exception as e:
                print(f"⚠️ Erreur lors de la génération de la description: {e}")

        flash(
            "✅ Exercice modifié avec succès" if session.get("lang") != "en"
            else "✅ Exercise successfully updated",
            "success"
        )
        return redirect(url_for("visualiser_exercices_lecon", lecon_id=exercice.lecon_id))

    return render_template("modifier_exercice.html", exercice=exercice, lang=session.get("lang", "fr"))


@app.route("/admin/modifier-lecon/<int:id>", methods=["GET", "POST"])
@admin_required
def modifier_lecon(id):
    lecon = Lecon.query.get_or_404(id)
    lang = session.get("lang", "fr")

    if request.method == "POST":
        lecon.titre_fr = request.form["titre_fr"]
        lecon.titre_en = request.form["titre_en"]
        lecon.objectif_fr = request.form["objectif_fr"]
        lecon.objectif_en = request.form["objectif_en"]
        db.session.commit()
        flash("✅ Leçon modifiée avec succès", "success")
        return redirect(url_for("admin_dashboard", lang=lang))

    return render_template("modifier_lecon.html", lecon=lecon, lang=lang)

@app.route("/admin/modifier-test/<int:test_id>", methods=["GET", "POST"])
def modifier_test(test_id):
    test = TestSommatif.query.get_or_404(test_id)
    unites = Unite.query.all()

    if request.method == "POST":
        try:
            # Champs principaux du test
            test.unite_id = request.form["unite_id"]
            test.temps = int(request.form["temps"])
            
            # Fichiers PDF facultatifs
            fichier_pdf = request.files.get("fichier_pdf")
            if fichier_pdf and fichier_pdf.filename:
                filename = secure_filename(fichier_pdf.filename)
                chemin = os.path.join(UPLOAD_FOLDER, filename)
                fichier_pdf.save(chemin)
                test.chemin_fichier = f"uploads/tests/{filename}"

            fichier_corrige = request.files.get("fichier_corrige")
            if fichier_corrige and fichier_corrige.filename:
                filename = secure_filename(fichier_corrige.filename)
                chemin = os.path.join(UPLOAD_FOLDER, filename)
                fichier_corrige.save(chemin)
                test.chemin_corrige = f"uploads/tests/{filename}"

            # Mise à jour des exercices
            total_ex = int(request.form.get("total_ex", 0))
            for i in range(1, total_ex + 1):
                ex_id = request.form.get(f"ex_id_{i}")
                if not ex_id:
                    continue
                    
                ex = TestExercice.query.get(int(ex_id))
                if ex:
                    ex.question_fr = request.form.get(f"question_fr_{i}", "")
                    ex.reponse_fr = request.form.get(f"reponse_fr_{i}", "")
                    ex.explication_fr = request.form.get(f"explication_fr_{i}", "")
                    ex.question_en = request.form.get(f"question_en_{i}", "")
                    ex.reponse_en = request.form.get(f"reponse_en_{i}", "")
                    ex.explication_en = request.form.get(f"explication_en_{i}", "")

            db.session.commit()
            flash("Test modifié avec succès!", "success")
            return redirect(url_for("liste_tests"))
            
        except Exception as e:
            db.session.rollback()
            flash(f"Erreur lors de la modification: {str(e)}", "danger")
            return redirect(url_for("modifier_test", test_id=test_id))

    return render_template("modifier_test.html", test=test, unites=unites, lang=request.args.get('lang', 'fr')) 




@app.route("/admin/modifier-niveau/<int:id>", methods=["GET", "POST"])
@admin_required
def modifier_niveau(id):
    niveau = Niveau.query.get_or_404(id)

    if request.method == "POST":
        niveau.nom = request.form.get("nom")
        db.session.commit()
        flash("✅ Niveau modifié avec succès", "success")
        return redirect("/admin/contenus")

    return render_template("modifier_niveau.html", niveau=niveau)

@app.route("/admin/supprimer-niveau/<int:id>", methods=["POST"])
@admin_required
def supprimer_niveau(id):
    niveau = Niveau.query.get_or_404(id)
    db.session.delete(niveau)
    db.session.commit()
    flash("🗑️ Niveau supprimé", "success")
    return redirect("/admin/contenus")

@app.route("/admin/modifier-matiere/<int:id>", methods=["GET", "POST"])
@admin_required
def modifier_matiere(id):
    matiere = Matiere.query.get_or_404(id)

    if request.method == "POST":
        matiere.nom = request.form.get("nom")
        db.session.commit()
        flash("✅ Matière modifiée", "success")
        # Rediriger vers une route qui existe
        return redirect(url_for("admin_dashboard"))  # Si votre dashboard est sur "/admin"

    return render_template("modifier_matiere.html", matiere=matiere)

@app.route("/admin/supprimer-matiere/<int:id>", methods=["POST"])
@admin_required
def supprimer_matiere(id):
    matiere = Matiere.query.get_or_404(id)
    db.session.delete(matiere)
    db.session.commit()
    flash("🗑️ Matière supprimée", "success")
    # Rediriger vers une route qui existe
    return redirect(url_for("admin_dashboard"))  # Si votre dashboard est sur "/admin"

@app.route("/admin/supprimer-test/<int:test_id>", methods=["POST"])
def supprimer_test(test_id):
    test = TestSommatif.query.get_or_404(test_id)
    db.session.delete(test)
    db.session.commit()
    
    # Si la requête vient d'AJAX, ne fais pas de redirection
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return '', 204  # No Content
    
    return redirect(url_for("liste_tests"))


@app.route("/login-admin", methods=["GET", "POST"])
def login_admin():
    if request.method == "POST":
        email = request.form.get("email")
        mot_de_passe = request.form.get("mot_de_passe")

        # 🔍 Vérifie si un admin existe dans la base
        admin_user = User.query.filter_by(email=email, role="admin").first()
        if admin_user and admin_user.verifier_mot_de_passe(mot_de_passe):
            session["is_admin"] = True
            session["admin_id"] = admin_user.id
            session["admin_nom"] = admin_user.nom_complet
            return redirect("/admin/dashboard")

        return "Identifiants incorrects", 401

    # AJOUT : Récupérer la langue de la session
    lang = session.get('lang', 'fr')
    return render_template("login_admin.html", lang=lang)



@app.route("/admin-enseignants")
@admin_required
def admin_enseignants():
    enseignants = Enseignant.query.options(
        joinedload(Enseignant.eleves).joinedload(User.niveau)
    ).all()
    return render_template("admin_enseignants.html", enseignants=enseignants)

@app.route("/admin/modifier-unite/<int:id>", methods=["GET", "POST"])
@admin_required
def modifier_unite(id):
    unite = Unite.query.get_or_404(id)

    if request.method == "POST":
        unite.nom = request.form.get("nom")
        db.session.commit()
        flash("✅ Unité modifiée", "success")
        return redirect("/admin/contenus")

    return render_template("modifier_unite.html", unite=unite)

@app.route("/admin/supprimer-unite/<int:id>", methods=["POST"])
@admin_required
def supprimer_unite(id):
    unite = Unite.query.get_or_404(id)
    try:
        db.session.delete(unite)
        db.session.commit()
        flash("🗑️ Unité supprimée", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"❌ Erreur : {str(e)}", "danger")
    return redirect(request.referrer or url_for("admin_dashboard"))


@app.route("/admin/modifier-enseignant/<int:enseignant_id>", methods=["GET", "POST"])
@admin_required
def modifier_enseignant_admin(enseignant_id):
    enseignant = Enseignant.query.get_or_404(enseignant_id)

    if request.method == "POST":
        enseignant.nom = request.form.get("nom").strip()
        enseignant.email = request.form.get("email").strip()
        nouveau_mot_de_passe = request.form.get("mot_de_passe")

        if nouveau_mot_de_passe:
            enseignant.mot_de_passe = nouveau_mot_de_passe

        db.session.commit()
        return redirect("/admin-enseignants")

    return render_template("modifier_enseignant.html", enseignant=enseignant)

@app.route("/supprimer-enseignant", methods=["POST"])
@admin_required
def supprimer_enseignant():
    enseignant_id = request.form.get("id")
    enseignant = Enseignant.query.get(enseignant_id)
    if enseignant:
        db.session.delete(enseignant)
        db.session.commit()

    return redirect("/admin-enseignants")

@app.route("/liste-enseignants")
def liste_enseignants():
    enseignants = Enseignant.query.all()
    return render_template("liste_enseignants.html", enseignants=enseignants)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/")
def index():
    try:
        lang = session.get("lang", "fr")
        return render_template("index.html", lang=lang)
    except Exception as e:
        # Fallback en cas d'erreur
        return f"""
        <h1>Bienvenue - Tutorat IA</h1>
        <p>Application en cours de chargement...</p>
        <p><a href="/test-template">Page de test</a></p>
        <p>Erreur: {str(e)}</p>
        """, 500

@app.route("/inscription")
def inscription():
    return render_template("inscription.html")

@app.route("/inscription-enseignant", methods=["GET", "POST"])
@admin_required  # ⬅️ Utilisez le décorateur admin_required au lieu de vérifier session
def inscription_enseignant():
    if request.method == "POST":
        nom = request.form.get("nom")
        email = request.form.get("email")
        mot_de_passe = request.form.get("mot_de_passe")

        if not all([nom, email, mot_de_passe]):
            flash("Tous les champs sont requis", "error")
            return render_template("inscription_enseignant.html")

        # Vérifier si l'email existe déjà
        if Enseignant.query.filter_by(email=email.strip()).first():
            flash("Un enseignant avec cet email existe déjà.", "error")
            return render_template("inscription_enseignant.html")

        # Créer l'enseignant
        enseignant = Enseignant(
            nom=nom.strip(),
            email=email.strip()
        )
        enseignant.mot_de_passe = mot_de_passe  # Utilise le setter pour hacher le mot de passe

        db.session.add(enseignant)
        db.session.commit()

        flash("Enseignant inscrit avec succès !", "success")
        return redirect(url_for("liste_enseignants"))  # Ou vers le dashboard

    return render_template("inscription_enseignant.html")


@app.route("/changer-langue", methods=["POST"])
def changer_langue():
    lang = request.form.get("lang", "fr")
    session["lang"] = lang

    redirect_page = request.form.get("redirect_page")
    username = request.form.get("username")
    lecon_id = request.form.get("lecon_id")
    index = request.form.get("index")

    # 🎯 Redirection spéciale pour exercice séquentiel
    if redirect_page == "exercice_sequentiel_progressif" and username and lecon_id is not None:
        return redirect(url_for("exercice_sequentiel_progressif", username=username, lecon_id=lecon_id, index=index or 0, lang=lang))

    # ✅ Redirection personnalisée
    if redirect_page:
        params = {"lang": lang}
        if username:
            params["username"] = username
        if lecon_id:
            params["lecon_id"] = lecon_id
        if index:
            params["index"] = index

        try:
            return redirect(url_for(redirect_page, **params))
        except Exception as e:
            print("🔁 Redirection échouée :", e)

    # 👩‍🏫 En fonction du rôle en session
    if "enseignant_id" in session:
        return redirect(url_for("dashboard_enseignant", lang=lang))
    elif "eleve_id" in session:
        return redirect(url_for("dashboard_eleve", lang=lang))
    elif "is_admin" in session:
        return redirect(url_for("admin_dashboard", lang=lang))

    # 🏠 Par défaut
    return redirect(url_for("index"))

@app.route("/enseignant/changer-mot-de-passe", methods=["GET", "POST"])
def changer_mot_de_passe_enseignant():
    if "enseignant_id" not in session:
        return redirect("/login-enseignant")

    enseignant = Enseignant.query.get(session["enseignant_id"])

    if request.method == "POST":
        ancien = request.form.get("ancien_mdp")
        nouveau = request.form.get("nouveau_mdp")
        confirmation = request.form.get("confirmation_mdp")

        if not enseignant.check_password(ancien):
            return "Mot de passe actuel incorrect", 403

        if nouveau != confirmation:
            return "Les nouveaux mots de passe ne correspondent pas", 400

        enseignant.set_password(nouveau)
        db.session.commit()
        return "Mot de passe mis à jour avec succès !"

    return render_template("changer_mot_de_passe.html", enseignant=enseignant)

@app.route("/login-parent", methods=["GET", "POST"])
def login_parent():
    if request.method == "POST":
        email = request.form.get("email")
        
        # Vérifier que le parent existe
        parent = Parent.query.filter_by(email=email).first()
        
        if parent:
            # Vérifier qu'il a au moins un enfant
            nb_enfants = ParentEleve.query.filter_by(parent_id=parent.id).count()
            
            if nb_enfants > 0:
                session["parent_email"] = parent.email
                return redirect(url_for("parent_dashboard"))
            else:
                flash("Aucun enfant n'est associé à votre compte", "warning")
        else:
            flash("Aucun compte parent trouvé avec cet email", "error")
    
    # AJOUT : Récupérer la langue de la session
    lang = session.get('lang', 'fr')
    return render_template("login_parent.html", lang=lang)

@app.route("/connexion", methods=["GET", "POST"])
def connexion():
    """Route pour la connexion des utilisateurs"""
    from flask import session, flash, redirect, url_for, request
    
    # Si l'utilisateur est déjà connecté, rediriger selon son rôle
    if session.get('eleve_id'):
        return redirect(url_for('dashboard_eleve'))
    elif session.get('enseignant_id'):
        return redirect(url_for('dashboard_enseignant'))
    elif session.get('is_admin'):
        return redirect(url_for('admin_dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        mot_de_passe = request.form.get('mot_de_passe')
        
        # Chercher l'utilisateur dans la base
        user = User.query.filter_by(email=email).first()
        
        if user and user.verifier_mot_de_passe(mot_de_passe):
            # Connecter selon le rôle
            if user.role == 'élève':
                session['eleve_id'] = user.id
                session['eleve_username'] = user.username
                flash('Connexion réussie!', 'success')
                return redirect(url_for('dashboard_eleve'))
            elif user.role == 'admin':
                session['is_admin'] = True
                session['admin_id'] = user.id
                flash('Connexion admin réussie!', 'success')
                return redirect(url_for('admin_dashboard'))
            else:
                flash('Rôle non reconnu', 'error')
        else:
            flash('Email ou mot de passe incorrect', 'error')
    
    lang = session.get('lang', 'fr')
    return render_template("connexion.html", lang=lang)


@app.route("/inscription-eleve", methods=["GET", "POST"])
def inscription_eleve():
    from forms import InscriptionEleveForm
    from models import Niveau, User, Parent, ParentEleve, db
    from datetime import datetime, timedelta
    
    form = InscriptionEleveForm()
    
    # Remplir les choix de niveau
    niveaux = Niveau.query.all()
    form.niveau.choices = [(n.id, n.nom) for n in niveaux]
    
    if request.method == 'POST' and form.validate_on_submit():
        # Récupérer l'option choisie (trial ou pay_now)
        payment_option = request.form.get('payment_option', 'trial')
        plan_type = request.form.get('plan_type', 'annual')
        
        print(f"📋 Option: {payment_option}, Plan: {plan_type}")
        
        # Vérifier les doublons
        if User.query.filter_by(email=form.email.data).first():
            flash("Cet email est déjà utilisé", "error")
            return render_template("inscription_eleve.html", form=form, lang=session.get('lang', 'fr'))
        
        if User.query.filter_by(username=form.username.data).first():
            flash("Ce nom d'utilisateur est déjà utilisé", "error")
            return render_template("inscription_eleve.html", form=form, lang=session.get('lang', 'fr'))
        
        # Récupérer les données du parent
        parent_nom_complet = request.form.get('parent_nom_complet')
        parent_email = request.form.get('parent_email')
        parent_telephone = request.form.get('parent_telephone')
        parent_telephone2 = request.form.get('parent_telephone2')
        
        # Création de l'élève
        try:
            eleve = User(
                username=form.username.data,
                nom_complet=form.nom_complet.data,
                email=form.email.data,
                niveau_id=form.niveau.data,
                role="élève",
                telephone=form.telephone.data,
                statut="actif",
                statut_paiement="essai_gratuit",  # Par défaut
                inscrit_par_admin=False,
                accepte_cgu=form.accepte_cgu.data,
                date_acceptation_cgu=datetime.now() if form.accepte_cgu.data else None
            )
            
            eleve.mot_de_passe = form.mot_de_passe.data
            
            db.session.add(eleve)
            db.session.flush()  # Pour obtenir l'ID
            
            # Création du parent si les informations sont fournies
            if parent_nom_complet and parent_email:
                parent = Parent.query.filter_by(email=parent_email).first()
                if not parent:
                    parent = Parent(
                        nom_complet=parent_nom_complet,
                        email=parent_email,
                        telephone=parent_telephone,
                        telephone2=parent_telephone2
                    )
                    db.session.add(parent)
                    db.session.flush()
                
                relation_parent_eleve = ParentEleve(
                    parent_id=parent.id,
                    eleve_id=eleve.id
                )
                db.session.add(relation_parent_eleve)
            
            # Option 1: Essai gratuit
            if payment_option == 'trial':
                # Activer l'essai de 1 heure
                eleve.activer_essai_gratuit(1)  # 1 heure au lieu de 48
                eleve.statut_paiement = "essai_gratuit"
                db.session.commit()
                
                # Connexion automatique
                session['eleve_id'] = eleve.id
                session['eleve_username'] = eleve.username
                session['eleve_nom_complet'] = eleve.nom_complet
                session['role'] = 'élève'
                
                lang = session.get('lang', 'fr')
                flash_message = f"✅ Essai gratuit de 1 heure activé ! Profitez de la plateforme." if lang == 'fr' else f"✅ 1-hour free trial activated! Enjoy the platform."
                flash(flash_message, "success")
                
                return redirect(url_for('dashboard_eleve'))
            
            # Option 2: Paiement immédiat
            elif payment_option == 'pay_now':
                # Sauvegarder les infos pour le paiement
                session['pending_plan_type'] = plan_type
                session['pending_eleve_id'] = eleve.id
                session['pending_payment_option'] = payment_option
                
                db.session.commit()
                
                # Rediriger vers Stripe
                try:
                    if not stripe.api_key:
                        raise Exception("Stripe non configuré")
                    
                    # Configuration des plans
                    plan_config = {
                        'weekly': {
                            'amount': 1500,  # 15.00 CAD
                            'description': "Abonnement hebdomadaire - Tutorat intelligent avec enseignant virtuel IA",
                            'product_name': "Forfait Hebdomadaire (15$/semaine)",
                            'interval': 'week'
                        },
                        'monthly': {
                            'amount': 5000,  # 50.00 CAD
                            'description': "Abonnement mensuel - Tutorat intelligent avec enseignant virtuel IA",
                            'product_name': "Forfait Mensuel (50$/mois)",
                            'interval': 'month'
                        },
                        'annual': {
                            'amount': 45000,  # 450.00 CAD
                            'description': "Abonnement annuel - Tutorat intelligent avec enseignant virtuel IA - Économisez 25%",
                            'product_name': "Forfait Annuel (450$/an) - Meilleur rapport",
                            'interval': 'year'
                        }
                    }
                    
                    plan_info = plan_config.get(plan_type, plan_config['annual'])
                    
                    # Traduction si nécessaire
                    lang = session.get('lang', 'fr')
                    if lang == 'fr':
                        if plan_type == 'weekly':
                            plan_info['description'] = "Abonnement hebdomadaire - Tutorat intelligent avec enseignant virtuel IA"
                        elif plan_type == 'monthly':
                            plan_info['description'] = "Abonnement mensuel - Tutorat intelligent avec enseignant virtuel IA"
                        elif plan_type == 'annual':
                            plan_info['description'] = "Abonnement annuel - Tutorat intelligent avec enseignant virtuel IA - Économisez 25%"
                    
                    print(f"💰 Paiement Stripe pour {plan_type}: {plan_info['amount']/100}$ CAD")
                    
                    checkout_session = stripe.checkout.Session.create(
                        payment_method_types=['card'],
                        line_items=[{
                            'price_data': {
                                'currency': 'cad',
                                'product_data': {
                                    'name': plan_info['product_name'],
                                    'description': plan_info['description'],
                                    'metadata': {
                                        'plan_type': plan_type,
                                        'lang': lang
                                    }
                                },
                                'unit_amount': plan_info['amount'],
                                'recurring': {
                                    'interval': plan_info.get('interval', 'year'),
                                    'interval_count': 1
                                }
                            },
                            'quantity': 1,
                        }],
                        mode='subscription',
                        subscription_data={
                            'metadata': {
                                'eleve_id': eleve.id,
                                'plan_type': plan_type,
                                'lang': lang
                            }
                        },
                        success_url=url_for('paiement_success', _external=True) + f'?session_id={{CHECKOUT_SESSION_ID}}&eleve_id={eleve.id}&plan_type={plan_type}',
                        cancel_url=url_for('inscription_eleve', _external=True) + f'?cancel=true',
                        customer_email=form.email.data,
                        metadata={
                            'eleve_id': eleve.id,
                            'plan_type': plan_type,
                            'lang': lang,
                            'type': f'abonnement_{plan_type}'
                        },
                        allow_promotion_codes=True,
                        billing_address_collection='required',
                        phone_number_collection={
                            'enabled': True
                        }
                    )
                    
                    print(f"🔗 Redirection vers Stripe pour paiement immédiat")
                    return redirect(checkout_session.url)
                    
                except Exception as e:
                    print(f"❌ Erreur Stripe: {e}")
                    traceback.print_exc()
                    
                    # En cas d'erreur Stripe, offrir l'essai gratuit de secours
                    eleve.activer_essai_gratuit(1)
                    eleve.statut_paiement = "essai_gratuit"
                    db.session.commit()
                    
                    session['eleve_id'] = eleve.id
                    session['eleve_username'] = eleve.username
                    session['eleve_nom_complet'] = eleve.nom_complet
                    session['role'] = 'élève'
                    
                    # Nettoyer les sessions
                    session.pop('pending_plan_type', None)
                    session.pop('pending_eleve_id', None)
                    session.pop('pending_payment_option', None)
                    
                    lang = session.get('lang', 'fr')
                    flash_message = f"⚠️ Paiement temporairement indisponible. Essai gratuit de 1 heure activé." if lang == 'fr' else f"⚠️ Payment temporarily unavailable. 1-hour free trial activated."
                    flash(flash_message, "warning")
                    
                    return redirect(url_for('dashboard_eleve'))
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Erreur création élève/parent: {e}")
            traceback.print_exc()
            
            error_message = "Une erreur est survenue lors de la création du compte" if session.get('lang', 'fr') == 'fr' else "An error occurred while creating your account"
            flash(error_message, "error")
    
    # Afficher un message d'annulation si l'utilisateur revient de Stripe
    if request.args.get('cancel') == 'true':
        cancel_message = "Paiement annulé. Vous pouvez réessayer ou choisir l'essai gratuit." if session.get('lang', 'fr') == 'fr' else "Payment cancelled. You can try again or choose the free trial."
        flash(cancel_message, "warning")
    
    lang = session.get('lang', 'fr')
    return render_template("inscription_eleve.html", form=form, lang=lang)

@app.route("/upgrade-options")
def upgrade_options():
    if "eleve_id" not in session:
        return redirect(url_for("login_eleve"))
    
    eleve = User.query.get(session["eleve_id"])
    if not eleve or eleve.role != "élève":
        return redirect(url_for("login_eleve"))
    
    lang = session.get("lang", "fr")
    
    return render_template("upgrade_options.html", eleve=eleve, lang=lang)

@app.route("/creer-session-paiement", methods=["POST"])
def creer_session_paiement():
    if "eleve_id" not in session:
        return jsonify({"error": "Non authentifié"}), 401
    
    eleve = User.query.get(session["eleve_id"])
    if not eleve or eleve.role != "élève":
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        # Récupérer le type de plan depuis le formulaire
        data = request.get_json()
        plan_type = data.get('plan_type', 'annual')  # weekly, monthly, quarterly, annual
        
        # CONFIGURATION DES PLANS - AJOUT DE QUARTERLY
        plan_config = {
            'weekly': {
                'amount': 1500,  # 15.00 CAD
                'description_fr': "Forfait hebdomadaire - Tutorat intelligent avec enseignant virtuel IA",
                'description_en': "Weekly plan - Intelligent tutoring with AI virtual teacher",
                'product_name_fr': "Forfait Hebdomadaire (15$/semaine)",
                'product_name_en': "Weekly Plan (15$/week)",
                'interval': 'week'
            },
            'monthly': {
                'amount': 5000,  # 50.00 CAD
                'description_fr': "Forfait mensuel - Tutorat intelligent avec enseignant virtuel IA",
                'description_en': "Monthly plan - Intelligent tutoring with AI virtual teacher",
                'product_name_fr': "Forfait Mensuel (50$/mois)",
                'product_name_en': "Monthly Plan (50$/month)",
                'interval': 'month'
            },
            'quarterly': {
                'amount': 12000,  # 120.00 CAD (40$/mois)
                'description_fr': "Forfait trimestriel - Tutorat intelligent avec enseignant virtuel IA - Économisez 20%",
                'description_en': "Quarterly plan - Intelligent tutoring with AI virtual teacher - Save 20%",
                'product_name_fr': "Forfait Trimestriel (120$/3 mois)",
                'product_name_en': "Quarterly Plan (120$/3 months)",
                'interval': 'month',
                'interval_count': 3
            },
            'annual': {
                'amount': 45000,  # 450.00 CAD
                'description_fr': "Forfait annuel - Tutorat intelligent avec enseignant virtuel IA - Économisez 25%",
                'description_en': "Annual plan - Intelligent tutoring with AI virtual teacher - Save 25%",
                'product_name_fr': "Forfait Annuel (450$/an) - Meilleur rapport",
                'product_name_en': "Annual Plan (450$/year) - Best value",
                'interval': 'year'
            }
        }
        
        # Vérifier si le type de plan existe
        if plan_type not in plan_config:
            return jsonify({"error": "Type de plan invalide"}), 400
        
        plan_info = plan_config[plan_type]
        lang = session.get("lang", "fr")
        
        # Sélectionner les textes selon la langue
        product_name = plan_info[f'product_name_{lang}'] if f'product_name_{lang}' in plan_info else plan_info['product_name_fr']
        description = plan_info[f'description_{lang}'] if f'description_{lang}' in plan_info else plan_info['description_fr']
        
        # Configurer le recurring (spécial pour quarterly)
        recurring_config = {
            'interval': plan_info['interval'],
            'interval_count': plan_info.get('interval_count', 1)
        }
        
        # Créer une session de paiement Stripe
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'cad',
                    'product_data': {
                        'name': product_name,
                        'description': description,
                        'metadata': {
                            'plan_type': plan_type,
                            'lang': lang
                        }
                    },
                    'unit_amount': plan_info['amount'],
                    'recurring': recurring_config
                },
                'quantity': 1,
            }],
            mode='subscription',
            subscription_data={
                'metadata': {
                    'eleve_id': eleve.id,
                    'plan_type': plan_type,
                    'lang': lang
                }
            },
            success_url=url_for('paiement_success', _external=True) + f'?session_id={{CHECKOUT_SESSION_ID}}&eleve_id={eleve.id}&plan_type={plan_type}',
            cancel_url=url_for('upgrade_options', _external=True) + '?cancel=true',
            customer_email=eleve.email,
            metadata={
                'eleve_id': eleve.id,
                'plan_type': plan_type,
                'lang': lang,
                'type': f'abonnement_{plan_type}'
            },
            allow_promotion_codes=True,
            billing_address_collection='required',
            phone_number_collection={'enabled': True}
        )
        
        # Retourner l'URL de la session Stripe
        return jsonify({
            "session_id": checkout_session.id,
            "session_url": checkout_session.url,
            "plan_type": plan_type,
            "amount": plan_info['amount']
        })
        
    except Exception as e:
        print(f"❌ Erreur création session Stripe: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    
@app.route("/paiement-direct")
def paiement_direct():
    if "eleve_id" not in session:
        return redirect(url_for("login_eleve"))
    
    eleve = User.query.get(session["eleve_id"])
    if not eleve or eleve.role != "élève":
        return redirect(url_for("login_eleve"))
    
    plan_type = request.args.get("type", "annual")
    print(f"📋 Paiement direct - Plan demandé: {plan_type}")
    
    # Vérifier si le type de plan est valide
    valid_plans = ['weekly', 'monthly', 'quarterly', 'annual']
    if plan_type not in valid_plans:
        plan_type = 'annual'  # Fallback au plan annuel
    
    try:
        # CONFIGURATION DES PLANS - AJOUT DE QUARTERLY
        plan_config = {
            'weekly': {
                'amount': 1500,  # 15.00 CAD
                'description_fr': "Forfait hebdomadaire - Tutorat intelligent avec enseignant virtuel IA",
                'description_en': "Weekly plan - Intelligent tutoring with AI virtual teacher",
                'product_name_fr': "Forfait Hebdomadaire (15$/semaine)",
                'product_name_en': "Weekly Plan (15$/week)",
                'interval': 'week'
            },
            'monthly': {
                'amount': 5000,  # 50.00 CAD
                'description_fr': "Forfait mensuel - Tutorat intelligent avec enseignant virtuel IA",
                'description_en': "Monthly plan - Intelligent tutoring with AI virtual teacher",
                'product_name_fr': "Forfait Mensuel (50$/mois)",
                'product_name_en': "Monthly Plan (50$/month)",
                'interval': 'month'
            },
            'quarterly': {
                'amount': 12000,  # 120.00 CAD (40$/mois)
                'description_fr': "Forfait trimestriel - Tutorat intelligent avec enseignant virtuel IA - Économisez 20%",
                'description_en': "Quarterly plan - Intelligent tutoring with AI virtual teacher - Save 20%",
                'product_name_fr': "Forfait Trimestriel (120$/3 mois)",
                'product_name_en': "Quarterly Plan (120$/3 months)",
                'interval': 'month',
                'interval_count': 3
            },
            'annual': {
                'amount': 45000,  # 450.00 CAD
                'description_fr': "Forfait annuel - Tutorat intelligent avec enseignant virtuel IA - Économisez 25%",
                'description_en': "Annual plan - Intelligent tutoring with AI virtual teacher - Save 25%",
                'product_name_fr': "Forfait Annuel (450$/an) - Meilleur rapport",
                'product_name_en': "Annual Plan (450$/year) - Best value",
                'interval': 'year'
            }
        }
        
        plan_info = plan_config[plan_type]
        lang = session.get("lang", "fr")
        
        # Sélectionner les textes selon la langue
        product_name = plan_info[f'product_name_{lang}'] if f'product_name_{lang}' in plan_info else plan_info['product_name_fr']
        description = plan_info[f'description_{lang}'] if f'description_{lang}' in plan_info else plan_info['description_fr']
        
        print(f"💰 Paiement direct - Montant pour {plan_type}: {plan_info['amount']/100}$ CAD")
        
        # Configurer le recurring (spécial pour quarterly)
        recurring_config = {
            'interval': plan_info['interval'],
            'interval_count': plan_info.get('interval_count', 1)
        }
        
        # Créer une session de paiement Stripe
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'cad',
                    'product_data': {
                        'name': product_name,
                        'description': description,
                        'metadata': {
                            'plan_type': plan_type,
                            'lang': lang
                        }
                    },
                    'unit_amount': plan_info['amount'],
                    'recurring': recurring_config
                },
                'quantity': 1,
            }],
            mode='subscription',
            subscription_data={
                'metadata': {
                    'eleve_id': eleve.id,
                    'plan_type': plan_type,
                    'lang': lang
                }
            },
            success_url=url_for('paiement_success', _external=True) + f'?session_id={{CHECKOUT_SESSION_ID}}&eleve_id={eleve.id}&plan_type={plan_type}',
            cancel_url=url_for('upgrade_options', _external=True) + '?cancel=true',
            customer_email=eleve.email,
            metadata={
                'eleve_id': eleve.id,
                'plan_type': plan_type,
                'lang': lang,
                'type': f'abonnement_{plan_type}'
            },
            allow_promotion_codes=True,
            billing_address_collection='required',
            phone_number_collection={'enabled': True}
        )
        
        # Redirection directe vers Stripe
        return redirect(checkout_session.url)
        
    except Exception as e:
        print(f"❌ Erreur paiement direct: {e}")
        import traceback
        traceback.print_exc()
        
        error_msg = "Erreur lors de la création du paiement" if session.get('lang', 'fr') == 'fr' else "Error creating payment"
        flash(error_msg, "error")
        return redirect(url_for('upgrade_options'))
    

@app.route("/paiement-success")
def paiement_success():
    try:
        session_id = request.args.get('session_id')
        eleve_id = request.args.get('eleve_id')
        plan_type = request.args.get('plan_type', 'annual')
        
        if not session_id or not eleve_id:
            flash("Paramètres de paiement manquants", "error")
            return redirect(url_for('inscription_eleve'))
        
        # Vérifier la session Stripe
        stripe_session = stripe.checkout.Session.retrieve(session_id)
        
        if stripe_session.payment_status == 'paid' or stripe_session.mode == 'subscription':
            # Activer le compte élève
            eleve = User.query.get(eleve_id)
            if eleve:
                # Déterminer la durée de l'abonnement selon le plan (AJOUT DE QUARTERLY)
                plan_durations = {
                    'weekly': 7,      # 7 jours
                    'monthly': 30,    # 30 jours
                    'quarterly': 90,  # 90 jours (3 mois)
                    'annual': 365     # 365 jours
                }
                duration_days = plan_durations.get(plan_type, 365)
                
                # Utiliser votre méthode existante sans modification
                eleve.marquer_comme_paye(
                    stripe_session_id=session_id,
                    stripe_payment_intent=stripe_session.payment_intent
                )
                
                # Ajouter la date de fin d'abonnement
                from datetime import datetime, timedelta
                eleve.date_fin_abonnement = datetime.utcnow() + timedelta(days=duration_days)
                
                # Stocker le type de plan dans les métadonnées existantes
                # Pas besoin d'ajouter type_plan au modèle
                
                from models import db
                db.session.commit()
                
                # Connexion automatique
                session['eleve_id'] = eleve.id
                session['eleve_username'] = eleve.username
                session['eleve_nom_complet'] = eleve.nom_complet
                
                # Messages de succès selon la langue (AJOUT DE QUARTERLY)
                lang = session.get('lang', 'fr')
                success_messages = {
                    'weekly': {
                        'fr': "✅ Paiement confirmé ! Votre abonnement hebdomadaire (15$/semaine) est activé.",
                        'en': "✅ Payment confirmed! Your weekly subscription (15$/week) is activated."
                    },
                    'monthly': {
                        'fr': "✅ Paiement confirmé ! Votre abonnement mensuel (50$/mois) est activé.",
                        'en': "✅ Payment confirmed! Your monthly subscription (50$/month) is activated."
                    },
                    'quarterly': {
                        'fr': "✅ Paiement confirmé ! Votre abonnement trimestriel (120$/3 mois) est activé pour 3 mois.",
                        'en': "✅ Payment confirmed! Your quarterly subscription (120$/3 months) is activated for 3 months."
                    },
                    'annual': {
                        'fr': "✅ Paiement confirmé ! Votre abonnement annuel (450$/an) est activé pour 1 an.",
                        'en': "✅ Payment confirmed! Your annual subscription (450$/year) is activated for 1 year."
                    }
                }
                
                message = success_messages.get(plan_type, success_messages['annual']).get(lang, success_messages['annual']['fr'])
                flash(message, "success")
                
                return redirect(url_for('dashboard_eleve'))
            else:
                flash("Élève non trouvé", "error")
        else:
            flash("Paiement non confirmé", "error")
            
    except Exception as e:
        print(f"❌ Erreur confirmation paiement: {e}")
        import traceback
        traceback.print_exc()
        
        error_msg = "Erreur lors de la confirmation du paiement" if session.get('lang', 'fr') == 'fr' else "Error confirming payment"
        flash(error_msg, "error")
    
    return redirect(url_for('inscription_eleve'))

@app.route("/paiement-cancel")
def paiement_cancel():
    """Page d'annulation de paiement Stripe"""
    try:
        eleve_id = request.args.get('eleve_id')
        plan_type = request.args.get('plan_type', 'annual')
        
        print(f"❌ Paiement annulé - Élève: {eleve_id}, Plan: {plan_type}")
        
        if eleve_id:
            from models import User, db
            eleve = User.query.get(eleve_id)
            if eleve:
                # Ne pas supprimer l'élève, mais laisser l'essai gratuit actif
                if eleve.statut_paiement == "essai_gratuit":
                    print(f"⚠️ Essai gratuit maintenu pour l'élève {eleve_id}")
                else:
                    print(f"ℹ️ Paiement annulé pour l'élève {eleve_id}")
        
        # Message d'annulation selon la langue
        lang = session.get('lang', 'fr')
        cancel_messages = {
            'fr': "Paiement annulé. Votre essai gratuit reste actif. Vous pouvez réessayer quand vous voulez.",
            'en': "Payment cancelled. Your free trial remains active. You can try again whenever you want."
        }
        
        flash(cancel_messages.get(lang, cancel_messages['fr']), "info")
        
    except Exception as e:
        print(f"❌ Erreur annulation: {e}")
        import traceback
        traceback.print_exc()
        
        # Message d'erreur
        error_msg = "Erreur lors de l'annulation" if session.get('lang', 'fr') == 'fr' else "Error during cancellation"
        flash(error_msg, "error")
    
    return redirect(url_for('upgrade_options'))

@app.route('/admin/inscrire-eleve', methods=['GET', 'POST'])
def admin_inscrire_eleve():
    from forms import InscriptionEleveAdminForm  # ✅ Formulaire AVEC parent
    from models import Niveau, Enseignant, User, db, Parent, ParentEleve
    from datetime import datetime
    
    form = InscriptionEleveAdminForm()
    
    # Remplir les choix dynamiques
    niveaux = Niveau.query.all()
    enseignants = Enseignant.query.all()
    
    # ✅ CORRECTION : Enlever "(0, 'Aucun')" car le niveau est maintenant obligatoire
    form.niveau_id.choices = [(n.id, n.nom) for n in niveaux]
    form.enseignant_id.choices = [(0, 'Aucun')] + [(e.id, e.nom) for e in enseignants]
    
    if form.validate_on_submit():
        try:
            # =====================
            # 1. CRÉATION DE L'ÉLÈVE
            # =====================
            user = User(
                username=form.username.data,
                email=form.email.data,
                nom_complet=form.nom_complet.data,
                role='élève',
                # Informations personnelles
                telephone=form.telephone.data,
                adresse=form.adresse.data,
                ville=form.ville.data,
                province=form.province.data,
                code_postal=form.code_postal.data,
                date_naissance=form.date_naissance.data,
                # Statuts et vérifications
                statut=form.statut.data,
                statut_paiement=form.statut_paiement.data,
                email_verifie=form.email_verifie.data,
                telephone_verifie=form.telephone_verifie.data,
                accepte_cgu=form.accepte_cgu.data,
                date_acceptation_cgu=datetime.now() if form.accepte_cgu.data else None,
                inscrit_par_admin=True,
                # Relations pédagogiques (OBLIGATOIRE maintenant)
                niveau_id=form.niveau_id.data
            )
            
            # Définir le mot de passe
            user.mot_de_passe = form.mot_de_passe.data
            
            # Assigner l'enseignant si sélectionné
            if form.enseignant_id.data and form.enseignant_id.data != 0:
                user.enseignant_id = form.enseignant_id.data
            
            db.session.add(user)
            db.session.flush()  # Pour obtenir l'ID de l'user
            
            # =====================
            # 2. CRÉATION/GESTION DU PARENT (SEULEMENT en ADMIN)
            # =====================
            parent = Parent.query.filter_by(email=form.parent_email.data).first()
            
            if not parent:
                # Créer un nouveau parent
                parent = Parent(
                    nom_complet=form.responsable_nom.data,
                    email=form.parent_email.data,
                    telephone=form.responsable_telephone.data
                )
                db.session.add(parent)
                db.session.flush()  # Pour obtenir l'ID du parent
            
            # =====================
            # 3. LIEN PARENT-ÉLÈVE (SEULEMENT en ADMIN)
            # =====================
            parent_eleve = ParentEleve(
                parent_id=parent.id,
                eleve_id=user.id
            )
            db.session.add(parent_eleve)
            
            # =====================
            # 4. FINALISATION
            # =====================
            db.session.commit()
            
            flash('Élève inscrit avec succès!', 'success')
            return redirect(url_for('admin_dashboard'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de l\'inscription: {str(e)}', 'error')
    
    lang = session.get('lang', 'fr')
    return render_template("admin_inscrire_eleve.html", form=form, lang=lang)


@app.route("/changer-mot-de-passe", methods=["GET", "POST"])
def changer_mot_de_passe():
    if "enseignant_id" not in session:
        return redirect("/login-enseignant")

    enseignant = Enseignant.query.get(session["enseignant_id"])

    if request.method == "POST":
        ancien = request.form.get("ancien_mdp")
        nouveau = request.form.get("nouveau_mdp")
        confirmation = request.form.get("confirmation_mdp")

        if not enseignant.verifier_mot_de_passe(ancien):
            flash("Mot de passe actuel incorrect.", "erreur")
        elif nouveau != confirmation:
            flash("Les nouveaux mots de passe ne correspondent pas.", "erreur")
        else:
            enseignant.mot_de_passe = nouveau
            db.session.commit()
            flash("Mot de passe mis à jour avec succès.", "succès")

    return render_template("changer_mot_de_passe.html")

@app.route("/enseignant/modifier-profil", methods=["GET", "POST"])
def modifier_profil_enseignant():
    if "enseignant_id" not in session:
        return redirect("/login-enseignant")

    enseignant = Enseignant.query.get(session["enseignant_id"])

    if request.method == "POST":
        nom = request.form.get("nom")
        email = request.form.get("email")

        if not nom or not email:
            return "Champs obligatoires manquants", 400

        existant = Enseignant.query.filter_by(email=email).first()
        if existant and existant.id != enseignant.id:
            return "Cet email est déjà utilisé", 409

        enseignant.nom = nom
        enseignant.email = email
        db.session.commit()
        return redirect("/dashboard-enseignant")

    return render_template("modifier_profil_enseignant.html", enseignant=enseignant, lang=session.get("lang", "fr"))


@app.route("/enseignant/creer-contenu")
def creer_contenu():
    if "enseignant_id" not in session:
        return redirect("/login-enseignant")
    
    lang = session.get("lang", "fr")
    enseignant = Enseignant.query.get(session["enseignant_id"])
    
    return render_template(
        "enseignant_creer_contenu.html",
        enseignant=enseignant,
        lang=lang
    )

@app.route("/enseignant/eleves")
def enseignant_eleves():
    if "enseignant_id" not in session:
        return redirect("/login-enseignant")
    
    lang = session.get("lang", "fr")
    enseignant_id = session["enseignant_id"]
    
    # Récupérer les élèves de cet enseignant
    eleves = User.query.filter_by(
        enseignant_id=enseignant_id, 
        role="élève"
    ).options(
        joinedload(User.niveau)
    ).all()
    
    # Calculer les statistiques pour chaque élève
    stats_eleves = []
    for eleve in eleves:
        reponses = StudentResponse.query.filter_by(user_id=eleve.id).all()
        total_reponses = len(reponses)
        moyenne = round(sum(r.etoiles or 0 for r in reponses) / total_reponses, 2) if total_reponses else 0
        
        stats_eleves.append({
            'eleve': eleve,
            'total_exercices': total_reponses,
            'moyenne_etoiles': moyenne,
            'niveau': eleve.niveau.nom if eleve.niveau else "Non défini"
        })
    
    enseignant = Enseignant.query.get(enseignant_id)
    
    return render_template(
        "enseignant_eleves.html",
        enseignant=enseignant,
        stats_eleves=stats_eleves,
        lang=lang
    )


@app.route("/enseignant/remediations-en-attente")
def remediations_en_attente():
    if "enseignant_id" not in session:
        return redirect("/login-enseignant")

    suggestions = RemediationSuggestion.query \
        .join(User, User.id == RemediationSuggestion.user_id) \
        .filter(RemediationSuggestion.statut == "en_attente") \
        .filter(User.enseignant_id == session["enseignant_id"]) \
        .all()

    return render_template("remediations_en_attente.html", suggestions=suggestions)

@app.route("/enseignant/valider-remediation/<int:remediation_id>", methods=["GET", "POST"])
def valider_remediation(remediation_id):
    if "enseignant_id" not in session:
        return redirect(url_for("login_enseignant"))

    lang = request.args.get("lang", "fr")
    suggestion = RemediationSuggestion.query.get_or_404(remediation_id)

    if request.method == "POST":
        # Récupérer les données du formulaire
        message = request.form.get("message")
        question = request.form.get("question")
        reponse = request.form.get("reponse")
        explication = request.form.get("explication")

        # Reconstruire le bloc texte de l'exercice suggéré
        if lang == "en":
            bloc = f"""Remediation:\n- Question: {question}\n- Expected answer: {reponse}\n- Explanation: {explication}"""
        else:
            bloc = f"""Remédiation :\n- Question : {question}\n- Réponse attendue : {reponse}\n- Explication : {explication}"""

        # Mettre à jour la suggestion
        suggestion.message = message
        suggestion.exercice_suggere = bloc
        suggestion.statut = "valide"
        db.session.commit()

        return redirect(url_for("remediations_a_valider", lang=lang))

    # 🧠 Pré-remplir les champs si possible
    import re

    exercice_suggere = suggestion.exercice_suggere or ""

    if lang == "en":
        question_match = re.search(r"Question\s*[:：]\s*(.*)", exercice_suggere)
        reponse_match = re.search(r"Expected answer\s*[:：]\s*(.*)", exercice_suggere)
        explication_match = re.search(r"Explanation\s*[:：]\s*(.*)", exercice_suggere)
    else:
        question_match = re.search(r"Question\s*[:：]\s*(.*)", exercice_suggere)
        reponse_match = re.search(r"Réponse attendue\s*[:：]\s*(.*)", exercice_suggere)
        explication_match = re.search(r"Explication\s*[:：]\s*(.*)", exercice_suggere)

    question_text = question_match.group(1).strip() if question_match else ""
    reponse_text = reponse_match.group(1).strip() if reponse_match else ""
    explication_text = explication_match.group(1).strip() if explication_match else ""

    return render_template(
        "valider_remediation.html",
        suggestion=suggestion,
        lang=lang,
        question=question_text,
        reponse=reponse_text,
        explication=explication_text
    )




@app.route("/enseignant/remediations-a-valider", methods=["GET"])
def remediations_a_valider():
    if "enseignant_id" not in session:
        return redirect("/login-enseignant")

    enseignant_id = session["enseignant_id"]
    niveau_filtre = request.args.get("niveau")
    statut_filtre = request.args.get("statut", "en_attente")  # Nouveau filtre par statut

    query = RemediationSuggestion.query \
        .join(User, RemediationSuggestion.user_id == User.id) \
        .options(joinedload(RemediationSuggestion.user).joinedload(User.niveau)) \
        .filter(User.enseignant_id == enseignant_id)

    if niveau_filtre:
        query = query.filter(User.niveau.has(nom=niveau_filtre))
    
    if statut_filtre != "tous":
        query = query.filter(RemediationSuggestion.statut == statut_filtre)
    else:
        # Si "tous", on montre tous les statuts sauf supprimés
        query = query.filter(RemediationSuggestion.statut != "supprime")

    suggestions = query.order_by(RemediationSuggestion.timestamp.desc()).all()

    # Pour la liste déroulante des niveaux disponibles
    niveaux = db.session.query(Niveau.nom).distinct().all()
    
    # Liste des statuts possibles
    statuts = ["en_attente", "valide", "tous"]

    return render_template(
        "enseignant_remediations_validation.html",
        suggestions=suggestions,
        niveaux=[n[0] for n in niveaux],
        niveau_filtre=niveau_filtre,
        statut_filtre=statut_filtre,
        statuts=statuts
    )

@app.route("/enseignant/remediation/<int:remediation_id>")
def view_remediation(remediation_id):
    if "enseignant_id" not in session:
        return redirect(url_for("login_enseignant"))

    lang = request.args.get("lang", "fr")
    suggestion = RemediationSuggestion.query.get_or_404(remediation_id)
    
    # Vérifier que cette remédiation appartient bien à un élève de cet enseignant
    if suggestion.user.enseignant_id != session["enseignant_id"]:
        return redirect(url_for("remediations_a_valider", lang=lang))
    
    # Parser le contenu de l'exercice suggéré
    import re
    
    exercice_suggere = suggestion.exercice_suggere or ""
    if lang == "en":
        question_match = re.search(r"Question\s*[:：]\s*(.*)", exercice_suggere)
        reponse_match = re.search(r"Expected answer\s*[:：]\s*(.*)", exercice_suggere)
        explication_match = re.search(r"Explanation\s*[:：]\s*(.*)", exercice_suggere)
    else:
        question_match = re.search(r"Question\s*[:：]\s*(.*)", exercice_suggere)
        reponse_match = re.search(r"Réponse attendue\s*[:：]\s*(.*)", exercice_suggere)
        explication_match = re.search(r"Explication\s*[:：]\s*(.*)", exercice_suggere)

    question_text = question_match.group(1).strip() if question_match else ""
    reponse_text = reponse_match.group(1).strip() if reponse_match else ""
    explication_text = explication_match.group(1).strip() if explication_match else ""
    
    return render_template(
        "view_remediation.html",
        suggestion=suggestion,
        lang=lang,
        question=question_text,
        reponse=reponse_text,
        explication=explication_text
    )

@app.route("/lecon/<int:lecon_id>")
def afficher_lecon(lecon_id):
    lang = request.args.get("lang", "fr")
    username = request.args.get("username")  # ✅ récupéré depuis l’URL

    lecon = Lecon.query.get_or_404(lecon_id)

    return render_template(
        "lecon_detail.html",
        lecon=lecon,
        lang=lang,
        username=username  # ✅ transmis au template
    )

@app.route("/admin-auth", methods=["GET", "POST"])
def admin_auth():
    if request.method == "POST":
        code = request.form.get("code")
        if code == os.getenv("ADMIN_SECRET"):
            session["admin_auth"] = True
            return redirect("/inscription-enseignant")
        return "Code incorrect", 403

    return '''
        <form method="POST">
            <input type="password" name="code" placeholder="Code admin">
            <button type="submit">Accéder</button>
        </form>
    '''

@app.route("/login-enseignant", methods=["GET", "POST"])
def login_enseignant():
    lang = session.get("lang", "fr")
    if request.method == "POST":
        email = request.form.get("email")
        mot_de_passe = request.form.get("mot_de_passe")
        enseignant = Enseignant.query.filter_by(email=email).first()

        if enseignant and enseignant.verifier_mot_de_passe(mot_de_passe):
            session["enseignant_id"] = enseignant.id
            return redirect(url_for("dashboard_enseignant"))
        else:
            return "Identifiants incorrects", 401

    return render_template("login_enseignant.html", lang=lang)

@app.route("/dashboard-enseignant", methods=["GET", "POST"])
def dashboard_enseignant():
    enseignant_id = session.get("enseignant_id")
    if not enseignant_id:
        return redirect(url_for("login_enseignant"))

    if request.method == "POST":
        selected_lang = request.form.get("lang")
        if selected_lang in ["fr", "en"]:
            session["lang"] = selected_lang
        return redirect(url_for("dashboard_enseignant"))

    lang = session.get("lang", "fr")
    enseignant = Enseignant.query.get(enseignant_id)
    if not enseignant:
        return redirect(url_for("login_enseignant"))

    # Charger les élèves avec la relation niveau déjà jointe
    eleves = User.query.options(joinedload(User.niveau))\
        .filter_by(role="élève", enseignant_id=enseignant.id).all()

    # 🔥 CORRECTION : Calcul des statistiques pour les cartes
    total_students = len(eleves)
    
    # Nombre total de leçons (toutes les leçons de la plateforme)
    total_lessons = Lecon.query.count()
    
    # 🔥 CORRECTION : Moyenne des étoiles de TOUS les élèves
    all_stars = []
    for eleve in eleves:
        reponses = StudentResponse.query.filter_by(user_id=eleve.id).all()
        if reponses:
            # Filtrer les étoiles non nulles
            etoiles_vals = [r.etoiles for r in reponses if r.etoiles is not None]
            if etoiles_vals:
                moyenne_eleve = sum(etoiles_vals) / len(etoiles_vals)
                all_stars.append(moyenne_eleve)
    
    avg_stars = round(sum(all_stars) / len(all_stars), 1) if all_stars else 0

    stats = []
    noms_eleves = []
    moyennes = []
    niveau_counts = {}

    for eleve in eleves:
        reponses = StudentResponse.query.filter_by(user_id=eleve.id).all()
        # 🔥 CORRECTION : Filtrer les étoiles non nulles
        etoiles_vals = [r.etoiles for r in reponses if r.etoiles is not None]
        total = len(etoiles_vals)
        moyenne = round(sum(etoiles_vals) / total, 2) if total else 0
        nom_niveau = eleve.niveau.nom if eleve.niveau else "Non défini"
        
        stats.append({
            "nom": eleve.nom_complet,
            "username": eleve.username,
            "niveau": nom_niveau,
            "moyenne": moyenne,
            "total": total
        })
        noms_eleves.append(eleve.nom_complet)
        moyennes.append(moyenne)
        niveau_counts[nom_niveau] = niveau_counts.get(nom_niveau, 0) + 1

    niveaux = list(niveau_counts.keys())
    counts = list(niveau_counts.values())

    # ✅ Compter les remédiations non encore vues
    nv_count = RemediationSuggestion.query \
    .join(User, RemediationSuggestion.user_id == User.id) \
    .filter(User.enseignant_id == enseignant_id) \
    .filter(RemediationSuggestion.statut == "en_attente") \
    .count()

    return render_template(
        "dashboard_enseignant.html",
        enseignant=enseignant,
        stats=stats,
        noms_eleves=noms_eleves,
        moyennes=moyennes,
        niveaux=niveaux,
        counts=counts,
        lang=lang,
        nv_count=nv_count,
        # 🔥 AJOUT : Passer les nouvelles statistiques au template
        total_students=total_students,
        total_lessons=total_lessons,
        avg_stars=avg_stars
    )


@app.route("/logout-parent")
def logout_parent():
    session.pop("parent_email", None)
    flash("Vous avez été déconnecté avec succès", "success")
    return redirect(url_for("login_parent"))

from flask import make_response, session, request
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from io import BytesIO
from datetime import datetime

def get_pdf_texts(lang):
    """Retourne les textes dans la langue appropriée"""
    if lang == 'en':
        return {
            'title': 'EDUCATIONAL PROGRESS REPORT',
            'parent': 'Parent',
            'generation_date': 'Report generated on',
            'global_summary': 'GLOBAL SUMMARY',
            'children_tracked': 'Children tracked',
            'overall_average': 'Overall average',
            'exercises_completed': 'Exercises completed',
            'period_covered': 'Period covered',
            'current_school_year': 'Current school year',
            'student': 'STUDENT',
            'grade': 'Grade',
            'username': 'Username',
            'personal_average': 'Personal average',
            'success_rate': 'Success rate',
            'exercises_done': 'Exercises done',
            'exercises_passed': 'Exercises passed',
            'recent_activities': 'RECENT ACTIVITIES',
            'activity_id': 'Activity ID',
            'stars': 'Stars',
            'performance': 'Performance',
            'recommendations': 'RECOMMENDATIONS',
            'global_analysis': 'GLOBAL ANALYSIS AND OUTLOOK',
            'analysis_text': """This report provides an overview of your children's learning journey. 
            The data is regularly updated and reflects the commitment and progress made.
            
            Key points to remember:
            • Regular monitoring is essential to maintain progress
            • Consistent practice significantly improves results
            • Feel free to check the platform for real-time data""",
            'excellent': 'Excellent',
            'good': 'Good',
            'needs_improvement': 'Needs improvement',
            'weak': 'Weak',
            'not_available': 'N/A'
        }
    else:
        return {
            'title': 'RAPPORT DE SUIVI SCOLAIRE',
            'parent': 'Parent',
            'generation_date': 'Rapport généré le',
            'global_summary': 'RÉSUMÉ GLOBAL',
            'children_tracked': 'Nombre d\'enfants suivis',
            'overall_average': 'Moyenne générale',
            'exercises_completed': 'Total d\'exercices réalisés',
            'period_covered': 'Période couverte',
            'current_school_year': 'Année scolaire en cours',
            'student': 'ÉLÈVE',
            'grade': 'Niveau',
            'username': 'Nom d\'utilisateur',
            'personal_average': 'Moyenne personnelle',
            'success_rate': 'Taux de réussite',
            'exercises_done': 'Exercices réalisés',
            'exercises_passed': 'Exercices réussis',
            'recent_activities': 'DERNIÈRES ACTIVITÉS',
            'activity_id': 'ID Activité',
            'stars': 'Étoiles',
            'performance': 'Performance',
            'recommendations': 'RECOMMANDATIONS',
            'global_analysis': 'ANALYSE GLOBALE ET PERSPECTIVES',
            'analysis_text': """Ce rapport présente une vue d'ensemble du parcours d'apprentissage de vos enfants. 
            Les données sont mises à jour régulièrement et reflètent l'engagement et les progrès réalisés.
            
            Points clés à retenir :
            • Le suivi régulier est essentiel pour maintenir la progression
            • La pratique constante améliore significativement les résultats
            • N'hésitez pas à consulter la plateforme pour des données en temps réel""",
            'excellent': 'Excellent',
            'good': 'Bon',
            'needs_improvement': 'À améliorer',
            'weak': 'Faible',
            'not_available': 'N/A'
        }

def get_recommendation_text(prenom, moyenne, lang):
    """Génère les recommandations dans la bonne langue"""
    if lang == 'en':
        if moyenne >= 2.5:
            return f"Congratulations! {prenom} shows excellent mastery of concepts. Continue to encourage them in their progress."
        elif moyenne >= 2:
            return f"Good work! {prenom} is progressing well. Some targeted revisions could help consolidate learning."
        elif moyenne >= 1:
            return f"{prenom} needs additional support. We recommend reinforcement exercises on basic concepts."
        else:
            return f"Attention needed. {prenom} is experiencing significant difficulties. Personalized support is recommended."
    else:
        if moyenne >= 2.5:
            return f"Félicitations ! {prenom} montre une excellente maîtrise des concepts. Continuez à l'encourager dans sa progression."
        elif moyenne >= 2:
            return f"Bon travail ! {prenom} progresse bien. Quelques révisions ciblées pourraient aider à consolider les acquis."
        elif moyenne >= 1:
            return f"{prenom} a besoin de soutien supplémentaire. Nous recommandons des exercices de renforcement sur les notions de base."
        else:
            return f"Attention nécessaire. {prenom} rencontre des difficultés significatives. Un accompagnement personnalisé est recommandé."

def get_performance_text(etoiles, lang):
    """Retourne l'évaluation de performance dans la bonne langue"""
    texts = get_pdf_texts(lang)
    if etoiles >= 2.5:
        return texts['excellent']
    elif etoiles >= 2:
        return texts['good']
    elif etoiles >= 1:
        return texts['needs_improvement']
    else:
        return texts['weak']

@app.route('/telecharger-pdf/<email>')
def telecharger_pdf(email):
    try:
        # ✅ Récupération de la langue
        lang = request.args.get('lang') or session.get('lang', 'fr')
        texts = get_pdf_texts(lang)
        
        # Récupération des données
        parent = Parent.query.filter_by(email=email).first()
        if not parent:
            return "Parent non trouvé" if lang == 'fr' else "Parent not found", 404
        
        liens = ParentEleve.query.filter_by(parent_id=parent.id).all()
        enfants_data = []
        
        for lien in liens:
            eleve = User.query.get(lien.eleve_id)
            if eleve:
                # Données détaillées de l'élève
                reponses = StudentResponse.query.filter_by(user_id=eleve.id).all()
                notes = [r.etoiles for r in reponses if r.etoiles is not None]
                moyenne = round(sum(notes) / len(notes), 2) if notes else None
                
                # Dernières activités
                dernieres_activites = StudentResponse.query.filter_by(
                    user_id=eleve.id
                ).order_by(StudentResponse.id.desc()).limit(5).all()
                
                # Calcul des statistiques
                total_exercices = len(reponses)
                exercices_reussis = len([r for r in reponses if r.etoiles and r.etoiles >= 2])
                taux_reussite = round((exercices_reussis / total_exercices * 100), 1) if total_exercices > 0 else 0
                
                enfants_data.append({
                    'eleve': eleve,
                    'moyenne': moyenne,
                    'total_exercices': total_exercices,
                    'exercices_reussis': exercices_reussis,
                    'taux_reussite': taux_reussite,
                    'dernieres_activites': dernieres_activites,
                    'notes_details': notes
                })
        
        # Génération du PDF
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=1*inch)
        elements = []
        
        # Styles
        styles = getSampleStyleSheet()
        titre_style = ParagraphStyle(
            'TitreStyle',
            parent=styles['Heading1'],
            fontSize=18,
            textColor=colors.HexColor('#2c3e50'),
            spaceAfter=30,
            alignment=1
        )
        
        sous_titre_style = ParagraphStyle(
            'SousTitreStyle',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#34495e'),
            spaceAfter=20
        )
        
        normal_style = styles['Normal']
        
        # ✅ En-tête adapté à la langue
        elements.append(Paragraph(texts['title'], titre_style))
        elements.append(Paragraph(f"{texts['parent']} : {parent.nom_complet}", sous_titre_style))
        elements.append(Paragraph(f"{texts['generation_date']} : {datetime.now().strftime('%d/%m/%Y à %H:%M') if lang == 'fr' else datetime.now().strftime('%m/%d/%Y at %H:%M')}", normal_style))
        elements.append(Spacer(1, 20))
        
        # ✅ Résumé global adapté
        elements.append(Paragraph(texts['global_summary'], sous_titre_style))
        
        # Statistiques globales
        total_enfants = len(enfants_data)
        enfants_avec_notes = [e for e in enfants_data if e['moyenne'] is not None]
        moyenne_generale = sum([e['moyenne'] for e in enfants_avec_notes]) / len(enfants_avec_notes) if enfants_avec_notes else 0
        total_exercices_globaux = sum([e['total_exercices'] for e in enfants_data])
        
        resume_data = [
            [texts['children_tracked'], str(total_enfants)],
            [texts['overall_average'], f"{moyenne_generale:.2f}/5" if enfants_avec_notes else texts['not_available']],
            [texts['exercises_completed'], str(total_exercices_globaux)],
            [texts['period_covered'], texts['current_school_year']]
        ]
        
        resume_table = Table(resume_data, colWidths=[200, 100])
        resume_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8f9fa')),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
        ]))
        
        elements.append(resume_table)
        elements.append(Spacer(1, 30))
        
        # ✅ Détails par enfant adaptés
        for enfant in enfants_data:
            eleve = enfant['eleve']
            
            # En-tête de l'enfant
            elements.append(Paragraph(f"{texts['student']} : {eleve.nom_complet}", sous_titre_style))
            
            # Informations de base
            niveau_nom = "Non spécifié" if lang == 'fr' else "Not specified"
            if eleve.niveau:
                if hasattr(eleve.niveau, 'nom'):
                    niveau_nom = eleve.niveau.nom
                elif hasattr(eleve.niveau, 'name'):
                    niveau_nom = eleve.niveau.name
                elif hasattr(eleve.niveau, 'libelle'):
                    niveau_nom = eleve.niveau.libelle
            
            info_data = [
                [texts['grade'], niveau_nom],
                [texts['username'], eleve.username],
                [texts['personal_average'], f"{enfant['moyenne']:.2f}/5" if enfant['moyenne'] is not None else texts['not_available']],
                [texts['success_rate'], f"{enfant['taux_reussite']}%"],
                [texts['exercises_done'], str(enfant['total_exercices'])],
                [texts['exercises_passed'], str(enfant['exercices_reussis'])]
            ]
            
            info_table = Table(info_data, colWidths=[150, 150])
            info_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#27ae60')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#ecf0f1')),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ]))
            
            elements.append(info_table)
            elements.append(Spacer(1, 15))
            
            # ✅ Dernières activités adaptées
            if enfant['dernieres_activites']:
                elements.append(Paragraph(texts['recent_activities'], normal_style))
                
                activites_data = [[texts['activity_id'], texts['stars'], texts['performance']]]
                for activite in enfant['dernieres_activites']:
                    etoiles = getattr(activite, 'etoiles', 0) or 0
                    performance = get_performance_text(etoiles, lang)
                    
                    activites_data.append([
                        f"{'Activité' if lang == 'fr' else 'Activity'} #{activite.id}",
                        f"{etoiles}/5",
                        performance
                    ])
                
                activites_table = Table(activites_data, colWidths=[100, 80, 100])
                activites_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f39c12')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                    ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                    ('FONTSIZE', (0, 0), (-1, -1), 8),
                ]))
                
                elements.append(activites_table)
                elements.append(Spacer(1, 15))
            
            # ✅ Recommandations adaptées
            elements.append(Paragraph(texts['recommendations'], normal_style))
            
            if enfant['moyenne'] is not None:
                prenom = eleve.nom_complet.split(' ')[0] if eleve.nom_complet and ' ' in eleve.nom_complet else eleve.nom_complet
                recommandation = get_recommendation_text(prenom, enfant['moyenne'], lang)
            else:
                prenom = eleve.nom_complet.split(' ')[0] if eleve.nom_complet and ' ' in eleve.nom_complet else eleve.nom_complet
                if lang == 'en':
                    recommandation = f"{prenom} does not yet have enough evaluated activities to establish a progress profile."
                else:
                    recommandation = f"{prenom} n'a pas encore suffisamment d'activités évaluées pour établir un profil de progression."
            
            elements.append(Paragraph(recommandation, normal_style))
            elements.append(Spacer(1, 30))
        
        # ✅ Analyse globale adaptée
        elements.append(Paragraph(texts['global_analysis'], sous_titre_style))
        elements.append(Paragraph(texts['analysis_text'], normal_style))
        
        # Génération du PDF
        doc.build(elements)
        
        # ✅ Nom de fichier adapté
        buffer.seek(0)
        response = make_response(buffer.read())
        response.headers['Content-Type'] = 'application/pdf'
        
        filename = f"school_report_{parent.nom_complet.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.pdf"
        if lang == 'fr':
            filename = f"rapport_scolaire_{parent.nom_complet.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.pdf"
        
        response.headers['Content-Disposition'] = f'attachment; filename={filename}'
        
        return response
        
    except Exception as e:
        print(f"Erreur génération PDF: {str(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        error_msg = "Erreur lors de la génération du PDF" if lang == 'fr' else "Error generating PDF"
        return f"{error_msg}: {str(e)}", 500

@app.route("/parent-dashboard")
def parent_dashboard():
    # ✅ CORRECTION : Récupérer l'email du parent depuis la session
    parent_email = session.get("parent_email")
    
    if not parent_email:
        flash("Veuillez vous connecter en tant que parent", "error")
        return redirect(url_for("login_parent"))
    
    parent = Parent.query.filter_by(email=parent_email).first()
    if not parent:
        flash("Parent non trouvé", "error")
        return redirect(url_for("login_parent"))
    
    # Récupération UNIQUEMENT des enfants liés à ce parent
    liens = ParentEleve.query.filter_by(parent_id=parent.id).all()
    
    enfants = []
    for lien in liens:
        eleve = db.session.get(User, lien.eleve_id)
        if eleve:
            # Calcul des données spécifiques à cet enfant
            reponses = StudentResponse.query.filter_by(user_id=eleve.id).all()
            notes = [r.etoiles for r in reponses if r.etoiles is not None]
            moyenne = round(sum(notes) / len(notes), 2) if notes else None
            
            enfants.append({
                "nom": eleve.nom_complet,
                "niveau": eleve.niveau.nom if eleve.niveau else "Non défini",
                "username": eleve.username,
                "moyenne_etoiles": moyenne
            })
    
    return render_template("parent_dashboard.html", parent=parent, enfants=enfants)

# ✅ AJOUTEZ CETTE ROUTE MANQUANTE
@app.route('/parent-dashboard/pdf')
def parent_dashboard_pdf():
    email = request.args.get('email')
    if not email:
        return "Email manquant", 400
    # Redirige vers la route PDF existante
    return redirect(url_for('telecharger_pdf', email=email))

@app.route("/choisir-sequence")
def choisir_sequence():
    username = request.args.get("username")
    lang = request.args.get("lang", "fr")

    eleve = User.query.options(
        joinedload(User.niveau)
        .joinedload(Niveau.matieres)
        .joinedload(Matiere.unites)
        .joinedload(Unite.lecons)
        .joinedload(Lecon.exercices),  # Ajout pour charger les exercices

        joinedload(User.niveau)
        .joinedload(Niveau.matieres)
        .joinedload(Matiere.unites)
        .joinedload(Unite.tests)
    ).filter_by(username=username).first_or_404()

    unites = []
    lecons_filtrees = []

    for matiere in eleve.niveau.matieres:
        for unite in matiere.unites:
            unites.append(unite)
            for lecon in unite.lecons:
                total_exos = len(lecon.exercices)
                print(f"🔎 {lecon.titre_fr} → {total_exos} exercice(s)")
                if total_exos > 0:
                    lecons_filtrees.append(lecon)

    return render_template(
        "choisir_sequence.html",
        eleve=eleve,
        unites=unites,
        lecons=lecons_filtrees,
        lang=lang
    )


from datetime import datetime, timedelta
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import io
import base64
from flask import request, render_template, redirect, url_for, flash, session
from sqlalchemy.orm import joinedload
from sqlalchemy import and_

@app.route("/dashboard-eleve")
def dashboard_eleve():
    if "eleve_id" not in session:
        return redirect(url_for("login_eleve"))

    eleve = User.query.options(joinedload(User.niveau)).get(session["eleve_id"])
    if not eleve or eleve.role != "élève":
        return "Accès non autorisé", 403

    # 🚨 VÉRIFICATION ACCÈS - ESSAI GRATUIT EXPIRÉ
    # NE PAS DÉCONNECTER L'ÉLÈVE, LE REDIRIGER VERS L'UPGRADE
    if eleve.essai_est_expire() and eleve.statut_paiement != "paye":
        flash("Votre période d'essai gratuit de 48h est terminée. Veuillez choisir un abonnement pour continuer.", "warning")
        return redirect(url_for('upgrade_options'))

    # ✅ CORRECTION : Stocker pour l'enseignant virtuel
    session['current_student'] = eleve.username

    lang = request.args.get("lang") or session.get("lang", "fr")
    session["lang"] = lang

    # 🔔 Remédiations non vues
    remediations_non_lues = RemediationSuggestion.query.filter_by(
        user_id=eleve.id,
        statut="valide",
        vue_par_eleve=False
    ).order_by(RemediationSuggestion.timestamp.desc()).limit(1).all()

    # 📊 Statistiques
    from sqlalchemy.sql import func
    
    reponses_eleve = StudentResponse.query.filter_by(user_id=eleve.id).order_by(StudentResponse.timestamp).all()
    total_reponses = len(reponses_eleve)

    # 🔧 Corrige les valeurs None
    etoiles_values = [r.etoiles or 0 for r in reponses_eleve]
    moyenne_etoiles = sum(etoiles_values) / total_reponses if total_reponses else 0
    bonnes_reponses = sum(1 for e in etoiles_values if e >= 3)
    taux_reussite = round((bonnes_reponses / total_reponses) * 100, 1) if total_reponses else 0

    stats = {
        "total": total_reponses,
        "average": round(moyenne_etoiles, 1),
        "success": taux_reussite
    }

    # 📈 Courbe progression - MOYENNE PAR JOUR
    courbe_progression = None
    if reponses_eleve:
        # Grouper les réponses par date et calculer la moyenne des étoiles par jour
        reponses_par_jour = {}
        for reponse in reponses_eleve:
            date_str = reponse.timestamp.strftime("%Y-%m-%d")
            if date_str not in reponses_par_jour:
                reponses_par_jour[date_str] = []
            reponses_par_jour[date_str].append(reponse.etoiles or 0)
        
        # Calculer la moyenne par jour
        dates_ordonnees = sorted(reponses_par_jour.keys())
        moyennes_journalieres = []
        
        for date_str in dates_ordonnees:
            etoiles_du_jour = reponses_par_jour[date_str]
            moyenne_jour = sum(etoiles_du_jour) / len(etoiles_du_jour)
            moyennes_journalieres.append(round(moyenne_jour, 2))
        
        # Formater les dates pour l'affichage
        dates_formatees = [datetime.strptime(date_str, "%Y-%m-%d").strftime("%d/%m") for date_str in dates_ordonnees]

        # Créer le graphique
        fig = plt.figure(figsize=(6, 2.5))
        ax = fig.add_subplot(111)

        titre = "Moyenne des Étoiles par Jour" if lang == "fr" else "Daily Average Stars"
        label_y = "Étoiles" if lang == "fr" else "Stars"

        ax.plot(dates_formatees, moyennes_journalieres, marker="o", color="blue", linewidth=2, markersize=4)
        ax.set_title(titre, fontsize=12, fontweight='bold')
        ax.set_ylabel(label_y, fontweight='bold')
        ax.set_ylim(0, 5.5)
        ax.grid(True, alpha=0.3)
        ax.tick_params(axis='x', rotation=45)
        
        # Ajouter les valeurs sur les points
        for i, (date, valeur) in enumerate(zip(dates_formatees, moyennes_journalieres)):
            ax.annotate(f'{valeur}', (date, valeur), 
                       textcoords="offset points", xytext=(0,10), ha='center', fontsize=8)
        
        fig.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=100, bbox_inches='tight')
        buf.seek(0)
        courbe_progression = base64.b64encode(buf.read()).decode('utf-8')
        buf.close()
        plt.close(fig)

    # ⏰ CALCUL TEMPS RESTANT ESSAI GRATUIT
    temps_restant = None
    pourcentage_temps_restant = 100
    total_seconds = 0
    
    if eleve.est_en_essai_gratuit() and eleve.date_fin_essai:
        maintenant = datetime.utcnow()
        if maintenant < eleve.date_fin_essai:
            temps_restant = eleve.date_fin_essai - maintenant
            total_seconds = int(temps_restant.total_seconds())
            
            # Calculer le pourcentage de temps restant
            duree_totale = eleve.date_fin_essai - eleve.date_inscription
            temps_ecoule = maintenant - eleve.date_inscription
            
            if duree_totale.total_seconds() > 0:
                pourcentage_temps_restant = max(0, min(100, 
                    100 - (temps_ecoule.total_seconds() / duree_totale.total_seconds() * 100)
                ))

    # 🎯 OBJECTIFS DU JOUR - CODE SIMPLIFIÉ SANS ENSEIGNANT VIRTUEL
    # Compter les remédiations complétées
    remediations_completees = RemediationSuggestion.query.filter(
        and_(
            RemediationSuggestion.user_id == eleve.id,
            RemediationSuggestion.statut == "valide",
            RemediationSuggestion.reponse_eleve.isnot(None)
        )
    ).count()

    # Créer les objectifs du jour (3 objectifs au lieu de 4)
    objectifs_du_jour = []

    # Objectif 1: Compléter au moins 1 exercice
    objectif1_completed = stats["total"] > 0
    objectif1_progress = f"({stats['total']} complété(s))" if lang == "fr" else f"({stats['total']} completed)"
    objectifs_du_jour.append({
        'text': "Compléter 1 exercice" if lang == "fr" else "Complete 1 exercise",
        'completed': objectif1_completed,
        'progress': objectif1_progress
    })

    # Objectif 2: Moyenne 3+ étoiles
    objectif2_completed = stats["average"] >= 3
    objectif2_progress = f"(Actuel : {stats['average']}/5)" if lang == "fr" else f"(Current: {stats['average']}/5)"
    objectifs_du_jour.append({
        'text': "Moyenne 3+ étoiles" if lang == "fr" else "3+ star average",
        'completed': objectif2_completed,
        'progress': objectif2_progress
    })

    # Objectif 3: Compléter une remédiation
    objectif3_completed = remediations_completees > 0
    objectif3_progress = f"({remediations_completees} complétée(s))" if lang == "fr" else f"({remediations_completees} completed)"
    objectifs_du_jour.append({
        'text': "Compléter 1 remédiation" if lang == "fr" else "Complete 1 remediation",
        'completed': objectif3_completed,
        'progress': objectif3_progress
    })

    # Calculer la progression quotidienne
    total_objectifs = len(objectifs_du_jour)
    objectifs_completes = sum(1 for obj in objectifs_du_jour if obj['completed'])
    progression_percent = int((objectifs_completes / total_objectifs) * 100) if total_objectifs > 0 else 0

    progression_quotidienne = {
        'completed': objectifs_completes,
        'total': total_objectifs,
        'percent': progression_percent
    }
    
    # ✅ NOUVEAU : AJOUTER LE STATUT DE PAIEMENT POUR LE TEMPLATE
    statut_paiement_info = {
        'est_en_essai': eleve.est_en_essai_gratuit(),
        'est_paye': eleve.statut_paiement == "paye",
        'essai_expire': eleve.essai_est_expire(),
        'jours_restants_abonnement': eleve.jours_restants_abonnement() if hasattr(eleve, 'jours_restants_abonnement') else 0
    }

    return render_template(
        "dashboard_eleve.html",
        eleve=eleve,
        lang=lang,
        stats=stats,
        remediations_non_lues=remediations_non_lues,
        reponses_eleve=reponses_eleve,
        courbe_progression=courbe_progression,
        temps_restant=temps_restant,
        pourcentage_temps_restant=pourcentage_temps_restant,
        total_seconds=total_seconds,
        # NOUVELLES VARIABLES POUR LES OBJECTIFS
        objectifs_du_jour=objectifs_du_jour,
        progression_quotidienne=progression_quotidienne,
        remediations_completees=remediations_completees,
        date_du_jour=datetime.utcnow(),
        # ✅ NOUVEAU : INFORMATION DE PAIEMENT
        statut_paiement_info=statut_paiement_info
    )

@app.route("/reset-admin-password")
def reset_admin_password():
    """Réinitialise le mot de passe admin - À SUPPRIMER APRÈS"""
    try:
        with app.app_context():
            from werkzeug.security import generate_password_hash, check_password_hash
            from datetime import datetime
            
            email = "ambroiseguehi@gmail.com"
            password = "Ninsem@n@912"
            
            # Trouver l'admin
            admin = User.query.filter_by(email=email, role="admin").first()
            
            if not admin:
                return "<h1>❌ Admin non trouvé</h1><p>Créez d'abord un compte admin.</p>"
            
            # Afficher le hash actuel
            current_hash = admin.mot_de_passe_hash[:30] if admin.mot_de_passe_hash else "N/A"
            
            # Générer un NOUVEAU hash
            new_hash = generate_password_hash(password)
            
            # Mettre à jour le hash
            admin.mot_de_passe_hash = new_hash
            db.session.commit()
            
            # Vérifier le nouveau hash
            test = check_password_hash(new_hash, password)
            
            return f"""
            <h1>✅ Mot de passe admin réinitialisé !</h1>
            <p><strong>Email:</strong> {email}</p>
            <p><strong>Mot de passe:</strong> {password}</p>
            <p><strong>Ancien hash:</strong> {current_hash}...</p>
            <p><strong>Nouveau hash:</strong> {new_hash[:30]}...</p>
            <p><strong>Test du mot de passe:</strong> {"✅ Réussi" if test else "❌ Échec"}</p>
            <p><strong>⚠️ IMPORTANT:</strong> Supprimez cette route après usage !</p>
            <a href="/login-admin">Se connecter maintenant</a>
            """
            
    except Exception as e:
        return f"<h1>❌ Erreur:</h1><p>{str(e)}</p>"
    
@app.route("/create-profile", methods=["POST"])
def create_profile():
    data = request.json
    nom_complet = data.get("nom_complet")
    niveau = data.get("niveau")
    email = data.get("email")
    parent_nom = data.get("parent_nom")
    parent_email = data.get("parent_email")

    if not all([nom_complet, niveau, email, parent_nom, parent_email]):
        return jsonify({"error": "Tous les champs sont obligatoires."}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Cette adresse e-mail est déjà utilisée."}), 409

    parent = Parent.query.filter_by(email=parent_email).first()
    if not parent:
        parent = Parent(nom_complet=parent_nom, email=parent_email)
        db.session.add(parent)
        db.session.commit()

    i = 1
    while True:
        username = f"student_{i:03d}"
        if not User.query.filter_by(username=username).first():
            break
        i += 1

    new_user = User(
        username=username,
        nom_complet=nom_complet,
        role="élève",
        niveau=niveau,
        email=email
    )
    db.session.add(new_user)
    db.session.commit()

    lien = ParentEleve(parent_id=parent.id, eleve_id=new_user.id)
    db.session.add(lien)
    db.session.commit()

    return jsonify({"message": "Profil créé avec succès.", "username": username})

       
@app.route("/exercice-sequentiel-progressif")
def exercice_sequentiel_progressif():
    username = request.args.get("username")
    lecon_id = request.args.get("lecon_id")
    lang = request.args.get("lang", "fr")
    index = int(request.args.get("index", 0))

    eleve = User.query.filter_by(username=username).first_or_404()
    lecon = Lecon.query.get_or_404(lecon_id)
    exercices = Exercice.query.filter_by(lecon_id=lecon.id).order_by(Exercice.id).all()

    if not exercices:
        flash("Aucun exercice trouvé dans cette leçon", "warning")
        return redirect(url_for("contenus_eleve", username=username, lang=lang))

    # Étape 1: Trouver le prochain exercice non fait à partir de l'index donné
    next_index = index
    while next_index < len(exercices):
        exercice_courant = exercices[next_index]
        reponse_existante = StudentResponse.query.filter_by(
            user_id=eleve.id, 
            exercice_id=exercice_courant.id
        ).first()
        
        if not reponse_existante:
            # Exercice non fait trouvé
            break
        next_index += 1

    # Étape 2: Gérer les cas de figure
    if next_index >= len(exercices):
        # Tous les exercices à partir de l'index sont faits
        if index == 0:
            # Tous les exercices de la leçon sont faits
            flash("🎉 Félicitations ! Vous avez terminé tous les exercices de cette leçon.", "success")
            return redirect(url_for("retour_exercices", username=username, lecon_id=lecon_id, lang=lang))
        else:
            # L'élève a terminé les exercices restants
            flash("✅ Vous avez terminé les exercices suivants de cette leçon.", "info")
            return redirect(url_for("retour_exercices", username=username, lecon_id=lecon_id, lang=lang))

    # Étape 3: Préparer les données pour l'affichage
    exercice = exercices[next_index]
    
    # Récupérer la réponse existante (normalement None puisque c'est le prochain non fait)
    reponse = StudentResponse.query.filter_by(user_id=eleve.id, exercice_id=exercice.id).first()

    # Calculer la progression réelle (exercices faits / total)
    total_exercices = len(exercices)
    exercices_faits = StudentResponse.query.filter(
        StudentResponse.user_id == eleve.id,
        StudentResponse.exercice_id.in_([ex.id for ex in exercices])
    ).count()
    
    progression_pourcentage = (exercices_faits / total_exercices * 100) if total_exercices > 0 else 0

    return render_template(
        "exercice_sequentiel_progressif.html",
        exercice=exercice,
        eleve=eleve,
        lecon=lecon,
        lang=lang,
        index=next_index,  # Utiliser l'index corrigé
        total=total_exercices,
        reponse=reponse,
        progression_pourcentage=progression_pourcentage,
        exercices_faits=exercices_faits
    )


@app.route("/retour-exercices")
def retour_exercices():
    username = request.args.get("username")
    lecon_id = request.args.get("lecon_id")
    lang = request.args.get("lang", "fr")

    # Récupération de l'élève
    eleve = User.query.filter_by(username=username).first_or_404()

    # Récupération de la leçon
    lecon = Lecon.query.get_or_404(lecon_id)

    # Récupération des exercices de cette leçon
    exercices = Exercice.query.filter_by(lecon_id=lecon.id).all()

    # Récupération des réponses de l'élève pour ces exercices
    corrections = {
        r.exercice_id: r for r in StudentResponse.query.filter_by(user_id=eleve.id)
        .filter(StudentResponse.exercice_id.in_([e.id for e in exercices]))
        .all()
    }

    return render_template(
        "retour_exercices.html",  # <- assure-toi que le fichier existe bien dans /templates/
        exercices=exercices,
        corrections=corrections,
        eleve=eleve,
        lang=lang
    )

@app.route("/test/<int:test_id>", methods=["GET", "POST"])
def faire_test_sommatif(test_id):
    from datetime import datetime

    username = request.args.get("username")
    lang = request.args.get("lang", "fr")

    eleve = User.query.filter_by(username=username).first_or_404()
    test = TestSommatif.query.get_or_404(test_id)

    if request.method == "POST" and request.form.get("revoir") == "1":
        StudentResponse.query.filter_by(user_id=eleve.id, test_id=test.id).delete()
        TestResponse.query.filter_by(user_id=eleve.id, test_id=test.id).delete()
        db.session.commit()
        return redirect(request.url)

    reponses_existantes = StudentResponse.query.filter_by(
        user_id=eleve.id,
        test_id=test.id
    ).filter(StudentResponse.test_exercice_id.isnot(None)).all()

    deja_enregistre = TestResponse.query.filter_by(user_id=eleve.id, test_id=test.id).first()

    if request.method == "POST" and not reponses_existantes and not deja_enregistre:
        reponses_elevees = request.form.getlist("reponses[]")
        ids_exercices = request.form.getlist("ex_ids[]")

        if not any(rep.strip() for rep in reponses_elevees):
            flash("❗ Aucune réponse saisie.", "error")
            return redirect(request.url)

        questions = []
        attendues = []
        for ex in test.exercices:
            q = ex.question_en if lang == "en" else ex.question_fr
            r = ex.reponse_en if lang == "en" else ex.reponse_fr
            questions.append(q.strip())
            attendues.append(r.strip() if r else "")

        enonce_complet = "\n\n".join(f"🧩 Q{idx+1}:\n{q}" for idx, q in enumerate(questions))
        reponses_concat = "\n\n".join(f"🧩 Q{idx+1}:\n{rep.strip()}" for idx, rep in enumerate(reponses_elevees))

        # ✅ NOUVEAU PROMPT avec barème sur 5
        if lang == "en":
            prompt = f"""
You are an expert math teacher evaluating a student's final test submission.

📘 Test Questions:
{enonce_complet}

📜 Student's Response:
{reponses_concat}

✅ Expected Answers:
{chr(10).join(attendues)}

🔍 What you must do:
- Solve all the exercises yourself to compare with the expected answers.
- For each exercise, compare each line of the student's reasoning.
- Accept correct reasoning even if it's presented differently.
- Be pedagogical and constructive.
- Give priority to reasoning over final result.
- Award partial credit for correct steps.
- ❗ Do not contradict yourself.

⭐ SCORING SCALE (5 points per exercise):
- 5: Excellent reasoning, complete methodology, correct result
- 4: Very good reasoning, appropriate method, minor calculation error
- 3: Good overall approach, method understood but imperfect application
- 2: Partial reasoning, some relevant elements but incomplete
- 1: Fragmented approach, very limited correct elements
- 0: Off-topic or no answer

📤 Output format:
🧩 Q1
Analysis: [...]
Score: X/5
Correction:
- Expert resolution: [...]
- Final answer: [...]

🧩 Q2
...
""".strip()
        else:
            prompt = f"""
Tu es un professeur expert en mathématiques. Tu dois corriger la soumission d'un test sommatif d'un élève.

📘 Questions du test :
{enonce_complet}

📜 Réponses de l'élève :
{reponses_concat}

✅ Réponses finales attendues :
{chr(10).join(attendues)}

🔍 Ce que tu dois faire :
- Résous tous les exercices toi-même pour vérifier les réponses.
- Compare chaque ligne du raisonnement de l'élève avec ta propre résolution.
- Si le raisonnement est correct même s'il est formulé différemment, accepte-le.
- Sois pédagogique, clair, et bienveillant.
- Privilégie le raisonnement sur le résultat final.
- Accordez des points partiels pour les étapes correctes.
- ❗ Ne te contredis pas : si la réponse est correcte avec un raisonnement valide, ne dis pas le contraire.

⭐ BARÈME (5 points par exercice) :
- 5 : Raisonnement excellent, méthodologie complète, résultat correct
- 4 : Très bon raisonnement, méthode appropriée, erreur mineure de calcul
- 3 : Bonne démarche globale, méthode comprise mais application imparfaite
- 2 : Raisonnement partiel, éléments pertinents mais incomplets
- 1 : Démarche ébauchée, éléments corrects très limités
- 0 : Hors sujet ou absence de réponse

📤 Format attendu :
🧩 Q1
Analyse : [...]
Note : X/5
Correction :
- Résolution experte : [...]
- Résultat final : [...]

🧩 Q2
...
""".strip()

        try:
            chat_completion = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
            )
            analyse_ia = chat_completion.choices[0].message.content.strip()
        except Exception as e:
            return f"Erreur IA : {e}", 500

        blocs = analyse_ia.split("🧩 Q")[1:]

        etoiles_total = 0
        exercices_corriges = 0
        
        for ex_id, reponse_texte, bloc in zip(ids_exercices, reponses_elevees, blocs):
            test_ex = TestExercice.query.get(int(ex_id))
            if not test_ex:
                continue

            texte = bloc.strip()
            etoiles = 0
            
            # ✅ EXTRACTION DE NOTE SUR 5
            match = re.search(r"(Note|Score)\s*:\s*(\d)/5", texte, re.IGNORECASE)
            if match:
                etoiles = int(match.group(2))
            else:
                # Fallback pour l'ancien format
                match = re.search(r"(Note|Score)\s*:\s*(\d)", texte, re.IGNORECASE)
                if match:
                    etoiles = min(int(match.group(2)), 5)  # Limite à 5 maximum

            etoiles_total += etoiles
            exercices_corriges += 1

            nouvelle = StudentResponse(
                user_id=eleve.id,
                test_id=test.id,
                test_exercice_id=test_ex.id,
                reponse_eleve=reponse_texte.strip(),
                analyse_ia=texte,
                etoiles=etoiles,
                timestamp=datetime.utcnow()
            )
            db.session.add(nouvelle)

        # Calcul de la moyenne sur 5
        moyenne = round(etoiles_total / max(exercices_corriges, 1), 1) if exercices_corriges > 0 else 0
        
        # ✅ CORRECTION : Supprimer le paramètre 'moyenne' qui n'existe pas dans le modèle
        resume_test = TestResponse(
            user_id=eleve.id,
            test_id=test.id,
            reponses_exercices={str(i+1): rep.strip() for i, rep in enumerate(reponses_elevees)},
            analyse_ia=analyse_ia,
            etoiles=etoiles_total,  # On garde le total des étoiles
            timestamp=datetime.utcnow()
        )
        db.session.add(resume_test)

        db.session.commit()
        
        # ✅ CORRECTION : Stocker la moyenne dans la session pour l'affichage
        session['derniere_moyenne'] = moyenne
        
        # Message de feedback adapté
        if moyenne >= 4:
            flash(f"🎉 Excellent travail ! Test réussi avec brio. Moyenne : {moyenne}/5", "success")
        elif moyenne >= 3:
            flash(f"✅ Bon travail ! Test réussi. Moyenne : {moyenne}/5", "success")
        else:
            flash(f"📚 Test terminé. Des révisions seraient bénéfiques. Moyenne : {moyenne}/5", "info")
            
        return redirect(request.url)

    reponses_par_exercice = {
        r.test_exercice_id: r for r in StudentResponse.query.filter_by(
            user_id=eleve.id,
            test_id=test.id
        ).filter(StudentResponse.test_exercice_id.isnot(None)).all()
    }

    # ✅ CORRECTION : Récupérer la moyenne depuis la session pour l'affichage
    derniere_moyenne = session.pop('derniere_moyenne', None)

    return render_template(
        "faire_test_sommatif.html",
        test=test,
        eleve=eleve,
        lang=lang,
        reponses_par_exercice=reponses_par_exercice,
        derniere_moyenne=derniere_moyenne  # Passer la moyenne au template
    )


@app.route("/remediations/export-pdf")
def export_remediations_pdf():
    suggestions = RemediationSuggestion.query.all()
    donnees = []
    for s in suggestions:
        eleve = User.query.get(s.user_id)
        donnees.append({
            "eleve_nom": eleve.nom_complet,
            "niveau": eleve.niveau.nom if eleve.niveau else "Non défini",
            "username": eleve.username,
            "theme": s.theme,
            "lecon": s.lecon,
            "message": s.message,
            "timestamp": s.timestamp.strftime("%d/%m/%Y %H:%M")
        })

    rendered = render_template("enseignant_remediations.html", suggestions=donnees)

    try:
        config = pdfkit.configuration(wkhtmltopdf=r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe")  # Windows
        pdf = pdfkit.from_string(rendered, False, configuration=config)
    except Exception as e:
        return f"Erreur PDF : {str(e)}", 500

    response = make_response(pdf)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = "attachment; filename=suggestions_remediations.pdf"
    return response


@app.route("/enseignant/supprimer-remediation/<int:id>", methods=["POST"])
def supprimer_remediation(id):
    if "enseignant_id" not in session:
        return redirect(url_for("login_enseignant"))

    suggestion = RemediationSuggestion.query.get_or_404(id)
    db.session.delete(suggestion)
    db.session.commit()
    flash("Remédiation supprimée avec succès.", "success")

    lang = request.args.get("lang", session.get("lang", "fr"))
    return redirect(url_for("remediations_a_valider", lang=lang))


# ============================================
# NOUVELLES ROUTES POUR LE SYSTÈME DE CONTESTATION
# ============================================

import json
import re
from datetime import datetime
from flask import request, jsonify
from flask_login import login_required, current_user  # AJOUT IMPORT MANQUANT

# Fonctions utilitaires pour le système de contestation
def parse_analysis_json(analysis_text):
    """Parse le champ analyse_ia qui peut être du texte ou du JSON"""
    if not analysis_text:
        return {
            "original": "",
            "history": [],
            "current_stars": None,
            "current_feedback": ""
        }
    
    try:
        # Essayer de parser comme JSON
        data = json.loads(analysis_text)
        # S'assurer que la structure est complète
        if isinstance(data, dict):
            return {
                "original": data.get("original", analysis_text),
                "history": data.get("history", []),
                "current_stars": data.get("current_stars"),
                "current_feedback": data.get("current_feedback", analysis_text)
            }
    except json.JSONDecodeError:
        # Si ce n'est pas du JSON, c'est du texte simple
        return {
            "original": analysis_text,
            "history": [],
            "current_stars": None,
            "current_feedback": analysis_text
        }

def update_analysis_with_contestation(analysis_text, student_justification, proposed_stars, ai_response, final_stars):
    """Mettre à jour l'analyse avec une nouvelle contestation"""
    current_data = parse_analysis_json(analysis_text)
    
    # Ajouter la contestation à l'historique
    new_entry = {
        "type": "contestation",
        "date": datetime.utcnow().isoformat(),
        "student_justification": student_justification,
        "proposed_stars": proposed_stars,
        "ai_response": ai_response,
        "final_stars": final_stars
    }
    
    current_data["history"].append(new_entry)
    current_data["current_stars"] = final_stars
    current_data["current_feedback"] = ai_response
    
    # Convertir en JSON
    return json.dumps(current_data, ensure_ascii=False, indent=2)

def get_current_feedback(analysis_text):
    """Obtenir le feedback actuel (peut être texte simple ou JSON)"""
    data = parse_analysis_json(analysis_text)
    return data["current_feedback"] or data["original"]

def get_current_stars(analysis_text):
    """Obtenir les étoiles actuelles"""
    data = parse_analysis_json(analysis_text)
    return data["current_stars"]

def analyze_student_justification(justification, student_answer, ai_feedback):
    """Analyser la justification de l'élève avec des règles plus intelligentes"""
    
    if not justification or justification.strip() == "":
        return {
            'valid_arguments': [],
            'math_keywords_count': 0,
            'argument_count': 0,
            'has_math_justification': False,
            'raw_text': justification or ""
        }
    
    justification_lower = justification.lower().strip()
    justification_original = justification.strip()
    
    # Détecter les arguments valides - règles PLUS LARGES
    valid_arguments = []
    
    # 1. Vérifier si l'élève dit avoir la même solution/résultat
    if any(phrase in justification_lower for phrase in [
        'même solution', 'même résultat', 'same solution', 'same result',
        'solution identique', 'resultat identique', 'identical solution',
        'solution égale', 'equal solution', 'résultat égal', 'equal result'
    ]):
        valid_arguments.append('Solution identique')
    
    # 2. Vérifier si l'élève dit avoir le même raisonnement/méthode
    if any(phrase in justification_lower for phrase in [
        'même raisonnement', 'même méthode', 'same reasoning', 'same method',
        'raisonnement identique', 'méthode identique', 'identical reasoning',
        'même démarche', 'same approach', 'même logique', 'same logic'
    ]):
        valid_arguments.append('Raisonnement identique')
    
    # 3. Vérifier les équivalences mathématiques
    if any(word in justification_lower for word in [
        'équivalent', 'equivalent', 'égal', 'equal', 'identique', 'identical',
        'correspond', 'corresponds', 'équivaut', 'equivalent'
    ]):
        valid_arguments.append('Réponse équivalente')
    
    # 4. Vérifier les méthodes alternatives
    if any(phrase in justification_lower for phrase in [
        'méthode différente', 'different method', 'autre méthode', 'autre façon',
        'alternative', 'approche différente', 'different approach'
    ]):
        valid_arguments.append('Méthode alternative')
    
    # 5. Vérifier les erreurs mineures
    if any(phrase in justification_lower for phrase in [
        'erreur de frappe', 'typo', 'faute', 'mistake', 'inattention',
        'petite erreur', 'small error', 'erreur mineure', 'minor error'
    ]):
        valid_arguments.append('Erreur mineure')
    
    # 6. ANALYSE SÉMANTIQUE SIMPLE - Vérifier le sens
    # Si l'élève mentionne explicitement qu'il a la même solution
    if ('même' in justification_lower and any(word in justification_lower for word in ['solution', 'résultat', 'result'])) or \
       ('same' in justification_lower and any(word in justification_lower for word in ['solution', 'result', 'answer'])):
        valid_arguments.append('Réponse correcte selon élève')
    
    # 7. Compter les mots-clés mathématiques AVEC pondération
    math_keywords = {
        'solution': 1, 'résultat': 1, 'result': 1, 
        'équation': 2, 'equation': 2, 'formule': 2, 'formula': 2,
        'calcul': 1, 'calculation': 1, 'raisonnement': 2, 'reasoning': 2,
        'méthode': 2, 'method': 2, 'logique': 1, 'logic': 1,
        'algèbre': 3, 'algebra': 3, 'math': 1, 'maths': 1,
        'vérifier': 1, 'verify': 1, 'prouver': 2, 'prove': 2
    }
    
    math_count = 0
    for keyword, weight in math_keywords.items():
        if keyword in justification_lower:
            math_count += weight
    
    # 8. ANALYSE DE LONGUEUR ET COHÉRENCE
    # Une justification de plus de 10 mots qui contient "solution" ou "résultat" est valide
    word_count = len(justification_original.split())
    if word_count > 10 and any(word in justification_lower for word in ['solution', 'résultat', 'result', 'answer', 'réponse']):
        valid_arguments.append('Justification détaillée')
    
    # Éliminer les doublons
    valid_arguments = list(set(valid_arguments))
    
    return {
        'valid_arguments': valid_arguments,
        'math_keywords_count': math_count,
        'argument_count': len(valid_arguments),
        'has_math_justification': math_count > 0,
        'word_count': word_count,
        'mentions_solution': any(word in justification_lower for word in ['solution', 'résultat', 'result']),
        'mentions_method': any(word in justification_lower for word in ['méthode', 'method', 'raisonnement', 'reasoning']),
        'raw_text': justification_original
    }

def evaluate_contestation(analysis, current_stars, proposed_stars):
    """Évaluer si on doit ajuster la note - version plus juste"""
    
    # Règles améliorées
    adjustment_needed = False
    reason = ""
    
    # RÈGLE 0: Si l'élève propose une note inférieure, refuser
    if proposed_stars < current_stars:
        return False, "Vous proposez une note inférieure à celle actuelle.", current_stars
    
    # RÈGLE 1: L'élève a-t-il des arguments valides?
    if analysis['argument_count'] == 0:
        # Vérifier quand même s'il a mentionné une solution ou méthode
        if analysis['mentions_solution'] or analysis['mentions_method']:
            reason = "Argument simple mais valide: l'élève mentionne une solution/méthode"
            adjustment_needed = True
        else:
            return False, "Aucun argument mathématique identifiable fourni.", current_stars
    
    # RÈGLE 2: La proposition est-elle raisonnable?
    star_difference = proposed_stars - current_stars
    
    # Si l'élève a des arguments raisonnables, permettre un ajustement
    if analysis['argument_count'] > 0 or analysis['mentions_solution']:
        
        # Différents niveaux d'ajustement selon la force des arguments
        if 'Solution identique' in analysis['valid_arguments'] or 'Raisonnement identique' in analysis['valid_arguments']:
            # Arguments forts : permettre +1 à +2 étoiles
            max_adjustment = min(star_difference, 2)
            adjustment_needed = True
            reason = f"Argument convaincant: {', '.join(analysis['valid_arguments'][:2])}"
            
        elif analysis['argument_count'] >= 2:
            # Arguments multiples : permettre +1 étoile
            max_adjustment = min(star_difference, 1)
            adjustment_needed = True
            reason = f"Plusieurs arguments valides: {', '.join(analysis['valid_arguments'][:2])}"
            
        else:
            # Argument simple : permettre +0.5 étoile (arrondi à +1)
            max_adjustment = min(star_difference, 1)
            adjustment_needed = True
            reason = f"Argument valide: {analysis['valid_arguments'][0] if analysis['valid_arguments'] else 'Justification fournie'}"
    
    # RÈGLE 3: Calculer la nouvelle note
    if adjustment_needed:
        # Calcul basé sur la force des arguments
        argument_strength = 0
        
        if 'Solution identique' in analysis['valid_arguments']:
            argument_strength += 1.5
        if 'Raisonnement identique' in analysis['valid_arguments']:
            argument_strength += 1.5
        if 'Réponse équivalente' in analysis['valid_arguments']:
            argument_strength += 1.0
        if 'Méthode alternative' in analysis['valid_arguments']:
            argument_strength += 0.5
        
        # Ajouter basé sur les mots-clés mathématiques
        argument_strength += min(analysis['math_keywords_count'] * 0.1, 1.0)
        
        # Limiter l'ajustement
        max_increase = min(argument_strength, 2.0)  # Max +2 étoiles
        new_stars = min(current_stars + max_increase, 5)
        new_stars = round(new_stars)
        
        # S'assurer qu'on ne baisse pas la note
        if new_stars < current_stars:
            new_stars = current_stars
        
        # Si l'élève demande spécifiquement 5/5 et a de bons arguments
        if proposed_stars == 5 and argument_strength > 1.5:
            new_stars = min(5, current_stars + 2)  # Max +2 même pour 5/5
        
        return True, reason, new_stars
    
    return False, reason, current_stars

def generate_ai_response(adjusted, reason, new_stars, student_justification, original_feedback):
    """Générer une réponse de l'IA pertinente"""
    
    # Obtenir la note actuelle depuis le feedback original
    current_data = parse_analysis_json(original_feedback)
    original_stars = current_data.get('current_stars', '?')
    
    # Obtenir un conseil PERTINENT
    relevant_tip = get_improvement_tip(student_justification, original_feedback)
    
    if adjusted:
        return f"""🎯 **Réévaluation effectuée**

📝 **Votre justification :**
"{student_justification[:200]}..."

✅ **Décision :** Note ajustée de {original_stars} à {new_stars}/5 ⭐

📋 **Raison :** {reason}

💡 **Pour progresser :** {relevant_tip}

---
📄 **Correction originale :**
{get_current_feedback(original_feedback)[:500]}..."""
    else:
        return f"""🎯 **Réévaluation effectuée**

📝 **Votre justification :**
"{student_justification[:200]}..."

⚠️ **Décision :** Note maintenue à {new_stars}/5 ⭐

📋 **Raison :** {reason}

💡 **Conseil pour améliorer votre note :** {relevant_tip}

---
📄 **Correction originale :**
{get_current_feedback(original_feedback)[:500]}..."""

def get_improvement_tip(justification, ai_feedback=""):
    """Donner un conseil personnalisé PERTINENT"""
    if not justification:
        return "Pour une meilleure évaluation, expliquez précisément pourquoi votre réponse est correcte."
    
    justification_lower = justification.lower()
    ai_feedback_lower = ai_feedback.lower() if ai_feedback else ""
    
    # Analyser le contexte de l'exercice depuis le feedback IA
    if any(word in ai_feedback_lower for word in ['équation', 'equation', 'algèbre', 'algebra', 'mathématique', 'mathematical']):
        # Exercice de maths
        if any(word in justification_lower for word in ['solution', 'résultat', 'result']):
            return "Pour les équations, montrez étape par étape comment vous arrivez à votre solution."
        else:
            return "Précisez chaque étape de votre raisonnement mathématique."
    
    elif any(word in ai_feedback_lower for word in ['géométrie', 'geometry', 'angle', 'triangle', 'cercle', 'circle']):
        # Exercice de géométrie
        return "En géométrie, précisez toujours les théorèmes ou propriétés utilisés."
    
    elif any(word in ai_feedback_lower for word in ['unité', 'unit', 'cm', 'm', 'km', 'gramme', 'gram', 'litre', 'liter']):
        # Exercice avec unités
        return "N'oubliez pas d'inclure les unités dans votre réponse finale."
    
    elif any(word in justification_lower for word in ['même', 'same', 'identique', 'identical']):
        # L'élève dit avoir la même chose
        return "Pour prouver l'équivalence, montrez la transformation étape par étape."
    
    elif any(word in justification_lower for word in ['méthode', 'method', 'raisonnement', 'reasoning']):
        # L'élève parle de sa méthode
        return "Décrivez clairement votre méthode de résolution."
    
    else:
        # Conseil général
        return "Soyez précis : indiquez quelle partie de votre réponse est correcte et pourquoi."
    
@app.route('/api/contest-evaluation', methods=['POST'])
def contest_evaluation():
    """Gérer une contestation AVEC réévaluation par l'IA"""
    try:
        data = request.json
        print(f"=== 📝 CONTESTATION REÇUE POUR RÉÉVALUATION IA ===")
        
        # 1. Récupérer la réponse existante
        reponse = StudentResponse.query.get(data['reponse_id'])
        if not reponse:
            return jsonify({'success': False, 'message': 'Réponse non trouvée'})
        
        # 2. Récupérer l'exercice et les informations
        exercice = Exercice.query.get(reponse.exercice_id)
        eleve = User.query.get(reponse.user_id)
        
        if not exercice or not eleve:
            return jsonify({'success': False, 'message': 'Exercice ou élève non trouvé'})
        
        # 3. PRÉPARER LE PROMPT POUR L'IA - RÉÉVALUATION COMPLÈTE
        lang = data.get('lang', 'fr')
        question = exercice.question_fr if lang == 'fr' else exercice.question_en
        
        if lang == 'en':
            prompt = f"""
RE-EVALUATE a student's answer considering their contestation arguments.

📘 ORIGINAL PROBLEM:
{question}

📜 STUDENT'S ORIGINAL ANSWER:
{reponse.reponse_eleve}

🎯 ORIGINAL AI CORRECTION (current grade: {reponse.etoiles}/5):
{parse_analysis_json(reponse.analyse_ia).get('original', reponse.analyse_ia)}

📝 STUDENT'S CONTESTATION ARGUMENTS:
"{data.get('justification', '')}"

⭐ STUDENT'S PROPOSED GRADE: {data.get('proposed_stars', reponse.etoiles)}/5

🔍 YOUR TASK:
1. RE-EVALUATE the student's answer considering their arguments
2. Decide if their arguments are valid and justify your decision
3. Adjust the grade if warranted (0-5 stars)
4. Provide detailed feedback explaining your decision

🎯 IMPORTANT CONSIDERATIONS:
- If the student shows their answer is equivalent to the expected answer, adjust the grade
- If they demonstrate a valid alternative method, acknowledge it
- If they point out a minor error that doesn't invalidate the reasoning, consider partial credit
- Be fair: reward good reasoning even with minor calculation errors

📤 FORMAT:
Analysis of contestation: [...]
New grade: X/5
Decision: [Grade increased/maintained/decreased] because [...]
Detailed feedback: [...]
""".strip()
        else:
            prompt = f"""
RÉÉVALUEZ la réponse d'un élève en considérant ses arguments de contestation.

📘 PROBLÈME ORIGINAL :
{question}

📜 RÉPONSE ORIGINALE DE L'ÉLÈVE :
{reponse.reponse_eleve}

🎯 CORRECTION IA ORIGINALE (note actuelle : {reponse.etoiles}/5) :
{parse_analysis_json(reponse.analyse_ia).get('original', reponse.analyse_ia)}

📝 ARGUMENTS DE CONTESTATION DE L'ÉLÈVE :
"{data.get('justification', '')}"

⭐ NOTE PROPOSÉE PAR L'ÉLÈVE : {data.get('proposed_stars', reponse.etoiles)}/5

🔍 VOTRE TÂCHE :
1. RÉÉVALUER la réponse de l'élève en considérant ses arguments
2. Décider si ses arguments sont valides et justifier votre décision
3. Ajuster la note si justifié (0-5 étoiles)
4. Fournir un feedback détaillé expliquant votre décision

🎯 CONSIDÉRATIONS IMPORTANTES :
- Si l'élève montre que sa réponse est équivalente à la réponse attendue, ajustez la note
- S'il démontre une méthode alternative valide, reconnaissez-la
- S'il pointe une erreur mineure qui n'invalide pas le raisonnement, considérez des points partiels
- Soyez juste : récompensez le bon raisonnement même avec des erreurs de calcul mineures

📤 FORMAT :
Analyse de la contestation : [...]
Nouvelle note : X/5
Décision : [Note augmentée/maintenue/diminuée] car [...]
Feedback détaillé : [...]
""".strip()
        
        print(f"🤖 Envoi à l'IA pour réévaluation...")
        
        # 4. APPEL À L'IA POUR RÉÉVALUATION
        try:
            chat_completion = client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            new_analysis = chat_completion.choices[0].message.content.strip()
            print("✅ Réévaluation IA reçue avec succès")
            
            # 5. EXTRACTION DE LA NOUVELLE NOTE
            new_stars = reponse.etoiles  # Par défaut, garder l'ancienne
            import re
            
            # Chercher la nouvelle note dans la réponse de l'IA
            match = re.search(r"(?:New grade|Nouvelle note|Grade|Note)\s*:\s*(\d)(?:\s*/?\s*5)?", new_analysis, re.IGNORECASE)
            if match:
                new_stars = int(match.group(1))
                print(f"⭐ Nouvelle note extraite: {new_stars}/5")
            else:
                # Fallback
                match = re.search(r"\b(\d)(?:\s*[/\\]\s*5)?\s*(?:⭐|stars|étoiles)", new_analysis, re.IGNORECASE)
                if match:
                    new_stars = min(int(match.group(1)), 5)
                    print(f"⭐ Nouvelle note extraite (format alternatif): {new_stars}/5")
            
        except Exception as e:
            print(f"❌ Erreur lors de l'appel IA: {e}")
            # Fallback aux règles simples
            justification_analysis = analyze_student_justification(
                data.get('justification', ''),
                data.get('student_answer', ''),
                reponse.analyse_ia
            )
            
            current_stars = reponse.etoiles or 0
            should_adjust, adjustment_reason, new_stars = evaluate_contestation(
                justification_analysis,
                current_stars,
                data.get('proposed_stars', current_stars)
            )
            
            new_analysis = generate_ai_response(
                should_adjust,
                adjustment_reason,
                new_stars,
                data.get('justification', ''),
                reponse.analyse_ia
            )
        
        # 6. METTRE À JOUR LA BASE DE DONNÉES
        reponse.analyse_ia = update_analysis_with_contestation(
            reponse.analyse_ia,
            data.get('justification', ''),
            data.get('proposed_stars', reponse.etoiles),
            new_analysis,
            new_stars
        )
        
        reponse.etoiles = new_stars
        db.session.commit()
        print(f"✅ Base de données mise à jour. Nouvelle note: {new_stars}/5")
        
        # 7. PRÉPARER LA RÉPONSE
        stars_changed = new_stars != (reponse.etoiles or 0)
        
        if lang == 'en':
            if stars_changed:
                message = f"Grade changed from {reponse.etoiles} to {new_stars}/5 stars!"
            else:
                message = f"Grade maintained at {new_stars}/5 stars."
        else:
            if stars_changed:
                message = f"Note changée de {reponse.etoiles} à {new_stars}/5 étoiles !"
            else:
                message = f"Note maintenue à {new_stars}/5 étoiles."
        
        return jsonify({
            'success': True,
            'new_stars': new_stars,
            'new_feedback': new_analysis,
            'old_stars': reponse.etoiles,
            'stars_changed': stars_changed,
            'message': message,
            'has_ai_reassessment': True
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Erreur dans contest_evaluation: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

# Route pour récupérer l'historique des contestations
@app.route('/api/contest-history/<int:reponse_id>', methods=['GET'])
def get_contest_history(reponse_id):
    """Récupérer l'historique des contestations pour une réponse"""
    try:
        reponse = StudentResponse.query.get(reponse_id)
        if not reponse:
            return jsonify({'success': False, 'message': 'Réponse non trouvée'})
        
        data = parse_analysis_json(reponse.analyse_ia)
        
        return jsonify({
            'success': True,
            'history': data.get('history', []),
            'current_stars': data.get('current_stars'),
            'original_feedback': data.get('original', '')
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

# Route pour réinitialiser une contestation (admin seulement)
@app.route('/api/reset-contest/<int:reponse_id>', methods=['POST'])
@login_required
def reset_contest(reponse_id):
    """Réinitialiser une contestation (admin seulement)"""
    try:
        # Vérifier que l'utilisateur est admin
        if not hasattr(current_user, 'role') or current_user.role != 'admin':
            return jsonify({'success': False, 'message': 'Accès non autorisé'})
        
        reponse = StudentResponse.query.get(reponse_id)
        if not reponse:
            return jsonify({'success': False, 'message': 'Réponse non trouvée'})
        
        data = parse_analysis_json(reponse.analyse_ia)
        
        # Réinitialiser aux valeurs originales
        original_stars = data.get('current_stars', 3)
        reponse.etoiles = original_stars  # Remettre la note d'origine
        reponse.analyse_ia = data.get('original', reponse.analyse_ia)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Contestation réinitialisée avec succès'
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Erreur reset_contest: {str(e)}")
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

@app.route("/soumettre-sequentiel", methods=["POST"])
def soumettre_sequentiel():
    from datetime import datetime, timezone
    import re
    import json  # IMPORT CRITIQUE

    print("=== 📝 SOUMISSION SÉQUENTIELLE ===")
    
    # Récupération des données du formulaire
    username = request.form.get("username")
    lang = request.form.get("lang", "fr")
    lecon_id = request.form.get("lecon_id")
    exercice_id = request.form.get("exercice_id")
    reponse_eleve = request.form.get("reponse_eleve", "").strip()
    index = int(request.form.get("index", 0))
    action = request.form.get("action", "submit")
    
    # NOUVEAU : Vérifier si c'est une contestation
    is_contestation = request.form.get("is_contestation") == "true"
    contestation_data = request.form.get("contestation_data", None)

    print(f"Username: {username}")
    print(f"Leçon ID: {lecon_id}")
    print(f"Exercice ID: {exercice_id}")
    print(f"Réponse longueur: {len(reponse_eleve)} caractères")
    print(f"Index: {index}")
    print(f"Action: {action}")
    print(f"Is Contestation: {is_contestation}")

    # CORRECTION : Utilisation de méthodes non dépréciées
    eleve = User.query.filter_by(username=username).first()
    lecon = db.session.get(Lecon, lecon_id)
    exercice = db.session.get(Exercice, exercice_id)

    if not eleve or not lecon or not exercice:
        return "Élève, leçon ou exercice non trouvé", 404

    # VARIABLES POUR LE TRAITEMENT
    reponse_id = None
    derniere_reponse = None
    analyse_ia = ""
    etoiles = 0
    
    # Si c'est une nouvelle soumission (pas une modification)
    if action == "submit" and reponse_eleve and not is_contestation:
        question = exercice.question_en if lang == "en" else exercice.question_fr

        # ✅ PROMPT de correction - BARÈME SUR 5
        if lang == "en":
            prompt = f"""
Correct the student's answer to a school exercise.

📘 Problem statement:
{question}

📜 Student's answer:
{reponse_eleve}

⭐ SCORING SCALE (5 points):
- 5: Excellent reasoning, complete methodology, correct result
- 4: Very good reasoning, appropriate method, minor calculation error
- 3: Good overall approach, method understood but imperfect application
- 2: Partial reasoning, some relevant elements but incomplete
- 1: Fragmented approach, very limited correct elements
- 0: Off-topic or no answer

🎯 IMPORTANT: Give priority to reasoning over final result. Award partial credit for correct steps.

📤 Expected format:
Analysis:
[...]
Score: X/5
Correction:
- Expert resolution: [...]
- Final answer: [...]
""".strip()
        else:
            prompt = f"""
Corrige la réponse d'un élève à un exercice scolaire.

📘 Énoncé :
{question}

📜 Réponse de l'élève :
{reponse_eleve}

⭐ BARÈME (5 points) :
- 5 : Raisonnement excellent, méthodologie complète, résultat correct
- 4 : Très bon raisonnement, méthode appropriée, erreur mineure de calcul
- 3 : Bonne démarche globale, méthode comprise mais application imparfaite
- 2 : Raisonnement partiel, éléments pertinents mais incomplets
- 1 : Démarche ébauchée, éléments corrects très limités
- 0 : Hors sujet ou absence de réponse

🎯 IMPORTANT : Privilégiez le raisonnement sur le résultat final. Accordez des points partiels pour les étapes correctes.

📤 Format attendu :
Analyse :
[...]
Note : X/5
Correction :
- Résolution experte : [...]
- Résultat final : [...]
""".strip()

        try:
            print("🤖 Appel à l'API OpenAI pour correction...")
            chat_completion = client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            analyse_ia = chat_completion.choices[0].message.content.strip()
            print("✅ Analyse IA reçue avec succès")
        except Exception as e:
            analyse_ia = f"Erreur IA : {str(e)[:200]}"
            print(f"❌ Erreur lors de l'appel IA: {e}")

        # Extraction de la note sur 5 avec amélioration
        etoiles = 0
        match = re.search(r"(Note|Score)\s*:\s*(\d)(?:\s*/?\s*5)?", analyse_ia, re.IGNORECASE)
        if match:
            etoiles = int(match.group(2))
            print(f"⭐ Note extraite: {etoiles}/5")
        else:
            # Recherche plus large
            match = re.search(r"\b(\d)(?:\s*[/\\]\s*5)?\s*(?:⭐|stars|étoiles|points)", analyse_ia, re.IGNORECASE)
            if match:
                etoiles = min(int(match.group(1)), 5)
                print(f"⭐ Note extraite (format alternatif): {etoiles}/5")
            else:
                # Fallback : analyser le texte pour estimer la note
                if "excellent" in analyse_ia.lower() or "5" in analyse_ia:
                    etoiles = 5
                elif "très bon" in analyse_ia.lower() or "very good" in analyse_ia.lower():
                    etoiles = 4
                elif "bon" in analyse_ia.lower() or "good" in analyse_ia.lower():
                    etoiles = 3
                elif "partiel" in analyse_ia.lower() or "partial" in analyse_ia.lower():
                    etoiles = 2
                elif "fragmented" in analyse_ia.lower() or "ébauchée" in analyse_ia.lower():
                    etoiles = 1
                else:
                    etoiles = 0
                print(f"⭐ Note estimée par analyse: {etoiles}/5")

        # ============================================
        # SECTION CRITIQUE : STRUCTURATION JSON
        # ============================================
        try:
            # NOUVEAU : Structurer le feedback en JSON pour supporter les contestations
            feedback_json = {
                "original": analyse_ia,
                "history": [],  # Liste vide correcte
                "current_stars": etoiles,
                "current_feedback": analyse_ia,
                "metadata": {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "exercise_id": exercice.id,
                    "student_id": eleve.id,
                    "language": lang
                }
            }

            # CONVERTIR EN JSON STRING
            feedback_json_str = json.dumps(feedback_json, ensure_ascii=False, indent=2)
            print(f"✅ JSON créé - Taille: {len(feedback_json_str)} caractères")
            
            # Sauvegarde réponse STRUCTURÉE
            nouvelle = StudentResponse(
                user_id=eleve.id,
                exercice_id=exercice.id,
                reponse_eleve=reponse_eleve,
                analyse_ia=feedback_json_str,  # JSON structuré
                etoiles=etoiles,
                timestamp=datetime.now(timezone.utc)
            )
            db.session.add(nouvelle)
            db.session.commit()
            reponse_id = nouvelle.id
            print(f"✅ Réponse sauvegardée (ID: {reponse_id}) avec JSON structuré")
            
        except Exception as e:
            print(f"❌ Erreur lors de la sauvegarde avec JSON: {e}")
            
            # Fallback : sauvegarde sans JSON
            try:
                nouvelle = StudentResponse(
                    user_id=eleve.id,
                    exercice_id=exercice.id,
                    reponse_eleve=reponse_eleve,
                    analyse_ia=analyse_ia,  # Texte simple
                    etoiles=etoiles,
                    timestamp=datetime.now(timezone.utc)
                )
                db.session.add(nouvelle)
                db.session.commit()
                reponse_id = nouvelle.id
                print(f"✅ Réponse sauvegardée (fallback texte simple)")
            except Exception as fallback_error:
                print(f"❌ Erreur lors du fallback: {fallback_error}")
                return f"Erreur base de données: {fallback_error}", 500
        # ============================================

        # ✅ REMÉDIATION si note < 3/5 (0, 1 ou 2/5)
        if etoiles < 3:
            print(f"🔄 Génération remédiation (note: {etoiles}/5)")
            if lang == "en":
                remediation_prompt = f"""
Generate a new math remediation exercise for a student who scored {etoiles}/5 on the previous exercise.

🧩 Context:
- Original question: {question}
- Student's answer: {reponse_eleve}
- Student's score: {etoiles}/5

✍️ Instructions:
- Create an exercise with equivalent difficulty focusing on the same concepts
- Adapt the exercise to address the specific difficulties shown in the student's answer
- Write clear instructions
- Provide the expected final answer
- Provide a short hint to guide the student

🎯 Output format:
Question: ...
Expected answer: ...
Hint: ...
""".strip()
            else:
                remediation_prompt = f"""
Génère un nouvel exercice de remédiation en mathématiques pour un élève qui a obtenu {etoiles}/5 sur l'exercice précédent.

🧩 Contexte :
- Énoncé initial : {question}
- Réponse de l'élève : {reponse_eleve}
- Note de l'élève : {etoiles}/5

✍️ Consignes :
- Crée un exercice de difficulté équivalente ciblant les mêmes concepts
- Adapte l'exercice pour adresser les difficultés spécifiques montrées dans la réponse de l'élève
- Rédige un énoncé clair
- Donne la réponse attendue
- Fournis un court indice pour aider l'élève

🎯 Format attendu :
Question : ...
Réponse attendue : ...
Indice : ...
""".strip()

            try:
                remediation_completion = client.chat.completions.create(
                    model="gpt-4",
                    messages=[{"role": "user", "content": remediation_prompt}],
                    temperature=0.7,
                )
                remediation_content = remediation_completion.choices[0].message.content.strip()
                print("✅ Remédiation générée")
            except Exception as e:
                remediation_content = f"Erreur IA lors de la génération de la remédiation : {str(e)[:200]}"
                print(f"❌ Erreur génération remédiation: {e}")

            # Création de la suggestion de remédiation
            try:
                nouvelle_suggestion = RemediationSuggestion(
                    user_id=eleve.id,
                    theme=exercice.theme,
                    lecon=lecon.titre_fr,
                    message=f"Exercice de remédiation proposé automatiquement (note: {etoiles}/5).",
                    exercice_suggere=remediation_content,
                    statut="en_attente",
                    timestamp=datetime.now(timezone.utc)
                )
                db.session.add(nouvelle_suggestion)
                db.session.commit()
                print(f"✅ Suggestion de remédiation sauvegardée (note: {etoiles}/5)")
            except Exception as e:
                print(f"⚠️ Erreur sauvegarde remédiation: {e}")

        print("=== ✅ RÉPONSE SÉQUENTIELLE SAUVEGARDÉE ===")
    
    # TRAITEMENT SPÉCIAL POUR LES CONTESTATIONS (via API)
    elif is_contestation and contestation_data:
        try:
            contest_data = json.loads(contestation_data)
            print(f"📝 Traitement contestation directe: {contest_data}")
            
            # Utiliser l'API contest-evaluation pour le traitement
            # Cette partie sera gérée par le JavaScript
            pass
            
        except Exception as e:
            print(f"❌ Erreur traitement contestation: {e}")

    # Récupérer tous les exercices pour déterminer s'il y a un suivant
    exercices = Exercice.query.filter_by(lecon_id=lecon_id).all()
    total_exercices = len(exercices)
    next_index = index + 1
    has_next = next_index < total_exercices

    # Récupérer la dernière réponse si elle existe
    if action == "submit" and reponse_eleve and not is_contestation:
        derniere_reponse = db.session.get(StudentResponse, reponse_id) if reponse_id else None
    else:
        # Chercher la dernière réponse existante
        derniere_reponse = StudentResponse.query.filter_by(
            user_id=eleve.id, 
            exercice_id=exercice.id
        ).order_by(StudentResponse.timestamp.desc()).first()
        
        # Si contestation, utiliser la réponse contestée
        if is_contestation and reponse_id:
            derniere_reponse = db.session.get(StudentResponse, reponse_id)

    # Gérer l'affichage du feedback
    show_feedback = False
    if action == "submit" and reponse_eleve:
        show_feedback = True
    elif is_contestation:
        show_feedback = True

    # Afficher le template avec les options appropriées
    return render_template(
        "exercice_sequentiel.html",  # Utiliser le nouveau template avec contestation
        exercice=exercice,
        eleve=eleve,
        lecon=lecon,
        lang=lang,
        index=index,
        total=total_exercices,
        reponse=derniere_reponse,
        show_feedback=show_feedback,
        has_next=has_next,
        next_index=next_index,
        current_reponse=reponse_eleve,
        is_contestation=is_contestation
    )

from datetime import datetime, timezone

@app.route("/faire-exercice-sequentiel")
def faire_exercice_sequentiel():
    username = request.args.get("username")
    lang = request.args.get("lang", "fr")
    lecon_id = request.args.get("lecon_id")
    index = int(request.args.get("index", 0))
    
    eleve = User.query.filter_by(username=username).first()
    lecon = db.session.get(Lecon, lecon_id)
    
    if not eleve:
        print(f"❌ Élève non trouvé avec username: {username}")
        return f"Élève non trouvé: {username}", 404
    if not lecon:
        print("❌ Leçon non trouvée")
        return "Leçon non trouvée", 404
    
    # Récupérer tous les exercices de la leçon
    exercices = Exercice.query.filter_by(lecon_id=lecon_id).all()
    
    if index >= len(exercices):
        # Tous les exercices sont terminés
        return redirect(f"/tableau-de-bord?username={username}&lang={lang}&message=sequence_complete")
    
    exercice = exercices[index]
    
    return render_template(
        "exercice_sequentiel.html",
        exercice=exercice,
        eleve=eleve,
        lecon=lecon,
        lang=lang,
        index=index,
        total=len(exercices),
        show_feedback=False,  # ✅ Pas de rétroaction au premier affichage
        has_next=(index + 1) < len(exercices)  # ✅ Indique s'il y a un suivant
    )


import re

@app.route("/soumettre-remediation/<int:remediation_id>", methods=["POST"])
def soumettre_remediation(remediation_id):
    from datetime import datetime
    reponse_eleve = request.form.get("reponse_eleve") or request.form.get("reponse", "").strip()

    remediation = RemediationSuggestion.query.get_or_404(remediation_id)
    user = remediation.user

    if not reponse_eleve:
        return "Réponse vide", 400

    enonce = remediation.exercice_suggere or ""
    lang = user.langue if hasattr(user, "langue") and user.langue == "en" else "fr"

    # ✅ NOUVEAU PROMPT avec barème sur 5
    if lang == "en":
        prompt = f"""
Correct the student's answer to a school exercise.

📘 Problem statement:
{enonce}

📜 Student's answer:
{reponse_eleve}

⭐ SCORING SCALE (5 points):
- 5: Excellent reasoning, complete methodology, correct result
- 4: Very good reasoning, appropriate method, minor calculation error
- 3: Good overall approach, method understood but imperfect application
- 2: Partial reasoning, some relevant elements but incomplete
- 1: Fragmented approach, very limited correct elements
- 0: Off-topic or no answer

🎯 IMPORTANT: Give priority to reasoning over final result. Award partial credit for correct steps.

📤 Expected format:
Analysis:
[...]
Score: X/5
Correction:
- Expert resolution: [...]
- Final answer: [...]
""".strip()
    else:
        prompt = f"""
Corrige la réponse d'un élève à un exercice scolaire.

📘 Énoncé :
{enonce}

📜 Réponse de l'élève :
{reponse_eleve}

⭐ BARÈME (5 points) :
- 5 : Raisonnement excellent, méthodologie complète, résultat correct
- 4 : Très bon raisonnement, méthode appropriée, erreur mineure de calcul
- 3 : Bonne démarche globale, méthode comprise mais application imparfaite
- 2 : Raisonnement partiel, éléments pertinents mais incomplets
- 1 : Démarche ébauchée, éléments corrects très limités
- 0 : Hors sujet ou absence de réponse

🎯 IMPORTANT : Privilégiez le raisonnement sur le résultat final. Accordez des points partiels pour les étapes correctes.

📤 Format attendu :
Analyse :
[...]
Note : X/5
Correction :
- Résolution experte : [...]
- Résultat final : [...]
""".strip()

    try:
        chat_completion = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
        )
        analyse_ia = chat_completion.choices[0].message.content.strip()
    except Exception as e:
        return f"Erreur IA : {e}", 500

    # ✅ EXTRACTION DE NOTE SUR 5
    etoiles = 0
    match = re.search(r"(Note|Score)\s*:\s*(\d)/5", analyse_ia, re.IGNORECASE)
    if match:
        etoiles = int(match.group(2))
        print(f"⭐ Note remédiation extraite: {etoiles}/5")
    else:
        # Fallback si le format /5 n'est pas respecté
        match = re.search(r"(Note|Score)\s*:\s*(\d)", analyse_ia, re.IGNORECASE)
        if match:
            etoiles = min(int(match.group(2)), 5)  # Limite à 5 maximum
            print(f"⭐ Note remédiation extraite (sans /5): {etoiles}/5")
        else:
            print("⚠️ Impossible d'extraire la note de l'analyse IA")

    # ✅ Mise à jour du statut de la remédiation
    if etoiles >= 3:  # Si note ≥ 3/5, la remédiation est réussie
        remediation.statut = "reussie"
        print(f"✅ Remédiation réussie (note: {etoiles}/5)")
    else:
        remediation.statut = "en_attente"  # Reste en attente si échec
        print(f"🔄 Remédiation à revoir (note: {etoiles}/5)")

    new_response = StudentResponse(
        user_id=user.id,
        exercice_id=None,
        reponse_eleve=reponse_eleve,
        analyse_ia=analyse_ia,
        etoiles=etoiles,
        timestamp=datetime.utcnow()
    )
    db.session.add(new_response)
    db.session.commit()

    return render_template(
        "feedback_exercice.html",
        reponse=reponse_eleve,
        analyse=analyse_ia,
        etoiles=etoiles,
        redirect_url=f"/eleve/remediations?username={user.username}&lang={lang}",
        lang=lang,
        is_remediation=True
    )



@app.route("/enseignant/nouvelles-remediations")
def nouvelles_remediations():
    if not session.get("enseignant_id"):
        return redirect("/login-enseignant")

    suggestions = RemediationSuggestion.query \
        .join(User, RemediationSuggestion.user_id == User.id) \
        .filter(User.enseignant_id == session["enseignant_id"]) \
        .filter(RemediationSuggestion.notif_envoyee == False) \
        .all()

    return render_template("enseignant_nouvelles_remediations.html", suggestions=suggestions)

@app.route("/enseignant/marquer-vue/<int:id>")
def marquer_remediation_vue(id):
    suggestion = RemediationSuggestion.query.get_or_404(id)
    suggestion.notif_envoyee = True
    db.session.commit()
    flash("Remédiation marquée comme vue.", "success")
    return redirect("/enseignant/nouvelles-remediations")

@app.route("/exercice_suggeres-eleve")
def exercice_suggeres_eleve():
    lang = session.get("lang", "fr")
    username = request.args.get("username")

    if not username:
        return redirect(url_for("login_eleve"))

    eleve = User.query.options(joinedload(User.niveau)).filter_by(username=username, role="élève").first()
    if not eleve:
        return "Élève non trouvé", 404

    niveau = Niveau.query.options(
        joinedload(Niveau.matieres)
        .joinedload(Matiere.unites)
        .joinedload(Unite.lecons)
        .joinedload(Lecon.exercices)
    ).filter_by(id=eleve.niveau_id).first()

    return render_template(
        "exercice_suggeres.html",
        niveaux=[niveau],  # on le met dans une liste pour compatibilité template
        lang=lang,
        eleve=eleve
    )

from sqlalchemy import select
from flask import render_template, session
from models import Niveau, Matiere, Unite, Lecon, Exercice
from app import db  # Importez db depuis votre application

@app.route("/exercice_suggeres")
def afficher_exercice_suggeres():
    lang = session.get("lang", "fr")
    
    # Utilisez db.engine au lieu de database.engine
    conn = db.engine.connect()

    Niveau_data = []
    Niveau_rows = conn.execute(select(Niveau)).scalars().all()

    for niveau in Niveau_rows:
        matiere_rows = conn.execute(select(Matiere).where(Matiere.niveau_id == niveau.id)).scalars().all()
        matiere_data = []

        for matiere in matiere_rows:
            unite_rows = conn.execute(select(Unite).where(Unite.matiere_id == matiere.id)).scalars().all()
            unite_data = []

            for unite in unite_rows:
                lecon_rows = conn.execute(select(Lecon).where(Lecon.unite_id == unite.id)).scalars().all()
                lecon_data = []

                for lecon in lecon_rows:
                    exercice_rows = conn.execute(select(Exercice).where(Exercice.lecon_id == lecon.id)).scalars().all()
                    exo_data = []
                    for ex in exercice_rows:
                        exo_data.append({
                            "question_fr": ex.question_fr,
                            "question_en": ex.question_en
                        })

                    lecon_data.append({
                        "titre_fr": lecon.titre_fr,
                        "titre_en": lecon.titre_en,
                        "exercice": exo_data
                    })

                unite_data.append({
                    "nom": unite.nom,
                    "lecon": lecon_data
                })

            matiere_data.append({
                "nom": matiere.nom,
                "unite": unite_data
            })

        Niveau_data.append({
            "nom": niveau.nom,
            "matiere": matiere_data
        })

    conn.close()  # Important : fermez la connexion
    return render_template("exercice_suggeres.html", Niveau=Niveau_data, lang=lang)

@app.route("/progression-eleve")
def progression_eleve():
    username = request.args.get("username")
    eleve = User.query.filter_by(username=username).first()
    if not eleve:
        return "Élève introuvable", 404

    reponses = StudentResponse.query.filter_by(user_id=eleve.id).all()
    donnees = []
    for r in reponses:
        exercice = exercice.query.get(r.exercice_id)
        donnees.append({
            "theme": exercice.theme,
            "niveau": exercice.niveau,
            "enonce": exercice.enonce,
            "reponse_eleve": r.reponse_eleve,
            "analyse_ia": r.analyse_ia,
            "etoiles": r.etoiles or "-"
        })

    return render_template("progression_eleve.html", eleve=eleve, exercice=donnees)

@app.route("/historique")
def historique_eleve():
    username = request.args.get("username")
    exercice_id = request.args.get("exercice_id")
    lang = request.args.get("lang", "fr")

    # ✅ DÉTECTION DU CONTEXTE : Priorité à l'enseignant s'il y a conflit
    parent_email = session.get("parent_email")
    enseignant_id = session.get("enseignant_id")
    
    # DEBUG
    print(f"SESSION - parent_email: {parent_email}")
    print(f"SESSION - enseignant_id: {enseignant_id}")
    
    # ✅ LOGIQUE DE PRIORITÉ : 
    # 1. Si enseignant_id existe → c'est un enseignant (priorité haute)
    # 2. Si parent_email existe ET pas d'enseignant_id → c'est un parent
    # 3. Sinon → c'est l'élève
    
    if enseignant_id:
        # L'utilisateur est connecté comme enseignant (même s'il a aussi parent_email)
        is_enseignant_access = True
        is_parent_access = False
        is_eleve_direct_access = False
        print(f"ACCÈS - ENSEIGNANT prioritaire (ID: {enseignant_id})")
    elif parent_email:
        # L'utilisateur est connecté comme parent (sans enseignant_id)
        is_parent_access = True
        is_enseignant_access = False
        is_eleve_direct_access = False
        print(f"ACCÈS - PARENT (email: {parent_email})")
    else:
        # Vérifier si l'élève accède à son propre historique
        eleve_session_username = session.get("username")
        is_eleve_direct_access = eleve_session_username == username
        is_parent_access = False
        is_enseignant_access = False
        print(f"ACCÈS - ÉLÈVE (session: {eleve_session_username}, requested: {username})")

    eleve = User.query.filter_by(username=username).first()
    if not eleve:
        return "Élève introuvable", 404

    # Récupérer l'ID de l'élève et son niveau
    eleve_id = eleve.id
    niveau_eleve = eleve.niveau  # Récupère l'objet Niveau de l'élève
    
    if not niveau_eleve:
        return "Niveau de l'élève non défini", 404
    
    niveau_eleve_nom = niveau_eleve.nom
    niveau_eleve_id = niveau_eleve.id
    
    print(f"ÉLÈVE - {eleve.nom_complet} - Niveau: {niveau_eleve_nom} (ID: {niveau_eleve_id})")

    # Récupérer toutes les réponses de l'élève
    reponses_exos = StudentResponse.query.filter_by(user_id=eleve_id).all()
    
    # Créer un dictionnaire pour suivre quels exercices ont été faits par ID
    exercices_faits_par_id = {r.exercice_id for r in reponses_exos if r.exercice_id}
    
    # Récupérer UNIQUEMENT le niveau de l'élève
    niveau_eleve_obj = Niveau.query.get(niveau_eleve_id)
    
    if not niveau_eleve_obj:
        return "Niveau de l'élève introuvable", 404
    
    # Structure pour organiser les données (UNIQUEMENT pour le niveau de l'élève)
    data_structure = {
        "niveaux": {}
    }
    
    # Compteurs globaux (UNIQUEMENT pour le niveau de l'élève)
    total_exercices_effectues = 0
    total_exercices_restants = 0
    total_exercices_totaux = 0
    
    # Initialiser le niveau de l'élève dans la structure
    data_structure["niveaux"][niveau_eleve_nom] = {
        "matieres": {},
        "total_effectues": 0,
        "total_restants": 0,
        "total_exercices": 0
    }
    
    # Parcourir les matières du niveau de l'élève
    for matiere in niveau_eleve_obj.matieres:
        matiere_nom = matiere.nom
        
        # Initialiser la matière
        data_structure["niveaux"][niveau_eleve_nom]["matieres"][matiere_nom] = {
            "unites": {},
            "total_effectues": 0,
            "total_restants": 0,
            "total_exercices": 0
        }
        
        # Parcourir les unités de cette matière
        for unite in matiere.unites:
            unite_nom = unite.nom
            
            # Initialiser l'unité
            data_structure["niveaux"][niveau_eleve_nom]["matieres"][matiere_nom]["unites"][unite_nom] = {
                "lecons": {},
                "total_effectues": 0,
                "total_restants": 0,
                "total_exercices": 0
            }
            
            # Parcourir les leçons de cette unité
            for lecon in unite.lecons:
                lecon_nom = lecon.titre_fr if lang == "fr" else lecon.titre_en
                
                # Initialiser la leçon
                data_structure["niveaux"][niveau_eleve_nom]["matieres"][matiere_nom]["unites"][unite_nom]["lecons"][lecon_nom] = {
                    "exercices": [],
                    "exercices_effectues": 0,
                    "exercices_restants": 0,
                    "exercices_totaux": 0,
                    "lecon_id": lecon.id
                }
                
                # Récupérer tous les exercices de cette leçon
                exercices_lecon = Exercice.query.filter_by(lecon_id=lecon.id).all()
                total_exercices_lecon = len(exercices_lecon)
                data_structure["niveaux"][niveau_eleve_nom]["matieres"][matiere_nom]["unites"][unite_nom]["lecons"][lecon_nom]["exercices_totaux"] = total_exercices_lecon
                
                # Mettre à jour les totaux du niveau
                total_exercices_totaux += total_exercices_lecon
    
    print(f"TOTAL EXERCICES DISPONIBLES pour {niveau_eleve_nom}: {total_exercices_totaux}")
    
    # Maintenant, traiter les exercices effectués par l'élève (uniquement ceux de son niveau)
    for r in reponses_exos:
        ex = Exercice.query.get(r.exercice_id) if r.exercice_id else None
        if not ex:
            continue
            
        # Naviguer dans la hiérarchie pour vérifier le niveau
        lecon = ex.lecon
        if not lecon:
            continue
            
        unite = lecon.unite if lecon else None
        if not unite:
            continue
            
        matiere = unite.matiere if unite else None
        if not matiere:
            continue
            
        niveau = matiere.niveau if matiere else None
        if not niveau:
            continue
        
        # VÉRIFIER SI L'EXERCICE EST DU NIVEAU DE L'ÉLÈVE
        if niveau.id != niveau_eleve_id:
            print(f"EXERCICE {ex.id} ignoré - Niveau: {niveau.nom} (pas le niveau de l'élève)")
            continue
        
        # Récupérer les noms avec les bons attributs
        niveau_nom = niveau.nom
        matiere_nom = matiere.nom
        unite_nom = unite.nom
        lecon_nom = lecon.titre_fr if lang == "fr" else lecon.titre_en
        
        # Vérifier que la structure existe
        if (niveau_nom in data_structure["niveaux"] and 
            matiere_nom in data_structure["niveaux"][niveau_nom]["matieres"] and
            unite_nom in data_structure["niveaux"][niveau_nom]["matieres"][matiere_nom]["unites"] and
            lecon_nom in data_structure["niveaux"][niveau_nom]["matieres"][matiere_nom]["unites"][unite_nom]["lecons"]):
            
            # Ajouter l'exercice à la leçon
            theme = unite_nom if unite else "—"
            enonce = ex.question_fr if lang == "fr" else (ex.question_en if ex else "Réponse libre (remédiation)")
            
            exercice_data = {
                "id": r.id,
                "theme": theme,
                "enonce": enonce,
                "reponse_eleve": r.reponse_eleve,
                "analyse_ia": r.analyse_ia or "—",
                "etoiles": r.etoiles if r.etoiles is not None else 0,
                "date": r.timestamp.strftime("%d/%m/%Y") if r.timestamp else ""
            }
            
            data_structure["niveaux"][niveau_nom]["matieres"][matiere_nom]["unites"][unite_nom]["lecons"][lecon_nom]["exercices"].append(exercice_data)
            
            # Mettre à jour les compteurs
            data_structure["niveaux"][niveau_nom]["matieres"][matiere_nom]["unites"][unite_nom]["lecons"][lecon_nom]["exercices_effectues"] += 1
            total_exercices_effectues += 1
    
    print(f"EXERCICES EFFECTUÉS dans le niveau {niveau_eleve_nom}: {total_exercices_effectues}")
    
    # Calculer les exercices restants et totaux pour chaque niveau de la hiérarchie
    for niveau_nom, niveau_data in data_structure["niveaux"].items():
        niveau_total_effectues = 0
        niveau_total_restants = 0
        niveau_total_exercices = 0
        
        for matiere_nom, matiere_data in niveau_data["matieres"].items():
            matiere_total_effectues = 0
            matiere_total_restants = 0
            matiere_total_exercices = 0
            
            for unite_nom, unite_data in matiere_data["unites"].items():
                unite_total_effectues = 0
                unite_total_restants = 0
                unite_total_exercices = 0
                
                for lecon_nom, lecon_data in unite_data["lecons"].items():
                    # Calculer les exercices restants pour cette leçon
                    exercices_restants = lecon_data["exercices_totaux"] - lecon_data["exercices_effectues"]
                    lecon_data["exercices_restants"] = max(0, exercices_restants)
                    
                    unite_total_effectues += lecon_data["exercices_effectues"]
                    unite_total_restants += lecon_data["exercices_restants"]
                    unite_total_exercices += lecon_data["exercices_totaux"]
                
                unite_data["total_effectues"] = unite_total_effectues
                unite_data["total_restants"] = unite_total_restants
                unite_data["total_exercices"] = unite_total_exercices
                
                matiere_total_effectues += unite_total_effectues
                matiere_total_restants += unite_total_restants
                matiere_total_exercices += unite_total_exercices
            
            matiere_data["total_effectues"] = matiere_total_effectues
            matiere_data["total_restants"] = matiere_total_restants
            matiere_data["total_exercices"] = matiere_total_exercices
            
            niveau_total_effectues += matiere_total_effectues
            niveau_total_restants += matiere_total_restants
            niveau_total_exercices += matiere_total_exercices
        
        niveau_data["total_effectues"] = niveau_total_effectues
        niveau_data["total_restants"] = niveau_total_restants
        niveau_data["total_exercices"] = niveau_total_exercices
        
        total_exercices_restants = niveau_total_restants
    
    # Calculer le total général des exercices disponibles dans le niveau
    total_exercices_disponibles = total_exercices_totaux
    
    print(f"RÉSUMÉ FINAL - Niveau: {niveau_eleve_nom}")
    print(f"  Exercices effectués: {total_exercices_effectues}")
    print(f"  Exercices restants: {total_exercices_restants}")
    print(f"  Exercices totaux: {total_exercices_disponibles}")
    
    # Réponses aux tests sommatifs (uniquement ceux du niveau de l'élève)
    reponses_tests = TestResponse.query.filter_by(user_id=eleve_id).all()
    donnees_tests = []
    for t in reponses_tests:
        test = t.test
        if not test:
            continue
            
        # Vérifier si le test est du niveau de l'élève
        if test.unite and test.unite.matiere and test.unite.matiere.niveau:
            if test.unite.matiere.niveau.id != niveau_eleve_id:
                continue  # Ignorer les tests qui ne sont pas du niveau de l'élève
        
        if test and test.unite:
            unite_nom_test = test.unite.nom
        else:
            unite_nom_test = "—"
            
        enonce_test = test.question_fr if test and lang == "fr" else (test.question_en if test else "—")

        reponses_ordonnees = ""
        if isinstance(t.reponses_exercices, dict):
            try:
                reponses_ordonnees = "\n\n".join(
                    t.reponses_exercices[str(i + 1)] for i in range(len(t.reponses_exercices))
                )
            except Exception:
                reponses_ordonnees = "\n".join(t.reponses_exercices.values())

        donnees_tests.append({
            "unite": unite_nom_test,
            "question": enonce_test,
            "reponse_eleve": reponses_ordonnees or "—",
            "analyse_ia": t.analyse_ia or "—",
            "etoiles": t.etoiles if t.etoiles is not None else 0,
            "date": t.timestamp.strftime("%d/%m/%Y") if t.timestamp else ""
        })

    return render_template(
        "historique_eleve.html",
        eleve=eleve,
        niveau_eleve=niveau_eleve_nom,  # Ajout du nom du niveau pour l'affichage
        lang=lang,
        data_structure=data_structure,
        total_exercices_effectues=total_exercices_effectues,
        total_exercices_restants=total_exercices_restants,
        total_exercices_disponibles=total_exercices_disponibles,
        tests=donnees_tests,
        is_parent_access=is_parent_access,
        is_enseignant_access=is_enseignant_access,
        is_eleve_direct_access=is_eleve_direct_access
    )

@app.route("/enseignant-remediations")
def enseignant_remediations():
    suggestions = RemediationSuggestion.query.all()
    donnees = []
    for s in suggestions:
        eleve = User.query.get(s.user_id)
        donnees.append({
            "eleve_nom": eleve.nom_complet,
            "niveau": eleve.niveau,
            "username": eleve.username,
            "theme": s.theme,
            "lecon": s.lecon,
            "message": s.message,
            "timestamp": s.timestamp.strftime("%d/%m/%Y %H:%M")
        })
    return render_template("enseignant_remediations.html", suggestions=donnees)

@app.route("/admin/creer-eleve", methods=["GET", "POST"])
@admin_required
def admin_creer_eleve():
    enseignants = Enseignant.query.all()
    niveaux = Niveau.query.all()
    lang = session.get("lang", "fr")

    if request.method == "POST":
        nom_complet = request.form.get("nom_complet")
        email = request.form.get("email")
        niveau_id = request.form.get("niveau_id")
        enseignant_id = request.form.get("enseignant_id")
        parents_emails = request.form.get("parents")
        telephone1 = request.form.get("telephone1")
        telephone2 = request.form.get("telephone2")
        mot_de_passe_clair = request.form.get("mot_de_passe")

        if not all([nom_complet, email, niveau_id, enseignant_id]):
            return "Tous les champs sont obligatoires", 400

        if User.query.filter_by(email=email).first():
            return "Un élève avec cet email existe déjà", 409

        if not mot_de_passe_clair:
            fruits = ["banane", "pomme", "mangue", "orange", "cerise", "kiwi", "raisin"]
            mot_de_passe_clair = random.choice(fruits) + str(random.randint(10, 99))

        i = 1
        while True:
            username = f"student_{i:03d}"
            if not User.query.filter_by(username=username).first():
                break
            i += 1

        eleve = User(
            username=username,
            nom_complet=nom_complet,
            email=email,
            niveau_id=niveau_id,
            role="élève",
            enseignant_id=enseignant_id
        )
        eleve.mot_de_passe = mot_de_passe_clair
        db.session.add(eleve)
        db.session.commit()

        if parents_emails:
            emails = [e.strip() for e in parents_emails.split(",") if e.strip()]
            for index, email_parent in enumerate(emails):
                parent = Parent.query.filter_by(email=email_parent).first()
                if not parent:
                    tel = telephone1 if index == 0 else telephone2
                    parent = Parent(nom_complet="Parent inconnu", email=email_parent, telephone=tel)
                    db.session.add(parent)
                    db.session.commit()

                if not ParentEleve.query.filter_by(parent_id=parent.id, eleve_id=eleve.id).first():
                    lien = ParentEleve(parent_id=parent.id, eleve_id=eleve.id)
                    db.session.add(lien)

        db.session.commit()

        return render_template(
            "eleve_cree.html",
            username=username,
            mot_de_passe=mot_de_passe_clair,
            lang=lang
        )

    return render_template("admin_creer_eleve.html", enseignants=enseignants, niveaux=niveaux, lang=lang)

from flask import request, session, redirect, render_template
from werkzeug.utils import secure_filename
import os
from models import db, Niveau, Exercice


@app.route("/admin/ajouter-exercice", methods=["GET", "POST"])
def ajouter_exercice():
    if not session.get("enseignant_id") and not session.get("is_admin"):
        return redirect("/login-enseignant")

    # Dashboard de retour
    if session.get("is_admin"):
        dashboard_url = "/admin/dashboard"
    elif session.get("enseignant_id"):
        dashboard_url = "/dashboard-enseignant"
    else:
        dashboard_url = "/"

    if request.method == "POST":
        lecon_id = request.form.get("lecon_id")
        nb_exercices = int(request.form.get("nb_exercices", 1))
        temps_commun = int(request.form.get("temps_commun", 60))
        
        print(f"=== DEBUG: Début traitement ===")
        print(f"Leçon ID: {lecon_id}")
        print(f"Nombre d'exercices demandé: {nb_exercices}")
        
        if not lecon_id:
            return jsonify({"error": "Aucune leçon sélectionnée"}), 400
        
        exercises_created = []
        
        # Pour chaque exercice de 1 à nb_exercices
        for i in range(1, nb_exercices + 1):
            print(f"\n--- Traitement exercice {i} ---")
            
            # Récupérer les données avec des noms simples indexés
            question_fr = request.form.get(f"question_fr_{i}", "").strip()
            question_en = request.form.get(f"question_en_{i}", "").strip()
            reponse_fr = request.form.get(f"reponse_fr_{i}", "").strip()
            reponse_en = request.form.get(f"reponse_en_{i}", "").strip()
            explication_fr = request.form.get(f"explication_fr_{i}", "").strip()
            explication_en = request.form.get(f"explication_en_{i}", "").strip()
            options_fr = request.form.get(f"options_fr_{i}", "").strip()
            options_en = request.form.get(f"options_en_{i}", "").strip()
            
            # Temps spécifique ou temps commun
            temps_specifique = request.form.get(f"temps_{i}")
            temps = int(temps_specifique) if temps_specifique else temps_commun
            
            print(f"Question FR: {question_fr[:50]}...")
            print(f"Question EN: {question_en[:50]}...")
            
            # ✅ CORRECTION: Ne pas ignorer si une question est vide
            if not question_fr and not question_en:
                print(f"⚠️ Exercice {i} ignoré: aucune question")
                continue
            
            # Gestion de l'image
            chemin_image = None
            file_key = f"image_exercice_{i}"
            
            if file_key in request.files:
                fichier = request.files[file_key]
                if fichier and fichier.filename:
                    # Sauvegarder l'image
                    nom_fichier = secure_filename(fichier.filename)
                    timestamp = int(datetime.now().timestamp())
                    nom_fichier = f"{timestamp}_{i}_{nom_fichier}"
                    dossier = os.path.join("static", "uploads", "images")
                    os.makedirs(dossier, exist_ok=True)
                    chemin_absolu = os.path.join(dossier, nom_fichier)
                    fichier.save(chemin_absolu)
                    chemin_image = f"uploads/images/{nom_fichier}"
                    print(f"📷 Image sauvegardée: {chemin_image}")
            
            # Créer l'exercice
            exercice = Exercice(
                lecon_id=lecon_id,
                question_fr=question_fr or "",
                question_en=question_en or "",
                reponse_fr=reponse_fr if reponse_fr else None,
                reponse_en=reponse_en if reponse_en else None,
                explication_fr=explication_fr if explication_fr else None,
                explication_en=explication_en if explication_en else None,
                options_fr=options_fr if options_fr else None,
                options_en=options_en if options_en else None,
                temps=temps,
                chemin_image=chemin_image
            )
            
            db.session.add(exercice)
            exercises_created.append(exercice)
            print(f"✅ Exercice {i} préparé")
        
        try:
            db.session.commit()
            print(f"\n🎉 {len(exercises_created)} exercices enregistrés avec succès")
        except Exception as e:
            db.session.rollback()
            print(f"\n❌ Erreur lors de l'enregistrement: {e}")
            return jsonify({"error": f"Erreur base de données: {str(e)}"}), 500
        
        # Génération automatique des descriptions si nécessaire
        if 'generer_description_auto' in globals():
            for ex in exercises_created:
                if ex.chemin_image:
                    try:
                        generer_description_auto(ex.id)
                    except Exception as e:
                        print(f"⚠️ Échec génération description: {e}")
        
        return render_template(
            "exercice_ajoute.html",
            dashboard_url=dashboard_url,
            count=len(exercises_created),
            lang=session.get("lang", "fr")
        )
    
    # GET: Afficher le formulaire
    niveaux = Niveau.query.all()
    return render_template(
        "ajouter_exercice.html",
        niveaux=niveaux,
        lang=session.get("lang", "fr"),
        dashboard_url=dashboard_url
    )

@app.route("/api/exercice/<int:exercice_id>", methods=["GET"])
def api_get_exercice(exercice_id):
    """API pour récupérer les détails d'un exercice pour l'aperçu"""
    if not session.get("enseignant_id") and not session.get("is_admin"):
        return jsonify({"error": "Non autorisé"}), 401
    
    exercice = Exercice.query.get(exercice_id)
    if not exercice:
        return jsonify({"error": "Exercice non trouvé"}), 404
    
    # Retourner les données de l'exercice
    return jsonify({
        "id": exercice.id,
        "question_fr": exercice.question_fr or "",
        "question_en": exercice.question_en or "",
        "reponse_fr": exercice.reponse_fr or "",
        "reponse_en": exercice.reponse_en or "",
        "explication_fr": exercice.explication_fr or "",
        "explication_en": exercice.explication_en or "",
        "options_fr": exercice.options_fr or "",
        "options_en": exercice.options_en or "",
        "temps": exercice.temps,
        "chemin_image": exercice.chemin_image or "",
        "created_at": exercice.created_at.strftime("%d/%m/%Y") if exercice.created_at else "",
        "lecon_id": exercice.lecon_id
    })

@app.route("/admin/ajouter-niveau", methods=["GET", "POST"])
@admin_required
def ajouter_niveau():
    if request.method == "POST":
        nom_fr = request.form.get("nom_fr")
        nom_en = request.form.get("nom_en")
        if nom_fr:
            nouveau = Niveau(nom=nom_fr, nom_en=nom_en)
            db.session.add(nouveau)
            db.session.commit()
            flash("✅ Niveau ajouté avec succès", "success")
            return redirect("/admin/dashboard")
        else:
            flash("⚠️ Le nom du niveau est requis", "error")

    return render_template("ajouter_niveau.html")


@app.route("/admin/ajouter-matiere", methods=["GET", "POST"])
@admin_required
def ajouter_matiere():
    niveaux = Niveau.query.all()
    if request.method == "POST":
        nom_fr = request.form.get("nom_fr")
        nom_en = request.form.get("nom_en")
        niveau_id = request.form.get("niveau_id")
        if nom_fr and niveau_id:
            matiere = Matiere(nom=nom_fr, nom_en=nom_en, niveau_id=niveau_id)
            db.session.add(matiere)
            db.session.commit()
            flash("✅ Matière ajoutée", "success")
            return redirect("/admin/dashboard")
        else:
            flash("⚠️ Le nom en français et le niveau sont requis", "error")
    return render_template("ajouter_matiere.html", niveaux=niveaux)

@app.route("/admin/ajouter-unite", methods=["GET", "POST"])
@admin_required
def ajouter_unite():
    niveaux = Niveau.query.all()  # nécessaire pour charger les niveaux dynamiquement dans le template

    if request.method == "POST":
        nom_fr = request.form.get("nom_fr")
        nom_en = request.form.get("nom_en")
        matiere_id = request.form.get("matiere_id")  # transmis dynamiquement
        if nom_fr and matiere_id:
            unite = Unite(nom=nom_fr, nom_en=nom_en, matiere_id=matiere_id)
            db.session.add(unite)
            db.session.commit()
            flash("✅ Unité ajoutée", "success")
            return redirect("/admin/dashboard")
        else:
            flash("⚠️ Nom et matière requis", "error")

    return render_template("ajouter_unite.html", niveaux=niveaux, lang=session.get("lang", "fr"))

@app.route("/admin/ajouter-lecon", methods=["GET", "POST"])
def ajouter_lecon():
    if not session.get("enseignant_id") and not session.get("is_admin"):
        return redirect("/login-enseignant")
    lang = session.get("lang", "fr")
    
    # Déterminer le dashboard de retour
    if session.get("is_admin"):
        dashboard_url = "/admin/dashboard"
    elif session.get("enseignant_id"):
        dashboard_url = "/dashboard-enseignant"
    else:
        dashboard_url = "/"

    if request.method == "POST":
        unite_id = request.form.get("unite_id")
        titre_fr = request.form.get("titre_fr")
        titre_en = request.form.get("titre_en")
        objectif_fr = request.form.get("objectif_fr")
        objectif_en = request.form.get("objectif_en")

        if unite_id and titre_fr and titre_en:
            lecon = Lecon(
                unite_id=unite_id,
                titre_fr=titre_fr,
                titre_en=titre_en,
                objectif_fr=objectif_fr,
                objectif_en=objectif_en
            )
            db.session.add(lecon)
            db.session.commit()
            flash("✅ Leçon ajoutée avec succès" if lang == "fr" else "✅ Lesson added successfully", "success")
            return redirect(dashboard_url)  # Utiliser dashboard_url au lieu de "/admin/dashboard"
        else:
            flash("⚠️ Tous les champs sont obligatoires" if lang == "fr" else "⚠️ All fields are required", "error")

    niveaux = Niveau.query.all()
    return render_template("ajouter_lecon.html", niveaux=niveaux, lang=lang, dashboard_url=dashboard_url)


@app.route("/admin/visualiser-exercices-lecon/<int:lecon_id>")
def visualiser_exercices_lecon(lecon_id):
    # 🔒 Vérification d'accès - pour enseignants et admin
    if not session.get("enseignant_id") and not session.get("is_admin"):
        return redirect("/login-enseignant")

    lecon = Lecon.query.get_or_404(lecon_id)
    exercices = Exercice.query.filter_by(lecon_id=lecon_id).all()
    
    # Déterminer le dashboard de retour dynamiquement
    if session.get("is_admin"):
        dashboard_url = "/admin/dashboard"
    elif session.get("enseignant_id"):
        dashboard_url = "/dashboard-enseignant"
    else:
        dashboard_url = "/"

    return render_template(
        "visualiser_exercices_lecon.html",  # Votre template existant
        lecon=lecon,
        exercices=exercices,
        lang=session.get("lang", "fr"),
        dashboard_url=dashboard_url  # Passer l'URL du dashboard
    )

@app.route("/api/matieres")
def api_matieres():
    niveau_id = request.args.get("niveau_id")
    lang = request.args.get("lang", "fr")
    matieres = Matiere.query.filter_by(niveau_id=niveau_id).all()
    return jsonify([
        {"id": m.id, "nom": m.nom_en if lang == "en" and m.nom_en else m.nom}
        for m in matieres
    ])

@app.route("/api/unites")
def api_unites():
    matiere_id = request.args.get("matiere_id")
    lang = request.args.get("lang", "fr")
    unites = Unite.query.filter_by(matiere_id=matiere_id).all()
    return jsonify([
        {"id": u.id, "nom": u.nom_en if lang == "en" and u.nom_en else u.nom}
        for u in unites
    ])

@app.route("/api/lecons")
def api_lecons():
    unite_id = request.args.get("unite_id")
    lang = request.args.get("lang", "fr")
    lecons = Lecon.query.filter_by(unite_id=unite_id).all()
    return jsonify([
        {"id": l.id, "titre": l.titre_en if lang == "en" and l.titre_en else l.titre_fr}
        for l in lecons
    ])

from models import TestExercice
@app.route("/admin/ajouter-test", methods=["GET", "POST"])
def ajouter_test():
    if not session.get("enseignant_id") and not session.get("is_admin"):
        return redirect("/login-enseignant")
    
    # Déterminer le dashboard de retour
    if session.get("is_admin"):
        dashboard_url = "/admin/dashboard"
    elif session.get("enseignant_id"):
        dashboard_url = "/dashboard-enseignant"
    else:
        dashboard_url = "/"

    if request.method == "POST":
        unite_id = request.form.get("unite_id")
        temps = int(request.form.get("temps") or 60)

        # 📎 Fichier test PDF
        fichier = request.files.get("fichier_pdf")
        chemin_fichier = None
        if fichier and fichier.filename:
            nom_fichier = secure_filename(fichier.filename)
            dossier_upload = os.path.join("static", "uploads", "tests")
            os.makedirs(dossier_upload, exist_ok=True)
            chemin_complet = os.path.join(dossier_upload, nom_fichier)
            fichier.save(chemin_complet)
            chemin_fichier = f"uploads/tests/{nom_fichier}"

        # 📎 Fichier corrigé PDF
        fichier_corrige = request.files.get("fichier_corrige")
        chemin_corrige = None
        if fichier_corrige and fichier_corrige.filename:
            nom_corrige = secure_filename("corrige_" + fichier_corrige.filename)
            dossier_corrige = os.path.join("static", "uploads", "corrections")
            os.makedirs(dossier_corrige, exist_ok=True)
            chemin_complet_corrige = os.path.join(dossier_corrige, nom_corrige)
            fichier_corrige.save(chemin_complet_corrige)
            chemin_corrige = f"uploads/corrections/{nom_corrige}"

        # 💾 Création du test sommatif
        test = TestSommatif(
            unite_id=unite_id,
            temps=temps,
            chemin_fichier=chemin_fichier,
            chemin_corrige=chemin_corrige
        )
        db.session.add(test)
        db.session.flush()  # pour récupérer test.id

        total_exercices = int(request.form.get("total_exercices", 0))

        for i in range(total_exercices):
            question_fr = request.form.get(f"question_fr_{i}")
            question_en = request.form.get(f"question_en_{i}")
            reponse_fr = request.form.get(f"reponse_fr_{i}")
            reponse_en = request.form.get(f"reponse_en_{i}")
            explication_fr = request.form.get(f"explication_fr_{i}")
            explication_en = request.form.get(f"explication_en_{i}")

            image_file = request.files.get(f"image_{i}")
            chemin_image = None
            if image_file and image_file.filename:
                nom_image = secure_filename(image_file.filename)
                dossier_images = os.path.join("static", "uploads", "images")
                os.makedirs(dossier_images, exist_ok=True)
                chemin_image_complet = os.path.join(dossier_images, nom_image)
                image_file.save(chemin_image_complet)
                chemin_image = f"uploads/images/{nom_image}"

            exercice = TestExercice(
                test_id=test.id,
                question_fr=question_fr,
                reponse_fr=reponse_fr,
                explication_fr=explication_fr,
                question_en=question_en,
                reponse_en=reponse_en,
                explication_en=explication_en,
                chemin_image=chemin_image
            )
            db.session.add(exercice)

        db.session.commit()
        flash("✅ Test sommatif ajouté avec succès", "success")
        return redirect(dashboard_url)  # Utiliser dashboard_url au lieu de "/admin/dashboard"

    niveaux = Niveau.query.all()
    return render_template("form_test_sommatif.html", niveaux=niveaux, lang=session.get("lang", "fr"), dashboard_url=dashboard_url)


@app.route("/admin/eleves")
@admin_required
def liste_eleves():
    eleves = User.query.options(
        joinedload(User.niveau),
        joinedload(User.enseignant),
        joinedload(User.parents)
    ).filter_by(role="élève").all()

    lang = session.get("lang", "fr")
    return render_template("admin_eleves.html", eleves=eleves, lang=lang)


@app.route("/admin/changer-statut-paiement", methods=["POST"])
@admin_required
def changer_statut_paiement():
    eleve_id = request.form.get('eleve_id')
    nouveau_statut = request.form.get('statut_paiement')
    
    eleve = User.query.get(eleve_id)
    if eleve and eleve.role == "élève":
        eleve.statut_paiement = nouveau_statut
        
        # Si marqué comme "payé" par admin, marquer comme inscrit par admin
        if nouveau_statut == 'paye':
            eleve.inscrit_par_admin = True
        
        db.session.commit()
        flash("Statut de paiement mis à jour avec succès", "success")
    else:
        flash("Élève non trouvé", "error")
    
    return redirect(url_for('liste_eleves'))


@app.route("/admin/modifier-eleve/<int:eleve_id>", methods=["GET", "POST"])
@admin_required
def modifier_eleve(eleve_id):
    eleve = User.query.get_or_404(eleve_id)
    enseignants = Enseignant.query.all()
    niveaux = Niveau.query.all()  # Ajout pour la sélection du niveau
    lang = session.get("lang", "fr")

    if request.method == "POST":
        # Récupération des données du formulaire
        eleve.nom_complet = request.form.get("nom")
        eleve.email = request.form.get("email")
        eleve.username = request.form.get("username")
        eleve.niveau_id = request.form.get("niveau_id")
        eleve.enseignant_id = request.form.get("enseignant_id")

        # Gestion du mot de passe
        changer_mdp = request.form.get("changer_mdp")
        if changer_mdp:
            nouveau_mot_de_passe = request.form.get("nouveau_mot_de_passe")
            confirmation_mot_de_passe = request.form.get("confirmation_mot_de_passe")
            
            if nouveau_mot_de_passe and confirmation_mot_de_passe:
                if nouveau_mot_de_passe == confirmation_mot_de_passe:
                    if len(nouveau_mot_de_passe) >= 3:
                        eleve.mot_de_passe = nouveau_mot_de_passe
                        flash("✅ Mot de passe modifié avec succès", "success")
                    else:
                        flash("❌ Le mot de passe doit contenir au moins 3 caractères", "error")
                        return render_template("modifier_eleve.html", 
                                             eleve=eleve, 
                                             enseignants=enseignants, 
                                             niveaux=niveaux,
                                             lang=lang)
                else:
                    flash("❌ Les mots de passe ne correspondent pas", "error")
                    return render_template("modifier_eleve.html", 
                                         eleve=eleve, 
                                         enseignants=enseignants, 
                                         niveaux=niveaux,
                                         lang=lang)

        try:
            db.session.commit()
            flash("✅ Élève modifié avec succès", "success")
            return redirect("/admin/eleves")
        except Exception as e:
            db.session.rollback()
            flash(f"❌ Erreur lors de la modification : {str(e)}", "error")

    return render_template("modifier_eleve.html", 
                         eleve=eleve, 
                         enseignants=enseignants, 
                         niveaux=niveaux,
                         lang=lang)

@app.route("/admin/supprimer-eleve/<int:eleve_id>", methods=["POST"])
@admin_required
def supprimer_eleve(eleve_id):
    eleve = User.query.get_or_404(eleve_id)
    db.session.delete(eleve)
    db.session.commit()
    return redirect("/admin/eleves")

@app.route("/login-eleve", methods=["GET", "POST"])
def login_eleve():
    from models import User
    
    if request.method == 'POST':
        email = request.form.get("email")
        mot_de_passe = request.form.get("mot_de_passe")
        eleve = User.query.filter_by(email=email, role="élève").first()

        if eleve and eleve.verifier_mot_de_passe(mot_de_passe):
            # Vérifier si l'essai est expiré
            if eleve.essai_est_expire():
                # 🔴 MODIFICATION ICI : Redirection vers upgrade_options
                session['eleve_id'] = eleve.id
                session['eleve_username'] = eleve.username
                flash("Votre période d'essai gratuit de 48h est terminée. Veuillez choisir un abonnement.", "warning")
                return redirect(url_for('upgrade_options'))
            
            # Afficher le temps restant pour l'essai
            if eleve.est_en_essai_gratuit():
                temps_restant = eleve.temps_restant_essai()
                heures_restantes = int(temps_restant.total_seconds() / 3600)
                jours_restants = int(temps_restant.total_seconds() / 86400)
                
                if jours_restants > 0:
                    message = f"Essai gratuit : {jours_restants} jour(s) restant(s)"
                else:
                    message = f"Essai gratuit : {heures_restantes} heure(s) restante(s)"
                
                flash(message, "info")

            # Connexion - STOCKER DANS LA SESSION
            session['eleve_id'] = eleve.id
            session['eleve_username'] = eleve.username
            session['current_student'] = eleve.username  # ✅ Pour l'enseignant virtuel
            
            return redirect(url_for('dashboard_eleve'))
        else:
            flash("Identifiants incorrects", "error")

    lang = session.get('lang', 'fr')
    return render_template("login_eleve.html", lang=lang)

# Ajoutez cette route à votre fichier de routes
@app.route('/a-propos')
def a_propos():
    """Page À propos accessible à tous"""
    return render_template('a_propos.html')

@app.before_request
def before_request():
    """Vérifier l'accès avant chaque requête - VERSION FINALE"""
    if 'eleve_id' in session and request.endpoint and any(route in request.endpoint for route in ['dashboard_eleve', 'contenus_eleve', 'exercice', 'enseignant_virtuel']):
        from models import User
        
        eleve = User.query.get(session['eleve_id'])
        if eleve and eleve.role == "élève":
            # VÉRIFICATION ESSAI GRATUIT EXPIRÉ
            if eleve.essai_est_expire() and eleve.statut_paiement != "paye":
                session.clear()
                flash("Votre période d'essai gratuit de 48h est terminée. Veuillez vous abonner pour continuer.", "error")
                return redirect(url_for('login_eleve'))

@app.route("/admin/exercices")
@admin_required
def liste_exercices():
    """Affiche tous les exercices organisés par matière, unité et leçon"""
    page = request.args.get('page', 1, type=int)
    per_page = 10  # 10 matières par page
    
    # Récupérer les matières qui ont des exercices (via leurs unités et leçons)
    matieres_query = Matiere.query\
        .join(Niveau)\
        .join(Unite)\
        .join(Lecon)\
        .join(Exercice)\
        .options(
            db.joinedload(Matiere.niveau),
            db.joinedload(Matiere.unites).joinedload(Unite.lecons).joinedload(Lecon.exercices)
        )\
        .distinct()
    
    # Tri par id du niveau puis par nom de matière
    matieres_paginated = matieres_query.order_by(Niveau.id.asc(), Matiere.nom.asc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    # Récupérer tous les niveaux et matières pour les filtres
    niveaux = Niveau.query.order_by(Niveau.id.asc()).all()
    matieres_par_niveau = {}
    for niveau in niveaux:
        matieres_par_niveau[niveau.id] = [
            {'id': matiere.id, 'nom': matiere.nom} 
            for matiere in niveau.matieres
        ]
    
    # Calculer le nombre total d'exercices pour chaque matière et unité
    for matiere in matieres_paginated.items:
        total_exercices_matiere = 0
        unites_avec_exercices = []
        
        for unite in matiere.unites:
            lecons_avec_exercices = []
            total_exercices_unite = 0
            
            for lecon in unite.lecons:
                if lecon.exercices:
                    lecons_avec_exercices.append(lecon)
                    total_exercices_unite += len(lecon.exercices)
            
            if lecons_avec_exercices:
                # Créer des attributs temporaires
                setattr(unite, 'lecons_avec_exercices', lecons_avec_exercices)
                setattr(unite, 'total_exercices', total_exercices_unite)
                unites_avec_exercices.append(unite)
                total_exercices_matiere += total_exercices_unite
        
        # Créer des attributs temporaires pour la matière
        setattr(matiere, 'unites_avec_exercices', unites_avec_exercices)
        setattr(matiere, 'total_exercices', total_exercices_matiere)
    
    # Statistiques
    total_exercices = Exercice.query.count()
    total_lecons = Lecon.query.count()
    total_unites = Unite.query.count()
    total_matieres = Matiere.query.count()
    
    return render_template("liste_exercices.html", 
                         matieres_avec_exercices=matieres_paginated.items,
                         total_exercices=total_exercices,
                         total_lecons=total_lecons,
                         total_unites=total_unites,
                         total_matieres=total_matieres,
                         niveaux=niveaux,
                         matieres_par_niveau=matieres_par_niveau,
                         page=page,
                         has_next=matieres_paginated.has_next,
                         per_page=per_page,
                         lang=session.get("lang", "fr"))



@app.route("/exercice")
def liste_exercice():
    username = request.args.get("username")
    eleve = User.query.filter_by(username=username).first()
    if not eleve:
        return "Élève non trouvé", 404

    niveau = request.args.get("niveau") or eleve.niveau
    theme = request.args.get("theme")
    lecon = request.args.get("lecon")

    exercice_faits_ids = db.session.query(StudentResponse.Exercice_id).filter_by(user_id=eleve.id).all()
    exercice_faits_ids = [id for (id,) in exercice_faits_ids]

    query = Exercice.query.filter_by(niveau=niveau)
    if theme:
        query = query.filter_by(theme=theme)
    if lecon:
        query = query.filter_by(lecon=lecon)

    query = query.filter(~Exercice.id.in_(exercice_faits_ids))
    exercice = query.order_by(Exercice.id).all()

    return render_template("exercice.html", eleve=eleve, exercice=exercice)


if __name__ == "__main__":
    app.run(debug=True)
