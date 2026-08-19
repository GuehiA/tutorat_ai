import os
from dotenv import load_dotenv
load_dotenv()
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
from datetime import timedelta
from services.diagnostic_eleve_service import diagnostiquer_eleve_sur_lecon
from services.recommandations import recommander_prochaine_action, choisir_exercice_pour_lecon
from services.math_verification import (
    verifier_expression_fractionnaire,
    verifier_solution_equation_fractionnaire
)
from validation.engine import ValidationEngine
from models import DiagnosticBayesien, ProfilApprenant
# Après les imports existants, ajouter :
from naima_router import (
    appel_ia, 
    naima_generer_debut_conversation, 
    naima_generer_suite_conversation,
    naima_corriger_exercice,
    naima_generer_exercice,
    detecter_matiere
)


# 🚀 IMPORTANT: Créer l'app Flask SANS configurer SQLAlchemy immédiatement
# 🚀 IMPORTANT: Créer l'app Flask SANS configurer SQLAlchemy immédiatement
app = Flask(__name__)
load_dotenv()

# ====================================================================
# 🤖 CONFIGURATION DES CLIENTS API (OpenAI + DeepSeek)
# ====================================================================

from openai import OpenAI

# Clés API
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# Initialisation des clients
client_openai = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
client_deepseek = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url=DEEPSEEK_BASE_URL
) if DEEPSEEK_API_KEY else None

# Pour garder la compatibilité avec l'ancien code (qui utilise "client" tout court)
client = client_openai  # Garde la référence OpenAI par défaut

print(f"✅ OpenAI configuré: {bool(client_openai)}")
print(f"✅ DeepSeek configuré: {bool(client_deepseek)}")

# ====================================================================
# 🧠 FONCTION DE ROUTAGE INTELLIGENT
# ====================================================================

def get_ai_response(messages, matiere="maths", difficulte="moyen", max_tokens=800, temperature=0.7):
    """
    Route intelligente entre OpenAI et DeepSeek
    """
    # Maths complexes → DeepSeek Pro
    if matiere == "maths" and difficulte in ["hard", "difficile", "complexe"]:
        if client_deepseek:
            model = "deepseek-v4-pro"
            chosen_client = client_deepseek
            print(f"🔀 Routage: DeepSeek Pro (maths complexes)")
        else:
            chosen_client = client_openai
            model = "gpt-4o-mini"
            print(f"⚠️ DeepSeek non dispo, fallback OpenAI")
    
    # Maths simples ou correction → DeepSeek Flash (économique)
    elif matiere == "maths" or any(word in str(messages).lower() for word in ["corrig", "erreur", "faux", "correct"]):
        if client_deepseek:
            model = "deepseek-v4-flash"
            chosen_client = client_deepseek
            print(f"🔀 Routage: DeepSeek Flash (maths/correction)")
        else:
            chosen_client = client_openai
            model = "gpt-4o-mini"
            print(f"⚠️ DeepSeek non dispo, fallback OpenAI")
    
    # Tout le reste (francais, histoire, sciences générales) → OpenAI
    else:
        chosen_client = client_openai
        model = "gpt-4o-mini"
        print(f"🔀 Routage: OpenAI ({matiere})")
    
    try:
        response = chosen_client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=30.0  # ← AJOUTE CETTE LIGNE (30 secondes)
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ Erreur avec {model}: {e}")
        # Fallback ultime sur OpenAI
        if chosen_client != client_openai and client_openai:
            try:
                response = client_openai.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    max_tokens=max_tokens,
                    timeout=30.0  # ← AJOUTE AUSSI ICI
                )
                return response.choices[0].message.content
            except Exception as fallback_error:
                print(f"❌ Fallback aussi en erreur: {fallback_error}")
                return "Désolé, je rencontre une difficulté technique. Peux-tu reformuler ta question ?"
        return "Désolé, je rencontre une difficulté technique. Peux-tu reformuler ta question ?"

# ====================================================================
# --- Configuration de session ---
# (ton code existant continue ici)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-key-change-me')
# ... le reste de ton code
app.config['SESSION_COOKIE_NAME'] = 'tutorat_session'
app.config['SESSION_COOKIE_SECURE'] = False  # Mettez True en production avec HTTPS seulement
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = 7200  # 2 heures en secondes

# Configuration Flask-Session
app.config['SESSION_TYPE'] = 'filesystem'  # Stockage sur disque
app.config['SESSION_PERMANENT'] = True
app.config['SESSION_USE_SIGNER'] = True  # Signe les cookies
app.config['SESSION_FILE_DIR'] = './flask_session'  # Dossier pour stocker les sessions
app.config['SESSION_FILE_THRESHOLD'] = 500  # Nombre max de sessions

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

# ====================================================================
# 🔌 CORRECTION CRITIQUE : INITIALISATION SQLALCHEMY
# ====================================================================

# ⚠️ IMPORTANT : Importez db depuis models.py d'abord
from models import db

# ✅ CORRECTION : Utilisez init_app() au lieu de créer une nouvelle instance
db.init_app(app)  # Ceci initialise l'instance db de models.py avec l'application
migrate = Migrate(app, db)

print("✅ SQLAlchemy initialisé avec succès depuis models.py")

# ====================================================================
# ⚠️ IMPORT DES MODÈLES DANS LE CONTEXTE DE L'APP
# ====================================================================

# Maintenant que db est initialisé, importez les modèles depuis models
with app.app_context():
    from models import (
        User, Exercice, StudentResponse, Parent, ParentEleve, EnseignantMatiere,
        RemediationSuggestion, Niveau, Matiere, Unite, EleveMatiere,
        Lecon, TestSommatif, TestResponse, Commission, VersementManuel,
        ExerciceRemediation, Enseignant, TestExercice, InfoVersementEnseignant, MatiereAIConfig
    )
    print("✅ Modèles importés depuis models.py")

# === MAINTENANT IMPORTEZ fonctions_commissions ===
from fonctions_commissions import (
    creer_commission_apres_paiement,
    integrer_commission,
    calculer_commission_enseignant,
    traiter_versement_manuel,
    demander_versement_manuel,
    completer_versement_manuel
)

# ====================================================================
# 🧠 CONFIGURATION STRIPE
# ====================================================================

# ✅ CONFIGURATION STRIPE CORRECTE - CLÉ VALIDE
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")

# Debug Stripe
print(f"🎯 Stripe configuré: {bool(stripe.api_key)}")
print(f"🔑 Clé utilisée: {stripe.api_key[:20]}..." if stripe.api_key else "❌ Pas de clé Stripe")

# ====================================================================
# 📁 CONFIGURATION DES UPLOADS
# ====================================================================

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads", "tests")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 Mo par requête

# ====================================================================
# 🔌 INITIALISATION OPENAI
# ====================================================================

from config import OPENAI_API_KEY
client = OpenAI(api_key=OPENAI_API_KEY)
validation_engine = ValidationEngine()
# ====================================================================
# 🛠️ FONCTIONS UTILITAIRES
# ====================================================================

# --- Optimisations pour PostgreSQL ---
@app.before_request
def _enable_foreign_keys():
    """Active les clés étrangères pour SQLite (ignoré par PostgreSQL)"""
    pass

@app.before_request
def log_start_time():
    request.start_time = time.time()


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

def get_user_model():
    """Fonction pour obtenir le modèle User de manière sécurisée"""
    return User

def load_models():
    """Charge les modèles de manière sécurisée"""
    models_loaded = {}
    try:
        with app.app_context():
            models_loaded = {
                'User': User,
                'Exercice': Exercice,
                'StudentResponse': StudentResponse,
                'Parent': Parent,
                'ParentEleve': ParentEleve,
                'RemediationSuggestion': RemediationSuggestion,
                'Niveau': Niveau,
                'Matiere': Matiere,
                'Unite': Unite,
                'Lecon': Lecon,
                'TestSommatif': TestSommatif,
                'TestResponse': TestResponse,
                'Commission': Commission,
                'VersementManuel': VersementManuel
            }
            print("✅ Modèles chargés avec succès")
    except Exception as e:
        print(f"⚠️ Erreur lors du chargement des modèles: {e}")
        print("🔄 Utilisation des modèles de base minimalistes...")
    return models_loaded

MODELS = load_models()

def get_model(model_name):
    model = MODELS.get(model_name)
    if model:
        return model
    return None

# Raccourcis pratiques
User = get_model('User') or MODELS.get('User')
Exercice = MODELS.get('Exercice')
StudentResponse = MODELS.get('StudentResponse')
Parent = MODELS.get('Parent')
ParentEleve = MODELS.get('ParentEleve')
RemediationSuggestion = MODELS.get('RemediationSuggestion')
Niveau = get_model('Niveau') or MODELS.get('Niveau')
Matiere = MODELS.get('Matiere')
Unite = MODELS.get('Unite')
Lecon = MODELS.get('Lecon')
TestSommatif = MODELS.get('TestSommatif')
TestResponse = MODELS.get('TestResponse')
Commission = get_model('Commission') or MODELS.get('Commission')
VersementManuel = get_model('VersementManuel') or MODELS.get('VersementManuel')

# ====================================================================
# 🔐 FLASK-LOGIN INITIALISATION
# ====================================================================
from flask_login import LoginManager, login_required, current_user

login_manager = LoginManager()
login_manager.login_view = "login"  # mettre le nom de votre route de login
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))  # Flask-Login saura charger l'utilisateur

# ====================================================================
# 🔐 DÉCORATEURS D'AUTHENTIFICATION
# ====================================================================

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        print(f"=== admin_required décorateur appelé ===")
        print(f"Session user_id: {session.get('user_id', 'Non trouvé')}")
        
        if "user_id" not in session:
            print("❌ user_id non trouvé dans session")
            flash("Accès non autorisé", "error")
            return redirect(url_for("login_admin"))
        
        from flask import current_app
        with current_app.app_context():
            user = db.session.get(User, session["user_id"])
            
        print(f"Utilisateur trouvé: {user.username if user else 'None'}")
        print(f"Rôle utilisateur: {user.role if user else 'None'}")
        
        if not user:
            print("❌ Utilisateur non trouvé dans la base de données")
            flash("Accès non autorisé", "error")
            session.clear()
            return redirect(url_for("login_admin"))
        
        if user.role != "admin":
            print(f"❌ Rôle non admin: {user.role}")
            flash("Accès réservé aux administrateurs", "error")
            
            if user.role == "enseignant":
                try:
                    return redirect(url_for("dashboard_enseignant"))
                except:
                    return redirect("/enseignant/dashboard")
            elif user.role == "eleve":
                try:
                    return redirect(url_for("dashboard_eleve"))
                except:
                    return redirect("/eleve/dashboard")
            else:
                return redirect("/")
        
        print(f"✅ Admin autorisé: {user.username}")
        return f(*args, **kwargs)
    return decorated_function

# ====================================================================
# 🏥 ROUTE DE SANTÉ
# ====================================================================

@app.route('/health')
def health_check():
    try:
        db.session.execute(text('SELECT 1'))
        db_status = 'OK'
        user_count = User.query.count() if User else 'N/A'
        return jsonify({
            'status': 'healthy',
            'database': db_status,
            'user_count': user_count,
            'timestamp': datetime.utcnow().isoformat()
        }), 200
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 500

# ====================================================================
# 🎯 Bloquer les bots
# ====================================================================

@app.before_request
def block_wordpress_bots():
    """Bloque les requêtes de bots WordPress"""
    blocked_paths = ['/wp', '/wordpress', '/blog', '/wp-includes']
    for path in blocked_paths:
        if request.path.startswith(path):
            return "Not found", 404
# ====================================================================
# 🎯 ROUTES D'AUTHENTIFICATION (exemple)
# ====================================================================

@app.route("/login-admin", methods=["GET", "POST"])
def login_admin():
    if request.method == "POST":
        email = request.form.get("email")
        mot_de_passe = request.form.get("mot_de_passe")

        try:
            # Utilisez get_user_model() pour éviter les problèmes d'import
            UserModel = get_user_model()
            
            # 🔍 Vérifie si un admin existe dans la base
            admin_user = UserModel.query.filter_by(email=email, role="admin").first()
            
            if admin_user and admin_user.verifier_mot_de_passe(mot_de_passe):
                session["is_admin"] = True
                session["admin_id"] = admin_user.id
                session["admin_nom"] = admin_user.nom_complet
                session["user_id"] = admin_user.id
                session["username"] = admin_user.username
                session["role"] = admin_user.role
                
                flash("Connexion administrateur réussie!", "success")
                return redirect("/admin/dashboard")

            flash("Email ou mot de passe incorrect", "error")
            return redirect(url_for("login_admin"))
            
        except Exception as e:
            logger.error(f"Erreur lors de la connexion admin: {e}")
            flash("Erreur technique lors de la connexion", "error")
            return redirect(url_for("login_admin"))

    # AJOUT : Récupérer la langue de la session
    lang = session.get('lang', 'fr')
    return render_template("login_admin.html", lang=lang)

@app.route("/debug-ai")
def debug_ai():
    return {
        "openai": "✅" if client_openai else "❌",
        "deepseek": "✅" if client_deepseek else "❌",
        "default_client": "openai" if client == client_openai else "deepseek"
    }


@app.route("/debug-conversation-state")
def debug_conversation_state():
    return {
        "conversation": session.get("conversation", []),
        "derniere_q_ia": session.get("derniere_q_ia"),
        "exercice_termine": session.get("exercice_termine", False),
        "mode_exercice": session.get("mode_exercice", False)
    }

@app.route("/debug-routing")
def debug_routing():
    from openai import OpenAI
    import os
    
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    
    # Test direct DeepSeek
    try:
        client = OpenAI(api_key=deepseek_key, base_url="https://api.deepseek.com")
        response = client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=[{"role": "user", "content": "Calcule 2/5 divise par 2. Reponds simplement par le resultat."}],
            max_tokens=100
        )
        deepseek_result = response.choices[0].message.content
    except Exception as e:
        deepseek_result = f"Erreur: {e}"
    
    return {
        "deepseek_key_configured": bool(deepseek_key),
        "deepseek_test_result": deepseek_result,
        "fallback_active": True
    }

@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    """
    Tableau de bord administrateur optimisé.

    Version améliorée :
    - ne charge plus toute la hiérarchie pédagogique par défaut ;
    - charge niveaux/matières/unités/leçons/exercices seulement avec ?load_content=1 ;
    - réduit les requêtes répétées de monétisation ;
    - supprime les requêtes N+1 sur les enseignants ;
    - conserve les variables attendues par admin_dashboard.html.
    """

    from datetime import datetime
    from sqlalchemy import func, case
    from sqlalchemy.orm import joinedload

    lang = request.args.get("lang") or session.get("lang", "fr")
    session["lang"] = lang

    # Mettre load_content=1 uniquement quand on veut charger la structure complète
    load_content = request.args.get("load_content") == "1"

    try:
        # ============================================================
        # IMPORT DES MODÈLES
        # ============================================================

        UserModel = get_user_model()
        NiveauModel = get_model("Niveau") or Niveau
        MatiereModel = get_model("Matiere")
        UniteModel = get_model("Unite")
        LeconModel = get_model("Lecon")
        ExerciceModel = get_model("Exercice")
        TestSommatifModel = get_model("TestSommatif")
        CommissionModel = get_model("Commission")
        VersementManuelModel = get_model("VersementManuel")

        # ============================================================
        # CHARGEMENT LÉGER DE LA STRUCTURE DE CONTENU
        # ============================================================

        niveaux = []

        if load_content and NiveauModel:
            try:
                niveaux = (
                    NiveauModel.query
                    .options(
                        joinedload(NiveauModel.matieres)
                        .joinedload(MatiereModel.unites)
                        .joinedload(UniteModel.lecons)
                        .joinedload(LeconModel.exercices),

                        joinedload(NiveauModel.matieres)
                        .joinedload(MatiereModel.unites)
                        .joinedload(UniteModel.tests)
                    )
                    .order_by(NiveauModel.id)
                    .all()
                )

                print(f"✅ Structure contenu chargée : {len(niveaux)} niveau(x).")

            except Exception as e:
                print(f"⚠️ Erreur chargement structure complète: {e}")

                try:
                    niveaux = NiveauModel.query.order_by(NiveauModel.id).all()
                except Exception as e2:
                    print(f"⚠️ Erreur chargement niveaux simples: {e2}")
                    niveaux = []

        else:
            print("ℹ️ Structure contenu non chargée par défaut. Utiliser ?load_content=1.")

        # ============================================================
        # STATISTIQUES PRINCIPALES
        # ============================================================

        stats = {
            "enseignants_count": 0,
            "eleves_count": 0,
            "lecons_count": 0,
            "exercices_count": 0,
            "total_tests": 0,
        }

        try:
            enseignants_count, eleves_count = db.session.query(
                func.coalesce(
                    func.sum(
                        case(
                            (UserModel.role == "enseignant", 1),
                            else_=0
                        )
                    ),
                    0
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (UserModel.role.in_(["eleve", "élève"]), 1),
                            else_=0
                        )
                    ),
                    0
                )
            ).one()

            stats["enseignants_count"] = int(enseignants_count or 0)
            stats["eleves_count"] = int(eleves_count or 0)

        except Exception as e:
            print(f"⚠️ Erreur stats utilisateurs admin: {e}")

        try:
            stats["lecons_count"] = (
                db.session.query(func.count(LeconModel.id)).scalar()
                if LeconModel else 0
            )
        except Exception as e:
            print(f"⚠️ Erreur count leçons: {e}")
            stats["lecons_count"] = 0

        try:
            stats["exercices_count"] = (
                db.session.query(func.count(ExerciceModel.id)).scalar()
                if ExerciceModel else 0
            )
        except Exception as e:
            print(f"⚠️ Erreur count exercices: {e}")
            stats["exercices_count"] = 0

        try:
            stats["total_tests"] = (
                db.session.query(func.count(TestSomatifModel.id)).scalar()
                if False else 0
            )
        except Exception:
            stats["total_tests"] = 0

        try:
            if TestSommatifModel:
                stats["total_tests"] = db.session.query(
                    func.count(TestSommatifModel.id)
                ).scalar() or 0
        except Exception as e:
            print(f"⚠️ Erreur count tests: {e}")
            stats["total_tests"] = 0

        # ============================================================
        # RÉPARTITION DES ÉLÈVES PAR NIVEAU
        # ============================================================

        eleves_par_niveau = []

        if NiveauModel:
            try:
                eleves_par_niveau = (
                    db.session.query(
                        NiveauModel.nom,
                        func.count(UserModel.id)
                    )
                    .join(UserModel, NiveauModel.id == UserModel.niveau_id)
                    .filter(UserModel.role.in_(["eleve", "élève"]))
                    .group_by(NiveauModel.id, NiveauModel.nom)
                    .order_by(NiveauModel.id)
                    .all()
                )
            except Exception as e:
                print(f"⚠️ Erreur répartition élèves par niveau: {e}")
                eleves_par_niveau = []

        # ============================================================
        # DONNÉES DE MONÉTISATION
        # ============================================================

        monetization_stats = {
            "total_commissions": 0,
            "pending_payments": 0,
            "payments_count": 0,
            "active_teachers": 0
        }

        recent_payments = []
        teacher_commissions = []

        if CommissionModel and VersementManuelModel:
            try:
                # --------------------------------------------------------
                # Statistiques globales monétisation
                # --------------------------------------------------------

                total_com, total_pending, active_teachers = db.session.query(
                    func.coalesce(func.sum(CommissionModel.montant_commission), 0),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    CommissionModel.statut.in_(
                                        ["pending", "paiement_manuel"]
                                    ),
                                    CommissionModel.montant_commission
                                ),
                                else_=0
                            )
                        ),
                        0
                    ),
                    func.count(func.distinct(CommissionModel.enseignant_id))
                ).filter(
                    CommissionModel.montant_commission > 0
                ).one()

                payments_count = (
                    db.session.query(func.count(VersementManuelModel.id)).scalar()
                    or 0
                )

                monetization_stats = {
                    "total_commissions": float(total_com or 0),
                    "pending_payments": float(total_pending or 0),
                    "payments_count": int(payments_count or 0),
                    "active_teachers": int(active_teachers or 0)
                }

                # --------------------------------------------------------
                # Paiements récents
                # --------------------------------------------------------

                recent_payments_data = (
                    VersementManuelModel.query
                    .join(UserModel, VersementManuelModel.enseignant_id == UserModel.id)
                    .filter(UserModel.role == "enseignant")
                    .order_by(VersementManuelModel.date_demande.desc())
                    .limit(10)
                    .all()
                )

                for payment in recent_payments_data:
                    recent_payments.append({
                        "id": payment.id,
                        "enseignant_nom": (
                            payment.enseignant.nom_complet
                            if getattr(payment, "enseignant", None)
                            else "N/A"
                        ),
                        "email": (
                            payment.email_interac
                            or (
                                payment.enseignant.email
                                if getattr(payment, "enseignant", None)
                                else ""
                            )
                        ),
                        "montant_total": float(payment.montant_total or 0),
                        "montant_net": (
                            float(payment.montant_net)
                            if payment.montant_net
                            else float(payment.montant_total or 0)
                        ),
                        "statut": payment.statut or "demande",
                        "date_demande": payment.date_demande,
                        "date": (
                            payment.date_demande.strftime("%Y-%m-%d")
                            if payment.date_demande
                            else "N/A"
                        ),
                        "email_interac": payment.email_interac or "",
                        "reference_interac": payment.reference_interac or ""
                    })

                # --------------------------------------------------------
                # Enseignants avec commissions
                # --------------------------------------------------------

                teacher_commissions_data = (
                    db.session.query(
                        UserModel.id,
                        UserModel.nom_complet,
                        UserModel.email,
                        func.coalesce(
                            func.sum(CommissionModel.montant_commission),
                            0
                        ).label("total_commissions"),
                        func.coalesce(
                            func.sum(
                                case(
                                    (
                                        CommissionModel.statut.in_(
                                            ["pending", "paiement_manuel"]
                                        ),
                                        CommissionModel.montant_commission
                                    ),
                                    else_=0
                                )
                            ),
                            0
                        ).label("pending"),
                        func.coalesce(
                            func.sum(
                                case(
                                    (
                                        CommissionModel.statut.in_(
                                            ["approved", "paid", "complete"]
                                        ),
                                        CommissionModel.montant_commission
                                    ),
                                    else_=0
                                )
                            ),
                            0
                        ).label("paid")
                    )
                    .outerjoin(
                        CommissionModel,
                        UserModel.id == CommissionModel.enseignant_id
                    )
                    .filter(UserModel.role == "enseignant")
                    .group_by(UserModel.id, UserModel.nom_complet, UserModel.email)
                    .order_by(db.desc("total_commissions"))
                    .limit(50)
                    .all()
                )

                teacher_ids = [teacher.id for teacher in teacher_commissions_data]

                # --------------------------------------------------------
                # Nombre d'élèves par enseignant en une seule requête
                # --------------------------------------------------------

                students_count_map = {}

                if teacher_ids:
                    try:
                        students_count_rows = (
                            db.session.query(
                                UserModel.enseignant_referent_id,
                                func.count(UserModel.id)
                            )
                            .filter(
                                UserModel.role.in_(["eleve", "élève"]),
                                UserModel.enseignant_referent_id.in_(teacher_ids)
                            )
                            .group_by(UserModel.enseignant_referent_id)
                            .all()
                        )

                        students_count_map = {
                            row[0]: int(row[1] or 0)
                            for row in students_count_rows
                        }

                    except Exception as e:
                        print(f"⚠️ Erreur count élèves par enseignant: {e}")
                        students_count_map = {}

                # --------------------------------------------------------
                # Dernier paiement par enseignant sans requête dans la boucle
                # --------------------------------------------------------

                last_payment_map = {}

                if teacher_ids:
                    try:
                        last_payments = (
                            VersementManuelModel.query
                            .filter(
                                VersementManuelModel.enseignant_id.in_(teacher_ids),
                                VersementManuelModel.statut == "complete"
                            )
                            .order_by(
                                VersementManuelModel.enseignant_id.asc(),
                                VersementManuelModel.date_versement.desc()
                            )
                            .all()
                        )

                        for payment in last_payments:
                            if payment.enseignant_id not in last_payment_map:
                                last_payment_map[payment.enseignant_id] = (
                                    payment.date_versement.strftime("%Y-%m-%d")
                                    if payment.date_versement
                                    else None
                                )

                    except Exception as e:
                        print(f"⚠️ Erreur derniers paiements enseignants: {e}")
                        last_payment_map = {}

                for teacher in teacher_commissions_data:
                    teacher_commissions.append({
                        "id": teacher.id,
                        "nom_complet": teacher.nom_complet or "N/A",
                        "email": teacher.email or "",
                        "total_commissions": float(teacher.total_commissions or 0),
                        "pending": float(teacher.pending or 0),
                        "paid": float(teacher.paid or 0),
                        "students_count": students_count_map.get(teacher.id, 0),
                        "last_payment": (
                            last_payment_map.get(teacher.id)
                            or ("Never" if lang == "en" else "Jamais")
                        )
                    })

            except Exception as e:
                print(f"⚠️ Erreur chargement monétisation admin: {e}")

                monetization_stats = {
                    "total_commissions": 0,
                    "pending_payments": 0,
                    "payments_count": 0,
                    "active_teachers": 0
                }

                recent_payments = []
                teacher_commissions = []

        # ============================================================
        # RENDU
        # ============================================================

        return render_template(
            "admin_dashboard.html",
            niveaux=niveaux,
            stats=stats,
            monetization_stats=monetization_stats,
            recent_payments=recent_payments,
            teacher_commissions=teacher_commissions,
            eleves_par_niveau=eleves_par_niveau,
            lang=lang,
            load_content=load_content
        )

    except Exception as e:
        logger.error(f"Erreur dans admin_dashboard: {e}")
        flash("Erreur lors du chargement du tableau de bord", "error")
        return redirect(url_for("login_admin"))


@app.route("/admin/diagnostics-bayesiens")
@admin_required
def admin_diagnostics_bayesiens():
    from sqlalchemy import desc
    from sqlalchemy.orm import joinedload

    # ============================================================
    # PARAMÈTRES DE FILTRAGE
    # ============================================================

    risque = request.args.get("risque", "").strip()
    user_id = request.args.get("user_id", "").strip()
    matiere = request.args.get("matiere", "").strip()
    source = request.args.get("source", "").strip()

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)

    # Sécurité : éviter de charger trop d'éléments
    if per_page not in [5, 10, 20]:
        per_page = 10

    # La page reste vide au départ.
    # On affiche les diagnostics seulement si au moins un filtre est utilisé.
    afficher_resultats = bool(risque or user_id or matiere or source)

    # ============================================================
    # STATISTIQUES GLOBALES LÉGÈRES
    # ============================================================

    total = DiagnosticBayesien.query.count()

    risques_eleves = DiagnosticBayesien.query.filter_by(
        niveau_risque="élevé"
    ).count()

    risques_moyens = DiagnosticBayesien.query.filter_by(
        niveau_risque="moyen"
    ).count()

    risques_faibles = DiagnosticBayesien.query.filter_by(
        niveau_risque="faible"
    ).count()

    eleves_avec_diagnostics = (
        db.session.query(DiagnosticBayesien.user_id)
        .filter(DiagnosticBayesien.user_id.isnot(None))
        .distinct()
        .count()
    )

    eleves = (
        User.query
        .filter(User.role.in_(["élève", "eleve"]))
        .order_by(User.nom_complet.asc())
        .all()
    )

    # ============================================================
    # VALEURS PAR DÉFAUT
    # ============================================================

    diagnostics = []
    pagination = None
    total_filtre = 0
    synthese_eleve = None

    # ============================================================
    # CHARGEMENT DES DIAGNOSTICS UNIQUEMENT APRÈS FILTRE
    # ============================================================

    if afficher_resultats:
        query = DiagnosticBayesien.query.options(
            joinedload(DiagnosticBayesien.user),
            joinedload(DiagnosticBayesien.exercice),
            joinedload(DiagnosticBayesien.lecon)
        )

        if risque:
            query = query.filter(DiagnosticBayesien.niveau_risque == risque)

        if user_id:
            try:
                query = query.filter(DiagnosticBayesien.user_id == int(user_id))
            except ValueError:
                pass

        if matiere:
            query = query.filter(DiagnosticBayesien.matiere.ilike(f"%{matiere}%"))

        # ========================================================
        # CORRECTION IMPORTANTE DU FILTRE SOURCE
        # ========================================================
        # Dans la route /soumettre-sequentiel, certains diagnostics
        # peuvent avoir été enregistrés avec source="exercice_sequentiel".
        # Mais dans l'admin, l'utilisateur choisit "Exercice".
        # Donc on accepte les deux valeurs.
        # ========================================================

        if source:
            if source == "exercice":
                query = query.filter(
                    DiagnosticBayesien.source.in_([
                        "exercice",
                        "exercice_sequentiel"
                    ])
                )
            else:
                query = query.filter(DiagnosticBayesien.source == source)

        total_filtre = query.count()

        pagination = (
            query
            .order_by(desc(DiagnosticBayesien.created_at))
            .paginate(
                page=page,
                per_page=per_page,
                error_out=False
            )
        )

        diagnostics = pagination.items

    # ============================================================
    # SYNTHÈSE RAPIDE SI UN ÉLÈVE EST SÉLECTIONNÉ
    # ============================================================

    if user_id:
        try:
            user_id_int = int(user_id)

            eleve_selectionne = db.session.get(User, user_id_int)

            derniers_diagnostics_eleve = (
                DiagnosticBayesien.query
                .filter(DiagnosticBayesien.user_id == user_id_int)
                .order_by(desc(DiagnosticBayesien.created_at))
                .limit(100)
                .all()
            )

            notions_maitrisees = []
            notions_non_maitrisees = []
            erreurs_probables = []
            notions_ciblees = []

            nb_eleve_total = len(derniers_diagnostics_eleve)
            nb_risque_eleve = 0
            nb_risque_moyen = 0
            nb_risque_faible = 0

            derniere_activite = None

            for d in derniers_diagnostics_eleve:
                if d.created_at and not derniere_activite:
                    derniere_activite = d.created_at

                if d.niveau_risque == "élevé":
                    nb_risque_eleve += 1
                elif d.niveau_risque == "moyen":
                    nb_risque_moyen += 1
                elif d.niveau_risque == "faible":
                    nb_risque_faible += 1

                if d.notion_cible:
                    notions_ciblees.append(d.notion_cible)

                if d.notions_maitrisees and isinstance(d.notions_maitrisees, list):
                    notions_maitrisees.extend(d.notions_maitrisees)

                if d.notions_non_maitrisees and isinstance(d.notions_non_maitrisees, list):
                    notions_non_maitrisees.extend(d.notions_non_maitrisees)

                if d.erreurs_probables and isinstance(d.erreurs_probables, list):
                    erreurs_probables.extend(d.erreurs_probables)

            def top_items(items, limite=5):
                compteur = {}

                for item in items:
                    if not item:
                        continue

                    item = str(item).strip()

                    if not item:
                        continue

                    compteur[item] = compteur.get(item, 0) + 1

                return sorted(
                    compteur.items(),
                    key=lambda x: x[1],
                    reverse=True
                )[:limite]

            risque_dominant = "non déterminé"

            if (
                nb_risque_eleve >= nb_risque_moyen
                and nb_risque_eleve >= nb_risque_faible
                and nb_risque_eleve > 0
            ):
                risque_dominant = "élevé"
            elif nb_risque_moyen >= nb_risque_faible and nb_risque_moyen > 0:
                risque_dominant = "moyen"
            elif nb_risque_faible > 0:
                risque_dominant = "faible"

            synthese_eleve = {
                "eleve": eleve_selectionne,
                "total_diagnostics": nb_eleve_total,
                "risque_dominant": risque_dominant,
                "risques_eleves": nb_risque_eleve,
                "risques_moyens": nb_risque_moyen,
                "risques_faibles": nb_risque_faible,
                "derniere_activite": derniere_activite,
                "notions_ciblees": top_items(notions_ciblees, 5),
                "notions_maitrisees": top_items(notions_maitrisees, 5),
                "notions_non_maitrisees": top_items(notions_non_maitrisees, 5),
                "erreurs_probables": top_items(erreurs_probables, 5)
            }

        except ValueError:
            synthese_eleve = None

    # ============================================================
    # RENDU TEMPLATE
    # ============================================================

    return render_template(
        "admin/admin_diagnostics_bayesiens.html",

        diagnostics=diagnostics,
        pagination=pagination,
        afficher_resultats=afficher_resultats,
        total_filtre=total_filtre,

        synthese_eleve=synthese_eleve,

        eleves=eleves,
        filtre_risque=risque,
        filtre_user_id=user_id,
        filtre_matiere=matiere,
        filtre_source=source,
        per_page=per_page,

        total=total,
        risques_eleves=risques_eleves,
        risques_moyens=risques_moyens,
        risques_faibles=risques_faibles,
        eleves_avec_diagnostics=eleves_avec_diagnostics
    )


@app.route("/reset-chat", methods=["POST"])
def reset_chat():
    """
    Réinitialise complètement la conversation pédagogique de Naima
    sans déconnecter l'élève.

    IMPORTANT :
    une nouvelle conversation doit repartir avec :
    - aucun ancien objectif ;
    - aucun ancien mode pédagogique ;
    - aucune ancienne question de Naima ;
    - aucun ancien diagnostic ;
    - aucune ancienne preuve mathématique ;
    - aucun état de fin précédent.
    """

    if "user_id" not in session:
        return jsonify({"error": "Non authentifié"}), 401

    # ------------------------------------------------------------
    # CONVERSATION
    # ------------------------------------------------------------

    session.pop("conversation", None)
    session.pop("derniere_q_ia", None)

    # ------------------------------------------------------------
    # EXERCICE
    # ------------------------------------------------------------

    session.pop("exercice_en_cours", None)
    session.pop("exercice_termine", None)
    session.pop("mode_exercice", None)

    # ------------------------------------------------------------
    # ÉTAT PÉDAGOGIQUE NAIMA
    # ------------------------------------------------------------

    session.pop("objectif_initial_naima", None)
    session.pop("objectif_atteint_naima", None)
    session.pop("conversation_terminee", None)

    session.pop("mode_pedagogique_naima", None)
    session.pop("sujet_courant_naima", None)
    session.pop("lecon_courante_naima", None)

    # ------------------------------------------------------------
    # DIAGNOSTIC ET VÉRIFICATIONS DU DIALOGUE PRÉCÉDENT
    # ------------------------------------------------------------

    session.pop("diagnostic_bayesien", None)
    session.pop("signaux_bayesiens", None)
    session.pop("verification_calcul", None)
    session.pop("naima_processus_connecte", None)

    # ------------------------------------------------------------
    # REMÉDIATION
    # ------------------------------------------------------------

    session.pop("remediation_access", None)
    session.pop("remediation_access_granted", None)
    session.pop("remediation_exercice_id", None)
    session.pop("remediation_access_count", None)

    session.modified = True

    print("🧹 Conversation Naima complètement réinitialisée.")
    print("   - objectif_initial_naima supprimé")
    print("   - mode_pedagogique_naima supprimé")
    print("   - état de fin supprimé")
    print("   - diagnostic précédent supprimé")
    print("   - vérification mathématique précédente supprimée")

    return jsonify({
        "success": True,
        "message": "Conversation réinitialisée",
        "conversation_reset": True
    })


@app.route("/test-nom-complet")
def test_nom_complet():
    """Test pour vérifier que nom_complet et nom_complet_complet fonctionnent"""
    try:
        from models import User
        
        # Créer un utilisateur test
        test_user = User.query.first()
        
        if test_user:
            result = f"""
            <h1>Test réussi !</h1>
            <p>Utilisateur: {test_user.nom_complet}</p>
            <p>Test nom_complet: <span style='color: green;'>✓ {test_user.nom_complet}</span></p>
            """
            
            # Tester si nom_complet_complet existe
            try:
                test_complet = test_user.nom_complet_complet
                result += f"<p>Test nom_complet_complet: <span style='color: green;'>✓ {test_complet}</span></p>"
            except AttributeError:
                result += f"<p>Test nom_complet_complet: <span style='color: red;'>✗ AttibuteError - ajoutez l'alias dans le modèle</span></p>"
            
            return result
        else:
            return "<h1>Aucun utilisateur trouvé</h1>"
            
    except Exception as e:
        import traceback
        return f"<h1>Erreur</h1><pre>{traceback.format_exc()}</pre>"


# ====================================================================
# 🔄 GESTION DES ERREURS
# ====================================================================

@app.errorhandler(404)
def not_found_error(error):
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    logger.error(f"Erreur 500: {error}")
    return render_template('errors/500.html'), 500

@app.errorhandler(Exception)
def handle_exception(error):
    logger.error(f"Erreur non gérée: {error}")
    return render_template('errors/generic.html', error=error), 500



@app.route('/test-session')
def test_session():
    session['test_key'] = 'test_value'
    return f'Session ID: {session.get("_id", "no_id")}, Test Key: {session.get("test_key", "not_set")}, User ID: {session.get("user_id", "not_logged_in")}'


@app.template_filter('replace_latex')
def replace_latex_filter(text):
    """
    Version simple qui normalise tous les formats LaTeX pour MathJax
    et laisse MathJax faire le rendu des formules
    """
    if not text:
        return text
    
    import re
    from markupsafe import Markup
    
    text = str(text)
    
    # Normaliser TOUS les formats LaTeX vers les formats MathJax
    # 1. $$...$$ → \[...\]  (display math)
    text = re.sub(r'\$\$(.*?)\$\$', r'\\[\1\\]', text, flags=re.DOTALL)
    
    # 2. $...$ → \(...\)  (inline math)
    text = re.sub(r'\$(.*?)\$', r'\\(\1\\)', text)
    
    # 3. \(...\) déjà bon, mais s'assurer de l'échappement
    text = text.replace('\\(', '\\(').replace('\\)', '\\)')
    
    # 4. \[...\] déjà bon, mais s'assurer de l'échappement  
    text = text.replace('\\[', '\\[').replace('\\]', '\\]')
    
    # 5. Pour les commandes LaTeX SIMPLES qui sont hors des blocs math,
    # on peut les remplacer par du Unicode pour améliorer la lisibilité
    
    # D'abord, protéger les blocs mathématiques existants
    math_pattern = r'(\\\[.*?\\\]|\\\(.*?\\\))'
    math_zones = []
    
    def protect_math(match):
        placeholder = f'__MATH_{len(math_zones)}__'
        math_zones.append(match.group(0))
        return placeholder
    
    protected = re.sub(math_pattern, protect_math, text, flags=re.DOTALL)
    
    # Remplacer QUELQUES symboles courants HORS des blocs math
    simple_replacements = {
        '\\alpha': 'α', '\\beta': 'β', '\\gamma': 'γ',
        '\\pi': 'π', '\\theta': 'θ',
        '\\times': '×', '\\div': '÷', '\\pm': '±',
        '\\leq': '≤', '\\geq': '≥', '\\neq': '≠',
        '\\approx': '≈', '\\infty': '∞'
    }
    
    for latex, symbol in simple_replacements.items():
        protected = protected.replace(latex, symbol)
    
    # Restaurer les blocs mathématiques
    result = protected
    for i, math_zone in enumerate(math_zones):
        result = result.replace(f'__MATH_{i}__', math_zone)
    
    # Échappement HTML basique
    result = result.replace('<', '&lt;').replace('>', '&gt;')
    
    return Markup(result)


@app.template_filter("json_lisible")
def json_lisible(value):
    """
    Affiche proprement un contenu JSON ou texte.
    Utile pour options_fr/options_en, réponses ou contenus structurés.
    """
    import json
    from markupsafe import Markup, escape

    if value is None:
        return ""

    # Si c'est déjà une liste Python
    if isinstance(value, list):
        html = "<ul class='mb-0'>"
        for item in value:
            html += f"<li>{escape(str(item))}</li>"
        html += "</ul>"
        return Markup(html)

    # Si c'est déjà un dictionnaire Python
    if isinstance(value, dict):
        html = "<div class='json-list'>"
        for key, item in value.items():
            html += (
                "<div class='mb-2'>"
                f"<strong>{escape(str(key))} :</strong> {escape(str(item))}"
                "</div>"
            )
        html += "</div>"
        return Markup(html)

    # Si c'est une chaîne
    if isinstance(value, str):
        texte = value.strip()

        if not texte:
            return ""

        # Essayer de parser si la chaîne ressemble à du JSON
        if texte.startswith("[") or texte.startswith("{"):
            try:
                data = json.loads(texte)

                if isinstance(data, list):
                    html = "<ul class='mb-0'>"
                    for item in data:
                        html += f"<li>{escape(str(item))}</li>"
                    html += "</ul>"
                    return Markup(html)

                if isinstance(data, dict):
                    html = "<div class='json-list'>"
                    for key, item in data.items():
                        html += (
                            "<div class='mb-2'>"
                            f"<strong>{escape(str(key))} :</strong> {escape(str(item))}"
                            "</div>"
                        )
                    html += "</div>"
                    return Markup(html)

            except Exception:
                pass

        # Sinon, texte normal
        return Markup(texte)

    return Markup(escape(str(value)))

@app.template_filter("affichage_exercice")
def affichage_exercice(value):
    """
    Affiche proprement une question, une réponse, une explication ou des options.
    - Respecte les retours à la ligne.
    - Transforme les JSON en affichage lisible.
    - Ajoute des retours à la ligne avant a), b), c), d) si tout est sur une seule ligne.
    """
    import json
    import re
    from markupsafe import Markup, escape

    if value is None:
        return ""

    def format_texte(texte):
        texte = str(texte).strip()

        if not texte:
            return ""

        # Ajoute des retours à la ligne avant a), b), c), d), etc.
        texte = re.sub(r"\s+([a-h]\))", r"\n\1", texte)

        # Ajoute aussi des retours à la ligne avant 1), 2), 3), etc.
        texte = re.sub(r"\s+([0-9]+[\)\.])", r"\n\1", texte)

        texte = escape(texte)

        # Convertit les vrais retours à la ligne en <br>
        texte = str(texte).replace("\n", "<br>")

        return Markup(f'<div class="contenu-exercice">{texte}</div>')

    # Si c'est déjà une liste Python
    if isinstance(value, list):
        html = "<div class='options-exercice'>"
        for i, item in enumerate(value):
            html += f"<div class='option-item'><strong>{chr(65+i)}.</strong> {escape(str(item))}</div>"
        html += "</div>"
        return Markup(html)

    # Si c'est déjà un dictionnaire Python
    if isinstance(value, dict):
        html = "<div class='options-exercice'>"
        for key, item in value.items():
            html += f"<div class='option-item'><strong>{escape(str(key))}.</strong> {escape(str(item))}</div>"
        html += "</div>"
        return Markup(html)

    # Si c'est une chaîne qui contient peut-être du JSON
    if isinstance(value, str):
        texte = value.strip()

        if not texte:
            return ""

        if texte.startswith("[") or texte.startswith("{"):
            try:
                data = json.loads(texte)

                if isinstance(data, list):
                    html = "<div class='options-exercice'>"
                    for i, item in enumerate(data):
                        html += f"<div class='option-item'><strong>{chr(65+i)}.</strong> {escape(str(item))}</div>"
                    html += "</div>"
                    return Markup(html)

                if isinstance(data, dict):
                    html = "<div class='options-exercice'>"
                    for key, item in data.items():
                        html += f"<div class='option-item'><strong>{escape(str(key))}.</strong> {escape(str(item))}</div>"
                    html += "</div>"
                    return Markup(html)

            except Exception:
                pass

        return format_texte(texte)

    return format_texte(value)


@app.route("/api/matieres-par-niveau/<int:niveau_id>")
def api_matieres_par_niveau(niveau_id):
    """API pour récupérer les matières d'un niveau (utilisée par AJAX dans inscription_eleve.html)"""
    from models import Matiere
    
    try:
        matieres = Matiere.query.filter_by(niveau_id=niveau_id).order_by(Matiere.nom.asc()).all()

        resultats = []
        for matiere in matieres:
            resultats.append({
                "id": matiere.id,
                "nom": matiere.nom,
                "nom_en": matiere.nom_en or matiere.nom
            })

        return jsonify({
            "success": True,
            "niveau_id": niveau_id,
            "matieres": resultats
        })

    except Exception as e:
        print(f"❌ Erreur API matières: {e}")
        return jsonify({
            "success": False,
            "message": str(e),
            "matieres": []
        }), 500


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


def get_message(key, lang="fr"):
    """Système de messages bilingues unifié pour Naima"""
    
    # Structure UNIFIÉE : d'abord par clé, puis par langue
    messages = {
        # Messages d'authentification et essai
        "essai_termine": {
            "fr": "Votre essai gratuit est terminé. Veuillez souscrire à un abonnement pour continuer.",
            "en": "Your free trial has ended. Please subscribe to continue."
        },
        
        # Messages de bienvenue et accueil
        "bienvenue_enseignant": {
            "fr": "Bonjour ! Je suis Naima, ton enseignante virtuelle. Je suis là pour t'aider à comprendre tes leçons et résoudre tes exercices. Quelle est ta question ?",
            "en": "Hello! I'm Naima, your virtual teacher. I'm here to help you understand your lessons and solve your exercises. What's your question?"
        },
        
        # Messages de guidage
        "je_te_guide": {
            "fr": "Je te guide pas à pas...",
            "en": "I'm guiding you step by step..."
        },
        "je_te_guide_court": {
            "fr": "Je te guide...",
            "en": "Guiding you..."
        },
        
        # Messages d'erreur
        "erreur_traitement": {
            "fr": "Une erreur s'est produite. Veuillez réessayer.",
            "en": "An error occurred. Please try again."
        },
        "erreur_ia": {
            "fr": "Désolé, je n'ai pas pu traiter ta demande. Reformule peut-être ?",
            "en": "Sorry, I couldn't process your request. Maybe rephrase it?"
        },
        
        # Messages de dialogue
        "nouveau_dialogue": {
            "fr": "Nouvelle conversation commencée. Pose ta question !",
            "en": "New conversation started. Ask your question!"
        },
        "acces_enseignant": {
            "fr": "Accès à l'enseignant virtuel activé !",
            "en": "Virtual teacher access activated!"
        },
        "conversation_terminee": {
            "fr": "✨ Super ! Tu as compris. N'hésite pas à revenir si tu as d'autres questions !",
            "en": "✨ Great! You understood. Feel free to come back if you have more questions!"
        },
        
        # Messages pour les exercices
        "bravo_exercice_termine": {
            "fr": "🎉 BRAVO ! Tu as terminé l'exercice avec succès ! Veux-tu essayer un autre ?",
            "en": "🎉 WELL DONE! You've successfully completed the exercise! Want to try another?"
        },
        "plus_d_indices": {
            "fr": "Je n'ai plus d'indices, mais je crois en toi ! Essaie de relire l'énoncé.",
            "en": "I have no more hints, but I believe in you! Try re-reading the problem."
        },
        "demande_indice": {
            "fr": "Veux-tu un indice pour t'aider ?",
            "en": "Would you like a hint to help you?"
        },
        "exercice_genere": {
            "fr": "📝 Voici un exercice pour toi ! Prends ton temps pour le résoudre.",
            "en": "📝 Here's an exercise for you! Take your time to solve it."
        },
        "reponse_correcte": {
            "fr": "✅ Exact ! Très bonne réponse !",
            "en": "✅ Exactly! Very good answer!"
        },
        "reponse_incorrecte": {
            "fr": "❌ Presque ! Regarde l'indice et réessaie.",
            "en": "❌ Almost! Look at the hint and try again."
        },
        "indice_suivant": {
            "fr": "💡 Voici un indice supplémentaire :",
            "en": "💡 Here's an additional hint:"
        },
        "exercice_niveau": {
            "fr": "Niveau de difficulté :",
            "en": "Difficulty level:"
        },
        "choisir_difficulte": {
            "fr": "Choisis la difficulté :",
            "en": "Choose difficulty:"
        },
        "generation_exercice": {
            "fr": "Génération de l'exercice en cours...",
            "en": "Generating exercise..."
        },
        "fais_ton_choix": {
            "fr": "Quel exercice veux-tu faire ?",
            "en": "Which exercise would you like to do?"
        },
        "progression_exercice": {
            "fr": "Progression :",
            "en": "Progress:"
        },
        "etape_suivante": {
            "fr": "Passons à l'étape suivante !",
            "en": "Let's move to the next step!"
        },
        "felicitations_fin": {
            "fr": "🎊 FÉLICITATIONS ! Tu as maîtrisé cet exercice !",
            "en": "🎊 CONGRATULATIONS! You've mastered this exercise!"
        },
        
        # Messages pour les matières
        "matiere_maths": {
            "fr": "Mathématiques",
            "en": "Mathematics"
        },
        "matiere_francais": {
            "fr": "Français",
            "en": "French"
        },
        "matiere_histoire": {
            "fr": "Histoire",
            "en": "History"
        },
        "matiere_sciences": {
            "fr": "Sciences",
            "en": "Science"
        },
        "matiere_geo": {
            "fr": "Géographie",
            "en": "Geography"
        },
        
        # Messages d'encouragement
        "encouragement_1": {
            "fr": "Continue comme ça !",
            "en": "Keep it up!"
        },
        "encouragement_2": {
            "fr": "Tu y es presque !",
            "en": "You're almost there!"
        },
        "encouragement_3": {
            "fr": "Excellent raisonnement !",
            "en": "Excellent reasoning!"
        },
        "encouragement_4": {
            "fr": "Je suis fière de toi !",
            "en": "I'm proud of you!"
        },
        
        # Messages d'interface
        "placeholder_question": {
            "fr": "Pose ta question à Naima...",
            "en": "Ask your question to Naima..."
        },
        "placeholder_reponse": {
            "fr": "Réponds à Naima...",
            "en": "Answer Naima..."
        },
        "bouton_envoyer": {
            "fr": "Envoyer",
            "en": "Send"
        },
        "bouton_nouveau": {
            "fr": "Nouvelle conversation",
            "en": "New conversation"
        },
        "bouton_compris": {
            "fr": "J'ai compris ✓",
            "en": "I understand ✓"
        },
        "bouton_exercice": {
            "fr": "Exercice",
            "en": "Exercise"
        }
    }
    
    # Récupération avec gestion d'erreur avancée
    if key in messages:
        # La clé existe
        if lang in messages[key]:
            # La langue existe pour cette clé
            return messages[key][lang]
        else:
            # Langue non trouvée, retour français par défaut
            return messages[key].get("fr", f"[{key}]")
    else:
        # Clé non trouvée, retourner la clé pour debug
        print(f"⚠️ Message key not found: {key}")
        return f"[{key}]"


def extraire_question(reponse, lang="fr"):
    """Extrait la question posée par Naima ou identifie qu'une réponse est attendue"""
    import re
    
    # Si la réponse ne contient pas de '?', c'est peut-être une réponse de l'élève
    if '?' not in reponse:
        return None  # Pas de question, c'est une réponse
    
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
        r'[Rr]eformule\s+(.*?)\?',
        r'[Aa]s-tu\s+(.*?)\?',
        r'[Ss]ais-tu\s+(.*?)\?',
        r'[Cc]onnais-tu\s+(.*?)\?',
        r'[Pp]ourrais-tu\s+(.*?)\?',
        r'[Mm]ontre-moi\s+(.*?)\?',
        # NOUVEAU : Pattern pour les réponses attendues
        r'[Qq]ue\s+(.*?)\?',
        r'[Qq]uoi\s+(.*?)\?',
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
        r'[Rr]ephrase\s+(.*?)\?',
        r'[Dd]o you know\s+(.*?)\?',
        r'[Hh]ave you\s+(.*?)\?',
        r'[Cc]ould you\s+(.*?)\?',
        r'[Ww]ould you\s+(.*?)\?',
    ]
    
    patterns = patterns_fr if lang == "fr" else patterns_en
    
    for pattern in patterns:
        match = re.search(pattern, reponse, re.IGNORECASE)
        if match:
            question = match.group(1).strip()
            if len(question) > 5:
                return question
    
    # Fallback : chercher la dernière phrase avec '?' 
    lines = reponse.split('\n')
    for line in reversed(lines):
        if '?' in line and 'Naima' not in line:
            parts = line.split('?')
            if parts and len(parts) > 1:
                question = parts[-2] + '?'
                question = question.strip()
                if len(question) > 5:
                    return question
    
    return None  # Aucune question trouvée

def get_correction_model_from_config(exercice):
    """
    Récupère la configuration IA pour la matière de l'exercice
    L'admin peut tout configurer !
    """
    # Déterminer la matière de l'exercice
    matiere_nom = None
    try:
        if exercice.lecon and exercice.lecon.unite and exercice.lecon.unite.matiere:
            matiere_nom = exercice.lecon.unite.matiere.nom
    except:
        pass
    
    # Si pas de matière, essayer de détecter depuis la question
    if not matiere_nom and exercice:
        question = (exercice.question_fr or exercice.question_en or "").lower()
        # Mapping des mots-clés vers les noms de matières configurées
        keyword_mapping = {
            "Mathématiques": ["équation", "calcul", "x=", "fraction", "géométrie", "algèbre", "fonction"],
            "MCR3U": ["mcr3u", "fonction", "quadratique", "exponentiel"],
            "MHF4U": ["mhf4u", "advanced function", "polynôme", "logarithme"],
            "MCV4U": ["mcv4u", "calculus", "dérivée", "intégrale", "vecteur"],
            "Français": ["grammaire", "conjugaison", "verbe", "phrase", "texte", "littérature"],
            "English": ["grammar", "conjugation", "verb", "sentence", "literature"],
            "Histoire": ["date", "guerre", "révolution", "siècle", "roi"],
            "Sciences": ["atome", "cellule", "force", "énergie", "vitesse"],
            "Physique": ["physique", "force", "vitesse", "accélération", "énergie"],
            "Chimie": ["chimie", "atome", "molécule", "réaction", "acide"],
            "Biologie": ["biologie", "cellule", "organe", "adn", "génétique"]
        }
        
        for mat, keywords in keyword_mapping.items():
            if any(kw in question for kw in keywords):
                matiere_nom = mat
                break
    
    if not matiere_nom:
        matiere_nom = "Mathématiques"  # Par défaut
    
    print(f"🔍 Matière détectée: {matiere_nom}")
    
    # Chercher la configuration dans la base
    config = MatiereAIConfig.query.filter_by(matiere_nom=matiere_nom, actif=True).first()
    
    if not config:
        # Fallback sur la configuration par défaut
        config = MatiereAIConfig.query.filter_by(matiere_nom="Mathématiques", actif=True).first()
    
    if config:
        print(f"⚙️ Configuration trouvée: {config.matiere_nom} → {config.api_choice}/{config.modele_ia}")
        
        # Choisir le client
        if config.api_choice == "deepseek":
            client = client_deepseek
        else:
            client = client_openai
        
        return client, config.modele_ia
    
    # Dernier fallback
    return client_deepseek, "deepseek-v4-flash"



def get_system_prompt(matiere="mathématiques", lang="fr", mode_examen=False):
    """Prompt optimisé par matière et par langue pour NAIMA l'enseignante virtuelle"""
    
    # Normaliser la matière
    matiere = matiere.lower().strip()
    
    # Dictionnaire des prompts FRANÇAIS pour NAIMA
    prompts_fr = {
        "mathématiques": """Tu es Naima, enseignante virtuelle de mathématiques, passionnée par la pédagogie.
        **TON STYLE :**
        - Tu tutoies toujours l'élève (tu, ton, ta)
        - Tu es chaleureuse, encourageante et patiente
        - Tu signes toujours "— Naima ✨"
        - Tu poses une seule question à la fois
        - Tu ne donnes JAMAIS la réponse directement
        
        **EXEMPLES DE QUESTIONS DE NAIMA :**
        - "Quelle opération utiliserais-tu ici ?"
        - "Peux-tu me montrer ton raisonnement ?"
        - "Comment formulerais-tu cette équation ?"
        - "As-tu une idée pour commencer ?"
        - "Que penses-tu de cette première étape ?"
        """,
        
        "français": """Tu es Naima, enseignante virtuelle de français, passionnée par la langue.
        **TON STYLE :**
        - Tu tutoies toujours l'élève (tu, ton, ta)
        - Tu es chaleureuse, encourageante et patiente
        - Tu signes toujours "— Naima ✨"
        - Tu poses une seule question à la fois
        - Tu ne donnes JAMAIS la réponse directement
        
        **EXEMPLES DE QUESTIONS DE NAIMA :**
        - "Peux-tu identifier le sujet dans cette phrase ?"
        - "Quelle figure de style reconnais-tu ici ?"
        - "Comment conjuguerais-tu ce verbe ?"
        - "Quelle idée principale vois-tu dans ce texte ?"
        - "Comment améliorerais-tu cette formulation ?"
        """,
        
        "anglais": """Tu es Naima, enseignante virtuelle d'anglais, passionnée par les langues.
        **TON STYLE :**
        - Tu tutoies toujours l'élève (tu, ton, ta)
        - Tu es chaleureuse, encourageante et patiente
        - Tu signes toujours "— Naima ✨"
        - Tu poses une seule question à la fois
        - Tu ne donnes JAMAIS la réponse directement
        
        **EXEMPLES DE QUESTIONS DE NAIMA :**
        - "Comment traduirais-tu cette phrase ?"
        - "Quel temps verbal utiliserais-tu ici ?"
        - "Peux-tu me donner un synonyme ?"
        - "Comment prononces-tu ce mot ?"
        - "Quelle est la différence entre ces deux mots ?"
        """,
        
        "histoire": """Tu es Naima, enseignante virtuelle d'histoire, passionnée par le passé.
        **TON STYLE :**
        - Tu tutoies toujours l'élève (tu, ton, ta)
        - Tu es chaleureuse, encourageante et patiente
        - Tu signes toujours "— Naima ✨"
        - Tu poses une seule question à la fois
        - Tu ne donnes JAMAIS les dates/événements directement
        
        **EXEMPLES DE QUESTIONS DE NAIMA :**
        - "Quelles causes imagines-tu pour cet événement ?"
        - "Que comprends-tu de ce document ?"
        - "Quels liens fais-tu avec ta vie d'aujourd'hui ?"
        - "Comment expliquerais-tu cette conséquence ?"
        - "Quelle hypothèse formulerais-tu ?"
        """,
        
        "sciences": """Tu es Naima, enseignante virtuelle de sciences, passionnée par la découverte.
        **TON STYLE :**
        - Tu tutoies toujours l'élève (tu, ton, ta)
        - Tu es chaleureuse, encourageante et patiente
        - Tu signes toujours "— Naima ✨"
        - Tu poses une seule question à la fois
        - Tu ne donnes JAMAIS les réponses directement
        
        **EXEMPLES DE QUESTIONS DE NAIMA :**
        - "Quelle hypothèse proposerais-tu ?"
        - "Comment vérifierais-tu ton idée ?"
        - "Que penses-tu de ce résultat ?"
        - "Quelle expérience imaginerais-tu ?"
        - "Que déduis-tu de cette observation ?"
        """,
        
        "physique": """Tu es Naima, enseignante virtuelle de physique, passionnée par les phénomènes naturels.
        **TON STYLE :**
        - Tu tutoies toujours l'élève (tu, ton, ta)
        - Tu es chaleureuse, encourageante et patiente
        - Tu signes toujours "— Naima ✨"
        - Tu poses une seule question à la fois
        - Tu ne donnes JAMAIS les réponses directement
        
        **EXEMPLES DE QUESTIONS DE NAIMA :**
        - "Quelle loi physique pourrais-tu appliquer ici ?"
        - "Comment décrirais-tu ce mouvement ?"
        - "Quelles forces sont en jeu ?"
        - "Que se passerait-il si... ?"
        - "Comment calculerais-tu cette énergie ?"
        """,
        
        "chimie": """Tu es Naima, enseignante virtuelle de chimie, passionnée par les transformations de la matière.
        **TON STYLE :**
        - Tu tutoies toujours l'élève (tu, ton, ta)
        - Tu es chaleureuse, encourageante et patiente
        - Tu signes toujours "— Naima ✨"
        - Tu poses une seule question à la fois
        - Tu ne donnes JAMAIS les réponses directement
        
        **EXEMPLES DE QUESTIONS DE NAIMA :**
        - "Quelle est la formule chimique ?"
        - "Comment équilibrerais-tu cette équation ?"
        - "Quel type de réaction observes-tu ?"
        - "Que deviendraient ces atomes ?"
        - "Comment nommerais-tu ce composé ?"
        """,
        
        "biologie": """Tu es Naima, enseignante virtuelle de biologie, passionnée par le vivant.
        **TON STYLE :**
        - Tu tutoies toujours l'élève (tu, ton, ta)
        - Tu es chaleureuse, encourageante et patiente
        - Tu signes toujours "— Naima ✨"
        - Tu poses une seule question à la fois
        - Tu ne donnes JAMAIS les réponses directement
        
        **EXEMPLES DE QUESTIONS DE NAIMA :**
        - "Quelle est la fonction de cet organe ?"
        - "Comment fonctionne ce système ?"
        - "Quelles sont les caractéristiques de cette espèce ?"
        - "Comment expliquerais-tu ce processus biologique ?"
        - "Quel rôle joue cette cellule ?"
        """,
        
        "géographie": """Tu es Naima, enseignante virtuelle de géographie, passionnée par le monde.
        **TON STYLE :**
        - Tu tutoies toujours l'élève (tu, ton, ta)
        - Tu es chaleureuse, encourageante et patiente
        - Tu signes toujours "— Naima ✨"
        - Tu poses une seule question à la fois
        - Tu ne donnes JAMAIS les réponses directement
        
        **EXEMPLES DE QUESTIONS DE NAIMA :**
        - "Que remarques-tu sur cette carte ?"
        - "Quel lien vois-tu entre climat et agriculture ?"
        - "Comment expliquerais-tu cette répartition ?"
        - "Quelles caractéristiques observes-tu ?"
        - "Quelle hypothèse fais-tu sur ce paysage ?"
        """,
        
        "musique": """Tu es Naima, enseignante virtuelle de musique, passionnée par l'art sonore.
        **TON STYLE :**
        - Tu tutoies toujours l'élève (tu, ton, ta)
        - Tu es chaleureuse, encourageante et patiente
        - Tu signes toujours "— Naima ✨"
        - Tu poses une seule question à la fois
        - Tu ne donnes JAMAIS les réponses directement
        
        **EXEMPLES DE QUESTIONS DE NAIMA :**
        - "Quelle note entends-tu ?"
        - "Comment nommerais-tu ce rythme ?"
        - "Quels instruments reconnais-tu ?"
        - "Comment interpréterais-tu cette partition ?"
        - "Quelle est la structure de ce morceau ?"
        """,
        
        "arts": """Tu es Naima, enseignante virtuelle d'arts plastiques, passionnée par la création.
        **TON STYLE :**
        - Tu tutoies toujours l'élève (tu, ton, ta)
        - Tu es chaleureuse, encourageante et patiente
        - Tu signes toujours "— Naima ✨"
        - Tu poses une seule question à la fois
        - Tu ne donnes JAMAIS les réponses directement
        
        **EXEMPLES DE QUESTIONS DE NAIMA :**
        - "Quelles couleurs utilises-tu ?"
        - "Quelle technique as-tu employée ?"
        - "Que veux-tu exprimer ?"
        - "Comment organises-tu ta composition ?"
        - "Quel artiste t'a inspiré ?"
        """,
        
        "éducation physique": """Tu es Naima, enseignante virtuelle d'éducation physique, passionnée par le sport.
        **TON STYLE :**
        - Tu tutoies toujours l'élève (tu, ton, ta)
        - Tu es chaleureuse, encourageante et patiente
        - Tu signes toujours "— Naima ✨"
        - Tu poses une seule question à la fois
        - Tu ne donnes JAMAIS les réponses directement
        
        **EXEMPLES DE QUESTIONS DE NAIMA :**
        - "Quelle est la bonne posture ?"
        - "Comment pourrais-tu améliorer ton geste ?"
        - "Quels muscles travaillent ici ?"
        - "Comment organiserais-tu ton échauffement ?"
        - "Quelles règles dois-tu respecter ?"
        """
    }
    
    # Version anglaise (similaire mais en anglais)
    prompts_en = {
        "mathematics": """You are Naima, virtual mathematics teacher, passionate about pedagogy.
        **YOUR STYLE:**
        - You always address students warmly
        - You are warm, encouraging, and patient
        - You always sign "— Naima ✨"
        - You ask one question at a time
        - You NEVER give the answer directly
        
        **NAIMA'S EXAMPLE QUESTIONS:**
        - "What operation would you use here?"
        - "Can you show me your reasoning?"
        - "How would you formulate this equation?"
        - "Do you have an idea to start?"
        - "What do you think about this first step?"
        """,
        
        "french": """You are Naima, virtual French teacher, passionate about language.
        **YOUR STYLE:**
        - You always address students warmly
        - You are warm, encouraging, and patient
        - You always sign "— Naima ✨"
        - You ask one question at a time
        - You NEVER give the answer directly
        
        **NAIMA'S EXAMPLE QUESTIONS:**
        - "How would you translate this sentence?"
        - "What tense would you use here?"
        - "Can you give me a synonym?"
        - "How do you pronounce this word?"
        - "What's the difference between these two words?"
        """,
        
        "english": """You are Naima, virtual English teacher, passionate about languages.
        **YOUR STYLE:**
        - You always address students warmly
        - You are warm, encouraging, and patient
        - You always sign "— Naima ✨"
        - You ask one question at a time
        - You NEVER give the answer directly
        
        **NAIMA'S EXAMPLE QUESTIONS:**
        - "How would you say this in English?"
        - "What verb tense should we use?"
        - "Can you give me a synonym?"
        - "How do you pronounce this word?"
        - "What's the difference between these two words?"
        """,
        
        "history": """You are Naima, virtual history teacher, passionate about the past.
        **YOUR STYLE:**
        - You always address students warmly
        - You are warm, encouraging, and patient
        - You always sign "— Naima ✨"
        - You ask one question at a time
        - You NEVER give dates/events directly
        
        **NAIMA'S EXAMPLE QUESTIONS:**
        - "What causes can you imagine for this event?"
        - "What do you understand from this document?"
        - "What connections do you make with your life today?"
        - "How would you explain this consequence?"
        - "What hypothesis would you formulate?"
        """,
        
        "science": """You are Naima, virtual science teacher, passionate about discovery.
        **YOUR STYLE:**
        - You always address students warmly
        - You are warm, encouraging, and patient
        - You always sign "— Naima ✨"
        - You ask one question at a time
        - You NEVER give answers directly
        
        **NAIMA'S EXAMPLE QUESTIONS:**
        - "What hypothesis would you propose?"
        - "How would you verify your idea?"
        - "What do you think about this result?"
        - "What experiment would you imagine?"
        - "What do you deduce from this observation?"
        """,
        
        "geography": """You are Naima, virtual geography teacher, passionate about the world.
        **YOUR STYLE:**
        - You always address students warmly
        - You are warm, encouraging, and patient
        - You always sign "— Naima ✨"
        - You ask one question at a time
        - You NEVER give answers directly
        
        **NAIMA'S EXAMPLE QUESTIONS:**
        - "What do you notice on this map?"
        - "What connection do you see between climate and agriculture?"
        - "How would you explain this distribution?"
        - "What characteristics do you observe?"
        - "What hypothesis do you make about this landscape?"
        """
    }
    
    # Mapper les noms français aux noms anglais
    fr_to_en = {
        "mathématiques": "mathematics",
        "français": "french",
        "anglais": "english",
        "histoire": "history",
        "sciences": "science",
        "physique": "physics",
        "chimie": "chemistry",
        "biologie": "biology",
        "géographie": "geography",
        "musique": "music",
        "arts": "arts",
        "éducation physique": "physical education"
    }
    
    # Choisir le bon dictionnaire et la bonne clé
    if lang == "fr":
        prompts_dict = prompts_fr
        matiere_key = matiere
    else:
        prompts_dict = prompts_en
        matiere_key = fr_to_en.get(matiere, matiere)
    
    # Récupérer le prompt spécifique ou utiliser un prompt générique
    prompt_base = prompts_dict.get(matiere_key)
    if not prompt_base:
        # Prompt générique si la matière n'est pas trouvée
        if lang == "fr":
            prompt_base = f"""Tu es Naima, enseignante virtuelle de {matiere}, passionnée par la pédagogie.
            **TON STYLE :**
            - Tu tutoies toujours l'élève (tu, ton, ta)
            - Tu es chaleureuse, encourageante et patiente
            - Tu signes toujours "— Naima ✨"
            - Tu poses une seule question à la fois
            - Tu ne donnes JAMAIS la réponse directement
            
            **CONSEILS PÉDAGOGIQUES :**
            - Guide l'élève vers la découverte
            - Encourage chaque petit progrès
            - Adapte-toi au niveau de l'élève
            - Utilise des exemples concrets
            """
        else:
            prompt_base = f"""You are Naima, virtual {matiere} teacher, passionate about pedagogy.
            **YOUR STYLE:**
            - You always address students warmly
            - You are warm, encouraging, and patient
            - You always sign "— Naima ✨"
            - You ask one question at a time
            - You NEVER give the answer directly
            
            **PEDAGOGICAL ADVICE:**
            - Guide the student toward discovery
            - Encourage every small progress
            - Adapt to the student's level
            - Use concrete examples
            """
    
    # Ajouter les règles pédagogiques
    if lang == "fr":
        regles_pedagogiques = f"""
        **MÉTHODOLOGIE PÉDAGOGIQUE DE NAIMA :**
        1. Présente-toi toujours comme Naima, l'enseignante virtuelle
        2. Reformule la question de l'élève pour vérifier ta compréhension
        3. Identifie la compétence spécifique en {matiere}
        4. Guide avec une seule question à la fois
        5. Attends toujours la réponse avant de continuer
        6. Félicite chaleureusement chaque progrès, même petit
        7. Corrige avec douceur et bienveillance
        8. Adapte ton langage au niveau scolaire
        9. Utilise des exemples concrets de la vie quotidienne
        10. Encourage la confiance en soi et la persévérance
        
        **FORMAT DES RÉPONSES DE NAIMA :**
        - Utilise le tutoiement systématique
        - Sois naturellement chaleureuse
        - Pose des questions ouvertes
        - Termine par ta signature "— Naima ✨"
        
        **TA MISSION :** Aider l'élève à construire SA propre compréhension, pas à lui donner des réponses.
        
        {"⚠️ MODE EXAMEN : Guide avec des indices seulement, ne donne pas les étapes complètes." if mode_examen else ""}
        """
    else:
        regles_pedagogiques = f"""
        **NAIMA'S PEDAGOGICAL METHODOLOGY:**
        1. Always introduce yourself as Naima, the virtual teacher
        2. Rephrase the student's question to check your understanding
        3. Identify the specific skill in {matiere}
        4. Guide with one question at a time
        5. Always wait for answer before continuing
        6. Warmly praise every progress, even small
        7. Correct gently and kindly
        8. Adapt your language to school level
        9. Use concrete examples from daily life
        10. Encourage self-confidence and perseverance
        
        **NAIMA'S RESPONSE FORMAT:**
        - Use warm, friendly language
        - Be naturally warm
        - Ask open-ended questions
        - End with your signature "— Naima ✨"
        
        **YOUR MISSION:** Help the student build THEIR own understanding, not give them answers.
        
        {"⚠️ EXAM MODE: Guide with hints only, do not give complete steps." if mode_examen else ""}
        """
    
    # Structure finale du prompt
    prompt_final = f"""# RÔLE : NAIMA, ENSEIGNANTE VIRTUELLE EN {matiere.upper()}

{prompt_base}

{regles_pedagogiques}

**DERNIER RAPPEL IMPORTANT :** 
Tu es NAIMA. Présente-toi, guide avec bienveillance, pose une seule question, félicite les efforts, signe tes messages.

Commence toujours par un accueil chaleureux avec ton nom : "Je suis Naima, ton enseignante virtuelle" (FR) ou "I'm Naima, your virtual teacher" (EN)."""
    
    return prompt_final

def generer_suite_conversation(derniere_q, reponse, historique, niveau, langue="fr", 
                                mode_examen=False, exercice_context="", matiere="mathématiques"):
    """Continue la conversation avec Naima - Version avec garde-fou et retour au sujet"""
    
    # Extraire la question initiale de l'élève (garder le cap)
    question_initiale = ""
    for msg in historique:
        if "👤" in msg and not question_initiale:
            question_initiale = msg.replace("👤 Élève:", "").replace("👤 Student:", "").strip()
            if len(question_initiale) > 10:
                break
    
    # Préparer l'historique
    historique_text = "\n".join(historique[-10:])
    
    if langue == "fr":
        system_prompt = f"""Tu es Naima, enseignante virtuelle en {matiere} (niveau {niveau}).

**GARDE LE CAP - RÈGLE D'OR :**

La question initiale de l'élève était : "{question_initiale if question_initiale else 'résoudre une équation'}"

Tu dois TOUJOURS revenir à cette question. Chaque étape doit te rapprocher de la solution.

**RÈGLES :**
1. Si l'élève s'éloigne du sujet, ramène-le à la question initiale.
2. Ne pars pas dans des sujets parallèles.
3. Réponses max 2-3 phrases.
4. Signe par "— Naima ✨"

**RAPPEL :** Objectif = {question_initiale if question_initiale else "aider l'élève"}

Réponds maintenant :"""
    else:
        system_prompt = f"""You are Naima, a virtual teacher in {matiere} (level {niveau}).

**STAY ON TRACK - GOLDEN RULE:**

The student's initial question was: "{question_initiale if question_initiale else 'solve an equation'}"

You MUST always come back to this question. Each step must move toward the solution.

**RULES:**
1. If the student goes off-topic, bring them back to the initial question.
2. Don't go into parallel subjects.
3. Max 2-3 sentences per response.
4. Sign with "-- Naima ✨"

**REMEMBER:** Goal = {question_initiale if question_initiale else "help the student"}

Answer now:"""
    
    prompt_utilisateur = f"""Dernière question: {derniere_q}
Réponse élève: {reponse}
Rappel objectif initial: {question_initiale}

Ne t'éloigne pas du sujet. Reste concentré sur la résolution de : {question_initiale}"""
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt_utilisateur}
    ]
    
    temperature = 0.2
    max_tokens = 300
    
    reponse_naima = appel_ia(
        messages, 
        type_requete="chat", 
        matiere=matiere, 
        niveau=niveau, 
        langue=langue, 
        temperature=temperature, 
        max_tokens=max_tokens
    )
    
    if langue == "fr" and "— Naima" not in reponse_naima:
        reponse_naima = f"{reponse_naima}\n\n— Naima ✨"
    elif langue == "en" and "-- Naima" not in reponse_naima:
        reponse_naima = f"{reponse_naima}\n\n-- Naima ✨"
    
    return reponse_naima

def generer_debut_conversation(question, niveau, langue="fr", mode_examen=False, matiere="mathématiques"):
    """Début de conversation avec Naima - Version avec routage DeepSeek/OpenAI"""
    
    if langue == "fr":
        system_prompt = f"""Tu es Naima, une enseignante virtuelle bienveillante et passionnée par {matiere}. Tu aides des élèves de niveau {niveau}.

**TON IDENTITÉ :**
- Tu es Naima, l'enseignante virtuelle
- Tu tutoies toujours l'élève (utilise "tu", "ta", "ton")
- Tu es chaleureuse, encourageante et pédagogue
- Tu signes tes messages avec "— Naima ✨"
- Tu poses des questions guidantes une par une
- Tu ne donnes JAMAIS la réponse directement

**TA MISSION :**
Un élève de {niveau} te pose cette question en {matiere} : "{question}"

1. Accueille-le chaleureusement en te présentant comme Naima
2. Reformule sa question pour montrer que tu as compris
3. Donne une orientation générale adaptée à {matiere}
4. Pose la PREMIÈRE QUESTION qui le guide vers la première étape
5. Termine par ton nom pour créer un lien personnel

**FORMAT DE TA RÉPONSE :**
- Salutation avec présentation de Naima
- Reformulation de la question
- Orientation pédagogique
- Première question précise
- Signature : — Naima ✨"""
    else:
        system_prompt = f"""You are Naima, a virtual teacher passionate about {matiere}. You help {niveau} students.

**YOUR IDENTITY:**
- You are Naima, the virtual teacher
- You use warm, friendly language
- You are warm, encouraging, and pedagogical
- You sign your messages with "— Naima ✨"
- You ask guiding questions one at a time
- You NEVER give the answer directly

**YOUR MISSION:**
A {niveau} student asks you this {matiere} question: "{question}"

1. Welcome them warmly, introducing yourself as Naima
2. Rephrase their question to show understanding
3. Give general guidance adapted to {matiere}
4. Ask the FIRST QUESTION that guides them to the first step
5. End with your name to create personal connection

**YOUR RESPONSE FORMAT:**
- Greeting with Naima introduction
- Question rephrasing
- Pedagogical orientation
- First precise question
- Signature: — Naima ✨"""
    
    prompt = f"""**Contexte pédagogique :**
- Niveau : {niveau}
- Matière : {matiere}
- Mode : {"examen (guide avec indices)" if mode_examen else "apprentissage normal"}
- Style : Tutoiement chaleureux et encourageant"""
    
    # Utilisation du routage intelligent
    reponse_naima = get_ai_response(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        matiere=matiere,
        difficulte="moyen",
        max_tokens=450,
        temperature=0.7
    )
    
    # S'assurer que Naima se présente et signe
    if langue == "fr":
        if "Naima" not in reponse_naima[:50]:
            reponse_naima = f"Bonjour ! Je suis Naima, ton enseignante virtuelle. {reponse_naima}"
        if "— Naima" not in reponse_naima and "Naima ✨" not in reponse_naima[-10:]:
            reponse_naima = f"{reponse_naima}\n\n— Naima ✨"
    else:
        if "Naima" not in reponse_naima[:50]:
            reponse_naima = f"Hello! I'm Naima, your virtual teacher. {reponse_naima}"
        if "— Naima" not in reponse_naima and "Naima ✨" not in reponse_naima[-10:]:
            reponse_naima = f"{reponse_naima}\n\n— Naima ✨"
    
    return reponse_naima


def get_message(key, lang="fr"):
    """Système de messages bilingues unifié pour Naima"""
    
    # Structure UNIFIÉE : d'abord par clé, puis par langue
    messages = {
        # Messages d'authentification et essai
        "essai_termine": {
            "fr": "Votre essai gratuit est terminé. Veuillez souscrire à un abonnement pour continuer.",
            "en": "Your free trial has ended. Please subscribe to continue."
        },
        
        # Messages de bienvenue et accueil
        "bienvenue_enseignant": {
            "fr": "Bonjour ! Je suis Naima, ton enseignante virtuelle. Je suis là pour t'aider à comprendre tes leçons et résoudre tes exercices. Quelle est ta question ?",
            "en": "Hello! I'm Naima, your virtual teacher. I'm here to help you understand your lessons and solve your exercises. What's your question?"
        },
        
        # Messages de guidage
        "je_te_guide": {
            "fr": "Je te guide pas à pas...",
            "en": "I'm guiding you step by step..."
        },
        "je_te_guide_court": {
            "fr": "Je te guide...",
            "en": "Guiding you..."
        },
        
        # Messages d'erreur
        "erreur_traitement": {
            "fr": "Une erreur s'est produite. Veuillez réessayer.",
            "en": "An error occurred. Please try again."
        },
        "erreur_ia": {
            "fr": "Désolé, je n'ai pas pu traiter ta demande. Reformule peut-être ?",
            "en": "Sorry, I couldn't process your request. Maybe rephrase it?"
        },
        
        # Messages de dialogue
        "nouveau_dialogue": {
            "fr": "Nouvelle conversation commencée. Pose ta question !",
            "en": "New conversation started. Ask your question!"
        },
        "acces_enseignant": {
            "fr": "Accès à l'enseignant virtuel activé !",
            "en": "Virtual teacher access activated!"
        },
        "conversation_terminee": {
            "fr": "✨ Super ! Tu as compris. N'hésite pas à revenir si tu as d'autres questions !",
            "en": "✨ Great! You understood. Feel free to come back if you have more questions!"
        },
        
        # Messages pour les exercices
        "bravo_exercice_termine": {
            "fr": "🎉 BRAVO ! Tu as terminé l'exercice avec succès ! Veux-tu essayer un autre ?",
            "en": "🎉 WELL DONE! You've successfully completed the exercise! Want to try another?"
        },
        "plus_d_indices": {
            "fr": "Je n'ai plus d'indices, mais je crois en toi ! Essaie de relire l'énoncé.",
            "en": "I have no more hints, but I believe in you! Try re-reading the problem."
        },
        "demande_indice": {
            "fr": "Veux-tu un indice pour t'aider ?",
            "en": "Would you like a hint to help you?"
        },
        "exercice_genere": {
            "fr": "📝 Voici un exercice pour toi ! Prends ton temps pour le résoudre.",
            "en": "📝 Here's an exercise for you! Take your time to solve it."
        },
        "reponse_correcte": {
            "fr": "✅ Exact ! Très bonne réponse !",
            "en": "✅ Exactly! Very good answer!"
        },
        "reponse_incorrecte": {
            "fr": "❌ Presque ! Regarde l'indice et réessaie.",
            "en": "❌ Almost! Look at the hint and try again."
        },
        "indice_suivant": {
            "fr": "💡 Voici un indice supplémentaire :",
            "en": "💡 Here's an additional hint:"
        },
        "exercice_niveau": {
            "fr": "Niveau de difficulté :",
            "en": "Difficulty level:"
        },
        "choisir_difficulte": {
            "fr": "Choisis la difficulté :",
            "en": "Choose difficulty:"
        },
        "generation_exercice": {
            "fr": "Génération de l'exercice en cours...",
            "en": "Generating exercise..."
        },
        "fais_ton_choix": {
            "fr": "Quel exercice veux-tu faire ?",
            "en": "Which exercise would you like to do?"
        },
        "progression_exercice": {
            "fr": "Progression :",
            "en": "Progress:"
        },
        "etape_suivante": {
            "fr": "Passons à l'étape suivante !",
            "en": "Let's move to the next step!"
        },
        "felicitations_fin": {
            "fr": "🎊 FÉLICITATIONS ! Tu as maîtrisé cet exercice !",
            "en": "🎊 CONGRATULATIONS! You've mastered this exercise!"
        },
        
        # Messages pour les matières
        "matiere_maths": {
            "fr": "Mathématiques",
            "en": "Mathematics"
        },
        "matiere_francais": {
            "fr": "Français",
            "en": "French"
        },
        "matiere_histoire": {
            "fr": "Histoire",
            "en": "History"
        },
        "matiere_sciences": {
            "fr": "Sciences",
            "en": "Science"
        },
        "matiere_geo": {
            "fr": "Géographie",
            "en": "Geography"
        },
        
        # Messages d'encouragement
        "encouragement_1": {
            "fr": "Continue comme ça !",
            "en": "Keep it up!"
        },
        "encouragement_2": {
            "fr": "Tu y es presque !",
            "en": "You're almost there!"
        },
        "encouragement_3": {
            "fr": "Excellent raisonnement !",
            "en": "Excellent reasoning!"
        },
        "encouragement_4": {
            "fr": "Je suis fière de toi !",
            "en": "I'm proud of you!"
        },
        
        # Messages d'interface
        "placeholder_question": {
            "fr": "Pose ta question à Naima...",
            "en": "Ask your question to Naima..."
        },
        "placeholder_reponse": {
            "fr": "Réponds à Naima...",
            "en": "Answer Naima..."
        },
        "bouton_envoyer": {
            "fr": "Envoyer",
            "en": "Send"
        },
        "bouton_nouveau": {
            "fr": "Nouvelle conversation",
            "en": "New conversation"
        },
        "bouton_compris": {
            "fr": "J'ai compris ✓",
            "en": "I understand ✓"
        },
        "bouton_exercice": {
            "fr": "Exercice",
            "en": "Exercise"
        }
    }
    
    # Récupération avec gestion d'erreur avancée
    if key in messages:
        # La clé existe
        if lang in messages[key]:
            # La langue existe pour cette clé
            return messages[key][lang]
        else:
            # Langue non trouvée, retour français par défaut
            return messages[key].get("fr", f"[{key}]")
    else:
        # Clé non trouvée, retourner la clé pour debug
        print(f"⚠️ Message key not found: {key}")
        return f"[{key}]"


# ============ ROUTE ADAPTÉE ============
@app.route("/api/eleve/stats", methods=["GET"])
def api_eleve_stats():
    """
    API pour récupérer les statistiques de l'élève.

    Version optimisée :
    - compatible SQLAlchemy 2 ;
    - évite User.query.get ;
    - réduit les requêtes ;
    - ajoute un petit cache session pour éviter de recalculer trop souvent ;
    - accepte eleve et élève.
    """

    from datetime import datetime, date
    from sqlalchemy import func, case

    if "user_id" not in session:
        return jsonify({"error": "Non authentifié"}), 401

    user_id = session.get("user_id")

    # Petit cache de 30 secondes pour éviter les recalculs répétés
    cache = session.get("api_eleve_stats_cache")

    if cache:
        cache_user_id = cache.get("user_id")
        cache_time = cache.get("timestamp")
        maintenant = datetime.utcnow().timestamp()

        if cache_user_id == user_id and cache_time and maintenant - cache_time < 30:
            data = cache.get("data", {})
            data["cached"] = True
            return jsonify(data)

    eleve = db.session.get(User, user_id)

    if not eleve or eleve.role not in ["eleve", "élève"]:
        return jsonify({"error": "Accès non autorisé"}), 403

    from models import StudentResponse

    # ============================================================
    # TOTAL + RÉUSSITES EN UNE SEULE REQUÊTE
    # ============================================================

    try:
        if hasattr(StudentResponse, "etoiles"):
            total, reussis = db.session.query(
                func.count(StudentResponse.id),
                func.coalesce(
                    func.sum(
                        case(
                            (StudentResponse.etoiles >= 3, 1),
                            else_=0
                        )
                    ),
                    0
                )
            ).filter(
                StudentResponse.user_id == eleve.id
            ).one()
        else:
            total = db.session.query(
                func.count(StudentResponse.id)
            ).filter(
                StudentResponse.user_id == eleve.id
            ).scalar() or 0

            reussis = 0

    except Exception as e:
        print(f"⚠️ Erreur statistiques élève: {e}")
        total = 0
        reussis = 0

    total = int(total or 0)
    reussis = int(reussis or 0)

    # ============================================================
    # CALCUL DE LA SÉRIE
    # ============================================================

    serie = 0

    def normaliser_date(valeur):
        """
        Convertit une valeur date venant de SQLite/PostgreSQL en objet date Python.
        """

        if not valeur:
            return None

        if isinstance(valeur, datetime):
            return valeur.date()

        if isinstance(valeur, date):
            return valeur

        if isinstance(valeur, str):
            try:
                return datetime.strptime(valeur[:10], "%Y-%m-%d").date()
            except Exception:
                return None

        return None

    try:
        dates_brutes = db.session.query(
            func.date(StudentResponse.timestamp)
        ).filter(
            StudentResponse.user_id == eleve.id,
            StudentResponse.timestamp.isnot(None)
        ).distinct().order_by(
            func.date(StudentResponse.timestamp).desc()
        ).limit(60).all()

        dates_list = []

        for ligne in dates_brutes:
            d = normaliser_date(ligne[0])
            if d:
                dates_list.append(d)

        if dates_list:
            today = datetime.utcnow().date()

            if dates_list[0] == today:
                serie = 1

                for i in range(len(dates_list) - 1):
                    if (dates_list[i] - dates_list[i + 1]).days == 1:
                        serie += 1
                    else:
                        break

    except Exception as e:
        print(f"⚠️ Erreur calcul série élève: {e}")
        serie = 0

    taux_reussite = round((reussis / total * 100) if total > 0 else 0)

    data = {
        "success": True,
        "total_exercices": total,
        "exercices_reussis": reussis,
        "taux_reussite": taux_reussite,
        "serie": serie,
        "temps_apprentissage": 0,
        "cached": False
    }

    # Sauvegarde cache session
    session["api_eleve_stats_cache"] = {
        "user_id": user_id,
        "timestamp": datetime.utcnow().timestamp(),
        "data": data
    }
    session.modified = True

    return jsonify(data)

@app.route("/admin/ai-config", methods=["GET"])
@admin_required
def admin_ai_config():
    """Page de configuration IA par matière"""
    configs = MatiereAIConfig.query.order_by(MatiereAIConfig.matiere_nom).all()
    return render_template("admin_ai_config.html", configs=configs, lang=session.get("lang", "fr"))


@app.route("/admin/ai-config/add", methods=["POST"])
@admin_required
def admin_ai_config_add():
    """Ajouter une configuration"""
    matiere_nom = request.form.get("matiere_nom")
    api_choice = request.form.get("api_choice")
    modele_ia = request.form.get("modele_ia")
    description = request.form.get("description", "")
    
    if not matiere_nom or not api_choice or not modele_ia:
        flash("Tous les champs sont requis", "error")
        return redirect(url_for("admin_ai_config"))
    
    existing = MatiereAIConfig.query.filter_by(matiere_nom=matiere_nom).first()
    if existing:
        flash(f"La matière '{matiere_nom}' existe déjà", "error")
        return redirect(url_for("admin_ai_config"))
    
    new_config = MatiereAIConfig(
        matiere_nom=matiere_nom,
        api_choice=api_choice,
        modele_ia=modele_ia,
        description=description,
        actif=True
    )
    db.session.add(new_config)
    db.session.commit()
    
    flash(f"Configuration pour '{matiere_nom}' ajoutée", "success")
    return redirect(url_for("admin_ai_config"))


@app.route("/admin/ai-config/<int:config_id>/edit", methods=["POST"])
@admin_required
def admin_ai_config_edit(config_id):
    """Modifier une configuration"""
    config = MatiereAIConfig.query.get_or_404(config_id)
    
    config.api_choice = request.form.get("api_choice")
    config.modele_ia = request.form.get("modele_ia")
    config.description = request.form.get("description", "")
    config.actif = request.form.get("actif") == "on"
    config.date_modification = datetime.utcnow()
    
    db.session.commit()
    flash(f"Configuration pour '{config.matiere_nom}' mise à jour", "success")
    return redirect(url_for("admin_ai_config"))


@app.route("/admin/ai-config/<int:config_id>/delete", methods=["POST"])
@admin_required
def admin_ai_config_delete(config_id):
    """Supprimer une configuration"""
    config = MatiereAIConfig.query.get_or_404(config_id)
    matiere_nom = config.matiere_nom
    db.session.delete(config)
    db.session.commit()
    flash(f"Configuration pour '{matiere_nom}' supprimée", "success")
    return redirect(url_for("admin_ai_config"))


@app.route("/debug-conversation")
def debug_conversation():
    """Affiche l'état de la conversation"""
    return {
        "conversation": session.get("conversation", []),
        "derniere_q_ia": session.get("derniere_q_ia"),
        "session_keys": list(session.keys())
    }


def ia_detect_comprehension(conversation_recente, matiere, langue):
    """Demande à l'IA si l'élève a vraiment compris"""
    from openai import OpenAI
    import os
    
    prompt = f"""
Analyse cette conversation et dis si l'élève a COMPRIS le concept ou s'il a besoin de continuer.

CONVERSATION:
{conversation_recente}

MATIÈRE: {matiere}

Réponds UNIQUEMENT par:
- "COMPRIS" si l'élève a démontré une compréhension solide
- "CONTINUER" si l'élève a besoin de plus de pratique
"""
    
    try:
        client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=20
        )
        result = response.choices[0].message.content.strip().upper()
        return result == "COMPRIS"
    except:
        return False  # En cas d'erreur, continuer


def detecter_mode_pedagogique(question):
    """
    Détecte le type de demande de l'élève.
    Retourne :
    - explication_lecon
    - resolution
    - entrainement
    - conversation
    """

    texte = (question or "").lower().strip()

    mots_explication = [
        "explique",
        "explique-moi",
        "explique moi",
        "je veux comprendre",
        "je ne comprends pas la leçon",
        "je ne comprends pas la lecon",
        "aide-moi à comprendre",
        "aide moi à comprendre",
        "c'est quoi",
        "qu'est-ce que",
        "qu’est-ce que",
        "peux-tu m'expliquer",
        "peux tu m'expliquer",
        "cours sur",
        "leçon sur",
        "lecon sur"
    ]

    mots_resolution = [
        "résous",
        "resous",
        "résoudre",
        "resoudre",
        "calcule",
        "trouve",
        "détermine",
        "determine",
        "factorise",
        "simplifie",
        "résolution",
        "resolution",
        "="
    ]

    mots_entrainement = [
        "donne-moi un exercice",
        "donne moi un exercice",
        "propose un exercice",
        "je veux m'exercer",
        "exercice pour pratiquer",
        "entraîne-moi",
        "entraine-moi",
        "entrainement",
        "pratiquer"
    ]

    if any(mot in texte for mot in mots_explication):
        return "explication_lecon"

    if any(mot in texte for mot in mots_entrainement):
        return "entrainement"

    if any(mot in texte for mot in mots_resolution):
        return "resolution"

    return "conversation"

def construire_contexte_apprentissage_eleve(user_id, limite=25, lang="fr"):
    """
    Construit un résumé pédagogique court à partir des dernières traces d'apprentissage
    d'un élève.

    Ce résumé est destiné à être injecté dans les prompts de Naima pour personnaliser
    l'accompagnement sans surcharger l'élève.
    """

    try:
        from models import TraceApprentissage
        from collections import Counter

        traces = (
            TraceApprentissage.query
            .filter(TraceApprentissage.user_id == user_id)
            .order_by(TraceApprentissage.created_at.desc())
            .limit(limite)
            .all()
        )

        if not traces:
            if lang == "en":
                return (
                    "\n\nStudent learning context:\n"
                    "- No previous learning trace is available yet.\n"
                    "- Adapt your guidance based only on the current answer.\n"
                )

            return (
                "\n\nContexte d’apprentissage de l’élève :\n"
                "- Aucune trace d’apprentissage précédente n’est encore disponible.\n"
                "- Adapte ton guidage uniquement à partir de la réponse actuelle.\n"
            )

        scores = [
            trace.score for trace in traces
            if trace.score is not None
        ]

        score_moyen = round(sum(scores) / len(scores), 1) if scores else None

        risques = Counter()
        notions = Counter()
        erreurs = Counter()
        difficultes = Counter()

        derniere_trace = traces[0] if traces else None

        for trace in traces:
            if trace.niveau_risque:
                risques[trace.niveau_risque] += 1

            if trace.notion_cible:
                notions[trace.notion_cible] += 1

            if trace.type_erreur:
                erreurs[trace.type_erreur] += 1

            if trace.difficulte_estimee:
                difficultes[trace.difficulte_estimee] += 1

        def top_items(counter, n=3):
            return [item for item, count in counter.most_common(n) if item]

        notions_principales = top_items(notions, 4)
        erreurs_principales = top_items(erreurs, 4)
        difficultes_principales = top_items(difficultes, 2)

        if risques:
            risque_dominant = risques.most_common(1)[0][0]
        else:
            risque_dominant = "non déterminé"

        if risque_dominant == "élevé":
            strategie_fr = (
                "Procède très progressivement. Pose une seule question simple à la fois. "
                "Reviens aux bases si nécessaire et évite de donner toute la solution directement."
            )
            strategie_en = (
                "Proceed very gradually. Ask only one simple question at a time. "
                "Go back to basics if needed and avoid giving the full solution directly."
            )

        elif risque_dominant == "moyen":
            strategie_fr = (
                "Guide l’élève avec des questions ciblées. Demande-lui de justifier sa démarche "
                "et corrige les petites erreurs sans changer de sujet."
            )
            strategie_en = (
                "Guide the student with targeted questions. Ask them to justify their reasoning "
                "and correct small mistakes without changing topic."
            )

        elif risque_dominant == "faible":
            strategie_fr = (
                "L’élève semble relativement à l’aise. Tu peux demander une justification, "
                "proposer un léger défi ou encourager la généralisation."
            )
            strategie_en = (
                "The student seems relatively comfortable. You may ask for justification, "
                "offer a small challenge, or encourage generalization."
            )

        else:
            strategie_fr = (
                "Le profil est encore peu documenté. Observe la réponse actuelle et adapte ton guidage."
            )
            strategie_en = (
                "The profile is not well documented yet. Observe the current answer and adapt your guidance."
            )

        if lang == "en":
            contexte = "\n\nStudent learning context from previous traces:\n"
            contexte += f"- Recent traces analyzed: {len(traces)}.\n"

            if score_moyen is not None:
                contexte += f"- Recent average score: {score_moyen}%.\n"
            else:
                contexte += "- Recent average score: not available.\n"

            contexte += f"- Dominant risk level: {risque_dominant}.\n"

            if notions_principales:
                contexte += "- Frequently targeted concepts: " + ", ".join(notions_principales) + ".\n"
            else:
                contexte += "- Frequently targeted concepts: not enough data.\n"

            if erreurs_principales:
                contexte += "- Frequent error types: " + ", ".join(erreurs_principales) + ".\n"
            else:
                contexte += "- Frequent error types: not enough data.\n"

            if difficultes_principales:
                contexte += "- Recent difficulty levels: " + ", ".join(difficultes_principales) + ".\n"

            if derniere_trace and derniere_trace.score is not None:
                contexte += f"- Last recorded score: {derniere_trace.score}%.\n"

            contexte += f"- Recommended teaching strategy: {strategie_en}\n"

            contexte += (
                "\nUse this context silently to adapt your teaching. "
                "Do not mention that you are reading database traces. "
                "Do not overwhelm the student with diagnostics. "
                "Use it only to choose the right level of guidance.\n"
            )

            return contexte

        contexte = "\n\nContexte d’apprentissage de l’élève à partir des traces précédentes :\n"
        contexte += f"- Nombre de traces récentes analysées : {len(traces)}.\n"

        if score_moyen is not None:
            contexte += f"- Score moyen récent : {score_moyen}%.\n"
        else:
            contexte += "- Score moyen récent : non disponible.\n"

        contexte += f"- Niveau de risque dominant : {risque_dominant}.\n"

        if notions_principales:
            contexte += "- Notions fréquemment travaillées : " + ", ".join(notions_principales) + ".\n"
        else:
            contexte += "- Notions fréquemment travaillées : données insuffisantes.\n"

        if erreurs_principales:
            contexte += "- Types d’erreurs fréquents : " + ", ".join(erreurs_principales) + ".\n"
        else:
            contexte += "- Types d’erreurs fréquents : données insuffisantes.\n"

        if difficultes_principales:
            contexte += "- Difficultés récentes observées : " + ", ".join(difficultes_principales) + ".\n"

        if derniere_trace and derniere_trace.score is not None:
            contexte += f"- Dernier score enregistré : {derniere_trace.score}%.\n"

        contexte += f"- Stratégie pédagogique recommandée : {strategie_fr}\n"

        contexte += (
            "\nUtilise ce contexte silencieusement pour adapter ton accompagnement. "
            "Ne dis pas à l’élève que tu lis des traces de base de données. "
            "Ne surcharge pas l’élève avec des diagnostics. "
            "Utilise ces informations uniquement pour choisir le bon niveau de guidage.\n"
        )

        return contexte

    except Exception as e:
        print(f"⚠️ Contexte apprentissage non disponible pour l'élève {user_id} : {e}")

        if lang == "en":
            return (
                "\n\nStudent learning context:\n"
                "- Previous learning context could not be loaded.\n"
                "- Adapt your guidance based on the current answer only.\n"
            )

        return (
            "\n\nContexte d’apprentissage de l’élève :\n"
            "- Le contexte d’apprentissage précédent n’a pas pu être chargé.\n"
            "- Adapte ton guidage à partir de la réponse actuelle uniquement.\n"
        )


@app.route("/enseignant-virtuel", methods=['GET', 'POST'])
def enseignant_virtuel():
    """
    Route pour l'enseignant virtuel Naima.

    Version avec :
    - IA conversationnelle ;
    - diagnostic bayésien ;
    - vérification mathématique locale sécurisée ;
    - mémoire de l'objectif pédagogique ;
    - recentrage général sur la demande initiale ;
    - détection quand l'élève signale que la conversation tourne en rond ;
    - contexte d'apprentissage personnalisé à partir des traces ;
    - suivi back-end de la connexion de Naima au processus pédagogique ;
    - analyse pédagogique intelligente ;
    - enregistrement admin sans doublon ;
    - trace d'apprentissage Naima avec rattachement simple et robuste.
    """

    from datetime import datetime
    import re

    from services.bayesian_diagnostic import diagnostiquer_difficulte
    from services.math_verification import (
        verifier_expression_fractionnaire,
        verifier_solution_equation_fractionnaire,
        verifier_resultat_expression_contextuelle,
        verifier_chaine_egalites_fractionnaire
    )

    # ============================================================
    # AUTHENTIFICATION
    # ============================================================

    if "user_id" not in session:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': 'Non authentifié'}), 401
        return redirect(url_for("login_eleve"))

    utilisateur = db.session.get(User, session["user_id"])

    if not utilisateur or utilisateur.role not in ["eleve", "élève"]:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': 'Accès non autorisé'}), 403
        return redirect(url_for("login_eleve"))

    # ============================================================
    # VARIABLES LOCALES
    # ============================================================

    eleve = utilisateur
    current_lang = session.get("lang", "fr")
    conversation = session.get("conversation", [])
    matiere = session.get("matiere", "mathématiques")

    niveau_eleve = (
        eleve.niveau.nom
        if eleve.niveau
        else ("6th grade" if current_lang == "en" else "6ème")
    )

    # ============================================================
    # CONTEXTE D'APPRENTISSAGE PERSONNALISÉ POUR NAIMA
    # ============================================================

    contexte_apprentissage_eleve = construire_contexte_apprentissage_eleve(
        user_id=eleve.id,
        limite=25,
        lang=current_lang
    )

    naima_processus_connecte = {
        "traces_apprentissage": bool(contexte_apprentissage_eleve),
        "diagnostic_bayesien": False,
        "verification_math_locale": False,
        "recentrage_pedagogique": False,
        "analyse_pedagogique": False,
        "profil_personnalise": True,
        "contexte_injecte": True,
        "source": "TraceApprentissage + DiagnosticBayesien + session pédagogique",
        "derniere_mise_a_jour": datetime.utcnow().isoformat()
    }

    session["naima_processus_connecte"] = naima_processus_connecte
    session.modified = True

    print("🧠 Naima connectée au processus pédagogique.")
    print("   - Traces apprentissage :", naima_processus_connecte["traces_apprentissage"])
    print("   - Profil personnalisé :", naima_processus_connecte["profil_personnalise"])
    print("   - Contexte injecté :", naima_processus_connecte["contexte_injecte"])

    # ============================================================
    # OUTILS INTERNES
    # ============================================================

    def format_messages(msgs, time_str):
        html = []

        for msg in msgs[-10:]:
            if "👤" in msg:
                content = (
                    msg.replace("👤 Élève:", "")
                    .replace("👤 Student:", "")
                    .strip()
                )

                html.append(
                    f'<div class="message user">'
                    f'<div class="message-avatar"><i class="fas fa-user-graduate"></i></div>'
                    f'<div class="message-content">{content}'
                    f'<div class="message-time">{time_str}</div>'
                    f'</div></div>'
                )

            elif "🤖" in msg:
                content = msg.replace("🤖 Naima:", "").strip()

                html.append(
                    f'<div class="message naima">'
                    f'<div class="message-avatar"><i class="fas fa-robot"></i></div>'
                    f'<div class="message-content">{content}'
                    f'<div class="message-time">{time_str}</div>'
                    f'</div></div>'
                )

        return html

    def detecter_mode_pedagogique(question):
        """
        Détecte le type général de demande de l'élève.

        Modes possibles :
        - explication_lecon
        - resolution
        - entrainement
        - conversation
        """

        texte = (question or "").lower().strip()

        mots_explication = [
            "explique",
            "explique-moi",
            "explique moi",
            "je veux comprendre",
            "je ne comprends pas la leçon",
            "je ne comprends pas la lecon",
            "aide-moi à comprendre",
            "aide moi à comprendre",
            "c'est quoi",
            "c’est quoi",
            "qu'est-ce que",
            "qu’est-ce que",
            "peux-tu m'expliquer",
            "peux tu m'expliquer",
            "cours sur",
            "leçon sur",
            "lecon sur",
            "notion de",
            "définition",
            "definition"
        ]

        mots_resolution = [
            "résous",
            "resous",
            "résoudre",
            "resoudre",
            "calcule",
            "calculer",
            "effectue",
            "effectuer",
            "effectue-moi",
            "effectue moi",
            "faire le calcul",
            "fais le calcul",
            "combien vaut",
            "quel est le résultat",
            "quel est le resultat",
            "trouve",
            "trouver",
            "détermine",
            "determine",
            "factorise",
            "factoriser",
            "simplifie",
            "simplifier",
            "résolution",
            "resolution",
            "équation",
            "equation",
            "="
        ]

        mots_entrainement = [
            "donne-moi un exercice",
            "donne moi un exercice",
            "propose un exercice",
            "je veux m'exercer",
            "je veux m’exercer",
            "exercice pour pratiquer",
            "entraîne-moi",
            "entraine-moi",
            "entrainement",
            "entraînement",
            "pratiquer",
            "m'exercer",
            "m’exercer"
        ]

        if any(mot in texte for mot in mots_explication):
            return "explication_lecon"

        if any(mot in texte for mot in mots_entrainement):
            return "entrainement"

        if any(mot in texte for mot in mots_resolution):
            return "resolution"

        return "conversation"

    def estimer_signaux_pedagogiques(question_eleve, derniere_question_ia=None):
        """
        Convertit une réponse d'élève en signaux simples
        pour le diagnostic bayésien.
        """

        texte = (question_eleve or "").lower().strip()
        derniere_q = (derniere_question_ia or "").lower().strip()

        if not texte:
            return "faible", "beaucoup", "lent"

        mots_blocage = [
            "je ne comprends pas",
            "je comprends pas",
            "je ne comprend pas",
            "je comprend pas",
            "je ne sais pas",
            "je sais pas",
            "je sais pas quoi faire",
            "aide-moi",
            "aide moi",
            "bloqué",
            "bloquée",
            "bloquee",
            "je suis bloqué",
            "je suis bloquée",
            "difficile",
            "je suis perdu",
            "je suis perdue",
            "pas compris",
            "comprend pas",
            "comprends pas",
            "explique",
            "explique-moi",
            "explique moi",
            "je n'arrive pas",
            "j'arrive pas",
            "je n’y arrive pas",
            "je n'y arrive pas",
            "je suis coincé",
            "je suis coince",
            "je suis coincée"
        ]

        mots_frustration = [
            "c'est toi",
            "tu ne sais pas",
            "tu sais pas",
            "vérifie toi-même",
            "verifie toi meme",
            "vérifie toi meme",
            "je suis désolé",
            "je suis desolé",
            "ce n'est pas ça",
            "ce n'est pas ca",
            "c'est faux",
            "tu te trompes",
            "tu fais erreur",
            "non",
            "pas du tout",
            "on tourne en rond",
            "tu répètes",
            "tu repetes",
            "déjà fait",
            "deja fait",
            "pas la peine"
        ]

        mots_maitrise = [
            "j'ai compris",
            "je comprends",
            "c'est clair",
            "facile",
            "je pense que",
            "la réponse est",
            "la reponse est",
            "donc",
            "parce que",
            "car",
            "revient à",
            "revient a",
            "on obtient",
            "j'obtiens",
            "en divisant",
            "en multipliant",
            "en additionnant",
            "en soustrayant",
            "des deux côtés",
            "des deux cotes",
            "aux deux membres",
            "je simplifie",
            "je remplace",
            "si je remplace",
            "je vérifie",
            "je verifie"
        ]

        mots_correction = [
            "pardon",
            "je corrige",
            "correction",
            "je voulais dire",
            "non plutôt",
            "non plutot",
            "c'est plutôt",
            "c'est plutot",
            "au lieu de",
            "et non"
        ]

        mots_reponse_finale = [
            "x=",
            "x =",
            "la réponse est",
            "la reponse est",
            "j'obtiens",
            "on obtient",
            "donc x",
            "alors x",
            "ça donne",
            "ca donne"
        ]

        mots_operation = [
            "+",
            "-",
            "*",
            "×",
            "/",
            "÷",
            "=",
            "divisé",
            "divise",
            "multiplié",
            "multiplie",
            "addition",
            "soustraction",
            "fraction",
            "simplifie",
            "simplifier",
            "factorise",
            "factoriser"
        ]

        blocage = any(mot in texte for mot in mots_blocage)
        frustration = any(mot in texte for mot in mots_frustration)
        maitrise = any(mot in texte for mot in mots_maitrise)
        correction = any(mot in texte for mot in mots_correction)
        reponse_finale = any(mot in texte for mot in mots_reponse_finale)
        contient_operation = any(mot in texte for mot in mots_operation)

        contexte_calcul = any(mot in derniere_q for mot in [
            "isoler x",
            "trouver la valeur",
            "simplifier",
            "calcule",
            "calcul",
            "division",
            "fraction",
            "équation",
            "equation",
            "résoudre",
            "resoudre",
            "addition",
            "soustraction",
            "multiplier",
            "diviser",
            "factoriser",
            "factorise",
            "racine",
            "solution"
        ])

        if blocage:
            return "faible", "beaucoup", "lent"

        if frustration:
            return "faible", "beaucoup", "lent"

        if correction and contient_operation:
            return "moyenne", "peu", "rapide"

        if contient_operation and maitrise:
            return "bonne", "peu", "rapide"

        if contexte_calcul and reponse_finale and len(texte) < 30:
            return "moyenne", "peu", "rapide"

        if contexte_calcul and len(texte) < 20:
            return "moyenne", "peu", "rapide"

        if maitrise and len(texte) >= 30:
            return "bonne", "peu", "rapide"

        if len(texte) < 12:
            return "moyenne", "peu", "rapide"

        if contient_operation:
            return "moyenne", "peu", "rapide"

        return "moyenne", "peu", "rapide"

    def peut_verifier_calcul_localement(texte):
        """
        Autorise la vérification locale seulement pour des égalités numériques simples.
        Évite les faux négatifs sur les phrases contenant des variables :
        b² - 4ac, ax² + bx + c, x = ..., etc.
        """

        texte = (texte or "").strip()

        if not texte:
            return False

        if "=" not in texte:
            return False

        # Si la réponse contient des lettres, on évite la vérification locale simple.
        # Exemple à éviter : b² - 4ac = ...
        if re.search(r"[a-zA-Z]", texte):
            return False

        caracteres_autorises = r"^[0-9\s\+\-\*\/\(\)\.,=×÷²³]+$"

        if not re.match(caracteres_autorises, texte):
            return False

        return True

    def obtenir_objectif_effectif_naima():
        exercice = session.get("exercice_en_cours") or {}
        enonce = (exercice.get("enonce") or "").strip()

        if enonce:
            return enonce, "exercice_genere"

        return (
            (session.get("objectif_initial_naima") or "").strip(),
            "chat"
        )


    def contient_variable_mathematique(texte):
        texte = (texte or "").lower()

        if re.search(
            r"(?<![a-zà-ÿ])[xyzabc](?![a-zà-ÿ])",
            texte
        ):
            return True

        if re.search(r"\d\s*[xyzabc]\b", texte):
            return True

        if re.search(r"\b[xyzabc]\s*[=+\-*/]", texte):
            return True

        return False


    def construire_contexte_exercice_genere():
        exercice = session.get("exercice_en_cours") or {}
        enonce = (exercice.get("enonce") or "").strip()

        if not enonce:
            return ""

        correction = exercice.get("correction") or {}
        reponse_finale = ""

        if isinstance(correction, dict):
            reponse_finale = str(
                correction.get("reponse_finale") or ""
            ).strip()

        texte = (
            "\n\nContexte interne de l'exercice généré : "
            f"Énoncé officiel : « {enonce} ». "
            f"Étape enregistrée : {exercice.get('etape', 1)}. "
        )

        if exercice.get("total_etapes"):
            texte += (
                f"Nombre total d'étapes prévues : "
                f"{exercice.get('total_etapes')}. "
            )

        if (
            reponse_finale
            and reponse_finale.lower()
            not in {"réponse à vérifier", "reponse a verifier"}
        ):
            texte += (
                f"Réponse finale interne de référence : "
                f"« {reponse_finale} ». "
                "Ne la donne pas directement à l'élève. "
            )

        texte += (
            "Ne remplace jamais cet énoncé par une réponse intermédiaire. "
            "Ne reviens pas à une étape déjà correctement validée. "
            "Si la réponse finale est prouvée correcte, conclus l'exercice."
        )

        return texte


    def mettre_a_jour_statut_naima(cle, valeur=True):
        """
        Met à jour le statut back-end de connexion de Naima au processus pédagogique.
        """

        statut = session.get("naima_processus_connecte") or naima_processus_connecte
        statut[cle] = valeur
        statut["derniere_mise_a_jour"] = datetime.utcnow().isoformat()
        session["naima_processus_connecte"] = statut
        session.modified = True

    def construire_instruction_bayesienne(diagnostic):
        """
        Transforme le diagnostic bayésien en consigne pédagogique interne.
        """

        diagnostic = diagnostic or {}
        niveau_risque = diagnostic.get("niveau_risque", "inconnu")
        pourcentage = diagnostic.get("pourcentage_difficulte", 0)

        if current_lang == "fr":
            if niveau_risque == "élevé":
                return (
                    f"\n\nDiagnostic pédagogique interne : risque de difficulté élevé "
                    f"({pourcentage}%). "
                    "Réponds comme une enseignante socratique très guidante. "
                    "Ne donne pas directement toute la solution. "
                    "Pose une question simple à la fois. "
                    "Reviens à l'étape précédente si nécessaire. "
                    "Encourage l'élève et vérifie sa compréhension. "
                    "Avant de dire que l'élève s'est trompé, vérifie soigneusement le calcul. "
                    "Si l'élève a raison, reconnais-le clairement et continue à partir de sa bonne réponse. "
                    "Si l'élève se trompe, explique l'erreur avec douceur."
                )

            if niveau_risque == "moyen":
                return (
                    f"\n\nDiagnostic pédagogique interne : risque de difficulté moyen "
                    f"({pourcentage}%). "
                    "Réponds de façon socratique. "
                    "Pose une question de clarification. "
                    "Aide l'élève à justifier son raisonnement sans donner directement toute la réponse. "
                    "Avant de dire que l'élève s'est trompé, vérifie toi-même le calcul. "
                    "Si l'élève a raison, reconnais-le clairement. "
                    "Si une étape est incomplète, demande-lui de la préciser."
                )

            return (
                f"\n\nDiagnostic pédagogique interne : risque de difficulté faible "
                f"({pourcentage}%). "
                "Tu peux proposer une question un peu plus exigeante, "
                "demander une justification ou encourager l'élève à généraliser sa méthode. "
                "Avant de dire que l'élève s'est trompé, vérifie toi-même le calcul. "
                "Si l'élève a raison, reconnais-le clairement. "
                "Ne force pas l'élève à changer une réponse correcte."
            )

        if niveau_risque == "élevé":
            return (
                f"\n\nInternal pedagogical diagnosis: high difficulty risk "
                f"({pourcentage}%). "
                "Answer like a very guided Socratic teacher. "
                "Do not give the full solution directly. "
                "Ask one simple question at a time. "
                "Go back to the previous step if needed. "
                "Encourage the student and check understanding. "
                "Before saying the student is wrong, carefully verify the calculation. "
                "If the student is correct, clearly acknowledge it and continue from their correct answer."
            )

        if niveau_risque == "moyen":
            return (
                f"\n\nInternal pedagogical diagnosis: medium difficulty risk "
                f"({pourcentage}%). "
                "Use a Socratic approach. "
                "Ask a clarifying question and help the student justify their reasoning. "
                "Before saying the student is wrong, verify the calculation yourself. "
                "If the student is correct, clearly acknowledge it."
            )

        return (
            f"\n\nInternal pedagogical diagnosis: low difficulty risk "
            f"({pourcentage}%). "
            "You may ask a more challenging question, request justification, "
            "or encourage the student to generalize the method. "
            "Before saying the student is wrong, verify the calculation yourself. "
            "If the student is correct, clearly acknowledge it."
        )

    def construire_instruction_recentrage(question_actuelle=""):
        """
        Instruction générale pour garder Naima centrée sur l'objectif pédagogique
        et l'obliger à traiter la réponse actuelle de l'élève avant de poser
        une nouvelle question.
        """

        objectif_initial = session.get("objectif_initial_naima", "").strip()
        mode_pedagogique = session.get("mode_pedagogique_naima", "conversation")
        lecon_courante = session.get("lecon_courante_naima", "").strip()
        derniere_question_ia = session.get("derniere_q_ia", "").strip()
        question_actuelle = (question_actuelle or "").strip()

        texte_actuel = question_actuelle.lower()

        signaux_tourne_en_rond = [
            "on tourne en rond",
            "déjà fait",
            "deja fait",
            "déjà calculé",
            "deja calculé",
            "pas la peine",
            "tu répètes",
            "tu repetes",
            "tu as déjà demandé",
            "tu as deja demandé",
            "on l'a déjà fait",
            "on l'a deja fait",
            "c'est déjà fait",
            "c'est deja fait",
            "tu me demandes la même chose",
            "tu me demandes la meme chose"
        ]

        if any(signal in texte_actuel for signal in signaux_tourne_en_rond):
            mettre_a_jour_statut_naima("recentrage_pedagogique", True)

            if current_lang == "fr":
                return (
                    "\n\nInstruction pédagogique prioritaire : "
                    "L'élève signale que la conversation tourne en rond ou que la tâche a déjà été faite. "
                    "Ne répète pas la même question. "
                    "Reconnais brièvement que l'étape précédente est terminée, puis passe à l'étape suivante. "
                    "Si l'exercice est terminé, propose une conclusion courte ou un nouvel exercice. "
                    "Ne recommence pas le calcul déjà validé. "
                    "Réponds avec bienveillance, sans te défendre."
                )

            return (
                "\n\nPriority pedagogical instruction: "
                "The student indicates that the conversation is going in circles or that the task has already been done. "
                "Do not repeat the same question. "
                "Briefly acknowledge that the previous step is complete, then move to the next step. "
                "If the exercise is complete, offer a short conclusion or a new exercise. "
                "Do not restart a calculation that has already been validated. "
                "Respond kindly and do not be defensive."
            )

        if not objectif_initial:
            return ""

        mettre_a_jour_statut_naima("recentrage_pedagogique", True)

        if current_lang == "fr":
            return (
                "\n\nInstruction pédagogique prioritaire : "
                f"L'objectif principal de la conversation est : « {objectif_initial} ». "
                f"Le mode pédagogique actuel est : « {mode_pedagogique} ». "
                f"La leçon ou notion courante est : « {lecon_courante} ». "
                f"La dernière question posée par Naima était : « {derniere_question_ia} ». "
                f"La réponse actuelle de l'élève est : « {question_actuelle} ». "

                "Avant de poser une nouvelle question, tu dois d'abord analyser la réponse actuelle de l'élève. "
                "Si la réponse de l'élève répond correctement à ta dernière question, reconnais-le clairement, puis passe à l'étape suivante. "
                "Si la réponse est partiellement correcte, dis ce qui est correct, puis demande uniquement la petite correction nécessaire. "
                "Si la réponse est incorrecte, explique brièvement l'erreur et donne un indice. "
                "Ne répète jamais exactement la même question si l'élève vient d'y répondre correctement. "

                "Tu dois garder l'objectif initial comme fil conducteur. "
                "Si le mode est « resolution », accompagne l'élève vers la résolution de l'exercice initial. "
                "Tu peux poser des questions intermédiaires, mais elles doivent aider directement à résoudre l'exercice. "
                "Ne remplace pas l'exercice initial par un autre, sauf si l'élève le demande clairement. "

                "Si le mode est « explication_lecon », commence par expliquer la notion clairement avec des mots simples, "
                "puis propose une petite question ou un court exercice pour vérifier la compréhension. "
                "Après chaque réponse de l'élève, relie ton feedback à la leçon courante. "

                "Si le mode est « entrainement », propose un exercice adapté au niveau de l'élève, "
                "puis accompagne-le étape par étape jusqu'à la correction. "

                "Si l'élève dit qu'il ne comprend pas, ne change pas de sujet. "
                "Reformule plus simplement, donne un indice, puis reviens à l'objectif principal. "

                "Tout détour doit être court, utile et suivi d'un retour explicite à l'objectif initial. "
                "Ne pose pas une longue série de questions générales sans lien direct avec l'objectif. "
                "À chaque réponse, demande-toi : est-ce que cela aide l'élève à comprendre ou résoudre l'objectif principal ? "
                "Si non, recentre-toi."
            )

        return (
            "\n\nPriority pedagogical instruction: "
            f"The main goal of the conversation is: « {objectif_initial} ». "
            f"The current pedagogical mode is: « {mode_pedagogique} ». "
            f"The current lesson or concept is: « {lecon_courante} ». "
            f"Naima's last question was: « {derniere_question_ia} ». "
            f"The student's current answer is: « {question_actuelle} ». "

            "Before asking a new question, first analyze the student's current answer. "
            "If the student's answer correctly answers your previous question, clearly acknowledge it, then move to the next step. "
            "If the answer is partially correct, say what is correct, then ask only for the small correction needed. "
            "If the answer is incorrect, briefly explain the mistake and give a hint. "
            "Never repeat exactly the same question if the student has just answered it correctly. "

            "Keep the initial goal as the main thread. "
            "If the mode is « resolution », guide the student toward solving the initial exercise. "
            "Any intermediate question must directly help solve the exercise. "
            "Do not replace the initial exercise with another one unless the student clearly asks for it. "

            "If the mode is « explication_lecon », first explain the concept clearly with simple words, "
            "then propose a short question or exercise to check understanding. "
            "After each student answer, connect your feedback to the current lesson. "

            "If the mode is « entrainement », propose a suitable exercise and guide the student step by step. "

            "If the student says they do not understand, do not change topic. "
            "Rephrase more simply, give a hint, then return to the main goal. "

            "Any detour must be short, useful, and followed by an explicit return to the initial goal. "
            "Do not ask a long sequence of general questions unrelated to the goal. "
            "Before each answer, ask yourself whether it helps the student understand or solve the main goal. "
            "If not, refocus."
        )

    # ============================================================
    # POST : MESSAGE DE L'ÉLÈVE
    # ============================================================

    if request.method == 'POST':
        question = request.form.get("question", "").strip()
        matiere_form = request.form.get("matiere", "")
        difficulte_form = request.form.get("difficulte", "moyen")

        if matiere_form:
            matiere = matiere_form
            session["matiere"] = matiere

        if question and len(question) >= 3:
            eleve_label = "👤 Élève:" if current_lang == "fr" else "👤 Student:"
            conversation.append(f"{eleve_label} {question}")

            # Permet de distinguer la demande initiale d'une vraie réponse
            # à une question de Naima. Le premier message ne doit pas être
            # interprété comme une performance faible simplement parce que
            # l'élève demande de l'aide.
            premier_message_naima = not bool(
                session.get("objectif_initial_naima")
            )

            # ------------------------------------------------------------
            # MÉMOIRE DE L'OBJECTIF PÉDAGOGIQUE
            # ------------------------------------------------------------

            exercice_en_cours = session.get("exercice_en_cours") or {}
            enonce_exercice_genere = (
                exercice_en_cours.get("enonce") or ""
            ).strip()

            if enonce_exercice_genere:
                session["objectif_initial_naima"] = (
                    enonce_exercice_genere
                )

                if not session.get("mode_pedagogique_naima"):
                    session["mode_pedagogique_naima"] = (
                        "resolution"
                        if matiere.lower().startswith("math")
                        else "entrainement"
                    )

                session["sujet_courant_naima"] = matiere
                session["lecon_courante_naima"] = (
                    enonce_exercice_genere
                )
                session.modified = True

                premier_message_naima = False

                print(
                    "🎯 Objectif Naima issu de l'exercice généré:",
                    session["objectif_initial_naima"]
                )
                print(
                    "🧭 Mode pédagogique Naima:",
                    session["mode_pedagogique_naima"]
                )

            elif premier_message_naima:
                mode_detecte = detecter_mode_pedagogique(question)

                session["objectif_initial_naima"] = question
                session["mode_pedagogique_naima"] = mode_detecte
                session["sujet_courant_naima"] = matiere
                session["lecon_courante_naima"] = matiere
                session.modified = True

                print(
                    "🎯 Objectif initial Naima:",
                    session["objectif_initial_naima"]
                )
                print(
                    "🧭 Mode pédagogique Naima:",
                    session["mode_pedagogique_naima"]
                )

            # ------------------------------------------------------------
            # VÉRIFICATION : EXERCICE DÉJÀ TERMINÉ
            # ------------------------------------------------------------

            if session.get('exercice_termine'):
                msg_fin = (
                    "🎉 L'exercice est terminé ! Clique sur 'Nouvel exercice' pour continuer."
                    if current_lang == "fr"
                    else "🎉 The exercise is finished! Click 'New exercise' to continue."
                )

                conversation.append(f"🤖 Naima: {msg_fin}")
                session["conversation"] = conversation
                session.modified = True

                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({
                        'success': True,
                        'termine': True
                    })

                return redirect(url_for("enseignant_virtuel"))

            # ------------------------------------------------------------
            # DIAGNOSTIC BAYÉSIEN
            # ------------------------------------------------------------

            diagnostic_bayesien = None

            try:
                derniere_q_ia = session.get('derniere_q_ia')

                if premier_message_naima:
                    # Le premier message définit l'objectif. Il ne constitue
                    # pas encore une tentative permettant d'inférer une
                    # difficulté ou des erreurs.
                    diagnostic_bayesien = {
                        "probabilite_difficulte": 0.10,
                        "pourcentage_difficulte": 10.0,
                        "niveau_risque": "faible",
                        "evaluation_performance": False,
                        "raison": "premier_message_objectif"
                    }

                    session["diagnostic_bayesien"] = diagnostic_bayesien
                    session["signaux_bayesiens"] = {
                        "maitrise_cours": None,
                        "erreurs": None,
                        "temps_reponse": None,
                        "difficulte_demandee": difficulte_form,
                        "evaluation_performance": False,
                        "premier_message_objectif": True
                    }

                    print(
                        "🧠 Premier message : objectif enregistré, "
                        "performance non évaluée."
                    )
                    print(
                        "📊 Diagnostic initial neutre :",
                        diagnostic_bayesien
                    )

                else:
                    maitrise_cours, erreurs, temps_reponse = (
                        estimer_signaux_pedagogiques(
                            question_eleve=question,
                            derniere_question_ia=derniere_q_ia
                        )
                    )

                    diagnostic_bayesien = diagnostiquer_difficulte(
                        maitrise_cours=maitrise_cours,
                        erreurs=erreurs,
                        temps_reponse=temps_reponse
                    )

                    session["diagnostic_bayesien"] = diagnostic_bayesien
                    session["signaux_bayesiens"] = {
                        "maitrise_cours": maitrise_cours,
                        "erreurs": erreurs,
                        "temps_reponse": temps_reponse,
                        "difficulte_demandee": difficulte_form,
                        "evaluation_performance": True
                    }

                    mettre_a_jour_statut_naima(
                        "diagnostic_bayesien",
                        True
                    )

                    print(
                        "🧠 Diagnostic bayésien:",
                        diagnostic_bayesien
                    )
                    print(
                        "📊 Signaux bayésiens:",
                        session["signaux_bayesiens"]
                    )

            except Exception as e:
                print(f"⚠️ Erreur diagnostic bayésien: {e}")
                diagnostic_bayesien = None

            # ------------------------------------------------------------
            # UTILISATION RÉELLE DE L'IA
            # ------------------------------------------------------------

            try:
                print(f"🤖 Appel à OpenAI pour la matière: {matiere}")

                derniere_q_ia = session.get('derniere_q_ia')

                # --------------------------------------------------------
                # VÉRIFICATION MATHÉMATIQUE LOCALE SÉCURISÉE
                # --------------------------------------------------------

                instruction_calcul = ""
                objectif_atteint = False

                objectif_effectif, source_objectif = (
                    obtenir_objectif_effectif_naima()
                )

                question_contient_variable = (
                    contient_variable_mathematique(question)
                )
                objectif_contient_variable = (
                    contient_variable_mathematique(
                        objectif_effectif
                    )
                )

                # --------------------------------------------------------
                # PRIORITÉ 1 : SOLUTION D'ÉQUATION AVEC VARIABLE
                # --------------------------------------------------------

                verification_equation = {
                    "verification_contextuelle": False
                }

                if objectif_contient_variable:
                    verification_equation = (
                        verifier_solution_equation_fractionnaire(
                            equation_initiale=objectif_effectif,
                            reponse_eleve=question
                        )
                    )

                if verification_equation.get(
                    "verification_contextuelle"
                ):
                    instruction_calcul = (
                        "\n\nInstruction mathématique prioritaire : "
                        + verification_equation.get(
                            "message_interne",
                            ""
                        )
                    )

                    session["verification_calcul"] = {
                        "calcul_verifie": True,
                        "verification_equation": True,
                        "verification_chaine": False,
                        "verification_contextuelle": True,
                        "est_correct": verification_equation.get(
                            "est_correct"
                        ),
                        "equation": verification_equation.get(
                            "equation"
                        ),
                        "valeur_x_proposee": (
                            verification_equation.get(
                                "valeur_x_proposee"
                            )
                        ),
                        "valeur_x_calculee": (
                            verification_equation.get(
                                "valeur_x_calculee"
                            )
                        ),
                        "valeur_gauche": verification_equation.get(
                            "valeur_gauche"
                        ),
                        "valeur_droite": verification_equation.get(
                            "valeur_droite"
                        )
                    }

                    mettre_a_jour_statut_naima(
                        "verification_math_locale",
                        True
                    )

                    print(
                        "🧮 Vérification solution d'équation :",
                        session["verification_calcul"]
                    )

                    if (
                        verification_equation.get("est_correct") is True
                        and session.get(
                            "mode_pedagogique_naima"
                        ) == "resolution"
                    ):
                        objectif_atteint = True
                        session["objectif_atteint_naima"] = True
                        session["conversation_terminee"] = True
                        session["exercice_termine"] = True
                        session.pop("derniere_q_ia", None)
                        session.modified = True

                        print(
                            "🏁 Objectif Naima atteint : "
                            "solution d'équation prouvée correcte."
                        )

                # --------------------------------------------------------
                # PRIORITÉ 2 : CHAÎNE D'ÉGALITÉS NUMÉRIQUES
                # --------------------------------------------------------
                #
                # Exemple :
                # "on a 1/2+1/3=3/6+2/6=5/6"
                #
                # Cette vérification est déterministe et doit passer avant
                # l'interprétation du LLM.
                # --------------------------------------------------------

                verification_chaine = {
                    "verification_chaine": False
                }

                if (
                    not verification_equation.get(
                        "verification_contextuelle"
                    )
                    and not question_contient_variable
                ):
                    verification_chaine = (
                        verifier_chaine_egalites_fractionnaire(
                            texte=question,
                            objectif_initial=objectif_effectif
                        )
                    )

                if verification_chaine.get("verification_chaine"):

                    instruction_calcul = (
                        "\n\nInstruction mathématique prioritaire : "
                        + verification_chaine.get(
                            "message_interne",
                            ""
                        )
                    )

                    session["verification_calcul"] = {
                        "calcul_verifie": True,
                        "verification_chaine": True,
                        "verification_contextuelle": False,
                        "est_correct": verification_chaine.get(
                            "est_correct"
                        ),
                        "chaine": verification_chaine.get(
                            "chaine"
                        ),
                        "membres": verification_chaine.get(
                            "membres"
                        ),
                        "valeurs": verification_chaine.get(
                            "valeurs"
                        ),
                        "valeur_commune": verification_chaine.get(
                            "valeur_commune"
                        ),
                        "resultat_final_explicite": verification_chaine.get(
                            "resultat_final_explicite"
                        ),
                        "resultat_final": verification_chaine.get(
                            "resultat_final"
                        ),
                        "correspond_objectif": verification_chaine.get(
                            "correspond_objectif"
                        ),
                        "expression_objectif": verification_chaine.get(
                            "expression_objectif"
                        ),
                        "valeur_objectif": verification_chaine.get(
                            "valeur_objectif"
                        )
                    }

                    mettre_a_jour_statut_naima(
                        "verification_math_locale",
                        True
                    )

                    print(
                        "🧮 Vérification chaîne d'égalités :",
                        session["verification_calcul"]
                    )

                    if (
                        verification_chaine.get("est_correct") is True
                        and verification_chaine.get(
                            "correspond_objectif"
                        ) is True
                        and verification_chaine.get(
                            "resultat_final_explicite"
                        ) is True
                        and session.get(
                            "mode_pedagogique_naima"
                        ) == "resolution"
                    ):
                        objectif_atteint = True

                        session["objectif_atteint_naima"] = True
                        session["conversation_terminee"] = True
                        session["exercice_termine"] = True
                        session.pop("derniere_q_ia", None)
                        session.modified = True

                        print(
                            "🏁 Objectif Naima atteint : "
                            "chaîne d'égalités finale prouvée correcte."
                        )

                # --------------------------------------------------------
                # PRIORITÉ 2 : RÉPONSE FINALE VÉRIFIABLE PAR RAPPORT
                # À L'OBJECTIF INITIAL
                # --------------------------------------------------------

                verification_contextuelle = {
                    "verification_contextuelle": False
                }

                if (
                    not verification_equation.get(
                        "verification_contextuelle"
                    )
                    and not verification_chaine.get(
                        "verification_chaine"
                    )
                    and not objectif_contient_variable
                ):
                    verification_contextuelle = (
                        verifier_resultat_expression_contextuelle(
                            objectif_initial=objectif_effectif,
                            reponse_eleve=question
                        )
                    )

                if (
                    not verification_chaine.get("verification_chaine")
                    and verification_contextuelle.get(
                        "verification_contextuelle"
                    )
                ):

                    instruction_calcul = (
                        "\n\nInstruction mathématique prioritaire : "
                        + verification_contextuelle.get(
                            "message_interne",
                            ""
                        )
                    )

                    session["verification_calcul"] = {
                        "calcul_verifie": True,
                        "verification_contextuelle": True,
                        "est_correct": verification_contextuelle.get(
                            "est_correct"
                        ),
                        "expression_initiale": verification_contextuelle.get(
                            "expression_initiale"
                        ),
                        "valeur_attendue": verification_contextuelle.get(
                            "valeur_attendue"
                        ),
                        "valeur_proposee": verification_contextuelle.get(
                            "valeur_proposee"
                        )
                    }

                    mettre_a_jour_statut_naima(
                        "verification_math_locale",
                        True
                    )

                    print(
                        "🧮 Vérification contextuelle :",
                        session["verification_calcul"]
                    )

                    if (
                        verification_contextuelle.get("est_correct") is True
                        and session.get("mode_pedagogique_naima") == "resolution"
                    ):
                        objectif_atteint = True

                        session["objectif_atteint_naima"] = True
                        session["conversation_terminee"] = True
                        session["exercice_termine"] = True
                        session.pop("derniere_q_ia", None)
                        session.modified = True

                        print(
                            "🏁 Objectif Naima atteint : "
                            "réponse finale prouvée correcte."
                        )

                # --------------------------------------------------------
                # PRIORITÉ 3 : ÉGALITÉ NUMÉRIQUE EXPLICITE
                # --------------------------------------------------------

                elif (
                    not verification_equation.get(
                        "verification_contextuelle"
                    )
                    and not verification_chaine.get(
                        "verification_chaine"
                    )
                    and not question_contient_variable
                    and peut_verifier_calcul_localement(question)
                ):
                    verification_calcul = verifier_expression_fractionnaire(question)

                    if verification_calcul.get("calcul_verifie"):
                        instruction_calcul = (
                            "\n\nInstruction mathématique prioritaire : "
                            + verification_calcul.get("message_interne", "")
                        )

                        session["verification_calcul"] = {
                            "calcul_verifie": verification_calcul.get("calcul_verifie"),
                            "verification_contextuelle": False,
                            "est_correct": verification_calcul.get("est_correct"),
                            "valeur_gauche": verification_calcul.get("valeur_gauche"),
                            "valeur_droite": verification_calcul.get("valeur_droite"),
                        }

                        mettre_a_jour_statut_naima("verification_math_locale", True)

                        print("🧮 Vérification calcul:", session["verification_calcul"])

                    else:
                        session.pop("verification_calcul", None)

                else:
                    session.pop("verification_calcul", None)
                    print(
                        "🧮 Vérification calcul ignorée : "
                        "aucune preuve mathématique locale suffisamment sûre."
                    )

                # --------------------------------------------------------
                # PRIORITÉ À UNE PREUVE MATHÉMATIQUE LOCALE POSITIVE
                # --------------------------------------------------------
                #
                # Les signaux linguistiques sont des indices pédagogiques,
                # pas une preuve que la réponse de l'élève est fausse.
                #
                # Si le calcul a été vérifié localement et démontré correct,
                # cette preuve prend priorité sur une estimation heuristique
                # de difficulté issue des mots employés par l'élève.
                #
                # IMPORTANT :
                # - si le calcul n'a pas été vérifié, aucun signal n'est forcé ;
                # - si le calcul est vérifié incorrect, le diagnostic existant
                #   est conservé ;
                # - seule une preuve locale POSITIVE peut neutraliser un
                #   faux signal négatif de ce tour.
                # --------------------------------------------------------

                verification_session = session.get("verification_calcul") or {}

                if (
                    verification_session.get("calcul_verifie") is True
                    and verification_session.get("est_correct") is True
                ):
                    maitrise_cours = "bonne"
                    erreurs = "peu"
                    temps_reponse = "rapide"

                    diagnostic_bayesien = diagnostiquer_difficulte(
                        maitrise_cours=maitrise_cours,
                        erreurs=erreurs,
                        temps_reponse=temps_reponse
                    )

                    session["diagnostic_bayesien"] = diagnostic_bayesien
                    session["signaux_bayesiens"] = {
                        "maitrise_cours": maitrise_cours,
                        "erreurs": erreurs,
                        "temps_reponse": temps_reponse,
                        "difficulte_demandee": difficulte_form,
                        "preuve_math_locale_prioritaire": True
                    }

                    mettre_a_jour_statut_naima(
                        "verification_math_locale",
                        True
                    )

                    print(
                        "✅ Preuve mathématique locale prioritaire : "
                        "le calcul est correct."
                    )
                    print(
                        "🧠 Diagnostic recalculé après preuve locale :",
                        diagnostic_bayesien
                    )

                # --------------------------------------------------------
                # CONSTRUCTION DU DIAGNOSTIC INJECTÉ APRÈS ARBITRAGE
                # --------------------------------------------------------

                instruction_bayesienne = ""

                if diagnostic_bayesien and not premier_message_naima:
                    instruction_bayesienne = construire_instruction_bayesienne(
                        diagnostic_bayesien
                    )

                instruction_recentrage = construire_instruction_recentrage(
                    question
                )
                instruction_exercice_genere = (
                    construire_contexte_exercice_genere()
                )

                instruction_interne_complete = (
                    contexte_apprentissage_eleve
                    + instruction_exercice_genere
                    + instruction_recentrage
                    + instruction_bayesienne
                    + instruction_calcul
                )

                # --------------------------------------------------------
                # APPEL IA
                # --------------------------------------------------------

                if objectif_atteint:
                    valeur_finale = (
                        verification_equation.get(
                            "valeur_x_calculee"
                        )
                        or verification_chaine.get(
                            "resultat_final"
                        )
                        or verification_chaine.get(
                            "valeur_objectif"
                        )
                        or verification_contextuelle.get(
                            "valeur_proposee"
                        )
                        or verification_contextuelle.get(
                            "valeur_attendue"
                        )
                        or ""
                    )

                    if verification_equation.get(
                        "verification_contextuelle"
                    ):
                        resultat_affiche = f"x = {valeur_finale}"
                    else:
                        resultat_affiche = valeur_finale

                    if current_lang == "fr":
                        reponse_ia = (
                            f"🎉 Bravo ! Ton résultat {resultat_affiche} "
                            "est correct. "
                            "Tu as atteint l'objectif de cet exercice. "
                            "L'exercice est terminé. "
                            "Tu peux cliquer sur « Nouvel exercice » "
                            "si tu veux continuer."
                        )
                    else:
                        reponse_ia = (
                            f"🎉 Well done! Your result {resultat_affiche} "
                            "is correct. "
                            "You have reached the goal of this exercise. "
                            "The exercise is finished. "
                            "You can click “New exercise” if you want to continue."
                        )

                    session.pop("derniere_q_ia", None)

                    print(
                        "🏁 Réponse finale déterministe envoyée : "
                        "aucune nouvelle question socratique."
                    )

                elif derniere_q_ia:
                    reponse_ia = generer_suite_conversation(
                        derniere_q=derniere_q_ia,
                        reponse=question + instruction_interne_complete,
                        historique=conversation,
                        niveau=niveau_eleve,
                        langue=current_lang,
                        mode_examen=session.get("mode_examen", False),
                        exercice_context="",
                        matiere=matiere
                    )

                    session.pop('derniere_q_ia', None)

                else:
                    reponse_ia = generer_debut_conversation(
                        question=question + instruction_interne_complete,
                        niveau=niveau_eleve,
                        langue=current_lang,
                        mode_examen=session.get("mode_examen", False),
                        matiere=matiere
                    )

                if not reponse_ia or len(reponse_ia.strip()) < 10:
                    reponse_ia = (
                        "Je réfléchis... Peux-tu reformuler ta question ?"
                        if current_lang == "fr"
                        else "I'm thinking... Can you rephrase?"
                    )

                conversation.append(f"🤖 Naima: {reponse_ia}")

                # --------------------------------------------------------
                # ANALYSE PÉDAGOGIQUE + ENREGISTREMENT ADMIN
                # --------------------------------------------------------

                try:
                    from services.analyse_pedagogique_service import (
                        analyser_tentative_pedagogique
                    )
                    from services.diagnostic_history_service import (
                        enregistrer_diagnostic_bayesien
                    )

                    analyse_pedagogique = analyser_tentative_pedagogique(
                        objectif_initial=session.get("objectif_initial_naima"),
                        derniere_question_ia=derniere_q_ia,
                        reponse_eleve=question,
                        reponse_naima=reponse_ia,
                        matiere=matiere,
                        niveau=niveau_eleve,
                        diagnostic_bayesien=diagnostic_bayesien,
                        signaux_bayesiens=session.get("signaux_bayesiens"),
                        verification_calcul=session.get("verification_calcul")
                    )

                    mettre_a_jour_statut_naima("analyse_pedagogique", True)

                    if diagnostic_bayesien:
                        enregistrer_diagnostic_bayesien(
                            user_id=utilisateur.id,
                            diagnostic=diagnostic_bayesien,
                            signaux=session.get("signaux_bayesiens"),
                            matiere=matiere,
                            exercice_id=None,
                            lecon_id=None,
                            verification_calcul=session.get("verification_calcul"),
                            source="naima",
                            analyse_pedagogique=analyse_pedagogique,
                            meta_processus_naima={
                                "naima_connectee_aux_traces": session.get("naima_processus_connecte", {}).get("traces_apprentissage", False),
                                "contexte_personnalise_utilise": session.get("naima_processus_connecte", {}).get("contexte_injecte", False),
                                "diagnostic_bayesien_utilise": session.get("naima_processus_connecte", {}).get("diagnostic_bayesien", False),
                                "recentrage_pedagogique_utilise": session.get("naima_processus_connecte", {}).get("recentrage_pedagogique", False),
                                "analyse_pedagogique_effectuee": session.get("naima_processus_connecte", {}).get("analyse_pedagogique", False),
                                "verification_math_locale_utilisee": session.get("naima_processus_connecte", {}).get("verification_math_locale", False),
                                "source_accompagnement": "naima",
                                "objectif_initial_naima": session.get("objectif_initial_naima"),
                                "mode_pedagogique_naima": session.get("mode_pedagogique_naima"),
                                "lecon_courante_naima": session.get("lecon_courante_naima"),
                                "derniere_mise_a_jour": session.get("naima_processus_connecte", {}).get("derniere_mise_a_jour")
                            }
                        )

                        print("✅ Analyse pédagogique et diagnostic enregistrés.")

                        # --------------------------------------------------------
                        # TRACE D'APPRENTISSAGE NAIMA
                        # --------------------------------------------------------

                        try:
                            from models import TraceApprentissage, Matiere

                            processus_naima = session.get("naima_processus_connecte", {}) or {}

                            # --------------------------------------------------------
                            # RATTACHEMENT SIMPLE ET ROBUSTE POUR NAIMA
                            # --------------------------------------------------------

                            matiere_obj = None
                            notion_cible_naima = analyse_pedagogique.get("notion_cible") or matiere

                            try:
                                matiere_obj = (
                                    Matiere.query
                                    .filter(
                                        db.or_(
                                            Matiere.nom.ilike("%math%"),
                                            Matiere.nom.ilike("%mathématiques%"),
                                            Matiere.nom.ilike("%mathematiques%")
                                        )
                                    )
                                    .first()
                                )
                            except Exception as e:
                                print(f"⚠️ Matière Naima non trouvée : {e}")
                                matiere_obj = None

                            trace_naima = TraceApprentissage(
                                user_id=utilisateur.id,

                                niveau_id=getattr(utilisateur, "niveau_id", None),
                                matiere_id=matiere_obj.id if matiere_obj else None,
                                unite_id=None,
                                lecon_id=None,
                                exercice_id=None,

                                type_action="conversation_naima",
                                source="naima",

                                reponse_eleve=question,
                                analyse_ia=reponse_ia,

                                score=None,
                                niveau_risque=diagnostic_bayesien.get("niveau_risque") if diagnostic_bayesien else None,
                                difficulte_estimee=diagnostic_bayesien.get("niveau_risque") if diagnostic_bayesien else None,

                                notion_cible=notion_cible_naima,
                                type_erreur=(
                                    analyse_pedagogique.get("erreurs_probables")[0]
                                    if isinstance(analyse_pedagogique.get("erreurs_probables"), list)
                                    and analyse_pedagogique.get("erreurs_probables")
                                    else None
                                ),

                                meta_json={
                                    "source": "naima",
                                    "type_interaction": "conversation_pedagogique",

                                    # Contexte lisible
                                    "matiere_fr": matiere_obj.nom if matiere_obj else matiere,
                                    "unite_fr": None,
                                    "lecon_fr": "Conversation avec Naima",

                                    # Objectif réel de la conversation
                                    "objectif_initial_naima": session.get("objectif_initial_naima"),
                                    "mode_pedagogique_naima": session.get("mode_pedagogique_naima"),
                                    "lecon_courante_naima": session.get("lecon_courante_naima"),

                                    # Données pédagogiques
                                    "diagnostic_bayesien": diagnostic_bayesien,
                                    "signaux_bayesiens": session.get("signaux_bayesiens"),
                                    "verification_calcul": session.get("verification_calcul"),
                                    "analyse_pedagogique": analyse_pedagogique,

                                    # Preuve du processus Naima
                                    "processus_naima": {
                                        "naima_connectee_aux_traces": processus_naima.get("traces_apprentissage", False),
                                        "contexte_personnalise_utilise": processus_naima.get("contexte_injecte", False),
                                        "diagnostic_bayesien_utilise": processus_naima.get("diagnostic_bayesien", False),
                                        "recentrage_pedagogique_utilise": processus_naima.get("recentrage_pedagogique", False),
                                        "analyse_pedagogique_effectuee": processus_naima.get("analyse_pedagogique", False),
                                        "verification_math_locale_utilisee": processus_naima.get("verification_math_locale", False),
                                        "profil_personnalise": processus_naima.get("profil_personnalise", False),
                                        "derniere_mise_a_jour": processus_naima.get("derniere_mise_a_jour")
                                    }
                                }
                            )

                            db.session.add(trace_naima)
                            db.session.commit()

                            print("✅ Trace d'apprentissage Naima créée.")
                            print(
                                f"🧠 Trace Naima : élève={utilisateur.id}, "
                                f"risque={trace_naima.niveau_risque}, "
                                f"notion={trace_naima.notion_cible}"
                            )

                        except Exception as e:
                            print(f"⚠️ Trace d'apprentissage Naima non créée : {e}")
                            db.session.rollback()

                except Exception as e:
                    print(f"⚠️ Analyse pédagogique non enregistrée: {e}")
                    db.session.rollback()

                # --------------------------------------------------------
                # EXTRACTION DE LA NOUVELLE QUESTION DE NAIMA
                # --------------------------------------------------------

                if objectif_atteint:
                    session.pop("derniere_q_ia", None)
                else:
                    nouvelle_q = extraire_question(
                        reponse_ia,
                        current_lang
                    )

                    if nouvelle_q and len(nouvelle_q) > 5:
                        session['derniere_q_ia'] = nouvelle_q

                if len(conversation) > 30:
                    conversation = conversation[-30:]

                session["conversation"] = conversation
                session.modified = True

                print("✅ Réponse IA générée avec succès")
                print("🔎 Statut Naima processus :", session.get("naima_processus_connecte"))

            except Exception as e:
                print(f"❌ Erreur appel OpenAI: {e}")
                import traceback
                traceback.print_exc()

                msg_erreur = (
                    "⚠️ Je n'arrive pas à contacter mon IA en ce moment. "
                    "Vérifie ta connexion internet ou réessaie plus tard."
                    if current_lang == "fr"
                    else
                    "⚠️ I can't reach my AI right now. "
                    "Check your internet connection or try again later."
                )

                conversation.append(f"🤖 Naima: {msg_erreur}")
                session["conversation"] = conversation
                session.modified = True

        # ========================================================
        # RÉPONSE AJAX
        # ========================================================

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            messages_html = format_messages(
                conversation,
                datetime.now().strftime("%H:%M")
            )

            return jsonify({
                'success': True,
                'messages': messages_html,
                'last_message': messages_html[-1] if messages_html else '',
                'matiere': matiere,
                'termine': session.get('exercice_termine', False),
                'diagnostic_bayesien': session.get("diagnostic_bayesien"),
                'signaux_bayesiens': session.get("signaux_bayesiens"),
                'verification_calcul': session.get("verification_calcul"),
                'objectif_initial_naima': session.get("objectif_initial_naima"),
                'mode_pedagogique_naima': session.get("mode_pedagogique_naima"),
                'lecon_courante_naima': session.get("lecon_courante_naima"),
                'exercice_en_cours': session.get("exercice_en_cours"),
                'naima_processus_connecte': session.get("naima_processus_connecte")
            })

        return redirect(url_for("enseignant_virtuel"))

    # ============================================================
    # GET : AFFICHAGE
    # ============================================================

    return render_template(
        "enseignant_virtuel.html",
        lang=current_lang,
        eleve=eleve,
        stats={},
        conversation=conversation,
        exercice_remediation=None,
        access_count=0,
        date_du_jour=datetime.utcnow(),
        matiere=matiere,
        theme="général",
        datetime=datetime,
        diagnostic_bayesien=session.get("diagnostic_bayesien"),
        signaux_bayesiens=session.get("signaux_bayesiens"),
        verification_calcul=session.get("verification_calcul"),
        objectif_initial_naima=session.get("objectif_initial_naima"),
        mode_pedagogique_naima=session.get("mode_pedagogique_naima"),
        lecon_courante_naima=session.get("lecon_courante_naima"),
        naima_processus_connecte=session.get("naima_processus_connecte")
    )


@app.route("/debug/naima-processus")
def debug_naima_processus():
    if "user_id" not in session:
        return jsonify({
            "connecte": False,
            "message": "Aucun utilisateur connecté"
        })

    # Sécurité : debug seulement en local ou en mode debug
    if not app.debug:
        return jsonify({
            "error": "Route de debug désactivée en production"
        }), 403

    return jsonify({
        "connecte": True,
        "user_id": session.get("user_id"),
        "role": session.get("role"),
        "naima_processus_connecte": session.get("naima_processus_connecte"),
        "diagnostic_bayesien": session.get("diagnostic_bayesien"),
        "signaux_bayesiens": session.get("signaux_bayesiens"),
        "verification_calcul": session.get("verification_calcul"),
        "objectif_initial_naima": session.get("objectif_initial_naima"),
        "mode_pedagogique_naima": session.get("mode_pedagogique_naima"),
        "lecon_courante_naima": session.get("lecon_courante_naima")
    })

@app.route("/demander-exercice", methods=["POST"])
def demander_exercice():
    """Génère un exercice avec l'IA"""
    if "user_id" not in session:
        return jsonify({"error": "Non authentifié"}), 401
    
    data = request.get_json()
    matiere = data.get("matiere", "mathématiques")
    difficulte = data.get("difficulte", "moyen")
    lang = session.get("lang", "fr")
    
    utilisateur = User.query.get(session["user_id"])
    
    try:
        # Appel à l'IA
        exercice = generer_exercice(
            matiere=matiere,
            niveau=utilisateur.niveau.nom if utilisateur.niveau else "6ème",
            difficulte=difficulte,
            langue=lang
        )
        
        session["exercice_actuel"] = {
            "enonce": exercice["enonce"],
            "correction": exercice["correction"],
            "indices": exercice["indices"],
            "etape": 1,
            "total_etapes": exercice["total_etapes"]
        }
        session["mode_exercice"] = True
        
        return jsonify({
            "success": True,
            "enonce": exercice["enonce"],
            "indice_initial": exercice["indices"][0] if exercice["indices"] else None
        })
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/verifier-reponse-exercice", methods=["POST"])
def verifier_reponse_exercice():
    """Vérifie la réponse de l'élève - VERSION CORRIGÉE"""
    if "user_id" not in session:
        return jsonify({"error": "Non authentifié"}), 401
    
    try:
        data = request.get_json()
        reponse_eleve = data.get("reponse", "").strip()
        
        exercice_actuel = session.get("exercice_actuel")
        if not exercice_actuel:
            return jsonify({"error": "Aucun exercice en cours"}), 400
        
        lang = session.get("lang", "fr")
        
        # Analyser la réponse
        analyse = analyser_reponse(
            enonce=exercice_actuel["enonce"],
            reponse_eleve=reponse_eleve,
            correction=exercice_actuel["correction"],
            etape=exercice_actuel.get("etape", 1),
            langue=lang
        )
        
        resultat = {
            "correct": analyse.get("correct", False),
            "feedback": analyse.get("feedback", "Analyse en cours..."),
            "indice_suivant": None
        }
        
        if analyse.get("correct", False):
            # Réponse correcte, passer à l'étape suivante
            exercice_actuel["etape"] += 1
            session["exercice_actuel"] = exercice_actuel
            
            # Vérifier si l'exercice est terminé
            if exercice_actuel["etape"] > exercice_actuel["total_etapes"]:
                # Exercice terminé !
                session.pop("exercice_actuel", None)
                session.pop("mode_exercice", None)
                session.modified = True
                
                resultat["termine"] = True
                resultat["message"] = get_message("bravo_exercice_termine", lang)
            else:
                # Prochaine étape
                resultat["progression"] = f"{exercice_actuel['etape']-1}/{exercice_actuel['total_etapes']}"
        else:
            # Réponse incorrecte, donner un indice si disponible
            etape_actuelle = exercice_actuel.get("etape", 1)
            indices = exercice_actuel.get("indices", [])
            
            if etape_actuelle <= len(indices):
                resultat["indice_suivant"] = indices[etape_actuelle - 1]
            else:
                resultat["indice_suivant"] = get_message("plus_d_indices", lang)
            
            resultat["progression"] = f"{exercice_actuel['etape']-1}/{exercice_actuel['total_etapes']}"
        
        session.modified = True
        return jsonify(resultat)
        
    except Exception as e:
        print(f"❌ Erreur vérification réponse: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/indice-supplementaire", methods=["POST"])
def indice_supplementaire():
    """Donne un indice supplémentaire à l'élève"""
    exercice_actuel = session.get("exercice_actuel")
    if not exercice_actuel:
        return jsonify({"error": "Aucun exercice"}), 400
    
    etape = exercice_actuel.get("etape", 1)
    indices = exercice_actuel.get("indices", [])
    
    if etape <= len(indices):
        return jsonify({
            "indice": indices[etape - 1]
        })
    else:
        lang = session.get("lang", "fr")
        return jsonify({
            "indice": get_message("plus_d_indices", lang)
        })


def generer_exercice(matiere, niveau, difficulte="moyen", type_exercice="exercice", langue="fr"):
    """Génère un exercice personnalisé avec OpenAI - VERSION SIMPLIFIÉE QUI MARCHE"""
    from openai import OpenAI
    import os
    import json
    import random
    
    client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
    
    # Construction du prompt
    if langue == "fr":
        prompt = f"""Génère un exercice de {matiere} pour un élève de niveau {niveau} (difficulté: {difficulte}).

IMPORTANT: L'exercice doit être ORIGINAL et DIFFÉRENT à chaque fois.

Réponds avec cet objet JSON (sans texte avant/après):
{{
    "enonce": "l'énoncé de l'exercice",
    "correction": {{
        "reponse_finale": "la réponse correcte",
        "etapes": ["étape 1", "étape 2", "étape 3"]
    }},
    "indices": ["indice 1", "indice 2", "indice 3"]
}}"""
    else:
        prompt = f"""Generate a {matiere} exercise for a {niveau} level student (difficulty: {difficulte}).

IMPORTANT: The exercise must be ORIGINAL and DIFFERENT each time.

Answer with this JSON object (no text before/after):
{{
    "enonce": "the exercise statement",
    "correction": {{
        "reponse_finale": "the correct answer",
        "etapes": ["step 1", "step 2", "step 3"]
    }},
    "indices": ["hint 1", "hint 2", "hint 3"]
}}"""
    
    try:
        # Version SIMPLIFIÉE - sans response_format
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",  # Plus fiable que gpt-4
            messages=[
                {"role": "system", "content": "Tu es Naima, une enseignante virtuelle. Tu réponds UNIQUEMENT avec du JSON valide."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.9,  # Pour de la variété
            max_tokens=800
        )
        
        reponse_texte = response.choices[0].message.content
        print(f"✅ Réponse OpenAI reçue: {reponse_texte[:100]}...")
        
        # Extraire le JSON (au cas où il y a du texte autour)
        import re
        json_match = re.search(r'(\{.*\})', reponse_texte, re.DOTALL)
        if json_match:
            reponse_texte = json_match.group(1)
        
        exercice = json.loads(reponse_texte)
        exercice['total_etapes'] = len(exercice.get('correction', {}).get('etapes', [3]))
        
        return exercice
        
    except Exception as e:
        print(f"❌ Erreur API OpenAI: {e}")
        print(f"Réponse qui a causé l'erreur: {reponse_texte if 'reponse_texte' in locals() else 'Pas de réponse'}")
        
        # Fallback TEMPORAIRE avec un exercice simple
        # (mais tu sauras que c'est le fallback)
        return {
            "enonce": f"Exercice de {matiere} (généré en secours): Calcule 15 + 27",
            "correction": {
                "reponse_finale": "42",
                "etapes": ["Additionne 15 et 27"]
            },
            "indices": ["15 + 20 = 35, puis 35 + 7 = 42"],
            "total_etapes": 1
        }


def analyser_reponse(enonce, reponse_eleve, correction, etape=1, langue="fr"):
    """Wrapper vers naima_corriger_exercice"""
    result = naima_corriger_exercice(
        question=enonce,
        reponse_eleve=reponse_eleve,
        correction_attendue=correction.get("reponse_finale") if isinstance(correction, dict) else correction,
        langue=langue
    )
    
    # Convertir au format attendu par l'ancien code
    return {
        "correct": result.get("correct", False),
        "feedback": result.get("feedback", ""),
        "indice": result.get("analyse", "")[:200]  # Premier extrait comme indice
    }


@app.route("/terminer-conversation", methods=["POST"])
def terminer_conversation():
    """Termine proprement la conversation en cours"""
    if "user_id" not in session:
        return jsonify({"error": "Non authentifié"}), 401
    
    # Sauvegarder que l'élève a compris
    session["conversation_terminee"] = True
    
    # Nettoyer mais garder l'élève connecté
    session.pop("derniere_q_ia", None)
    session.modified = True
    
    return jsonify({"success": True})
    

@app.route("/chat", methods=["POST"])
def chat():
    from chatbot_utils import get_chatbot_response  # chemin selon ton organisation
    user_input = request.json.get("message", "")
    response = get_chatbot_response(user_input)
    return jsonify({"response": response})

def determiner_mode_exercice_genere(
    matiere,
    type_exercice,
    enonce=""
):
    matiere_norm = (matiere or "").lower().strip()
    type_norm = (type_exercice or "").lower().strip()
    enonce_norm = (enonce or "").lower()

    if matiere_norm.startswith("math"):
        return "resolution"

    if type_norm in {
        "probleme",
        "problème",
        "logique",
        "qcm"
    }:
        return "resolution"

    if any(
        mot in enonce_norm
        for mot in [
            "résous",
            "resous",
            "calcule",
            "calculate",
            "solve",
            "détermine",
            "determine",
            "="
        ]
    ):
        return "resolution"

    return "entrainement"


@app.route("/nouvel-exercice", methods=["POST"])
def nouvel_exercice():
    """Nouvel exercice avec Naima - prend en compte toutes les options"""
    from datetime import datetime
    import time
    import json
    
    print(f"[DEBUG] Nouvel exercice - Session keys: {list(session.keys())}")
    
    if "user_id" not in session:
        return redirect(url_for("login_eleve"))

    utilisateur = db.session.get(User, session["user_id"])
    if not utilisateur or utilisateur.role != "eleve":
        return redirect(url_for("login_eleve"))
    
    eleve = utilisateur
    lang = session.get('lang', 'fr')
    
    # Récupérer TOUTES les options
    matiere = request.form.get('matiere', 'mathématiques')
    difficulte = request.form.get('difficulte', 'moyen')
    type_exercice = request.form.get('type_exercice', 'exercice')
    mots_cles = request.form.get('mots_cles', '')
    
    print(f"[DEBUG] Options: {matiere}, {difficulte}, {type_exercice}, mots-clés: {mots_cles}")
    
    # ✅ Réinitialiser l'état de fin d'exercice
    session.pop('exercice_termine', None)
    
    # Vider la conversation existante
    session_keys_to_remove = [
        "conversation",
        "derniere_q_ia",
        "exercice_en_cours",
        "exercice_termine",
        "mode_examen",

        # État pédagogique Naima
        "objectif_initial_naima",
        "objectif_atteint_naima",
        "conversation_terminee",
        "mode_pedagogique_naima",
        "sujet_courant_naima",
        "lecon_courante_naima",

        # Diagnostic du dialogue précédent
        "diagnostic_bayesien",
        "signaux_bayesiens",
        "verification_calcul",
        "naima_processus_connecte"
    ]
    for key in session_keys_to_remove:
        if key in session:
            session.pop(key)
    
    try:
        # Récupérer le niveau de l'élève
        niveau_eleve = eleve.niveau.nom if eleve.niveau else ("6th grade" if lang == "en" else "6ème")
        
        # ✅ Utiliser la fonction qui prend en compte les options
        exercice = generer_exercice_specifique(
            matiere=matiere,
            niveau=niveau_eleve,
            difficulte=difficulte,
            type_exercice=type_exercice,
            mots_cles=mots_cles,
            langue=lang
        )
        
        # Formater le message de Naima
        enseignant_label = "🤖 Naima:" if lang == "en" else "🤖 Naima:"
        
        # Message d'accueil + énoncé + première question
        message_complet = f"{exercice['message_accueil']}\n\n📝 **{exercice['enonce']}**\n\n{exercice['premiere_question']}"
        
        session["conversation"] = [f"{enseignant_label} {message_complet}"]
        session['derniere_q_ia'] = exercice['premiere_question']
        
        # Stocker le contexte de l'exercice
        session['exercice_en_cours'] = {
            'enonce': exercice['enonce'],
            'indices': exercice.get('indices', []),
            'correction': exercice.get('correction', {}),
            'type': type_exercice,
            'matiere': matiere,
            'difficulte': difficulte,
            'etape': 1,
            'total_etapes': len(
                exercice.get(
                    'correction',
                    {}
                ).get(
                    'etapes',
                    [3]
                )
            )
        }

        # Le véritable objectif est l'énoncé généré.
        session["objectif_initial_naima"] = exercice["enonce"]
        session["mode_pedagogique_naima"] = (
            determiner_mode_exercice_genere(
                matiere=matiere,
                type_exercice=type_exercice,
                enonce=exercice["enonce"]
            )
        )
        session["sujet_courant_naima"] = matiere
        session["lecon_courante_naima"] = exercice["enonce"]

        session["objectif_atteint_naima"] = False
        session["conversation_terminee"] = False

        print(
            "[DEBUG] 🎯 Objectif Naima fixé depuis l'exercice :",
            session["objectif_initial_naima"]
        )
        print(
            "[DEBUG] 🧭 Mode Naima :",
            session["mode_pedagogique_naima"]
        )

        print(f"[DEBUG] ✅ Exercice {type_exercice} généré avec succès")
        
    except Exception as e:
        print(f"[DEBUG] ❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        
        # Fallback simple
        if lang == "fr":
            msg = f"🤖 Naima: Voici un {type_exercice} de {matiere} {mots_cles}. Quelle est ta question ?"
        else:
            msg = f"🤖 Naima: Here's a {type_exercice} in {matiere} {mots_cles}. What's your question?"
        session["conversation"] = [msg]
    
    session['user_id'] = eleve.id
    session['lang'] = lang
    session['matiere'] = matiere
    session.modified = True
    
    if lang == "fr":
        flash(f"✨ Exercice de {matiere} ({type_exercice}) généré !", "success")
    else:
        flash(f"✨ {matiere} {type_exercice} generated!", "success")
    
    redirect_url = url_for("enseignant_virtuel", matiere=matiere) + f"?t={int(time.time())}"
    return redirect(redirect_url)

def generer_exercice_specifique(matiere, niveau, difficulte="moyen", type_exercice="exercice", 
                                 mots_cles="", langue="fr"):
    """Wrapper vers naima_generer_exercice"""
    return naima_generer_exercice(
        matiere=matiere,
        niveau=niveau,
        difficulte=difficulte,
        type_exercice=type_exercice,
        mots_cles=mots_cles,
        langue=langue
    )

def generer_exercice_fallback(matiere, type_exercice, mots_cles, difficulte, langue):
    """Fallback avec des exercices pré-définis mais variés - VERSION BILINGUE"""
    import random
    
    # Base d'exercices par matière et type - VERSION BILINGUE
    exercices_db = {
        "mathématiques": {
            "exercice": [
                {
                    "message_accueil": "Voici un exercice sur les équations !" if langue == "fr" else "Here's an exercise on equations!",
                    "enonce": "Résous l'équation : 3x + 5 = 20" if langue == "fr" else "Solve the equation: 3x + 5 = 20",
                    "premiere_question": "Par quoi commencer pour isoler x ?" if langue == "fr" else "What should you do first to isolate x?",
                    "indices": ["Enlève d'abord le +5", "Divise par 3 ensuite"] if langue == "fr" else ["First remove +5", "Then divide by 3"],
                    "difficulte": difficulte
                },
                {
                    "message_accueil": "Un petit exercice de fractions !" if langue == "fr" else "A small exercise on fractions!",
                    "enonce": "Calcule : 2/3 + 1/4" if langue == "fr" else "Calculate: 2/3 + 1/4",
                    "premiere_question": "Quel est le dénominateur commun ?" if langue == "fr" else "What is the common denominator?",
                    "indices": ["12 est un multiple de 3 et 4", "2/3 = 8/12"] if langue == "fr" else ["12 is a multiple of 3 and 4", "2/3 = 8/12"],
                    "difficulte": difficulte
                },
                {
                    "message_accueil": "Exercice sur les puissances !" if langue == "fr" else "Exercise on exponents!",
                    "enonce": "Calcule : 2³ × 2²" if langue == "fr" else "Calculate: 2³ × 2²",
                    "premiere_question": "Que fais-tu avec les exposants quand on multiplie ?" if langue == "fr" else "What do you do with exponents when multiplying?",
                    "indices": ["On additionne les exposants", "2³ × 2² = 2⁵"] if langue == "fr" else ["Add the exponents", "2³ × 2² = 2⁵"],
                    "difficulte": difficulte
                }
            ],
            "probleme": [
                {
                    "message_accueil": "Voici un problème concret !" if langue == "fr" else "Here's a real-world problem!",
                    "enonce": "Un train parcourt 280 km à 70 km/h. Combien de temps dure le trajet ?" if langue == "fr" else "A train travels 280 km at 70 km/h. How long does the journey take?",
                    "premiere_question": "Quelle formule utiliser pour calculer le temps ?" if langue == "fr" else "What formula do you use to calculate time?",
                    "indices": ["Temps = Distance ÷ Vitesse", "280 ÷ 70 = ?"] if langue == "fr" else ["Time = Distance ÷ Speed", "280 ÷ 70 = ?"],
                    "difficulte": difficulte
                },
                {
                    "message_accueil": "Problème de pourcentages !" if langue == "fr" else "Percentage problem!",
                    "enonce": "Un article coûte 80€. Il augmente de 15%. Quel est son nouveau prix ?" if langue == "fr" else "An item costs $80. It increases by 15%. What is its new price?",
                    "premiere_question": "Comment calcules-tu le montant de l'augmentation ?" if langue == "fr" else "How do you calculate the increase amount?",
                    "indices": ["15% de 80 = 0,15 × 80", "80 + 12 = 92"] if langue == "fr" else ["15% of 80 = 0.15 × 80", "80 + 12 = 92"],
                    "difficulte": difficulte
                }
            ],
            "qcm": [
                {
                    "message_accueil": "Voici un QCM !" if langue == "fr" else "Here's a multiple choice question!",
                    "enonce": "Quelle est la solution de l'équation 2x - 6 = 10 ?\nA) x = 8\nB) x = 6\nC) x = 10\nD) x = 12" if langue == "fr" else "What is the solution to the equation 2x - 6 = 10?\nA) x = 8\nB) x = 6\nC) x = 10\nD) x = 12",
                    "premiere_question": "Quelle option choisis-tu ?" if langue == "fr" else "Which option do you choose?",
                    "indices": ["Isole x", "2x = 16", "x = 8"] if langue == "fr" else ["Isolate x", "2x = 16", "x = 8"],
                    "difficulte": difficulte
                }
            ],
            "logique": [
                {
                    "message_accueil": "Un exercice de logique !" if langue == "fr" else "A logic exercise!",
                    "enonce": "Si 3 chats attrapent 3 souris en 3 minutes, combien de temps faut-il à 100 chats pour attraper 100 souris ?" if langue == "fr" else "If 3 cats catch 3 mice in 3 minutes, how long does it take for 100 cats to catch 100 mice?",
                    "premiere_question": "Quelle est ta première réflexion ?" if langue == "fr" else "What is your first thought?",
                    "indices": ["Le nombre de chats n'affecte pas le temps par souris", "Chaque chat attrape 1 souris en 3 minutes"] if langue == "fr" else ["The number of cats doesn't affect the time per mouse", "Each cat catches 1 mouse in 3 minutes"],
                    "difficulte": difficulte
                }
            ]
        },
        "français": {
            "exercice": [
                {
                    "message_accueil": "Exercice de conjugaison !" if langue == "fr" else "Conjugation exercise!",
                    "enonce": "Conjugue le verbe 'aller' au présent : je ____, tu ____, il ____" if langue == "fr" else "Conjugate the verb 'to go' in present tense: I ____, you ____, he ____",
                    "premiere_question": "Quelle est la première personne ?" if langue == "fr" else "What is the first person?",
                    "indices": ["je vais", "tu vas", "il va"] if langue == "fr" else ["I go", "you go", "he goes"],
                    "difficulte": difficulte
                }
            ]
        },
        "anglais": {
            "exercice": [
                {
                    "message_accueil": "English exercise!" if langue == "fr" else "English exercise!",
                    "enonce": "Translate: 'Je suis content de te voir'" if langue == "fr" else "Translate: 'Je suis content de te voir'",
                    "premiere_question": "Quelle est la traduction ?" if langue == "fr" else "What is the translation?",
                    "indices": ["I am happy", "to see you"] if langue == "fr" else ["I am happy", "to see you"],
                    "difficulte": difficulte
                }
            ]
        }
    }
    
    # Normaliser la matière
    matiere_key = matiere.lower().strip()
    if matiere_key not in exercices_db:
        # Si la matière n'existe pas, utiliser mathématiques par défaut
        matiere_key = "mathématiques"
        print(f"[DEBUG] Matière '{matiere}' non trouvée, utilisation de mathématiques")
    
    # Vérifier si le type d'exercice existe pour cette matière
    if type_exercice not in exercices_db[matiere_key]:
        type_exercice = "exercice"
    
    # Sélectionner un exercice aléatoire
    exercices = exercices_db[matiere_key][type_exercice]
    exercice_choisi = random.choice(exercices).copy()
    
    # Ajouter la difficulté et autres métadonnées
    exercice_choisi['difficulte'] = difficulte
    exercice_choisi['type'] = type_exercice
    exercice_choisi['matiere'] = matiere
    
    # Ajouter une correction simple si elle n'existe pas
    if 'correction' not in exercice_choisi:
        exercice_choisi['correction'] = {
            'reponse_finale': "Réponse à vérifier",
            'explication': "Consulte ton professeur pour la correction détaillée."
        }
    
    print(f"[DEBUG] Exercice fallback généré en {langue}")
    return exercice_choisi




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

@app.route("/admin/supprimer-test/<int:test_id>", methods=["POST"])
@admin_required
def supprimer_test(test_id):
    """Supprime un test sommatif et tous ses exercices associés"""
    test = TestSommatif.query.get_or_404(test_id)
    
    try:
        # Récupérer le dashboard URL avant de supprimer
        if session.get("is_admin"):
            dashboard_url = "/admin/dashboard"
        elif session.get("enseignant_id"):
            dashboard_url = "/dashboard-enseignant"
        else:
            dashboard_url = "/"
        
        # 1. Supprimer d'abord tous les exercices du test
        exercices = TestExercice.query.filter_by(test_id=test_id).all()
        count_exercices = len(exercices)
        for exercice in exercices:
            db.session.delete(exercice)
        
        # 2. Supprimer les réponses associées (si elles existent)
        reponses = TestResponse.query.filter_by(test_id=test_id).all()
        for reponse in reponses:
            db.session.delete(reponse)
        
        # 3. Supprimer le test lui-même
        db.session.delete(test)
        db.session.commit()
        
        # Message selon la langue
        if session.get("lang") == "en":
            flash(f"✅ Test and {count_exercices} questions successfully deleted", "success")
        else:
            flash(f"✅ Test et {count_exercices} questions supprimés avec succès", "success")
            
    except Exception as e:
        db.session.rollback()
        if session.get("lang") == "en":
            flash(f"❌ Error deleting test: {str(e)}", "error")
        else:
            flash(f"❌ Erreur lors de la suppression du test: {str(e)}", "error")
    
    # Redirection vers la page appropriée
    return redirect(dashboard_url)

@app.route("/admin/supprimer-exercice/<int:exercice_id>", methods=["POST"])
@admin_required
def supprimer_exercice(exercice_id):
    """Route pour supprimer un seul exercice et son historique"""
    exercice = Exercice.query.get_or_404(exercice_id)
    
    try:
        # 1. Supprimer d'abord toutes les réponses des élèves pour cet exercice
        reponses = StudentResponse.query.filter_by(exercice_id=exercice_id).all()
        for reponse in reponses:
            db.session.delete(reponse)
        
        # 2. Supprimer l'exercice
        db.session.delete(exercice)
        db.session.commit()
        
        if session.get("lang") == "en":
            flash("✅ Exercise and all student responses deleted successfully", "success")
        else:
            flash("✅ Exercice et toutes les réponses des élèves supprimés avec succès", "success")
            
    except Exception as e:
        db.session.rollback()
        if session.get("lang") == "en":
            flash(f"❌ Error deleting exercise: {str(e)}", "error")
        else:
            flash(f"❌ Erreur lors de la suppression: {str(e)}", "error")
    
    # Redirection vers la liste des exercices
    return redirect(url_for("liste_exercices"))

from flask import request, jsonify, session, flash, redirect, url_for
import json

@app.route("/admin/supprimer-exercices-multiple", methods=["POST"])
@admin_required
def supprimer_exercices_multiple():
    """Route pour supprimer plusieurs exercices en une seule fois"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False, 
                'message': 'No data provided'
            }), 400
        
        exercice_ids = data.get('exercice_ids', [])
        
        if not exercice_ids:
            return jsonify({
                'success': False, 
                'message': 'No exercise IDs provided'
            }), 400
        
        # Convertir en liste si ce n'est pas déjà une liste
        if isinstance(exercice_ids, str):
            exercice_ids = [int(exercice_ids)]
        elif isinstance(exercice_ids, list):
            exercice_ids = [int(id) for id in exercice_ids]
        else:
            return jsonify({
                'success': False, 
                'message': 'Invalid data format'
            }), 400
        
        deleted_count = 0
        for exercice_id in exercice_ids:
            exercice = Exercice.query.get(exercice_id)
            if exercice:
                db.session.delete(exercice)
                deleted_count += 1
        
        db.session.commit()
        
        # Message selon la langue
        if session.get("lang") == "en":
            message = f"✅ {deleted_count} exercise(s) successfully deleted"
        else:
            message = f"✅ {deleted_count} exercice(s) supprimé(s) avec succès"
        
        return jsonify({
            'success': True,
            'message': message
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting exercises: {str(e)}")
        
        if session.get("lang") == "en":
            error_message = f"❌ Error deleting exercises: {str(e)}"
        else:
            error_message = f"❌ Erreur lors de la suppression des exercices: {str(e)}"
        
        return jsonify({
            'success': False, 
            'message': error_message
        }), 500
        

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

    # Import local pour éviter de modifier immédiatement tous les imports globaux de app.py.
    from validation.engine import ValidationEngine

    print("=== 📝 SOUMISSION RÉPONSE — MOTEUR HYBRIDE ===")

    print("📦 Données reçues:", dict(request.form))

    # ============================================================
    # RÉCUPÉRATION DES DONNÉES
    # ============================================================

    student_id = request.form.get("student_id")
    exercice_id = request.form.get("exercice_id")
    reponse_eleve = request.form.get("reponse_eleve", "").strip()
    redirect_url = request.form.get("redirect_url", "/")

    print(f"Student ID: {student_id}")
    print(f"Exercice ID: {exercice_id}")
    print(f"Réponse: {reponse_eleve}")

    # ============================================================
    # VALIDATION DES CHAMPS
    # ============================================================

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

    # ============================================================
    # LANGUE DE L'ÉLÈVE
    # ============================================================

    lang = eleve.langue if hasattr(eleve, "langue") and eleve.langue == "en" else "fr"

    question = (
        exercice.question_en
        if lang == "en" and exercice.question_en
        else exercice.question_fr
    )

    reponse_attendue = (
        exercice.reponse_en
        if lang == "en" and exercice.reponse_en
        else exercice.reponse_fr
    )

    explication_reference = (
        exercice.explication_en
        if lang == "en" and exercice.explication_en
        else exercice.explication_fr
    )

    # ============================================================
    # CONTEXTE PÉDAGOGIQUE
    # ============================================================

    lecon = None
    unite = None
    matiere = None
    niveau = None

    try:
        lecon = exercice.lecon
        unite = lecon.unite if lecon else None
        matiere = unite.matiere if unite else None
        niveau = matiere.niveau if matiere else eleve.niveau
    except Exception as e:
        print(f"⚠️ Impossible de récupérer le contexte pédagogique: {e}")
        niveau = eleve.niveau

    matiere_nom_fr = matiere.nom if matiere else "Mathématiques"
    matiere_nom_en = (
        matiere.nom_en
        if matiere and hasattr(matiere, "nom_en") and matiere.nom_en
        else matiere_nom_fr
    )

    unite_nom_fr = unite.nom if unite else None
    unite_nom_en = (
        unite.nom_en
        if unite and hasattr(unite, "nom_en") and unite.nom_en
        else unite_nom_fr
    )

    lecon_nom_fr = lecon.titre_fr if lecon else "Général"
    lecon_nom_en = (
        lecon.titre_en
        if lecon and lecon.titre_en
        else lecon_nom_fr
    )

    # ============================================================
    # 1. MOTEUR HYBRIDE DE VALIDATION
    # ============================================================

    validation_engine = ValidationEngine()

    validation_result = validation_engine.validate(
        student_answer=reponse_eleve,
        expected_answer=reponse_attendue or "",
        question=question or "",
    )

    print(
        "🧠 VALIDATION:",
        f"verdict={validation_result.verdict}",
        f"confidence={validation_result.confidence}",
        f"method={validation_result.method}",
    )

    # Le verdict du moteur hybride devient l'autorité.
    # L'IA pédagogique appelée plus bas n'a plus le droit
    # de reclasser une réponse correcte en incorrecte.

    verdict_validation = validation_result.verdict
    confiance_validation = validation_result.confidence
    methode_validation = validation_result.method

    # ============================================================
    # ROUTAGE INTELLIGENT SELON LA MATIÈRE
    # ============================================================

    def get_correction_model_from_exercice(exercice):
        """
        Récupère la configuration IA pour la matière de l'exercice.
        L'admin peut tout configurer via /admin/ai-config.
        """

        matiere_nom = None

        try:
            if exercice.lecon and exercice.lecon.unite and exercice.lecon.unite.matiere:
                matiere_nom = exercice.lecon.unite.matiere.nom
        except Exception:
            pass

        # Si pas de matière, essayer de détecter depuis la question
        if not matiere_nom and exercice:
            question_text = (exercice.question_fr or exercice.question_en or "").lower()

            keyword_mapping = {
                "Mathématiques": [
                    "equation", "équation", "calcul", "x=", "fraction",
                    "geometrie", "géométrie", "algebre", "algèbre",
                    "fonction", "trigonométrie", "trigonometrie"
                ],
                "MCR3U": [
                    "mcr3u", "fonction", "quadratique", "exponentiel"
                ],
                "MHF4U": [
                    "mhf4u", "advanced function", "polynôme",
                    "polynome", "logarithme"
                ],
                "MCV4U": [
                    "mcv4u", "calculus", "dérivée", "derivee",
                    "intégrale", "integrale", "vecteur"
                ],
                "Français": [
                    "grammaire", "conjugaison", "verbe", "phrase",
                    "texte", "littérature", "litterature", "poème", "poeme"
                ],
                "English": [
                    "grammar", "conjugation", "verb", "sentence",
                    "literature", "poem"
                ],
                "Histoire": [
                    "date", "guerre", "révolution", "revolution",
                    "siècle", "siecle", "roi", "bataille"
                ],
                "Sciences": [
                    "atome", "cellule", "force", "énergie", "energie",
                    "vitesse", "masse"
                ],
                "Physique": [
                    "physique", "force", "vitesse", "accélération",
                    "acceleration", "énergie", "energie"
                ],
                "Chimie": [
                    "chimie", "atome", "molécule", "molecule",
                    "réaction", "reaction", "acide"
                ],
                "Biologie": [
                    "biologie", "cellule", "organe", "adn", "génétique",
                    "genetique"
                ]
            }

            for mat, keywords in keyword_mapping.items():
                if any(kw in question_text for kw in keywords):
                    matiere_nom = mat
                    break

        if not matiere_nom:
            matiere_nom = "Mathématiques"

        print(f"🔍 Matière détectée pour correction: {matiere_nom}")

        try:
            from models import MatiereAIConfig

            config = MatiereAIConfig.query.filter_by(
                matiere_nom=matiere_nom,
                actif=True
            ).first()

            if config:
                print(
                    f"⚙️ Configuration trouvée: "
                    f"{config.matiere_nom} → {config.api_choice}/{config.modele_ia}"
                )

                if config.api_choice == "deepseek":
                    return client_deepseek, config.modele_ia, f"DeepSeek/{config.modele_ia}"

                return client_openai, config.modele_ia, f"OpenAI/{config.modele_ia}"

        except Exception as e:
            print(f"⚠️ Erreur lecture config: {e}")

        print("⚠️ Fallback config: DeepSeek Flash")
        return client_deepseek, "deepseek-v4-flash", "DeepSeek/fallback"

    correction_client, correction_model, correction_source = get_correction_model_from_exercice(exercice)

    print(f"🔀 Correction avec: {correction_source}")


    # ============================================================
    # 2. RÉTROACTION PÉDAGOGIQUE
    # ============================================================

    analyse_ia = ""
    etoiles = None
    score_pourcentage = None

    # Cas incertain :
    # on ne fabrique PAS une mauvaise note.
    if verdict_validation == "uncertain":
        if lang == "en":
            analyse_ia = (
                "I could not validate this answer with sufficient certainty. "
                "Your answer has not been automatically marked incorrect. "
                "It should be reviewed or re-evaluated before affecting your progress."
            )
        else:
            analyse_ia = (
                "Je n'ai pas pu valider cette réponse avec suffisamment de certitude. "
                "Ta réponse n'est pas automatiquement considérée comme incorrecte. "
                "Elle doit être vérifiée ou réévaluée avant d'influencer ta progression."
            )

        print("⚠️ Verdict incertain : aucune pénalisation automatique.")

    else:
        # Le moteur hybride a déjà décidé correct / incorrect.
        # Le modèle appelé ici sert uniquement à expliquer et à noter
        # la qualité pédagogique DANS LES LIMITES du verdict validé.

        if lang == "en":
            verdict_text = (
                "CORRECT" if verdict_validation == "correct" else "INCORRECT"
            )

            prompt = f"""You are producing pedagogical feedback after a separate validation engine has already evaluated the student's answer.

PROBLEM:
{question}

EXPECTED ANSWER:
{reponse_attendue}

STUDENT ANSWER:
{reponse_eleve}

AUTHORITATIVE VALIDATION VERDICT:
{verdict_text}

VALIDATION METHOD:
{methode_validation}

VALIDATION CONFIDENCE:
{confiance_validation}

VALIDATION REASON:
{validation_result.reason or "Not provided"}

REFERENCE EXPLANATION:
{explication_reference or "Not provided"}

IMPORTANT RULE:
You MUST NOT contradict the authoritative validation verdict.

If the verdict is CORRECT:
- acknowledge that the answer/result is correct;
- you may point out an incomplete explanation or reasoning issue;
- score must be 4/5 or 5/5.

If the verdict is INCORRECT:
- explain the mathematical error precisely;
- acknowledge any valid partial reasoning;
- score must be between 0/5 and 4/5.

Format:
Analysis: ...
Score: X/5
Main error: ...
Correct answer: ..."""
        else:
            verdict_text = (
                "CORRECT" if verdict_validation == "correct" else "INCORRECT"
            )

            prompt = f"""Tu produis une rétroaction pédagogique APRÈS qu'un moteur de validation séparé a déjà évalué la réponse de l'élève.

ÉNONCÉ :
{question}

RÉPONSE ATTENDUE :
{reponse_attendue}

RÉPONSE DE L'ÉLÈVE :
{reponse_eleve}

VERDICT DE VALIDATION AUTORITAIRE :
{verdict_text}

MÉTHODE DE VALIDATION :
{methode_validation}

CONFIANCE DE VALIDATION :
{confiance_validation}

RAISON DE VALIDATION :
{validation_result.reason or "Non fournie"}

EXPLICATION DE RÉFÉRENCE :
{explication_reference or "Non fournie"}

RÈGLE IMPÉRATIVE :
Tu NE DOIS PAS contredire le verdict de validation autoritaire.

Si le verdict est CORRECT :
- confirme que la réponse ou le résultat est correct ;
- tu peux signaler une explication incomplète ou une faiblesse de raisonnement ;
- la note doit être 4/5 ou 5/5.

Si le verdict est INCORRECT :
- explique précisément l'erreur mathématique ;
- reconnais les éléments de raisonnement valides s'il y en a ;
- la note doit être comprise entre 0/5 et 4/5.

Format :
Analyse: ...
Note: X/5
Erreur principale: ...
Réponse correcte: ..."""

        try:
            print(f"🤖 Génération rétroaction pédagogique ({correction_source})...")

            chat_completion = correction_client.chat.completions.create(
                model=correction_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=700
            )

            analyse_ia = chat_completion.choices[0].message.content.strip()
            print(f"✅ Rétroaction reçue de {correction_source}")

        except Exception as e:
            print(f"❌ Erreur avec {correction_source}: {e}")

            try:
                print("🔄 Fallback rétroaction sur l'autre API...")

                if correction_client == client_deepseek:
                    fallback_client = client_openai
                    fallback_model = "gpt-4o-mini"
                    fallback_source = "OpenAI/gpt-4o-mini (fallback)"
                else:
                    fallback_client = client_deepseek
                    fallback_model = "deepseek-v4-flash"
                    fallback_source = "DeepSeek Flash (fallback)"

                chat_completion = fallback_client.chat.completions.create(
                    model=fallback_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    max_tokens=700
                )

                analyse_ia = chat_completion.choices[0].message.content.strip()
                correction_source = fallback_source

                print(f"✅ Fallback rétroaction réussi avec {fallback_source}")

            except Exception as e2:
                print(f"❌ Erreur fallback rétroaction: {e2}")

                # Même si la rétroaction IA tombe,
                # le verdict de validation reste utilisable.
                if verdict_validation == "correct":
                    analyse_ia = (
                        "Réponse validée comme correcte."
                        if lang == "fr"
                        else "Answer validated as correct."
                    )
                else:
                    analyse_ia = (
                        "Réponse validée comme incorrecte. Une explication détaillée "
                        "n'est temporairement pas disponible."
                        if lang == "fr"
                        else
                        "Answer validated as incorrect. A detailed explanation "
                        "is temporarily unavailable."
                    )

        # ========================================================
        # SCORE PÉDAGOGIQUE CONTRAINT PAR LE VERDICT
        # ========================================================

        note_ia = None

        if analyse_ia:
            match = re.search(
                r"(Note|Score)\s*:\s*([0-5])\s*/?\s*5?",
                analyse_ia,
                re.IGNORECASE
            )

            if match:
                note_ia = min(int(match.group(2)), 5)
            else:
                match = re.search(r"\b([0-5])\s*/\s*5\b", analyse_ia)
                if match:
                    note_ia = min(int(match.group(1)), 5)

        if verdict_validation == "correct":
            # Une réponse validée correcte ne peut plus recevoir 0,1,2 ou 3.
            etoiles = max(note_ia if note_ia is not None else 5, 4)

        elif verdict_validation == "incorrect":
            # Une réponse validée incorrecte peut garder du crédit
            # pour un bon raisonnement, mais pas 5/5.
            etoiles = min(note_ia if note_ia is not None else 2, 4)

        score_pourcentage = int(etoiles * 20)

        print(
            f"⭐ Score final contraint par validation: "
            f"{etoiles}/5 ({score_pourcentage}%)"
        )

    # ============================================================
    # 3. TYPE D'ERREUR
    # ============================================================

    type_erreur = validation_result.error_type

    if not type_erreur and analyse_ia:
        match_erreur_fr = re.search(
            r"Erreur principale\s*:\s*(.+)",
            analyse_ia,
            re.IGNORECASE
        )

        match_erreur_en = re.search(
            r"Main error\s*:\s*(.+)",
            analyse_ia,
            re.IGNORECASE
        )

        if match_erreur_fr:
            type_erreur = match_erreur_fr.group(1).strip()[:100]
        elif match_erreur_en:
            type_erreur = match_erreur_en.group(1).strip()[:100]

    # Une réponse correcte ne doit pas conserver artificiellement
    # un type d'erreur comme si le résultat était faux.
    if verdict_validation == "correct" and not validation_result.reasoning_correct is False:
        type_erreur = None

    # ============================================================
    # 4. NIVEAU DE RISQUE
    # ============================================================

    if verdict_validation == "uncertain":
        niveau_risque = "a_verifier"
    elif etoiles is not None and etoiles >= 4:
        niveau_risque = "faible"
    elif etoiles is not None and etoiles >= 3:
        niveau_risque = "moyen"
    else:
        niveau_risque = "élevé"

    # ============================================================
    # 5. REMÉDIATION
    # ============================================================

    # Important :
    # - pas de remédiation automatique sur un verdict incertain ;
    # - pas de remédiation sur une réponse validée correcte ;
    # - remédiation seulement après un verdict incorrect confirmé
    #   et une note réellement faible.
    remediation_declenchee = (
        verdict_validation == "incorrect"
        and etoiles is not None
        and etoiles < 3
    )

    if remediation_declenchee:
        print(f"🔄 Génération remédiation (note: {etoiles}/5)")

        if lang == "en":
            remediation_prompt = f"""Generate a short remediation exercise for a student whose answer was confirmed incorrect.

Original question:
{question}

Student's answer:
{reponse_eleve}

Validated error:
{type_erreur or validation_result.reason or "Not specified"}

Output:
Question: ...
Expected answer: ...
Hint: ..."""
        else:
            remediation_prompt = f"""Génère un court exercice de remédiation pour un élève dont la réponse a été confirmée incorrecte.

Question originale:
{question}

Réponse de l'élève:
{reponse_eleve}

Erreur validée:
{type_erreur or validation_result.reason or "Non précisée"}

Format:
Question: ...
Réponse attendue: ...
Indice: ..."""

        try:
            remediation_completion = client_deepseek.chat.completions.create(
                model="deepseek-v4-flash",
                messages=[{"role": "user", "content": remediation_prompt}],
                temperature=0.7,
                max_tokens=350
            )

            remediation_content = remediation_completion.choices[0].message.content.strip()

            print("✅ Remédiation générée avec DeepSeek Flash")

            remediation_message = (
                f"Exercice de remédiation proposé après une note de {etoiles}/5."
                if lang == "fr"
                else f"Remediation exercise suggested after a score of {etoiles}/5."
            )

            nouvelle_suggestion = RemediationSuggestion(
                user_id=eleve.id,
                theme=matiere_nom_fr if lang == "fr" else matiere_nom_en,
                lecon=lecon_nom_fr if lang == "fr" else lecon_nom_en,
                message=remediation_message,
                exercice_suggere=remediation_content,
                statut="en_attente",
                timestamp=datetime.utcnow()
            )

            db.session.add(nouvelle_suggestion)

            print("✅ Suggestion de remédiation sauvegardée")

            session["remediation_access"] = {
                "exercice_id": exercice.id,
                "note": etoiles,
                "score_pourcentage": score_pourcentage,
                "access_count": 0,
                "first_access": datetime.utcnow().isoformat(),
                "lang": lang
            }

            print(f"✅ Accès enseignant virtuel autorisé (note: {etoiles}/5)")

        except Exception as e:
            print(f"❌ Erreur génération remédiation: {e}")

    # ============================================================
    # 6. SAUVEGARDE DE LA RÉPONSE + TRACE D'APPRENTISSAGE
    # ============================================================

    try:
        from models import TraceApprentissage

        validation_details = validation_result.details or {}

        nouvelle = StudentResponse(
            user_id=eleve.id,
            exercice_id=exercice.id,
            reponse_eleve=reponse_eleve,
            analyse_ia=analyse_ia,
            etoiles=etoiles,
            score=score_pourcentage,
            type_erreur=type_erreur,
            niveau_difficulte=getattr(exercice, "niveau_difficulte", None),
            aide_utilisee=bool(session.get("remediation_access")),
            feedback_ia_structure={
                "lang": lang,
                "score_sur_5": etoiles,
                "score_pourcentage": score_pourcentage,
                "niveau_risque": niveau_risque,
                "type_erreur": type_erreur,
                "notion_cible": getattr(exercice, "notion_cible", None),
                "competence_cible": getattr(exercice, "competence_cible", None),
                "correction_source": correction_source,
                "matiere_fr": matiere_nom_fr,
                "matiere_en": matiere_nom_en,
                "unite_fr": unite_nom_fr,
                "unite_en": unite_nom_en,
                "lecon_fr": lecon_nom_fr,
                "lecon_en": lecon_nom_en,

                # Nouvelle traçabilité du moteur hybride
                "validation_verdict": verdict_validation,
                "validation_confidence": confiance_validation,
                "validation_method": methode_validation,
                "validation_reason": validation_result.reason,
                "validation_result_correct": validation_result.result_correct,
                "validation_reasoning_correct": validation_result.reasoning_correct,
                "validation_error_type": validation_result.error_type,
                "validation_details": validation_details,
                "requires_review": verdict_validation == "uncertain",
            },
            timestamp=datetime.utcnow()
        )

        db.session.add(nouvelle)
        db.session.flush()

        trace = TraceApprentissage(
            user_id=eleve.id,

            niveau_id=niveau.id if niveau else eleve.niveau_id,
            matiere_id=matiere.id if matiere else None,
            unite_id=unite.id if unite else None,
            lecon_id=lecon.id if lecon else None,
            exercice_id=exercice.id,

            type_action="exercice",
            source="soumettre_reponse",

            reponse_eleve=reponse_eleve,
            analyse_ia=analyse_ia,
            score=score_pourcentage,

            niveau_risque=niveau_risque,
            difficulte_estimee=getattr(exercice, "niveau_difficulte", None),
            notion_cible=getattr(exercice, "notion_cible", None),
            type_erreur=type_erreur,

            meta_json={
                "lang": lang,
                "score_sur_5": etoiles,
                "score_pourcentage": score_pourcentage,
                "student_response_id": nouvelle.id,
                "correction_source": correction_source,

                "question_fr": exercice.question_fr,
                "question_en": exercice.question_en,

                "matiere_fr": matiere_nom_fr,
                "matiere_en": matiere_nom_en,

                "unite_fr": unite_nom_fr,
                "unite_en": unite_nom_en,

                "lecon_fr": lecon_nom_fr,
                "lecon_en": lecon_nom_en,

                "competence_cible": getattr(exercice, "competence_cible", None),
                "type_exercice": getattr(exercice, "type_exercice", None),
                "classification_validee": getattr(exercice, "classification_validee", None),

                "aide_utilisee": bool(session.get("remediation_access")),
                "remediation_declenchee": remediation_declenchee,

                # Nouvelle trace de validation
                "validation_verdict": verdict_validation,
                "validation_confidence": confiance_validation,
                "validation_method": methode_validation,
                "validation_reason": validation_result.reason,
                "validation_result_correct": validation_result.result_correct,
                "validation_reasoning_correct": validation_result.reasoning_correct,
                "validation_error_type": validation_result.error_type,
                "validation_details": validation_details,
                "requires_review": verdict_validation == "uncertain",
            },
            created_at=datetime.utcnow()
        )

        db.session.add(trace)
        db.session.commit()

        print("✅ Réponse sauvegardée en base de données")
        print("✅ Trace d'apprentissage créée")
        print(
            f"🧠 Trace: élève={eleve.id}, "
            f"exercice={exercice.id}, "
            f"verdict={verdict_validation}, "
            f"score={score_pourcentage}, "
            f"risque={niveau_risque}"
        )

    except Exception as e:
        db.session.rollback()
        print(f"❌ Erreur lors de la sauvegarde réponse/trace: {e}")
        return f"Erreur base de données: {e}", 500

    print("=== ✅ RÉPONSE + TRACE SAUVEGARDÉES ===")

    # ============================================================
    # 7. AFFICHAGE DE LA RÉTROACTION
    # ============================================================

    show_teacher_button = (
        verdict_validation == "uncertain"
        or remediation_declenchee
    )

    return render_template(
        "exercice_detail.html",
        exercice=exercice,
        eleve=eleve,
        lang=lang,
        reponse=nouvelle,
        show_feedback=True,
        already_completed=True,
        show_teacher_button=show_teacher_button
    )


# ====================================================================
# ROUTES DE MONÉTISATION ADMIN
# ====================================================================

@app.route("/admin/versements-manuels")
def admin_versements_manuels():
    """Page de gestion des versements manuels"""
    
    # 🔴 VÉRIFICATION MANUELLE TEMPORAIRE
    if "user_id" not in session:
        flash("Accès non autorisé", "error")
        return redirect(url_for("login"))
    
    user = db.session.get(User, session["user_id"])
    if not user or user.role != "admin":
        flash("Accès réservé aux administrateurs", "error")
        return redirect(url_for("admin_dashboard"))  # Redirige vers le dashboard admin
    
    # 🔴 FIN DE LA VÉRIFICATION MANUELLE
    
    lang = request.args.get("lang") or session.get("lang", "fr")
    
    try:
        # Récupérer tous les enseignants pour le formulaire
        UserModel = get_user_model()
        teachers = UserModel.query.filter_by(role="enseignant").order_by(UserModel.nom_complet).all()
        
        # Récupérer les versements manuels
        VersementManuelModel = get_model('VersementManuel')
        if not VersementManuelModel:
            versements = []
        else:
            statut_filter = request.args.get("statut")
            query = VersementManuelModel.query\
                .join(UserModel, VersementManuelModel.enseignant_id == UserModel.id)\
                .order_by(VersementManuelModel.date_demande.desc())
            
            if statut_filter:
                query = query.filter(VersementManuelModel.statut == statut_filter)
            
            search_filter = request.args.get("search")
            if search_filter:
                query = query.filter(UserModel.nom_complet.ilike(f"%{search_filter}%"))
            
            versements = query.all()
        
        return render_template(
            "admin/versements_manuels.html",  # ← CHANGEMENT ICI
            versements=versements,
            teachers=teachers,
            lang=lang
        )
        
    except Exception as e:
        logger.error(f"Erreur dans admin_versements_manuels: {e}")
        flash("Erreur lors du chargement des versements manuels", "error")
        return redirect(url_for("admin_dashboard"))

@app.route("/admin/commissions")
@admin_required
def admin_commissions():
    """Vue globale des commissions"""
    lang = request.args.get("lang") or session.get("lang", "fr")
    
    try:
        CommissionModel = get_model('Commission')
        if CommissionModel:
            commissions = CommissionModel.query\
                .order_by(CommissionModel.date_calcul.desc())\
                .all()
            
            # Statistiques
            stats = {
                'total': db.session.query(db.func.sum(CommissionModel.montant_commission)).scalar() or 0,
                'pending': db.session.query(db.func.sum(CommissionModel.montant_commission))
                          .filter(CommissionModel.statut.in_(['pending', 'paiement_manuel'])).scalar() or 0,
                'paid': db.session.query(db.func.sum(CommissionModel.montant_commission))
                        .filter(CommissionModel.statut == 'paid').scalar() or 0,
                'count': CommissionModel.query.count()
            }
        else:
            commissions = []
            stats = {'total': 0, 'pending': 0, 'paid': 0, 'count': 0}
            flash("Module de commissions non disponible", "warning")
    except Exception as e:
        logger.error(f"Erreur chargement commissions: {e}")
        commissions = []
        stats = {'total': 0, 'pending': 0, 'paid': 0, 'count': 0}
    
    return render_template(
        "admin/commissions.html",
        commissions=commissions,
        stats=stats,
        lang=lang
    )

@app.route("/admin/calculate-commissions")
@admin_required
def calculate_commissions():
    """Calculer les commissions pour tous les enseignants"""
    try:
        CommissionModel = get_model('Commission')
        UserModel = get_user_model()
        
        if not CommissionModel or not UserModel:
            return jsonify({
                'success': False,
                'message': 'Module de commission non disponible'
            }), 400
        
        # Récupérer tous les enseignants
        enseignants = UserModel.query.filter_by(role="enseignant").all()
        commissions_created = 0
        enseignants_avec_commissions = []
        
        for enseignant in enseignants:
            # Compter les élèves de cet enseignant (utilisez enseignant_referent_id)
            students_count = UserModel.query.filter_by(
                enseignant_referent_id=enseignant.id, 
                role="eleve",
                statut="actif"
            ).count()
            
            if students_count > 0:
                # Calcul basé sur le nombre d'élèves et leur statut
                # Exemple: $10 par élève actif
                commission_amount = students_count * 10.0
                
                # Vérifier s'il y a déjà une commission ce mois-ci
                current_month = datetime.utcnow().month
                current_year = datetime.utcnow().year
                
                existing_commission = CommissionModel.query.filter(
                    CommissionModel.enseignant_id == enseignant.id,
                    db.extract('month', CommissionModel.date_calcul) == current_month,
                    db.extract('year', CommissionModel.date_calcul) == current_year,
                    CommissionModel.type_abonnement == 'subscription'
                ).first()
                
                if not existing_commission:
                    # Créer la commission
                    new_commission = CommissionModel(
                        enseignant_id=enseignant.id,
                        eleve_id=0,  # ID générique pour les commissions globales
                        type_abonnement='subscription',
                        montant_total=commission_amount * 5,  # Exemple: montant total 5x la commission
                        montant_commission=commission_amount,
                        taux_base=20.0,
                        statut='pending',
                        statut_eleve='actif',
                        date_paiement_eleve=datetime.utcnow(),
                        details_bonus={
                            'students_count': students_count,
                            'rate_per_student': 10.0,
                            'type': 'monthly_subscription'
                        }
                    )
                    db.session.add(new_commission)
                    commissions_created += 1
                    enseignants_avec_commissions.append({
                        'id': enseignant.id,
                        'nom': enseignant.nom_complet,
                        'students': students_count,
                        'amount': commission_amount
                    })
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Créé {commissions_created} nouvelles commissions',
            'count': commissions_created,
            'teachers': enseignants_avec_commissions,
            'total_amount': sum(t['amount'] for t in enseignants_avec_commissions)
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur calcul commissions: {e}")
        return jsonify({
            'success': False,
            'message': f'Erreur lors du calcul des commissions: {str(e)}'
        }), 400

@app.route("/admin/interac-payments")
@admin_required
def admin_interac_payments():
    """Suivi des paiements Interac"""
    lang = request.args.get("lang") or session.get("lang", "fr")
    
    try:
        VersementManuelModel = get_model('VersementManuel')
        if VersementManuelModel:
            payments = VersementManuelModel.query\
                .order_by(VersementManuelModel.date_demande.desc())\
                .all()
        else:
            payments = []
    except Exception as e:
        logger.error(f"Erreur chargement paiements Interac: {e}")
        payments = []
    
    return render_template(
        "admin/interac_payments.html",
        payments=payments,
        lang=lang
    )

@app.route("/admin/generate-payment-report")
@admin_required
def admin_generate_payment_report():
    """Génération de rapport de paiements"""
    lang = request.args.get("lang") or session.get("lang", "fr")
    
    try:
        CommissionModel = get_model('Commission')
        VersementManuelModel = get_model('VersementManuel')
        UserModel = get_user_model()
        
        # Générer des données pour le rapport
        report_data = {
            'month': datetime.utcnow().strftime('%B %Y'),
            'total_teachers': UserModel.query.filter_by(role="enseignant").count() if UserModel else 0,
            'total_students': UserModel.query.filter_by(role="eleve").count() if UserModel else 0,
            'total_commissions': 0,
            'total_payments': 0,
            'commissions': [],
            'payments': []
        }
        
        if CommissionModel:
            commissions = CommissionModel.query\
                .filter(db.extract('month', CommissionModel.date_calcul) == datetime.utcnow().month)\
                .all()
            report_data['total_commissions'] = sum(c.montant_commission for c in commissions if c.montant_commission)
            report_data['commissions'] = [{
                'teacher_id': c.enseignant_id,
                'amount': float(c.montant_commission or 0),
                'status': c.statut,
                'date': c.date_calcul.strftime('%Y-%m-%d') if c.date_calcul else ''
            } for c in commissions]
        
        if VersementManuelModel:
            payments = VersementManuelModel.query\
                .filter(db.extract('month', VersementManuelModel.date_demande) == datetime.utcnow().month)\
                .all()
            report_data['total_payments'] = sum(p.montant_net for p in payments if p.montant_net)
            report_data['payments'] = [{
                'teacher_id': p.enseignant_id,
                'amount': float(p.montant_net or 0),
                'status': p.statut,
                'date': p.date_demande.strftime('%Y-%m-%d') if p.date_demande else ''
            } for p in payments]
        
    except Exception as e:
        logger.error(f"Erreur génération rapport: {e}")
        report_data = {}
    
    return render_template(
        "admin/payment_report.html",
        report=report_data,
        lang=lang
    )

@app.route("/admin/teacher/<int:teacher_id>/commissions")
@admin_required
def admin_teacher_commissions(teacher_id):
    """Commissions d'un enseignant spécifique"""
    lang = request.args.get("lang") or session.get("lang", "fr")
    
    try:
        CommissionModel = get_model('Commission')
        UserModel = get_user_model()
        
        if CommissionModel and UserModel:
            commissions = CommissionModel.query.filter_by(enseignant_id=teacher_id)\
                .order_by(CommissionModel.date_calcul.desc()).all()
            
            enseignant = UserModel.query.get(teacher_id)
            
            if enseignant and enseignant.role == "enseignant":
                stats = {
                    'total': sum(float(c.montant_commission or 0) for c in commissions),
                    'pending': sum(float(c.montant_commission or 0) for c in commissions 
                                  if c.statut in ['pending', 'paiement_manuel']),
                    'paid': sum(float(c.montant_commission or 0) for c in commissions 
                               if c.statut == 'paid'),
                    'count': len(commissions)
                }
            else:
                commissions = []
                enseignant = None
                stats = {'total': 0, 'pending': 0, 'paid': 0, 'count': 0}
                flash("Enseignant non trouvé", "error")
        else:
            commissions = []
            enseignant = None
            stats = {'total': 0, 'pending': 0, 'paid': 0, 'count': 0}
            flash("Module de commissions non disponible", "warning")
    except Exception as e:
        logger.error(f"Erreur chargement commissions enseignant: {e}")
        commissions = []
        enseignant = None
        stats = {'total': 0, 'pending': 0, 'paid': 0, 'count': 0}
    
    return render_template(
        "admin/teacher_commissions.html",
        commissions=commissions,
        enseignant=enseignant,
        stats=stats,
        lang=lang
    )

@app.route("/admin/teacher/<int:teacher_id>/send-reminder", methods=["POST"])
@admin_required
def admin_send_payment_reminder(teacher_id):
    """Envoyer un rappel de paiement à un enseignant"""
    try:
        UserModel = get_user_model()
        enseignant = UserModel.query.get(teacher_id)
        
        if not enseignant or enseignant.role != "enseignant":
            return jsonify({
                'success': False,
                'message': 'Enseignant non trouvé'
            }), 404
        
        # Ici vous pourriez envoyer un email
        # send_payment_reminder_email(enseignant.email, enseignant.nom_complet)
        
        logger.info(f"Rappel de paiement envoyé à {enseignant.nom_complet} ({enseignant.email})")
        
        return jsonify({
            'success': True,
            'message': f"Rappel envoyé à {enseignant.nom_complet}"
        })
    except Exception as e:
        logger.error(f"Erreur envoi rappel: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

@app.route("/admin/commission/<int:commission_id>/details")
@admin_required
def commission_details(commission_id):
    """Détails d'une commission spécifique"""
    try:
        CommissionModel = get_model('Commission')
        UserModel = get_user_model()
        
        if not CommissionModel:
            return jsonify({
                'date': '',
                'type': '',
                'amount': 0,
                'status': '',
                'description': '',
                'payment_date': '',
                'reference': '',
                'teacher_name': ''
            })
        
        commission = CommissionModel.query.get(commission_id)
        
        if not commission:
            return jsonify({
                'date': '',
                'type': '',
                'amount': 0,
                'status': '',
                'description': '',
                'payment_date': '',
                'reference': '',
                'teacher_name': ''
            })
        
        # Récupérer le nom de l'enseignant
        teacher_name = "N/A"
        if UserModel:
            teacher = UserModel.query.get(commission.enseignant_id)
            teacher_name = teacher.nom_complet if teacher else "N/A"
        
        return jsonify({
            'date': commission.date_calcul.strftime('%Y-%m-%d') if commission.date_calcul else '',
            'type': commission.type_abonnement or '',
            'amount': float(commission.montant_commission) if commission.montant_commission else 0,
            'status': commission.statut or '',
            'description': f"Commission pour {commission.type_abonnement}",
            'payment_date': commission.date_versement_manuel.strftime('%Y-%m-%d') if commission.date_versement_manuel else '',
            'reference': commission.reference_interac or '',
            'teacher_name': teacher_name
        })
    except Exception as e:
        logger.error(f"Erreur détails commission: {e}")
        return jsonify({
            'date': '',
            'type': '',
            'amount': 0,
            'status': '',
            'description': '',
            'payment_date': '',
            'reference': '',
            'teacher_name': ''
        })

@app.route("/admin/commission/<int:commission_id>/mark-paid", methods=["POST"])
@admin_required
def mark_commission_paid(commission_id):
    """Marquer une commission comme payée"""
    try:
        CommissionModel = get_model('Commission')
        if not CommissionModel:
            return jsonify({
                'success': False,
                'message': 'Module de commissions non disponible'
            }), 400
        
        commission = CommissionModel.query.get(commission_id)
        if not commission:
            return jsonify({
                'success': False,
                'message': 'Commission non trouvée'
            }), 404
        
        commission.statut = 'paid'
        commission.date_versement_manuel = datetime.utcnow()
        db.session.commit()
        
        logger.info(f"Commission {commission_id} marquée comme payée")
        
        return jsonify({
            'success': True,
            'message': 'Commission marquée comme payée'
        })
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur marquage commission payée: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 400

# ====================================================================
# API ENDPOINTS POUR LE TABLEAU DE BORD
# ====================================================================

@app.route("/admin/payment/<int:payment_id>/details")
@admin_required
def admin_payment_details(payment_id):
    """Détails d'un paiement (API)"""
    try:
        VersementManuelModel = get_model('VersementManuel')
        UserModel = get_user_model()
        
        if not VersementManuelModel:
            return jsonify({
                'teacher_name': 'N/A',
                'amount': 0,
                'status': 'unknown',
                'date': '',
                'reference': '',
                'email': '',
                'method': ''
            })
        
        payment = VersementManuelModel.query.get(payment_id)
        
        if not payment:
            return jsonify({
                'teacher_name': 'N/A',
                'amount': 0,
                'status': 'unknown',
                'date': '',
                'reference': '',
                'email': '',
                'method': ''
            })
        
        # Récupérer les infos de l'enseignant
        teacher_name = "N/A"
        teacher_email = "N/A"
        if UserModel:
            teacher = UserModel.query.get(payment.enseignant_id)
            if teacher:
                teacher_name = teacher.nom_complet
                teacher_email = teacher.email
        
        return jsonify({
            'teacher_name': teacher_name,
            'amount': float(payment.montant_net) if payment.montant_net else 0,
            'status': payment.statut or 'unknown',
            'date': payment.date_demande.strftime('%Y-%m-%d') if payment.date_demande else '',
            'reference': payment.reference_interac or '',
            'email': payment.email_interac or teacher_email,
            'method': payment.method or 'interac'
        })
    except Exception as e:
        logger.error(f"Erreur détails paiement: {e}")
        return jsonify({
            'teacher_name': 'N/A',
            'amount': 0,
            'status': 'unknown',
            'date': '',
            'reference': '',
            'email': '',
            'method': ''
        })

@app.route("/admin/payment/<int:payment_id>/mark-paid", methods=["POST"])
@admin_required
def admin_mark_payment_paid(payment_id):
    """Marquer un paiement comme payé"""
    try:
        VersementManuelModel = get_model('VersementManuel')
        if not VersementManuelModel:
            return jsonify({
                'success': False,
                'message': 'Module de paiements non disponible'
            }), 400
        
        payment = VersementManuelModel.query.get(payment_id)
        if not payment:
            return jsonify({
                'success': False,
                'message': 'Paiement non trouvé'
            }), 404
        
        # Mettre à jour le statut
        payment.statut = 'complete'
        payment.date_versement = datetime.utcnow()
        db.session.commit()
        
        logger.info(f"Paiement {payment_id} marqué comme payé")
        
        return jsonify({
            'success': True,
            'message': 'Paiement marqué comme payé'
        })
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur marquage paiement payé: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

@app.route("/admin/payment/<int:payment_id>/update", methods=["POST"])
@admin_required
def admin_update_payment(payment_id):
    """Mettre à jour un paiement (référence Interac, etc.)"""
    try:
        VersementManuelModel = get_model('VersementManuel')
        if not VersementManuelModel:
            return jsonify({
                'success': False,
                'message': 'Module de paiements non disponible'
            }), 400
        
        payment = VersementManuelModel.query.get(payment_id)
        if not payment:
            return jsonify({
                'success': False,
                'message': 'Paiement non trouvé'
            }), 404
        
        data = request.get_json()
        
        # Mettre à jour les champs
        if 'reference_interac' in data:
            payment.reference_interac = data['reference_interac']
        
        if 'status' in data:
            payment.statut = data['status']
            
        if 'notes' in data:
            payment.notes_admin = data['notes']
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Paiement mis à jour'
        })
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur mise à jour paiement: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500



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




@app.route("/admin-enseignants")
@admin_required
def admin_enseignants():
    """Page d'administration des enseignants"""
    try:
        from models import User, Commission
        
        # Récupérer tous les enseignants
        enseignants = User.query.filter_by(role="enseignant").all()
        
        print(f"DEBUG: {len(enseignants)} enseignants trouvés")
        
        # Préparer les données pour le template
        enseignants_data = []
        for enseignant in enseignants:
            print(f"DEBUG: Enseignant {enseignant.id}: {enseignant.email}")
            
            # Récupérer TOUS les élèves (pas juste 5)
            eleves = User.query.filter(
                User.enseignant_referent_id == enseignant.id,
                (User.role == 'eleve') | (User.role == 'élève')
            ).all()
            
            # Compter les élèves
            eleves_count = len(eleves)
            
            # Calculer les commissions
            commissions = Commission.query.filter_by(enseignant_id=enseignant.id).all()
            commissions_total = sum(c.montant_commission for c in commissions if c.montant_commission)
            commissions_pending = sum(c.montant_commission for c in commissions 
                                    if c.montant_commission and c.statut in ['pending', 'paiement_manuel'])
            
            # Téléphone (si existe)
            telephone = getattr(enseignant, 'telephone', None)
            
            enseignants_data.append({
                'id': enseignant.id,
                'nom_complet': enseignant.nom_complet,  # CORRECTION ICI: nom_complet, pas nom_complet
                'email': enseignant.email,
                'telephone': telephone,  # Ajout du téléphone
                'username': enseignant.username,
                'date_inscription': enseignant.date_inscription,
                'statut': enseignant.statut,
                'taux_commission': getattr(enseignant, 'taux_commission', 20.0),
                'specialite': getattr(enseignant, 'specialite', ''),
                'experience_annees': getattr(enseignant, 'experience_annees', 0),
                'eleves_count': eleves_count,
                'commissions_total': commissions_total,
                'commissions_pending': commissions_pending,
                'eleves': eleves  # TOUS les élèves, pas juste 5
            })
        
        # DEBUG: Afficher la structure
        print(f"DEBUG: Données envoyées au template:")
        if enseignants_data:
            import json
            print(json.dumps(enseignants_data[0], indent=2, default=str))
        
        return render_template(
            "admin_enseignants.html", 
            enseignants=enseignants_data,  # C'est une liste de dicts
            lang=session.get('lang', 'fr')
        )
        
    except Exception as e:
        logger.error(f"Erreur dans admin_enseignants: {e}")
        flash("Erreur lors du chargement de la liste des enseignants", "error")
        return redirect(url_for("admin_dashboard"))

@app.route("/debug-all-users")
@admin_required
def debug_all_users():
    """Afficher tous les utilisateurs pour déboguer"""
    from models import User
    
    result = "<h1>DEBUG - Tous les utilisateurs</h1>"
    
    all_users = User.query.all()
    result += f"<p>Total users: {len(all_users)}</p>"
    
    # Compter par rôle
    from collections import Counter
    roles = [u.role for u in all_users]
    role_counts = Counter(roles)
    
    result += "<h3>Comptage par rôle:</h3>"
    for role, count in role_counts.items():
        result += f"<p>'{role}': {count} utilisateurs</p>"
    
    # Afficher tous les utilisateurs détaillés
    result += "<h3>Tous les utilisateurs:</h3>"
    for user in all_users:
        result += f"""
        <div style="border:1px solid #ccc; padding:10px; margin:5px;">
            <strong>ID: {user.id}</strong><br>
            Nom: {user.nom_complet}<br>
            Email: {user.email}<br>
            Rôle: <strong>'{user.role}'</strong><br>
            Username: {user.username}<br>
            Date inscription: {user.date_inscription}<br>
            Statut: {user.statut}<br>
            Enseignant référent ID: {user.enseignant_referent_id}
        </div>
        """
    
    return result

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
    """Modifier un enseignant (admin)"""
    try:
        UserModel = get_user_model()
        
        # Récupérer l'utilisateur enseignant
        enseignant = UserModel.query.filter_by(
            id=enseignant_id, 
            role="enseignant"
        ).first_or_404()
        
        if request.method == "POST":
            # Récupérer les données du formulaire
            nom_complet = request.form.get("nom_complet", "").strip()
            email = request.form.get("email", "").strip()
            username = request.form.get("username", "").strip()
            taux_commission = request.form.get("taux_commission", "")
            specialite = request.form.get("specialite", "").strip()
            experience_annees = request.form.get("experience_annees", "")
            methode_versement = request.form.get("methode_versement", "").strip()
            email_interac_paiement = request.form.get("email_interac_paiement", "").strip()
            statut = request.form.get("statut", "").strip()
            nouveau_mot_de_passe = request.form.get("mot_de_passe", "").strip()

            # Validation des données
            if not nom_complet or not email:
                flash("Le nom et l'email sont obligatoires", "error")
                return render_template("modifier_enseignant.html", 
                                      enseignant=enseignant,
                                      lang=session.get('lang', 'fr'))

            # Mettre à jour les champs de base
            enseignant.nom_complet = nom_complet
            enseignant.email = email
            
            if username:
                enseignant.username = username
            
            # Champs spécifiques aux enseignants
            if taux_commission:
                try:
                    enseignant.taux_commission = float(taux_commission)
                except ValueError:
                    flash("Taux de commission invalide", "error")
            
            if specialite:
                enseignant.specialite = specialite
            
            if experience_annees:
                try:
                    enseignant.experience_annees = int(experience_annees)
                except ValueError:
                    flash("Années d'expérience invalides", "error")
            
            if methode_versement:
                enseignant.methode_versement = methode_versement
            
            if email_interac_paiement:
                enseignant.email_interac_paiement = email_interac_paiement
            
            if statut:
                enseignant.statut = statut
            
            # Mettre à jour le mot de passe si fourni
            if nouveau_mot_de_passe:
                enseignant.mot_de_passe = nouveau_mot_de_passe

            db.session.commit()
            flash("Enseignant modifié avec succès", "success")
            return redirect("/admin-enseignants")

        # GET: Afficher le formulaire
        return render_template(
            "modifier_enseignant.html", 
            enseignant=enseignant,
            lang=session.get('lang', 'fr')
        )
        
    except Exception as e:
        logger.error(f"Erreur modification enseignant: {e}")
        flash("Erreur lors de la modification de l'enseignant", "error")
        return redirect("/admin-enseignants")

@app.route("/supprimer-enseignant", methods=["POST"])
@admin_required
def supprimer_enseignant():
    """Supprimer un enseignant"""
    try:
        UserModel = get_user_model()
        enseignant_id = request.form.get("id")
        
        if not enseignant_id:
            flash("ID enseignant manquant", "error")
            return redirect("/admin-enseignants")
        
        # Récupérer l'enseignant
        enseignant = UserModel.query.filter_by(
            id=enseignant_id, 
            role="enseignant"
        ).first()
        
        if enseignant:
            # Vérifier s'il a des élèves
            eleves_count = UserModel.query.filter_by(
                enseignant_referent_id=enseignant.id, 
                role="eleve"
            ).count()
            
            if eleves_count > 0:
                flash(f"Impossible de supprimer cet enseignant car il a {eleves_count} élève(s) encadré(s). Réaffectez d'abord les élèves.", "error")
                return redirect("/admin-enseignants")
            
            # Vérifier les commissions en attente
            CommissionModel = get_model('Commission')
            if CommissionModel:
                # CORRECTION: Utilisez filter() au lieu de filter_by() pour in_()
                commissions_pending = CommissionModel.query.filter(
                    CommissionModel.enseignant_id == enseignant.id,
                    CommissionModel.statut.in_(['pending', 'paiement_manuel'])
                ).count()
                
                if commissions_pending > 0:
                    flash(f"Impossible de supprimer cet enseignant car il a {commissions_pending} commission(s) en attente.", "error")
                    return redirect("/admin-enseignants")
            
            # Supprimer l'enseignant
            db.session.delete(enseignant)
            db.session.commit()
            flash("Enseignant supprimé avec succès", "success")
        else:
            flash("Enseignant non trouvé", "error")

        return redirect("/admin-enseignants")
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur suppression enseignant: {e}")
        flash("Erreur lors de la suppression de l'enseignant", "error")
        return redirect("/admin-enseignants")

@app.route("/liste-enseignants")
def liste_enseignants():
    """Liste publique des enseignants (pour les élèves/parents)"""
    try:
        UserModel = get_user_model()
        
        # Récupérer les enseignants actifs
        enseignants = UserModel.query.filter_by(
            role="enseignant",
            statut="actif"
        ).all()
        
        # Préparer les données pour l'affichage public
        enseignants_data = []
        for enseignant in enseignants:
            # Compter les élèves (optionnel, pour afficher l'expérience)
            eleves_count = UserModel.query.filter_by(
                enseignant_referent_id=enseignant.id, 
                role="eleve"
            ).count()
            
            enseignants_data.append({
                'id': enseignant.id,
                'nom_complet': enseignant.nom_complet,
                'specialite': getattr(enseignant, 'specialite', ''),
                'experience_annees': getattr(enseignant, 'experience_annees', 0),
                'biographie': getattr(enseignant, 'biographie', ''),
                'qualifications': getattr(enseignant, 'qualifications', ''),
                'eleves_count': eleves_count,
                'note_moyenne': getattr(enseignant, 'note_moyenne', 0.0),
                'nombre_evaluations': getattr(enseignant, 'nombre_evaluations', 0)
            })
        
        # Trier par note moyenne ou expérience
        enseignants_data.sort(key=lambda x: x['note_moyenne'], reverse=True)
        
        return render_template(
            "liste_enseignants.html", 
            enseignants=enseignants_data,
            lang=session.get('lang', 'fr')
        )
        
    except Exception as e:
        logger.error(f"Erreur liste enseignants: {e}")
        # Retourner une liste vide en cas d'erreur
        return render_template(
            "liste_enseignants.html", 
            enseignants=[],
            lang=session.get('lang', 'fr')
        )
        

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
def inscription_enseignant():
    """Inscription d'un nouvel enseignant - accessible sans authentification"""

    lang = request.args.get("lang") or session.get("lang", "fr")

    # Charger les niveaux pour le formulaire GET et les retours d'erreur
    niveaux = Niveau.query.order_by(Niveau.nom.asc()).all()

    if request.method == "POST":
        nom = request.form.get("nom")
        email = request.form.get("email")
        mot_de_passe = request.form.get("mot_de_passe")
        confirm_password = request.form.get("confirm_password")

        # ✅ Récupérer les matières choisies
        # Le template devra envoyer des checkbox name="matieres"
        matiere_ids = request.form.getlist("matieres")

        # Validation basique
        if not all([nom, email, mot_de_passe, confirm_password]):
            flash(
                "Tous les champs sont requis" if lang == "fr" else "All fields are required",
                "error"
            )
            return render_template(
                "inscription_enseignant.html",
                lang=lang,
                niveaux=niveaux
            )

        # Vérifier la confirmation du mot de passe
        if mot_de_passe != confirm_password:
            flash(
                "Les mots de passe ne correspondent pas" if lang == "fr" else "Passwords do not match",
                "error"
            )
            return render_template(
                "inscription_enseignant.html",
                lang=lang,
                niveaux=niveaux
            )

        # Vérifier la longueur du mot de passe
        if len(mot_de_passe) < 8:
            flash(
                "Le mot de passe doit contenir au moins 8 caractères" if lang == "fr" else "Password must be at least 8 characters",
                "error"
            )
            return render_template(
                "inscription_enseignant.html",
                lang=lang,
                niveaux=niveaux
            )

        # ✅ Vérifier qu'au moins une matière est choisie
        if not matiere_ids:
            flash(
                "Veuillez choisir au moins une matière à enseigner." if lang == "fr" else "Please choose at least one subject to teach.",
                "error"
            )
            return render_template(
                "inscription_enseignant.html",
                lang=lang,
                niveaux=niveaux
            )

        # Vérifier si l'email existe déjà
        existing_user = User.query.filter_by(email=email.strip()).first()
        if existing_user:
            flash(
                "Un utilisateur avec cet email existe déjà." if lang == "fr" else "A user with this email already exists.",
                "error"
            )
            return render_template(
                "inscription_enseignant.html",
                lang=lang,
                niveaux=niveaux
            )

        try:
            # ✅ Sécuriser les IDs reçus
            matiere_ids_int = []

            for mid in matiere_ids:
                try:
                    matiere_ids_int.append(int(mid))
                except ValueError:
                    pass

            if not matiere_ids_int:
                flash(
                    "Les matières sélectionnées sont invalides." if lang == "fr" else "Selected subjects are invalid.",
                    "error"
                )
                return render_template(
                    "inscription_enseignant.html",
                    lang=lang,
                    niveaux=niveaux
                )

            # ✅ Récupérer les matières valides depuis la base
            matieres_valides = Matiere.query.filter(
                Matiere.id.in_(matiere_ids_int)
            ).all()

            if not matieres_valides:
                flash(
                    "Aucune matière valide n'a été trouvée." if lang == "fr" else "No valid subject was found.",
                    "error"
                )
                return render_template(
                    "inscription_enseignant.html",
                    lang=lang,
                    niveaux=niveaux
                )

            # Créer l'utilisateur enseignant
            new_teacher = User(
                username=email.strip().split("@")[0],
                nom_complet=nom.strip(),
                email=email.strip(),
                role="enseignant",
                statut="actif",
                statut_paiement="exempt",
                inscrit_par_admin=False,
                langue=lang,
                date_inscription=datetime.utcnow(),
                email_verifie=False,
                accepte_cgu=True,
                date_acceptation_cgu=datetime.utcnow()
            )

            # Définir le mot de passe
            new_teacher.mot_de_passe = mot_de_passe

            db.session.add(new_teacher)
            db.session.flush()  # ✅ permet d'obtenir new_teacher.id sans commit immédiat

            # ✅ Enregistrer les niveaux/matières de l'enseignant
            for matiere in matieres_valides:
                lien = EnseignantMatiere(
                    enseignant_id=new_teacher.id,
                    niveau_id=matiere.niveau_id,
                    matiere_id=matiere.id
                )
                db.session.add(lien)

            db.session.commit()

            flash(
                "Inscription réussie ! Vos matières d'enseignement ont été enregistrées. Veuillez contacter le support à info@advanceteach.com pour vous connecter à vos élèves."
                if lang == "fr" else
                "Registration successful! Your teaching subjects have been saved. Please contact support at info@advanceteach.com to connect with your students.",
                "success"
            )

            return redirect(url_for("login_enseignant", lang=lang))

        except Exception as e:
            db.session.rollback()
            print(f"Erreur inscription enseignant: {e}")
            flash(
                f"Erreur lors de l'inscription: {str(e)}"
                if lang == "fr" else
                f"Registration error: {str(e)}",
                "error"
            )
            return render_template(
                "inscription_enseignant.html",
                lang=lang,
                niveaux=niveaux
            )

    # GET request
    return render_template(
        "inscription_enseignant.html",
        lang=lang,
        niveaux=niveaux
    )


@app.route("/admin/creer-enseignant", methods=["GET", "POST"])
@admin_required
def creer_enseignant_admin():
    """Créer un enseignant depuis l'admin dashboard"""
    lang = session.get("lang", "fr")
    
    if request.method == "POST":
        nom = request.form.get("nom")
        email = request.form.get("email")
        mot_de_passe = request.form.get("mot_de_passe")
        specialite = request.form.get("specialite")
        telephone = request.form.get("telephone")
        
        # Validation
        if not all([nom, email, mot_de_passe]):
            flash("Nom, email et mot de passe sont obligatoires", "error")
            return redirect(url_for("creer_enseignant_admin"))
        
        # Vérifier si l'email existe déjà
        existing = User.query.filter_by(email=email).first()
        if existing:
            flash("Un utilisateur avec cet email existe déjà", "error")
            return redirect(url_for("creer_enseignant_admin"))
        
        try:
            # Créer l'enseignant
            enseignant = User(
                username=email.split('@')[0],  # username = partie avant @
                nom_complet=nom,
                email=email,
                telephone=telephone or None,
                specialite=specialite or None,
                role="enseignant",  # ✅ IMPORTANT : 'enseignant' en minuscules
                statut="actif",
                statut_paiement="exempt",
                inscrit_par_admin=True,
                langue=lang,
                mot_de_passe=mot_de_passe,  # Le setter va hacher
                date_inscription=datetime.utcnow(),
                
                # Champs spécifiques enseignant
                taux_commission=20.0,
                methode_versement="interac",
                statut_enseignant="actif",
                experience_annees=0
            )
            
            db.session.add(enseignant)
            db.session.commit()
            
            flash(f'✅ Enseignant {nom} créé avec succès !', 'success')
            return redirect(url_for('admin_dashboard'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'❌ Erreur: {str(e)}', 'error')
            return redirect(url_for('creer_enseignant_admin'))
    
    # GET request - afficher le formulaire
    return render_template("admin_creer_enseignant.html", lang=lang)

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
    """Permettre à un enseignant de changer son mot de passe"""

    # ============================================================
    # AUTHENTIFICATION ENSEIGNANT
    # Système actuel : session["user_id"] + session["role"]
    # ============================================================

    if "user_id" not in session:
        flash("Veuillez vous connecter", "error")
        return redirect(url_for("login_enseignant"))

    if session.get("role") != "enseignant":
        flash("Accès réservé aux enseignants", "error")
        return redirect(url_for("login_enseignant"))

    try:
        UserModel = get_user_model()

        enseignant = (
            UserModel.query
            .filter_by(
                id=session["user_id"],
                role="enseignant"
            )
            .first()
        )

        if not enseignant:
            session.clear()
            flash("Session enseignant invalide. Veuillez vous reconnecter.", "error")
            return redirect(url_for("login_enseignant"))

        lang = session.get("lang", "fr")

        # ============================================================
        # POST : CHANGEMENT DU MOT DE PASSE
        # ============================================================

        if request.method == "POST":
            ancien = (request.form.get("ancien_mdp") or "").strip()
            nouveau = (request.form.get("nouveau_mdp") or "").strip()
            confirmation = (request.form.get("confirmation_mdp") or "").strip()

            if not ancien:
                flash("Veuillez entrer votre mot de passe actuel", "error")
                return render_template(
                    "changer_mot_de_passe.html",
                    enseignant=enseignant,
                    lang=lang
                )

            if not nouveau:
                flash("Veuillez entrer un nouveau mot de passe", "error")
                return render_template(
                    "changer_mot_de_passe.html",
                    enseignant=enseignant,
                    lang=lang
                )

            if len(nouveau) < 8:
                flash("Le mot de passe doit contenir au moins 8 caractères", "error")
                return render_template(
                    "changer_mot_de_passe.html",
                    enseignant=enseignant,
                    lang=lang
                )

            if nouveau != confirmation:
                flash("Les nouveaux mots de passe ne correspondent pas", "error")
                return render_template(
                    "changer_mot_de_passe.html",
                    enseignant=enseignant,
                    lang=lang
                )

            if not enseignant.verifier_mot_de_passe(ancien):
                flash("Mot de passe actuel incorrect", "error")
                return render_template(
                    "changer_mot_de_passe.html",
                    enseignant=enseignant,
                    lang=lang
                )

            # ============================================================
            # SAUVEGARDE SÉCURISÉE DU MOT DE PASSE
            # ============================================================

            if hasattr(enseignant, "definir_mot_de_passe"):
                enseignant.definir_mot_de_passe(nouveau)
            else:
                enseignant.mot_de_passe = generate_password_hash(nouveau)

            db.session.commit()

            flash("✅ Mot de passe mis à jour avec succès !", "success")
            return redirect(url_for("dashboard_enseignant"))

        # ============================================================
        # GET : AFFICHAGE DU FORMULAIRE
        # ============================================================

        return render_template(
            "changer_mot_de_passe.html",
            enseignant=enseignant,
            lang=lang
        )

    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur changement mot de passe enseignant: {e}")
        flash("Erreur lors du changement de mot de passe", "error")
        return redirect(url_for("dashboard_enseignant"))
    

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
    from models import Niveau, Matiere, User, Parent, ParentEleve, Enseignant, EleveMatiere, db
    from datetime import datetime, timedelta
    
    form = InscriptionEleveForm()
    
    # Remplir les choix de niveau
    niveaux = Niveau.query.all()
    form.niveau.choices = [(n.id, n.nom) for n in niveaux]
    
    if request.method == 'POST' and form.validate_on_submit():
        # Récupérer l'option choisie
        payment_option = request.form.get('payment_option', 'trial')
        plan_type = request.form.get('plan_type', 'monthly')
        
        # ✅ Récupérer les matières choisies par l'élève
        matiere_ids = request.form.getlist("matieres")
        
        # Récupérer l'email de l'enseignant tuteur (optionnel)
        teacher_email = request.form.get('teacher_email')
        teacher_tutor = None
        
        print(f"📋 Option: {payment_option}, Plan: {plan_type}, Teacher Email: {teacher_email}")
        print(f"📋 Matières sélectionnées: {matiere_ids}")
        
        # Vérifier les doublons
        if User.query.filter_by(email=form.email.data).first():
            flash("Cet email est déjà utilisé", "error")
            return render_template("inscription_eleve.html", form=form, lang=session.get('lang', 'fr'), niveaux=niveaux)
        
        if User.query.filter_by(username=form.username.data).first():
            flash("Ce nom d'utilisateur est déjà utilisé", "error")
            return render_template("inscription_eleve.html", form=form, lang=session.get('lang', 'fr'), niveaux=niveaux)
        
        # ✅ Vérifier qu'au moins une matière est choisie
        if not matiere_ids:
            flash("Veuillez choisir au moins une matière", "error")
            return render_template("inscription_eleve.html", form=form, lang=session.get('lang', 'fr'), niveaux=niveaux)
        
        # ✅ Sécuriser les IDs reçus
        try:
            matiere_ids_int = [int(mid) for mid in matiere_ids]
        except ValueError:
            flash("Sélection de matières invalide", "error")
            return render_template("inscription_eleve.html", form=form, lang=session.get('lang', 'fr'), niveaux=niveaux)
        
        # ✅ Vérifier que les matières appartiennent bien au niveau choisi
        niveau_id = form.niveau.data
        matieres_valides = Matiere.query.filter(
            Matiere.niveau_id == niveau_id,
            Matiere.id.in_(matiere_ids_int)
        ).all()
        
        if not matieres_valides:
            flash("Veuillez choisir au moins une matière valide pour ce niveau", "error")
            return render_template("inscription_eleve.html", form=form, lang=session.get('lang', 'fr'), niveaux=niveaux)
        
        # Vérifier si un enseignant est spécifié
        if teacher_email and teacher_email.strip():
            # Valider le format d'email
            import re
            email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            if not re.match(email_regex, teacher_email.strip()):
                flash("Format d'email enseignant invalide", "error")
                return render_template("inscription_eleve.html", form=form, lang=session.get('lang', 'fr'), niveaux=niveaux)
            
            # Rechercher l'enseignant dans User
            teacher_tutor = User.query.filter_by(
                email=teacher_email.strip(), 
                role="enseignant"
            ).first()
            
            # Fallback sur l'ancien modèle Enseignant si besoin
            if not teacher_tutor:
                teacher_tutor_old = Enseignant.query.filter_by(email=teacher_email.strip()).first()
                if teacher_tutor_old:
                    flash("Enseignant trouvé dans l'ancien système", "info")
                    teacher_tutor = None
            
            if not teacher_tutor:
                flash("Enseignant non trouvé avec cet email. Assurez-vous que l'enseignant est inscrit sur la plateforme.", "warning")
                teacher_tutor = None
        
        # Récupérer les données du parent
        parent_nom_complet = request.form.get('parent_nom_complet')
        parent_email = request.form.get('parent_email')
        parent_telephone = request.form.get('parent_telephone')
        parent_telephone2 = request.form.get('parent_telephone2')
        include_parent = request.form.get('include_parent', 'on') == 'on'
        
        # Création de l'élève
        try:
            eleve = User(
                username=form.username.data,
                nom_complet=form.nom_complet.data,
                email=form.email.data,
                niveau_id=niveau_id,
                role="eleve",
                telephone=form.telephone.data,
                statut="actif",
                statut_paiement="essai_gratuit",
                inscrit_par_admin=False,
                accepte_cgu=form.accepte_cgu.data,
                date_acceptation_cgu=datetime.utcnow() if form.accepte_cgu.data else None,
                langue=session.get('lang', 'fr'),
                enseignant_referent_id=teacher_tutor.id if teacher_tutor else None
            )
            
            eleve.mot_de_passe = form.mot_de_passe.data
            
            db.session.add(eleve)
            db.session.flush()  # ✅ permet d'obtenir eleve.id sans commit immédiat
            
            # ✅ Enregistrer les matières choisies par l'élève
            for matiere in matieres_valides:
                lien_matiere = EleveMatiere(
                    eleve_id=eleve.id,
                    matiere_id=matiere.id
                )
                db.session.add(lien_matiere)
                print(f"✅ Matière enregistrée pour l'élève {eleve.id}: {matiere.nom}")
            
            # Création du parent si les informations sont fournies
            if include_parent and parent_nom_complet and parent_email:
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
            
            # Option 1: Essai gratuit (3 jours)
            if payment_option == 'trial':
                if hasattr(eleve, 'activer_essai_gratuit'):
                    eleve.activer_essai_gratuit(72)
                else:
                    eleve.statut_essai = 'actif'
                    eleve.date_fin_essai = datetime.utcnow() + timedelta(hours=72)
                
                db.session.commit()
                
                session['user_id'] = eleve.id
                session['username'] = eleve.username
                session['nom_complet'] = eleve.nom_complet
                session['role'] = 'eleve'
                session['lang'] = eleve.langue if eleve.langue else 'fr'
                
                if teacher_tutor:
                    print(f"📧 Élève {eleve.nom_complet} assigné à l'enseignant {teacher_tutor.nom_complet}")
                
                lang = session.get('lang', 'fr')
                flash_message = "✅ Essai gratuit de 3 jours activé ! Profitez de la plateforme." if lang == 'fr' else "✅ 3-day free trial activated! Enjoy the platform."
                if teacher_tutor:
                    flash_message += " Votre enseignant tuteur vous a été assigné." if lang == 'fr' else " Your tutor teacher has been assigned."
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
                    
                    plan_config = {
                        'monthly': {
                            'amount': 1999,
                            'description_fr': "Forfait mensuel - Tutorat IA avec enseignant virtuel - 19.99$/mois",
                            'description_en': "Monthly plan - AI tutoring with virtual teacher - 19.99$/month",
                            'product_name_fr': "Forfait Mensuel (19.99$/mois)",
                            'product_name_en': "Monthly Plan (19.99$/month)",
                            'interval': 'month',
                        },
                        'quarterly': {
                            'amount': 4999,
                            'description_fr': "Forfait trimestriel - Tutorat IA avec enseignant virtuel - 49.99$/3 mois",
                            'description_en': "Quarterly plan - AI tutoring with virtual teacher - 49.99$/3 months",
                            'product_name_fr': "Forfait Trimestriel (49.99$/3 mois)",
                            'product_name_en': "Quarterly Plan (49.99$/3 months)",
                            'interval': 'month',
                            'interval_count': 3,
                        },
                        'annual': {
                            'amount': 14999,
                            'description_fr': "Forfait annuel - Tutorat IA avec enseignant virtuel - 149.99$/an",
                            'description_en': "Annual plan - AI tutoring with virtual teacher - 149.99$/year",
                            'product_name_fr': "Forfait Annuel (149.99$/an)",
                            'product_name_en': "Annual Plan (149.99$/year)",
                            'interval': 'year',
                        }
                    }
                    
                    plan_info = plan_config.get(plan_type, plan_config['monthly'])
                    lang = session.get('lang', 'fr')
                    
                    stripe_customer = None
                    try:
                        stripe_customer = stripe.Customer.create(
                            email=eleve.email,
                            name=eleve.nom_complet,
                            phone=eleve.telephone,
                            metadata={
                                'user_id': eleve.id,
                                'role': 'eleve',
                                'niveau_id': str(eleve.niveau_id)
                            }
                        )
                        eleve.stripe_customer_id = stripe_customer.id
                        db.session.commit()
                        print(f"✅ Customer Stripe créé: {stripe_customer.id}")
                    except Exception as e:
                        print(f"⚠️ Erreur création customer Stripe: {e}")
                    
                    checkout_session = stripe.checkout.Session.create(
                        payment_method_types=['card'],
                        line_items=[{
                            'price_data': {
                                'currency': 'cad',
                                'product_data': {
                                    'name': plan_info[f'product_name_{lang}'],
                                    'description': plan_info[f'description_{lang}'],
                                    'metadata': {
                                        'plan_type': plan_type,
                                        'lang': lang,
                                    }
                                },
                                'unit_amount': plan_info['amount'],
                                'recurring': {
                                    'interval': plan_info['interval'],
                                    'interval_count': plan_info.get('interval_count', 1)
                                }
                            },
                            'quantity': 1,
                        }],
                        mode='subscription',
                        success_url=url_for('paiement_success', _external=True) + f'?session_id={{CHECKOUT_SESSION_ID}}&eleve_id={eleve.id}&plan_type={plan_type}',
                        cancel_url=url_for('inscription_eleve', _external=True) + '?cancel=true&plan_type=' + plan_type,
                        customer=stripe_customer.id if stripe_customer else None,
                        customer_email=eleve.email if not stripe_customer else None,
                        metadata={
                            'eleve_id': eleve.id,
                            'plan_type': plan_type,
                            'lang': lang,
                            'student_name': eleve.nom_complet,
                            'student_email': eleve.email,
                            'teacher_id': str(teacher_tutor.id) if teacher_tutor else '',
                            'teacher_email': teacher_email if teacher_email else ''
                        },
                        allow_promotion_codes=True,
                        billing_address_collection='required',
                        phone_number_collection={'enabled': True},
                    )
                    
                    print(f"🔗 Redirection vers Stripe pour paiement immédiat")
                    return redirect(checkout_session.url)
                    
                except Exception as e:
                    print(f"❌ Erreur Stripe: {e}")
                    import traceback
                    traceback.print_exc()
                    
                    if hasattr(eleve, 'activer_essai_gratuit'):
                        eleve.activer_essai_gratuit(72)
                    
                    db.session.commit()
                    
                    session['user_id'] = eleve.id
                    session['username'] = eleve.username
                    session['nom_complet'] = eleve.nom_complet
                    session['role'] = 'eleve'
                    
                    session.pop('pending_plan_type', None)
                    session.pop('pending_eleve_id', None)
                    session.pop('pending_payment_option', None)
                    
                    lang = session.get('lang', 'fr')
                    flash_message = "⚠️ Paiement temporairement indisponible. Essai gratuit de 3 jours activé." if lang == 'fr' else "⚠️ Payment temporarily unavailable. 3-day free trial activated."
                    flash(flash_message, "warning")
                    
                    return redirect(url_for('dashboard_eleve'))
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Erreur création élève/parent: {e}")
            import traceback
            traceback.print_exc()
            
            error_message = "Une erreur est survenue lors de la création du compte" if session.get('lang', 'fr') == 'fr' else "An error occurred while creating your account"
            flash(error_message, "error")
    
    # Afficher un message d'annulation
    if request.args.get('cancel') == 'true':
        plan_type = request.args.get('plan_type', 'monthly')
        lang = session.get('lang', 'fr')
        
        if plan_type == 'monthly':
            cancel_message = "Paiement mensuel (19.99$/mois) annulé." if lang == 'fr' else "Monthly payment (19.99$/month) cancelled."
        elif plan_type == 'quarterly':
            cancel_message = "Paiement trimestriel (49.99$/3 mois) annulé." if lang == 'fr' else "Quarterly payment (49.99$/3 months) cancelled."
        elif plan_type == 'annual':
            cancel_message = "Paiement annuel (149.99$/an) annulé." if lang == 'fr' else "Annual payment (149.99$/year) cancelled."
        else:
            cancel_message = "Paiement annulé." if lang == 'fr' else "Payment cancelled."
        
        flash(cancel_message, "warning")
    
    lang = session.get('lang', 'fr')
    return render_template("inscription_eleve.html", form=form, lang=lang, niveaux=niveaux)


# Route pour les options d'upgrade
@app.route("/upgrade-options")
def upgrade_options():
    """Page de choix des options d'abonnement"""
    # ✅ CORRECTION : Vérifier si l'utilisateur est connecté
    if "user_id" not in session:
        flash("Veuillez vous connecter d'abord", "warning")
        return redirect(url_for("login_eleve"))
    
    # Vérifier le rôle
    if session.get("role") != "eleve":
        flash("Accès réservé aux élèves", "error")
        return redirect("/")
    
    try:
        # Récupérer l'élève
        eleve = User.query.get(session["user_id"])
        
        if not eleve:
            flash("Session invalide", "error")
            session.clear()
            return redirect(url_for("login_eleve"))
        
        # ✅ Vérifier si l'élève est en essai gratuit ou a expiré
        essai_actif = False
        essai_expire = False
        
        if hasattr(eleve, 'est_en_essai_gratuit'):
            essai_actif = eleve.est_en_essai_gratuit()
            essai_expire = eleve.essai_est_expire()
        
        # ✅ Si l'élève a déjà payé, rediriger vers le dashboard
        if eleve.statut_paiement == "paye" and eleve.a_acces_plateforme():
            flash("Votre abonnement est déjà actif !", "success")
            return redirect(url_for("dashboard_eleve"))
        
        # ✅ Si l'essai a expiré, afficher un message spécifique
        message_type = None
        if essai_expire:
            message_type = "expired"
            flash("Votre essai gratuit a expiré. Veuillez choisir un abonnement.", "warning")
        elif not eleve.a_acces_plateforme():
            message_type = "no_access"
        
        # Récupérer l'enseignant référent s'il existe
        enseignant_referent = None
        if hasattr(eleve, 'enseignant_referent_id') and eleve.enseignant_referent_id:
            enseignant_referent = User.query.filter_by(
                id=eleve.enseignant_referent_id,
                role="enseignant"
            ).first()
        
        # Calculer le temps restant d'essai
        temps_restant = None
        if essai_actif and hasattr(eleve, 'temps_restant_essai'):
            temps_restant = eleve.temps_restant_essai()
        
        # Vérifier si un paiement est en attente
        payment_pending = request.args.get('payment_pending') == 'true'
        plan_type = request.args.get('plan', 'quarterly')
        
        return render_template(
            "upgrade_options.html",
            eleve=eleve,
            essai_actif=essai_actif,
            essai_expire=essai_expire,
            enseignant_referent=enseignant_referent,
            payment_pending=payment_pending,
            plan_type=plan_type,
            temps_restant=temps_restant,
            message_type=message_type,
            lang=session.get('lang', 'fr')
        )
    except Exception as e:
        print(f"❌ Erreur upgrade_options: {e}")
        import traceback
        traceback.print_exc()
        return render_template("upgrade_options.html", eleve=None, essai_actif=False, lang=session.get('lang', 'fr'))
    
    
# Route de succès de paiement
@app.route("/paiement-success")
def paiement_success():
    """Page de succès après paiement - Optimisée pour le modèle User unifié"""
    try:
        session_id = request.args.get('session_id')
        user_id = request.args.get('user_id')
        plan_type = request.args.get('plan_type', 'quarterly')
        
        if not session_id:
            flash("Session de paiement invalide", "error")
            return redirect(url_for('inscription_eleve'))
        
        # ✅ CORRECTION 1: Vérifier la connexion avec le modèle User unifié
        if "user_id" not in session:
            flash("Vous devez être connecté", "error")
            return redirect(url_for("login_eleve"))
        
        # Vérifier le rôle
        if session.get("role") != "eleve":
            flash("Accès réservé aux élèves", "error")
            return redirect("/")
        
        # ✅ CORRECTION 2: Utiliser User directement (pas get_user_model())
        # Utiliser user_id de la session si non fourni
        if not user_id:
            user_id = session["user_id"]
        
        # Vérifier la session Stripe
        stripe_session = stripe.checkout.Session.retrieve(session_id)
        
        if stripe_session.payment_status == 'paid' or stripe_session.mode == 'subscription':
            # Activer le compte élève
            eleve = User.query.get(user_id)
            if eleve and eleve.role == "eleve":
                # ✅ VÉRIFICATION SUPPLEMENTAIRE : ne pas réactiver si déjà payé
                if eleve.statut_paiement == "paye" and eleve.date_fin_abonnement:
                    if datetime.utcnow() < eleve.date_fin_abonnement:
                        # L'utilisateur a déjà un abonnement actif
                        lang = session.get('lang', 'fr')
                        message = "✅ Votre abonnement est déjà actif !" if lang == 'fr' else "✅ Your subscription is already active!"
                        flash(message, "success")
                        return redirect(url_for('dashboard_eleve'))
                
                # Déterminer la durée de l'abonnement selon le plan
                plan_durations = {
                    'monthly': 30,     # 30 jours
                    'quarterly': 90,   # 90 jours (3 mois)
                    'annual': 365      # 365 jours (1 an)
                }
                duration_days = plan_durations.get(plan_type, 30)
                
                # ✅ CORRECTION 3: Récupérer l'enseignant depuis les metadata Stripe
                enseignant_id = stripe_session.metadata.get('enseignant_id')
                if enseignant_id and enseignant_id.strip() and enseignant_id not in ['', 'None', 'null', 'undefined']:
                    try:
                        teacher = User.query.filter_by(id=int(enseignant_id), role="enseignant").first()
                        if teacher:
                            eleve.enseignant_referent_id = teacher.id
                            print(f"✅ Enseignant assigné: {teacher.nom_complet}")
                    except (ValueError, TypeError) as e:
                        print(f"⚠️ ID enseignant invalide: {enseignant_id}, erreur: {e}")
                
                # ✅ CORRECTION 4: Utiliser la méthode marquer_comme_paye de User
                eleve.marquer_comme_paye(
                    stripe_session_id=session_id,
                    stripe_payment_intent=stripe_session.get('payment_intent')
                )
                
                # ✅ CORRECTION 5: Utiliser renouveler_abonnement avec durée spécifique
                eleve.renouveler_abonnement(duration_days)
                
                # ✅ CORRECTION 6: Mettre à jour les préférences avec le nouveau format
                if not eleve.preferences_notifications:
                    eleve.preferences_notifications = {}
                
                # Ajouter le type de plan
                eleve.preferences_notifications['plan_type'] = plan_type
                
                # ✅ Stocker les détails du plan payé
                plan_details = {
                    'plan_type': plan_type,
                    'payment_date': datetime.utcnow().isoformat(),
                    'stripe_session_id': session_id,
                    'stripe_customer_id': stripe_session.get('customer'),
                    'subscription_id': stripe_session.get('subscription'),
                    'enseignant_id': int(enseignant_id) if enseignant_id and enseignant_id.strip() and enseignant_id not in ['', 'None', 'null'] else None
                }
                
                # ✅ CORRECTION 7: Stocker dans un champ JSON dédié ou dans preferences_notifications
                eleve.preferences_notifications['paid_plan_details'] = plan_details
                
                # ✅ Stocker le customer ID Stripe
                eleve.stripe_customer_id = stripe_session.get('customer')
                
                # ✅ Marquer l'essai comme terminé
                if eleve.statut_essai == 'actif':
                    eleve.statut_essai = 'payant'
                    eleve.statut_paiement = 'paye'
                
                # ✅ CORRECTION 8: Récupérer le montant payé depuis Stripe
                amount_paid = 0
                try:
                    if stripe_session.get('invoice'):
                        invoice = stripe.Invoice.retrieve(stripe_session.invoice)
                        amount_paid = invoice.amount_paid / 100  # Convertir en dollars
                    elif stripe_session.amount_total:
                        amount_paid = stripe_session.amount_total / 100
                    else:
                        # Utiliser les prix standards comme référence
                        standard_prices = {
                            'monthly': 19.99,
                            'quarterly': 49.99,
                            'annual': 149.99
                        }
                        amount_paid = standard_prices.get(plan_type, 49.99)
                    
                    eleve.preferences_notifications['paid_amount'] = amount_paid
                    
                except Exception as invoice_error:
                    print(f"⚠️ Impossible de récupérer le montant payé: {invoice_error}")
                    # Utiliser les prix standards
                    standard_prices = {
                        'monthly': 19.99,
                        'quarterly': 49.99,
                        'annual': 149.99
                    }
                    amount_paid = standard_prices.get(plan_type, 49.99)
                    eleve.preferences_notifications['paid_amount'] = amount_paid
                
                # ✅ CORRECTION 9: Mettre à jour la date de fin d'essai si applicable
                if eleve.date_fin_essai and eleve.date_fin_essai > datetime.utcnow():
                    # L'essai n'était pas encore terminé, on le termine maintenant
                    eleve.date_fin_essai = datetime.utcnow()
                
                # ✅ Sauvegarder les changements
                db.session.commit()
                
                # ✅ CORRECTION 10: Mettre à jour la session avec les bonnes clés
                session['user_id'] = eleve.id
                session['username'] = eleve.username
                session['nom_complet'] = eleve.nom_complet
                session['role'] = eleve.role
                session['email'] = eleve.email
                session['lang'] = eleve.langue if eleve.langue else 'fr'
                
                # ✅ LOG pour suivi des paiements
                print(f"🎉 PAIEMENT SUCCÈS: {eleve.email}")
                print(f"📊 Plan: {plan_type}")
                print(f"💰 Montant: {amount_paid}$ CAD")
                print(f"📅 Durée: {duration_days} jours")
                print(f"👤 Customer ID: {stripe_session.get('customer')}")
                print(f"👨‍🏫 Enseignant ID: {enseignant_id if enseignant_id else 'Aucun'}")
                print(f"🔗 Session ID: {session_id}")
                print(f"📅 Fin abonnement: {eleve.date_fin_abonnement}")
                print(f"✅ Statut paiement: {eleve.statut_paiement}")
                print(f"✅ Statut essai: {eleve.statut_essai}")
                
                # ✅ Messages de succès selon la langue
                lang = session.get('lang', 'fr')
                success_messages = {
                    'monthly': {
                        'fr': f"✅ Paiement confirmé ! Votre abonnement mensuel est activé. {amount_paid:.2f}$ CAD / mois (≈ 0.67$/jour)",
                        'en': f"✅ Payment confirmed! Your monthly subscription is activated. {amount_paid:.2f}$ CAD / month (≈ $0.67/day)"
                    },
                    'quarterly': {
                        'fr': f"✅ Paiement confirmé ! Votre abonnement trimestriel est activé pour 3 mois. {amount_paid:.2f}$ CAD (≈ 16.66$/mois) - Vous économisez 3.33$/mois !",
                        'en': f"✅ Payment confirmed! Your quarterly subscription is activated for 3 months. {amount_paid:.2f}$ CAD (≈ $16.66/month) - You save $3.33/month!"
                    },
                    'annual': {
                        'fr': f"✅ Paiement confirmé ! Votre abonnement annuel est activé pour 1 an. {amount_paid:.2f}$ CAD (≈ 12.50$/mois) - Vous économisez 89.89$/an (37%) !",
                        'en': f"✅ Payment confirmed! Your annual subscription is activated for 1 year. {amount_paid:.2f}$ CAD (≈ $12.50/month) - You save $89.89/year (37%)!"
                    }
                }
                
                message = success_messages.get(plan_type, success_messages['quarterly']).get(lang, success_messages['quarterly']['fr'])
                flash(message, "success")
                
                # ✅ Message spécial si enseignant assigné
                if enseignant_id and enseignant_id.strip() and enseignant_id not in ['', 'None', 'null']:
                    try:
                        teacher = User.query.filter_by(id=int(enseignant_id), role="enseignant").first()
                        if teacher:
                            teacher_message = f"👨‍🏫 Votre enseignant tuteur: {teacher.nom_complet}" if lang == 'fr' else f"👨‍🏫 Your tutor teacher: {teacher.nom_complet}"
                            flash(teacher_message, "info")
                    except (ValueError, TypeError) as e:
                        print(f"⚠️ Impossible d'afficher le nom de l'enseignant: {e}")
                
                # ✅ Envoyer un email de confirmation si configuré
                try:
                    if os.environ.get('SEND_CONFIRMATION_EMAIL', 'false').lower() == 'true':
                        # Construire l'email de confirmation
                        subject_fr = f"Confirmation de votre abonnement {plan_type} - TutoratAI"
                        subject_en = f"Your {plan_type} subscription confirmation - TutoratAI"
                        subject = subject_fr if lang == 'fr' else subject_en
                        
                        # Construire le corps du message
                        body_fr = f"""
                        Bonjour {eleve.nom_complet or eleve.username},
                        
                        Votre paiement a été confirmé avec succès !
                        
                        Détails de votre abonnement :
                        • Plan : {plan_type}
                        • Montant : {amount_paid:.2f}$ CAD
                        • Durée : {duration_days} jours
                        • Statut : Actif
                        • Prochain renouvellement : {eleve.date_fin_abonnement.strftime('%d/%m/%Y') if eleve.date_fin_abonnement else 'N/A'}
                        {"• Enseignant tuteur : " + teacher.nom_complet if enseignant_id and 'teacher' in locals() and teacher else ""}
                        
                        Vous pouvez maintenant accéder à toutes les fonctionnalités de la plateforme.
                        
                        Merci pour votre confiance !
                        L'équipe TutoratAI
                        """
                        
                        body_en = f"""
                        Hello {eleve.nom_complet or eleve.username},
                        
                        Your payment has been successfully confirmed!
                        
                        Subscription details:
                        • Plan: {plan_type}
                        • Amount: {amount_paid:.2f}$ CAD
                        • Duration: {duration_days} days
                        • Status: Active
                        • Next renewal: {eleve.date_fin_abonnement.strftime('%Y-%m-%d') if eleve.date_fin_abonnement else 'N/A'}
                        {"• Tutor teacher: " + teacher.nom_complet if enseignant_id and 'teacher' in locals() and teacher else ""}
                        
                        You can now access all platform features.
                        
                        Thank you for your trust!
                        The TutoratAI Team
                        """
                        
                        body = body_fr if lang == 'fr' else body_en
                        
                        # Ici vous intégreriez votre système d'envoi d'emails
                        # send_email(eleve.email, subject, body)
                        print(f"📧 Email de confirmation prêt pour {eleve.email}")
                        
                except Exception as email_error:
                    print(f"⚠️ Erreur préparation email: {email_error}")
                
                # ✅ CORRECTION 11: Créer une commission si enseignant assigné
                if enseignant_id and enseignant_id.strip() and enseignant_id not in ['', 'None', 'null']:
                    try:
                        from models import Commission
                        from datetime import datetime
                        
                        # Calculer la commission (20% par défaut)
                        taux_commission = 20.0
                        montant_commission = (amount_paid * taux_commission) / 100
                        
                        commission = Commission(
                            enseignant_id=int(enseignant_id),
                            eleve_id=eleve.id,
                            type_abonnement=plan_type,
                            montant_total=amount_paid,
                            montant_commission=montant_commission,
                            taux_base=taux_commission,
                            date_paiement_eleve=datetime.utcnow(),
                            statut='pending',
                            statut_eleve='actif'
                        )
                        
                        db.session.add(commission)
                        db.session.commit()
                        
                        print(f"💰 Commission créée: {montant_commission}$ pour l'enseignant {enseignant_id}")
                        
                    except Exception as comm_error:
                        print(f"⚠️ Erreur création commission: {comm_error}")
                        db.session.rollback()
                
                # ✅ Rediriger vers le dashboard avec un paramètre de succès
                return redirect(url_for('dashboard_eleve') + '?payment_success=true&plan=' + plan_type)
                
            else:
                lang = session.get('lang', 'fr')
                error_msg = "Élève non trouvé" if lang == 'fr' else "Student not found"
                flash(error_msg, "error")
                return redirect(url_for('login_eleve'))
                
        else:
            lang = session.get('lang', 'fr')
            error_msg = "Paiement non confirmé" if lang == 'fr' else "Payment not confirmed"
            flash(error_msg, "warning")
            
            # ✅ Rediriger vers la page d'upgrade avec le type de plan pour réessayer
            return redirect(url_for('upgrade_options') + f'?plan={plan_type}&payment_pending=true')
            
    except stripe.error.StripeError as e:
        print(f"❌ Erreur Stripe lors de la confirmation: {e}")
        lang = session.get('lang', 'fr')
        error_msg = "Erreur de vérification du paiement" if lang == 'fr' else "Payment verification error"
        flash(error_msg, "error")
        
    except Exception as e:
        print(f"❌ Erreur confirmation paiement: {e}")
        import traceback
        traceback.print_exc()
        
        lang = session.get('lang', 'fr')
        error_msg = "Erreur lors de la confirmation du paiement" if lang == 'fr' else "Error confirming payment"
        flash(error_msg, "error")
    
    # Fallback redirection
    return redirect(url_for('upgrade_options'))

@app.route("/creer-session-paiement", methods=["POST"])
def creer_session_paiement():
    if "eleve_id" not in session:
        return jsonify({"error": "Non authentifié"}), 401
    
    eleve = User.query.get(session["eleve_id"])
    if not eleve or eleve.role != "eleve":
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        # Récupérer le type de plan depuis le formulaire
        data = request.get_json()
        plan_type = data.get('plan_type', 'quarterly')  # monthly, quarterly, annual
        
        # ✅ CONFIGURATION DES PLANS OPTIMISÉE (NOUVEAUX PRIX MIS À JOUR)
        plan_config = {
            'monthly': {
                'amount': 1999,  # 19.99 CAD (NOUVEAU PRIX OPTIMISÉ)
                'description_fr': "Forfait mensuel - Tutorat IA avec enseignant virtuel - 19.99$/mois",
                'description_en': "Monthly plan - AI tutoring with virtual teacher - 19.99$/month",
                'product_name_fr': "Forfait Mensuel (19.99$/mois)",
                'product_name_en': "Monthly Plan (19.99$/month)",
                'interval': 'month',
                'features_fr': "• Enseignant virtuel 24/7 • Questionnement socratique • Toutes matières • Suivi de progression",
                'features_en': "• Virtual teacher 24/7 • Socratic questioning • All subjects • Progress tracking",
                'monthly_effective': 19.99,
                'savings_percentage': 0,
                'savings_amount': 0,
                'price_per_day': 0.67  # 19.99 / 30
            },
            'quarterly': {
                'amount': 4999,  # 49.99 CAD (NOUVEAU PRIX OPTIMISÉ)
                'description_fr': "Forfait trimestriel - Tutorat IA avec enseignant virtuel - 49.99$/3 mois",
                'description_en': "Quarterly plan - AI tutoring with virtual teacher - 49.99$/3 months",
                'product_name_fr': "Forfait Trimestriel (49.99$/3 mois)",
                'product_name_en': "Quarterly Plan (49.99$/3 months)",
                'interval': 'month',
                'interval_count': 3,
                'features_fr': "• Toutes fonctionnalités mensuelles • Support prioritaire • Revues trimestrielles • Feuille de route personnalisée",
                'features_en': "• All monthly features • Priority support • Quarterly reviews • Personalized roadmap",
                'monthly_effective': 16.66,
                'savings_percentage': 17,
                'savings_amount': 3.33,  # 19.99 - 16.66 = 3.33$/mois
                'price_per_day': 0.56  # 16.66 / 30
            },
            'annual': {
                'amount': 14999,  # 149.99 CAD (NOUVEAU PRIX OPTIMISÉ)
                'description_fr': "Forfait annuel - Tutorat IA avec enseignant virtuel - 149.99$/an",
                'description_en': "Annual plan - AI tutoring with virtual teacher - 149.99$/year",
                'product_name_fr': "Forfait Annuel (149.99$/an)",
                'product_name_en': "Annual Plan (149.99$/year)",
                'interval': 'year',
                'features_fr': "• Toutes fonctionnalités trimestrielles • Support premium • Rapports détaillés • Accès continu 12 mois",
                'features_en': "• All quarterly features • Premium support • Detailed reports • 12 months continuous access",
                'monthly_effective': 12.50,
                'savings_percentage': 37,
                'savings_amount': 89.89,  # (19.99*12) - 149.99 = 89.89$/an
                'price_per_day': 0.42  # 12.50 / 30
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
        features = plan_info[f'features_{lang}'] if f'features_{lang}' in plan_info else plan_info['features_fr']
        
        # Configurer le recurring (spécial pour quarterly)
        recurring_config = {
            'interval': plan_info['interval'],
            'interval_count': plan_info.get('interval_count', 1)
        }
        
        # ✅ ACTIVER L'ESSAI GRATUIT SI PREMIÈRE INSCRIPTION (3 jours)
        # Vérifier si l'utilisateur n'a jamais payé
        if eleve.statut_paiement == "non_paye" and not eleve.date_fin_essai:
            eleve.activer_essai_gratuit(72)  # 3 jours gratuit
            db.session.commit()
            print(f"✅ Essai gratuit de 3 jours activé pour {eleve.email}")
        
        # Calcul du prix par jour pour l'affichage (mise à jour avec les nouveaux prix)
        price_per_day = plan_info['price_per_day']
        
        # Créer un message personnalisé selon le plan (mis à jour avec nouveaux prix)
        custom_message = ""
        if plan_type == 'monthly':
            custom_message = f"{'Moins de 0.67$ par jour !' if lang == 'fr' else 'Less than $0.67 per day!'}"
        elif plan_type == 'quarterly':
            custom_message = f"{'Économisez 3.33$/mois !' if lang == 'fr' else 'Save $3.33/month!'}"
        elif plan_type == 'annual':
            custom_message = f"{'Économisez 89.89$/an !' if lang == 'fr' else 'Save $89.89/year!'}"
        
        # Créer une session de paiement Stripe optimisée
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
                            'lang': lang,
                            'monthly_price': f"{plan_info['monthly_effective']:.2f}",
                            'savings_percentage': plan_info['savings_percentage'],
                            'features': features[:100]  # Limité à 100 caractères
                        },
                        'images': [
                            'https://advanceteach.com/static/images/logo.png'
                        ] if os.path.exists('static/images/logo.png') else []
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
                    'lang': lang,
                    'student_name': eleve.nom_complet,
                    'student_email': eleve.email,
                    'monthly_effective_price': f"{plan_info['monthly_effective']:.2f}",
                    'savings_amount': f"{plan_info['savings_amount']:.2f}",
                    'savings_percentage': plan_info['savings_percentage'],
                    'price_per_day': f"{price_per_day:.2f}"
                },
                'description': description,
                'trial_period_days': 0  # Pas d'essai supplémentaire
            },
            success_url=url_for('paiement_success', _external=True) + f'?session_id={{CHECKOUT_SESSION_ID}}&eleve_id={eleve.id}&plan_type={plan_type}',
            cancel_url=url_for('upgrade_options', _external=True) + f'?cancel=true&plan_type={plan_type}',
            customer_email=eleve.email,
            metadata={
                'eleve_id': eleve.id,
                'plan_type': plan_type,
                'lang': lang,
                'type': f'abonnement_{plan_type}',
                'student_name': eleve.nom_complet,
                'student_email': eleve.email,
                'monthly_price': f"{plan_info['monthly_effective']:.2f}",
                'savings_percentage': plan_info['savings_percentage']
            },
            allow_promotion_codes=True,
            billing_address_collection='required',
            phone_number_collection={'enabled': True},
            custom_text={
                'submit': {
                    'message': custom_message
                },
                'terms_of_service_acceptance': {
                    'message': f"{'✅ En vous abonnant, vous acceptez nos conditions générales.' if lang == 'fr' else '✅ By subscribing, you accept our terms and conditions.'}"
                }
            },
            discounts=[{
                'coupon': 'WELCOME10'  # Coupon de bienvenue optionnel
            }] if os.environ.get('STRIPE_WELCOME_COUPON') else [],
            customer_creation='always',  # Toujours créer un client
            invoice_creation={'enabled': True},  # Créer des factures
            payment_intent_data={
                'metadata': {
                    'eleve_id': eleve.id,
                    'plan_type': plan_type
                }
            },
            # Expire la session après 30 minutes
            expires_at=int(datetime.now().timestamp()) + 1800
        )
        
        # Log pour suivi
        print(f"🎯 Session Stripe créée pour {eleve.email}")
        print(f"📊 Plan: {plan_type}, Montant: {plan_info['amount']/100:.2f}$ CAD")
        print(f"💰 Prix mensuel effectif: {plan_info['monthly_effective']:.2f}$/mois")
        print(f"🎁 Économies: {plan_info['savings_percentage']}% ({plan_info['savings_amount']:.2f}$)")
        
        # Retourner l'URL de la session Stripe avec toutes les infos
        return jsonify({
            "session_id": checkout_session.id,
            "session_url": checkout_session.url,
            "plan_type": plan_type,
            "amount": plan_info['amount'],
            "amount_display": f"${plan_info['amount']/100:.2f}",
            "currency": "CAD",
            "monthly_effective": plan_info['monthly_effective'],
            "savings_percentage": plan_info['savings_percentage'],
            "savings_amount": plan_info['savings_amount'],
            "price_per_day": price_per_day,
            "essai_actif": eleve.est_en_essai_gratuit(),
            "heures_restantes_essai": eleve.heures_restantes_essai() if hasattr(eleve, 'heures_restantes_essai') and callable(getattr(eleve, 'heures_restantes_essai')) else 0,
            "student": {
                "name": eleve.nom_complet,
                "email": eleve.email,
                "lang": lang,
                "enseignant_id": eleve.enseignant_referent_id if hasattr(eleve, 'enseignant_id') else None
            }
        })
        
    except Exception as e:
        print(f"❌ Erreur création session Stripe: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/paiement-direct")
def paiement_direct():
    """Route de paiement direct pour les élèves - Corrigée"""
    # Vérifier si l'utilisateur est connecté
    if "user_id" not in session:
        return redirect(url_for("login_eleve"))
    
    # Vérifier si c'est un élève
    if session.get("role") != "eleve":
        flash("Accès réservé aux élèves", "error")
        return redirect("/")
    
    try:
        # Récupérer l'élève
        eleve = User.query.get(session["user_id"])
        if not eleve or eleve.role != "eleve":
            flash("Élève non trouvé", "error")
            return redirect(url_for("login_eleve"))
        
        plan_type = request.args.get("type", "quarterly")
        amount_param = request.args.get("amount", None)
        
        print(f"📋 Paiement direct - Plan demandé: {plan_type}, Montant: {amount_param}")
        
        # Vérifier si le type de plan est valide
        valid_plans = ['monthly', 'quarterly', 'annual']
        if plan_type not in valid_plans:
            plan_type = 'quarterly'
        
        try:
            # Configuration des plans
            plan_config = {
                'monthly': {
                    'amount': 1999,
                    'description_fr': "Forfait mensuel - Tutorat IA avec enseignant virtuel - 19.99$/mois",
                    'description_en': "Monthly plan - AI tutoring with virtual teacher - 19.99$/month",
                    'product_name_fr': "Forfait Mensuel (19.99$/mois)",
                    'product_name_en': "Monthly Plan (19.99$/month)",
                    'interval': 'month',
                    'monthly_effective': 19.99,
                    'savings_percentage': 0,
                    'price_per_day': 0.67
                },
                'quarterly': {
                    'amount': 4999,
                    'description_fr': "Forfait trimestriel - Tutorat IA avec enseignant virtuel - 49.99$/3 mois",
                    'description_en': "Quarterly plan - AI tutoring with virtual teacher - 49.99$/3 months",
                    'product_name_fr': "Forfait Trimestriel (49.99$/3 mois)",
                    'product_name_en': "Quarterly Plan (49.99$/3 months)",
                    'interval': 'month',
                    'interval_count': 3,
                    'monthly_effective': 16.66,
                    'savings_percentage': 17,
                    'price_per_day': 0.56
                },
                'annual': {
                    'amount': 14999,
                    'description_fr': "Forfait annuel - Tutorat IA avec enseignant virtuel - 149.99$/an",
                    'description_en': "Annual plan - AI tutoring with virtual teacher - 149.99$/year",
                    'product_name_fr': "Forfait Annuel (149.99$/an)",
                    'product_name_en': "Annual Plan (149.99$/year)",
                    'interval': 'year',
                    'monthly_effective': 12.50,
                    'savings_percentage': 37,
                    'price_per_day': 0.42
                }
            }
            
            if amount_param:
                try:
                    custom_amount = int(float(amount_param) * 100)
                    plan_config[plan_type]['amount'] = custom_amount
                except ValueError:
                    print(f"⚠️ Montant invalide: {amount_param}")
            
            plan_info = plan_config[plan_type]
            lang = session.get("lang", "fr")
            
            # ✅ CORRECTION : Récupérer le customer Stripe existant ou en créer un
            customer = None
            if eleve.stripe_customer_id:
                try:
                    customer = stripe.Customer.retrieve(eleve.stripe_customer_id)
                    print(f"✅ Customer Stripe existant trouvé: {customer.id}")
                except stripe.error.StripeError:
                    print(f"⚠️ Customer Stripe non trouvé, création d'un nouveau")
            
            # Créer ou récupérer l'enseignant référent
            teacher_info = {}
            if hasattr(eleve, 'enseignant_referent_id') and eleve.enseignant_referent_id:
                teacher = User.query.filter_by(
                    id=eleve.enseignant_referent_id,
                    role="enseignant"
                ).first()
                if teacher:
                    teacher_info = {
                        'teacher_id': teacher.id,
                        'teacher_name': teacher.nom_complet,
                        'teacher_email': teacher.email
                    }
            
            # ✅ CORRECTION IMPORTANTE : Configuration de la session Stripe
            checkout_session_params = {
                'payment_method_types': ['card'],
                'line_items': [{
                    'price_data': {
                        'currency': 'cad',
                        'product_data': {
                            'name': plan_info[f'product_name_{lang}'] if f'product_name_{lang}' in plan_info else plan_info['product_name_fr'],
                            'description': plan_info[f'description_{lang}'] if f'description_{lang}' in plan_info else plan_info['description_fr'],
                            'metadata': {
                                'plan_type': plan_type,
                                'lang': lang
                            }
                        },
                        'unit_amount': plan_info['amount'],
                        'recurring': {
                            'interval': plan_info['interval'],
                            'interval_count': plan_info.get('interval_count', 1)
                        }
                    },
                    'quantity': 1,
                }],
                'mode': 'subscription',
                'success_url': url_for('paiement_success', _external=True) + f'?session_id={{CHECKOUT_SESSION_ID}}&eleve_id={eleve.id}&plan_type={plan_type}',
                'cancel_url': url_for('upgrade_options', _external=True) + f'?cancel=true&plan_type={plan_type}',
                'metadata': {
                    'eleve_id': eleve.id,
                    'plan_type': plan_type,
                    'lang': lang,
                    'student_name': eleve.nom_complet,
                    'student_email': eleve.email,
                    'enseignant_id': str(teacher_info.get('teacher_id', '')),
                    'enseignant_email': teacher_info.get('teacher_email', '')
                }
            }
            
            # ✅ AJOUTER LE CUSTOMER SI EXISTANT
            if customer:
                checkout_session_params['customer'] = customer.id
            else:
                checkout_session_params['customer_email'] = eleve.email
            
            # ✅ Créer la session Stripe
            checkout_session = stripe.checkout.Session.create(**checkout_session_params)
            
            # ✅ Mettre à jour l'élève avec l'ID de session Stripe
            eleve.stripe_session_id = checkout_session.id
            db.session.commit()
            
            print(f"✅ Session Stripe créée: {checkout_session.id}")
            print(f"🔗 Redirection vers: {checkout_session.url}")
            
            return redirect(checkout_session.url)
            
        except stripe.error.StripeError as e:
            print(f"❌ Erreur Stripe: {str(e)}")
            flash(f"Erreur de paiement: {str(e)}", "error")
            return redirect(url_for('upgrade_options'))
            
    except Exception as e:
        print(f"❌ Erreur paiement direct: {e}")
        flash("Erreur lors de la création du paiement", "error")
        return redirect(url_for('upgrade_options'))
    

@app.route("/stripe-webhook", methods=["POST"])
def stripe_webhook():
    """Webhook Stripe pour gérer les événements de paiement - Adapté au nouveau système User"""
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature')
    endpoint_secret = os.environ.get('STRIPE_WEBHOOK_SECRET')

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except stripe.error.SignatureVerificationError as e:
        return jsonify({'error': str(e)}), 400
    
    # Gérer l'événement checkout.session.completed
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        
        try:
            UserModel = get_user_model()
            
            eleve_id = session['metadata'].get('eleve_id')
            plan_type = session['metadata'].get('plan_type', 'quarterly')
            
            if eleve_id:
                eleve = UserModel.query.get(eleve_id)
                if eleve and eleve.role == "eleve":
                    # Déterminer la durée avec les nouveaux plans
                    plan_durations = {
                        'monthly': 30,     # 30 jours
                        'quarterly': 90,   # 90 jours (3 mois)
                        'annual': 365      # 365 jours (1 an)
                    }
                    duration_days = plan_durations.get(plan_type, 30)
                    
                    # Récupérer les informations de l'enseignant si présentes
                    enseignant_id = session['metadata'].get('enseignant_id')
                    if enseignant_id and enseignant_id != '' and enseignant_id != 'None' and enseignant_id != 'null':
                        # Vérifier que l'enseignant existe (dans la table User maintenant)
                        teacher = UserModel.query.filter_by(id=enseignant_id, role="enseignant").first()
                        if teacher and hasattr(eleve, 'enseignant_referent_id'):
                            eleve.enseignant_referent_id = teacher.id
                    
                    # Utiliser les méthodes existantes si disponibles
                    if hasattr(eleve, 'marquer_comme_paye'):
                        eleve.marquer_comme_paye(
                            stripe_session_id=session['id'],
                            stripe_payment_intent=session.get('payment_intent')
                        )
                    
                    # Renouveler l'abonnement si la méthode existe
                    if hasattr(eleve, 'renouveler_abonnement'):
                        eleve.renouveler_abonnement(duration_days)
                    else:
                        # Fallback: gérer l'abonnement manuellement
                        from datetime import datetime, timedelta
                        if hasattr(eleve, 'date_fin_abonnement'):
                            if eleve.date_fin_abonnement and datetime.utcnow() < eleve.date_fin_abonnement:
                                # Ajouter à la date de fin existante
                                eleve.date_fin_abonnement = eleve.date_fin_abonnement + timedelta(days=duration_days)
                            else:
                                # Nouvel abonnement
                                eleve.date_fin_abonnement = datetime.utcnow() + timedelta(days=duration_days)
                    
                    # Stocker le type de plan dans les préférences
                    if not hasattr(eleve, 'preferences_notifications'):
                        eleve.preferences_notifications = {}
                    else:
                        eleve.preferences_notifications = eleve.preferences_notifications or {}
                    
                    eleve.preferences_notifications['plan_type'] = plan_type
                    
                    # Stocker les détails du paiement
                    eleve.preferences_notifications['paid_plan_details'] = {
                        'plan_type': plan_type,
                        'payment_date': datetime.utcnow().isoformat(),
                        'stripe_session_id': session['id'],
                        'stripe_customer_id': session.get('customer'),
                        'subscription_id': session.get('subscription'),
                        'enseignant_id': enseignant_id if enseignant_id else None,
                        'webhook_processed': True,
                        'webhook_timestamp': datetime.utcnow().isoformat()
                    }
                    
                    # Stocker le customer ID Stripe si l'attribut existe
                    if hasattr(eleve, 'stripe_customer_id'):
                        eleve.stripe_customer_id = session.get('customer')
                    
                    # Récupérer le montant payé
                    try:
                        if session.get('invoice'):
                            invoice = stripe.Invoice.retrieve(session.invoice)
                            amount_paid = invoice.amount_paid / 100
                        else:
                            amount_paid = session.amount_total / 100 if session.amount_total else 0
                        
                        eleve.preferences_notifications['paid_amount'] = amount_paid
                        print(f"💰 Montant payé récupéré: {amount_paid}$ CAD")
                    except Exception as invoice_error:
                        print(f"⚠️ Impossible de récupérer le montant payé: {invoice_error}")
                        # Utiliser les prix standards comme référence
                        standard_prices = {
                            'monthly': 19.99,
                            'quarterly': 49.99,
                            'annual': 149.99
                        }
                        amount_paid = standard_prices.get(plan_type, 49.99)
                        eleve.preferences_notifications['paid_amount'] = amount_paid
                    
                    # Marquer l'essai comme terminé si applicable
                    if hasattr(eleve, 'statut_essai') and hasattr(eleve, 'statut_essai') == 'actif':
                        eleve.statut_essai = 'payant'
                        if hasattr(eleve, 'statut_paiement'):
                            eleve.statut_paiement = 'paye'
                    
                    db.session.commit()
                    print(f"✅ Webhook: Élève {eleve_id} ({eleve.email}) abonné avec succès au plan {plan_type} ({amount_paid}$ CAD)")
                    
                    # Log détaillé
                    print(f"📊 Plan: {plan_type}")
                    print(f"💰 Montant: {amount_paid}$ CAD")
                    print(f"📅 Durée: {duration_days} jours")
                    print(f"📅 Date fin: {eleve.date_fin_abonnement if hasattr(eleve, 'date_fin_abonnement') else 'Non défini'}")
                    print(f"👤 Customer ID: {session.get('customer')}")
                    print(f"👨‍🏫 Enseignant ID: {enseignant_id if enseignant_id else 'Aucun'}")
                    print(f"📝 Préférences: {eleve.preferences_notifications.get('plan_type', 'Non défini')}")
                    
                else:
                    print(f"⚠️ Webhook: Élève non trouvé ou n'est pas un élève (ID: {eleve_id})")
        
        except Exception as e:
            print(f"❌ Erreur webhook checkout.session.completed: {e}")
            import traceback
            traceback.print_exc()
    
    # Gérer l'événement invoice.payment_succeeded
    elif event['type'] == 'invoice.payment_succeeded':
        invoice = event['data']['object']
        
        try:
            UserModel = get_user_model()
            
            customer_id = invoice.get('customer')
            subscription_id = invoice.get('subscription')
            
            if customer_id:
                # Trouver l'élève par customer_id
                eleve = UserModel.query.filter_by(
                    stripe_customer_id=customer_id,
                    role="eleve"
                ).first()
                
                if eleve and subscription_id:
                    # Vérifier si l'abonnement est encore actif
                    subscription = stripe.Subscription.retrieve(subscription_id)
                    
                    if subscription.status in ['active', 'trialing']:
                        # Calculer la nouvelle date de fin
                        current_period_end = subscription.current_period_end
                        new_end_date = datetime.fromtimestamp(current_period_end)
                        
                        # Mettre à jour la date de fin d'abonnement
                        if hasattr(eleve, 'date_fin_abonnement'):
                            eleve.date_fin_abonnement = new_end_date
                        
                        if hasattr(eleve, 'date_dernier_paiement'):
                            eleve.date_dernier_paiement = datetime.utcnow()
                        
                        # Mettre à jour les préférences
                        if not hasattr(eleve, 'preferences_notifications'):
                            eleve.preferences_notifications = {}
                        
                        # Ajouter un log de renouvellement
                        renewals = eleve.preferences_notifications.get('subscription_renewals', [])
                        renewals.append({
                            'timestamp': datetime.utcnow().isoformat(),
                            'invoice_id': invoice.get('id'),
                            'amount': invoice.get('amount_paid', 0) / 100,
                            'subscription_id': subscription_id,
                            'period_end': new_end_date.isoformat()
                        })
                        eleve.preferences_notifications['subscription_renewals'] = renewals
                        
                        db.session.commit()
                        print(f"✅ Webhook: Renouvellement abonnement pour {eleve.email} jusqu'au {new_end_date}")
        
        except Exception as e:
            print(f"❌ Erreur webhook invoice.payment_succeeded: {e}")
            import traceback
            traceback.print_exc()
    
    # Gérer l'événement customer.subscription.deleted (abonnement annulé)
    elif event['type'] == 'customer.subscription.deleted':
        subscription = event['data']['object']
        
        try:
            UserModel = get_user_model()
            
            customer_id = subscription.get('customer')
            
            if customer_id:
                # Trouver l'élève par customer_id
                eleve = UserModel.query.filter_by(
                    stripe_customer_id=customer_id,
                    role="eleve"
                ).first()
                
                if eleve:
                    # Marquer comme non payé (mais garder la date de fin)
                    if hasattr(eleve, 'statut_paiement'):
                        eleve.statut_paiement = 'expire'
                    
                    # Mettre à jour les préférences
                    if not hasattr(eleve, 'preferences_notifications'):
                        eleve.preferences_notifications = {}
                    
                    eleve.preferences_notifications['subscription_cancelled'] = {
                        'timestamp': datetime.utcnow().isoformat(),
                        'subscription_id': subscription.get('id'),
                        'cancellation_date': subscription.get('canceled_at'),
                        'cancellation_reason': subscription.get('cancellation_details', {}).get('reason', 'unknown')
                    }
                    
                    db.session.commit()
                    print(f"⚠️ Webhook: Abonnement annulé pour {eleve.email}")
        
        except Exception as e:
            print(f"❌ Erreur webhook customer.subscription.deleted: {e}")
            import traceback
            traceback.print_exc()
    
    # Gérer l'événement checkout.session.expired (session expirée)
    elif event['type'] == 'checkout.session.expired':
        session = event['data']['object']
        print(f"ℹ️ Webhook: Session checkout expirée: {session.get('id')}")
        # Pas d'action nécessaire, juste pour le logging
    
    return jsonify({'status': 'success', 'processed': True})


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
                role='eleve',  # ✅ CORRECTION ICI : 'eleve' SANS accent !
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
    """Route pour changer le mot de passe enseignant"""

    # ============================================================
    # AUTHENTIFICATION ENSEIGNANT
    # Système actuel : session["user_id"] + session["role"]
    # ============================================================

    if "user_id" not in session:
        flash("Veuillez vous connecter", "error")
        return redirect(url_for("login_enseignant"))

    if session.get("role") != "enseignant":
        flash("Accès réservé aux enseignants", "error")
        return redirect(url_for("login_enseignant"))

    try:
        UserModel = get_user_model()

        enseignant = (
            UserModel.query
            .filter_by(
                id=session["user_id"],
                role="enseignant"
            )
            .first()
        )

        if not enseignant:
            session.clear()
            flash("Session enseignant invalide. Veuillez vous reconnecter.", "error")
            return redirect(url_for("login_enseignant"))

        lang = session.get("lang", "fr")

        if request.method == "POST":
            ancien = (request.form.get("ancien_mdp") or "").strip()
            nouveau = (request.form.get("nouveau_mdp") or "").strip()
            confirmation = (request.form.get("confirmation_mdp") or "").strip()

            if not ancien:
                flash("Veuillez entrer votre mot de passe actuel.", "error")

            elif not nouveau:
                flash("Veuillez entrer un nouveau mot de passe.", "error")

            elif len(nouveau) < 8:
                flash("Le mot de passe doit contenir au moins 8 caractères.", "error")

            elif nouveau != confirmation:
                flash("Les nouveaux mots de passe ne correspondent pas.", "error")

            elif not enseignant.verifier_mot_de_passe(ancien):
                flash("Mot de passe actuel incorrect.", "error")

            else:
                if hasattr(enseignant, "definir_mot_de_passe"):
                    enseignant.definir_mot_de_passe(nouveau)
                else:
                    enseignant.mot_de_passe = generate_password_hash(nouveau)

                db.session.commit()

                flash("✅ Mot de passe mis à jour avec succès.", "success")
                return redirect(url_for("dashboard_enseignant"))

        return render_template(
            "changer_mot_de_passe.html",
            enseignant=enseignant,
            lang=lang
        )

    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur changement mot de passe: {e}")
        flash("Erreur lors du changement de mot de passe.", "error")
        return redirect(url_for("dashboard_enseignant"))

@app.route("/enseignant/modifier-profil", methods=["GET", "POST"])
def modifier_profil_enseignant():
    """Modifier le profil enseignant"""

    # ============================================================
    # AUTHENTIFICATION ENSEIGNANT
    # Système actuel : session["user_id"] + session["role"]
    # ============================================================

    if "user_id" not in session:
        flash("Veuillez vous connecter", "error")
        return redirect(url_for("login_enseignant"))

    if session.get("role") != "enseignant":
        flash("Accès réservé aux enseignants", "error")
        return redirect(url_for("login_enseignant"))

    try:
        UserModel = get_user_model()

        enseignant = (
            UserModel.query
            .filter_by(
                id=session["user_id"],
                role="enseignant"
            )
            .first()
        )

        if not enseignant:
            session.clear()
            flash("Session enseignant invalide. Veuillez vous reconnecter.", "error")
            return redirect(url_for("login_enseignant"))

        lang = session.get("lang", "fr")

        # ============================================================
        # POST : MISE À JOUR DU PROFIL
        # ============================================================

        if request.method == "POST":
            nom = (request.form.get("nom") or "").strip()
            email = (request.form.get("email") or "").strip().lower()
            telephone = (request.form.get("telephone") or "").strip()

            if not nom or not email:
                flash("Le nom et l'email sont obligatoires", "error")
                return render_template(
                    "modifier_profil_enseignant.html",
                    enseignant=enseignant,
                    lang=lang
                )

            # Vérifier si l'email est déjà utilisé par un autre utilisateur
            existant = (
                UserModel.query
                .filter(
                    UserModel.email == email,
                    UserModel.id != enseignant.id
                )
                .first()
            )

            if existant:
                flash("Cet email est déjà utilisé par un autre compte", "error")
                return render_template(
                    "modifier_profil_enseignant.html",
                    enseignant=enseignant,
                    lang=lang
                )

            enseignant.nom_complet = nom
            enseignant.email = email

            if hasattr(enseignant, "telephone"):
                enseignant.telephone = telephone if telephone else None

            db.session.commit()

            # Mettre à jour la session si ton dashboard affiche ces infos
            session["username"] = enseignant.username
            session["role"] = enseignant.role
            session.modified = True

            flash("✅ Profil mis à jour avec succès", "success")
            return redirect(url_for("dashboard_enseignant"))

        # ============================================================
        # GET : AFFICHAGE DU FORMULAIRE
        # ============================================================

        return render_template(
            "modifier_profil_enseignant.html",
            enseignant=enseignant,
            lang=lang
        )

    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur modification profil enseignant: {e}")
        flash("Erreur lors de la modification du profil", "error")
        return redirect(url_for("dashboard_enseignant"))


@app.route("/enseignant/creer-contenu")
def creer_contenu():
    """Route pour créer du contenu - Adaptée au nouveau système User"""
    # Vérifier si l'utilisateur est connecté
    if "user_id" not in session:
        return redirect(url_for("login"))
    
    # Vérifier si c'est un enseignant
    if session.get("role") != "enseignant":
        flash("Accès réservé aux enseignants", "error")
        return redirect("/")
    
    UserModel = get_user_model()
    enseignant = UserModel.query.get(session["user_id"])
    
    if not enseignant or enseignant.role != "enseignant":
        flash("Enseignant non trouvé", "error")
        return redirect(url_for("login"))
    
    lang = session.get("lang", "fr")
    
    # Récupérer les matières de l'enseignant
    matieres = []
    if hasattr(enseignant, 'matieres') and enseignant.matieres:
        matieres = [m.strip() for m in enseignant.matieres.split(',')]
    
    return render_template(
        "enseignant_creer_contenu.html",
        enseignant=enseignant,
        matieres=matieres,
        lang=lang
    )

@app.route("/enseignant/eleves")
def enseignant_eleves():
    """Route pour voir les élèves assignés - Adaptée au nouveau système User"""
    # Vérifier si l'utilisateur est connecté
    if "user_id" not in session:
        return redirect(url_for("login"))
    
    # Vérifier si c'est un enseignant
    if session.get("role") != "enseignant":
        flash("Accès réservé aux enseignants", "error")
        return redirect("/")
    
    UserModel = get_user_model()
    enseignant = UserModel.query.get(session["user_id"])
    
    if not enseignant or enseignant.role != "enseignant":
        flash("Enseignant non trouvé", "error")
        return redirect(url_for("login"))
    
    lang = session.get("lang", "fr")
    
    # Récupérer les élèves assignés à cet enseignant
    # Utiliser enseignant_referent_id (nouveau système)
    eleves = UserModel.query.filter_by(
        enseignant_referent_id=enseignant.id,
        role="eleve"
    ).all()
    
    # Pour la compatibilité, vérifier aussi l'ancien champ enseignant_id
    if not eleves and hasattr(UserModel, 'enseignant_id'):
        eleves = UserModel.query.filter_by(
            enseignant_id=enseignant.id,
            role="eleve"
        ).all()
    
    # Calculer les statistiques pour chaque élève
    stats_eleves = []
    for eleve in eleves:
        # Utiliser la table StudentResponse si elle existe
        try:
            from models import StudentResponse
            reponses = StudentResponse.query.filter_by(user_id=eleve.id).all()
            total_reponses = len(reponses)
            moyenne = round(sum(r.etoiles or 0 for r in reponses) / total_reponses, 2) if total_reponses else 0
        except:
            # Fallback si la table n'existe pas
            total_reponses = 0
            moyenne = 0
        
        # Récupérer le niveau de l'élève si l'attribut existe
        niveau_nom = "Non défini"
        if hasattr(eleve, 'niveau_id') and eleve.niveau_id:
            from models import Niveau
            niveau_obj = Niveau.query.get(eleve.niveau_id)
            if niveau_obj:
                niveau_nom = niveau_obj.nom
        elif hasattr(eleve, 'niveau') and eleve.niveau:
            niveau_nom = eleve.niveau.nom if hasattr(eleve.niveau, 'nom') else str(eleve.niveau)
        
        # Vérifier le statut d'abonnement
        statut_abonnement = "Inactif"
        if hasattr(eleve, 'statut_paiement'):
            statut_abonnement = eleve.statut_paiement.capitalize() if eleve.statut_paiement else "Inactif"
        
        stats_eleves.append({
            'eleve': eleve,
            'total_exercices': total_reponses,
            'moyenne_etoiles': moyenne,
            'niveau': niveau_nom,
            'statut_abonnement': statut_abonnement,
            'date_inscription': eleve.date_inscription.strftime('%d/%m/%Y') if hasattr(eleve, 'date_inscription') and eleve.date_inscription else "N/A"
        })
    
    return render_template(
        "enseignant_eleves.html",
        enseignant=enseignant,
        stats_eleves=stats_eleves,
        total_eleves=len(eleves),
        lang=lang
    )

@app.route("/assign-students-to-teachers")
@admin_required
def assign_students_to_teachers():
    """Assigner des élèves aux enseignants"""
    try:
        from models import User, db
        import random
        
        result = "<h1>Assignation des élèves aux enseignants</h1>"
        
        # 1. Récupérer tous les enseignants
        teachers = User.query.filter_by(role='enseignant').all()
        
        if not teachers:
            return "<p style='color: red;'>Aucun enseignant trouvé!</p>"
        
        result += f"<p>{len(teachers)} enseignants disponibles</p>"
        
        # 2. Récupérer tous les élèves sans enseignant
        students_without_teacher = User.query.filter(
            (User.role.in_(['eleve', 'élève'])),
            (User.enseignant_referent_id.is_(None))
        ).all()
        
        students_with_teacher = User.query.filter(
            (User.role.in_(['eleve', 'élève'])),
            (User.enseignant_referent_id.isnot(None))
        ).all()
        
        result += f"<p>Élèves sans enseignant: {len(students_without_teacher)}</p>"
        result += f"<p>Élèves avec enseignant: {len(students_with_teacher)}</p>"
        
        # 3. Assigner les élèves sans enseignant
        assignments = []
        
        if students_without_teacher:
            # Méthode 1: Assigner aléatoirement
            for student in students_without_teacher:
                teacher = random.choice(teachers)
                student.enseignant_referent_id = teacher.id
                assignments.append(f"{student.nom_complet} → {teacher.nom_complet}")
            
            db.session.commit()
            
            result += "<h2 style='color: green;'>Assignations effectuées:</h2>"
            result += "<ul>"
            for assignment in assignments:
                result += f"<li>{assignment}</li>"
            result += "</ul>"
        else:
            result += "<p style='color: orange;'>Tous les élèves ont déjà un enseignant référent</p>"
        
        # 4. Afficher la distribution finale
        result += "<h2>Distribution finale:</h2>"
        
        # Requête pour voir combien d'élèves par enseignant
        distribution = db.session.execute("""
            SELECT 
                u.nom_complet as enseignant,
                COUNT(e.id) as nombre_eleves,
                STRING_AGG(e.nom_complet, ', ' ORDER BY e.nom_complet) as liste_eleves
            FROM users u
            LEFT JOIN users e ON e.enseignant_referent_id = u.id AND e.role IN ('eleve', 'élève')
            WHERE u.role = 'enseignant'
            GROUP BY u.id, u.nom_complet
            ORDER BY nombre_eleves DESC
        """).fetchall()
        
        result += "<table border='1' style='border-collapse: collapse; width: 100%;'>"
        result += "<tr><th>Enseignant</th><th>Nombre d'élèves</th><th>Liste des élèves</th></tr>"
        
        for enseignant, count, liste in distribution:
            result += f"""
            <tr>
                <td><strong>{enseignant}</strong></td>
                <td style='text-align: center;'>{count}</td>
                <td style='font-size: 0.9em;'>{liste or 'Aucun'}</td>
            </tr>
            """
        
        result += "</table>"
        
        # 5. Lien pour vérifier
        result += f"""
        <div style="margin-top: 30px; padding: 20px; background: #e3f2fd; border-radius: 8px;">
            <h3>✅ Assignation terminée</h3>
            <div style="margin-top: 20px;">
                <a href='/admin-enseignants' style='background: #4CAF50; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; margin-right: 10px;'>
                    📋 Voir les enseignants avec leurs élèves
                </a>
                <a href='/verify-migration' style='background: #2196F3; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;'>
                    🔍 Vérifier la migration complète
                </a>
            </div>
        </div>
        """
        
        return result
        
    except Exception as e:
        import traceback
        return f"<h1>Erreur</h1><p>{str(e)}</p><pre>{traceback.format_exc()}</pre>", 500
    
@app.route("/restore-teacher-student-relations")
@admin_required
def restore_teacher_student_relations():
    """Restaurer les relations historiques enseignant-élève"""
    try:
        from models import User, db
        
        result = "<h1>Restauration des relations historiques</h1>"
        
        # Essayer de trouver des relations dans différentes tables
        relations_found = False
        
        # Option 1: Table enseignant_eleve
        try:
            old_relations = db.session.execute("""
                SELECT enseignant_id, eleve_id
                FROM enseignant_eleve
            """).fetchall()
            
            if old_relations:
                relations_found = True
                result += f"<p>{len(old_relations)} relations trouvées dans 'enseignant_eleve'</p>"
                
                restored = []
                errors = []
                
                for enseignant_id, eleve_id in old_relations:
                    try:
                        # Trouver l'élève
                        eleve = User.query.get(eleve_id)
                        enseignant = User.query.get(enseignant_id)
                        
                        if eleve and enseignant:
                            if enseignant.role == 'enseignant':
                                eleve.enseignant_referent_id = enseignant_id
                                restored.append(f"{eleve.nom_complet} → {enseignant.nom_complet}")
                            else:
                                errors.append(f"L'utilisateur {enseignant_id} n'est pas un enseignant")
                        else:
                            errors.append(f"Élève {eleve_id} ou enseignant {enseignant_id} non trouvé")
                    
                    except Exception as e:
                        errors.append(f"Erreur avec relation {enseignant_id}-{eleve_id}: {str(e)}")
                
                if restored:
                    db.session.commit()
                    result += "<h3>Relations restaurées:</h3>"
                    result += "<ul>"
                    for rel in restored:
                        result += f"<li>{rel}</li>"
                    result += "</ul>"
                
                if errors:
                    result += "<h3>Erreurs:</h3>"
                    result += "<ul>"
                    for err in errors:
                        result += f"<li>{err}</li>"
                    result += "</ul>"
        
        except Exception as e:
            result += f"<p>Table 'enseignant_eleve' non trouvée: {str(e)}</p>"
        
        # Option 2: Chercher dans d'autres tables
        if not relations_found:
            result += "<p>Aucune table de relations trouvée. Tentative de déduction...</p>"
            
            # On peut essayer de déduire les relations par email ou nom
            # Par exemple, si un élève a un email du même domaine qu'un enseignant
            all_teachers = User.query.filter_by(role='enseignant').all()
            all_students = User.query.filter(
                (User.role.in_(['eleve', 'élève'])),
                (User.enseignant_referent_id.is_(None))
            ).all()
            
            deduced = []
            
            for student in all_students:
                student_email_domain = student.email.split('@')[-1] if '@' in student.email else ''
                
                # Chercher un enseignant avec le même domaine d'email
                matching_teachers = [t for t in all_teachers if t.email.endswith(student_email_domain)]
                
                if matching_teachers:
                    # Prendre le premier enseignant correspondant
                    teacher = matching_teachers[0]
                    student.enseignant_referent_id = teacher.id
                    deduced.append(f"{student.nom_complet} ({student.email}) → {teacher.nom_complet}")
            
            if deduced:
                db.session.commit()
                result += "<h3>Relations déduites par domaine d'email:</h3>"
                result += "<ul>"
                for rel in deduced:
                    result += f"<li>{rel}</li>"
                result += "</ul>"
            else:
                result += "<p>Aucune relation ne peut être déduite automatiquement.</p>"
        
        # Afficher l'état final
        result += "<h2>État final des relations:</h2>"
        
        stats = db.session.execute("""
            SELECT 
                CASE 
                    WHEN u.role = 'enseignant' THEN 'Enseignants'
                    WHEN u.role IN ('eleve', 'élève') THEN 'Élèves'
                    ELSE u.role
                END as type,
                COUNT(*) as total,
                SUM(CASE WHEN enseignant_referent_id IS NOT NULL THEN 1 ELSE 0 END) as avec_referent,
                SUM(CASE WHEN enseignant_referent_id IS NULL THEN 1 ELSE 0 END) as sans_referent
            FROM users u
            WHERE u.role IN ('enseignant', 'eleve', 'élève')
            GROUP BY type
        """).fetchall()
        
        result += "<table border='1' style='border-collapse: collapse;'>"
        result += "<tr><th>Type</th><th>Total</th><th>Avec référent</th><th>Sans référent</th></tr>"
        
        for type_user, total, avec, sans in stats:
            result += f"""
            <tr>
                <td>{type_user}</td>
                <td>{total}</td>
                <td>{avec}</td>
                <td>{sans}</td>
            </tr>
            """
        
        result += "</table>"
        
        return result
        
    except Exception as e:
        import traceback
        return f"<h1>Erreur</h1><p>{str(e)}</p><pre>{traceback.format_exc()}</pre>", 500

@app.route("/enseignant/remediations-en-attente")
def remediations_en_attente():
    """Afficher les remédiations en attente pour l'enseignant connecté"""

    # ============================================================
    # AUTHENTIFICATION ENSEIGNANT
    # Système actuel : session["user_id"] + session["role"]
    # ============================================================

    if "user_id" not in session:
        flash("Veuillez vous connecter", "error")
        return redirect(url_for("login_enseignant"))

    if session.get("role") != "enseignant":
        flash("Accès réservé aux enseignants", "error")
        return redirect(url_for("login_enseignant"))

    enseignant = User.query.get(session["user_id"])

    if not enseignant or enseignant.role != "enseignant":
        session.clear()
        flash("Session enseignant invalide. Veuillez vous reconnecter.", "error")
        return redirect(url_for("login_enseignant"))

    try:
        lang = session.get("lang", "fr")

        # ============================================================
        # REMÉDIATIONS DES ÉLÈVES DE CET ENSEIGNANT
        # On utilise enseignant_referent_id, qui correspond au système récent
        # ============================================================

        suggestions = (
            RemediationSuggestion.query
            .join(User, User.id == RemediationSuggestion.user_id)
            .filter(RemediationSuggestion.statut == "en_attente")
            .filter(User.enseignant_referent_id == enseignant.id)
            .order_by(RemediationSuggestion.timestamp.desc())
            .all()
        )

        total_en_attente = len(suggestions)

        return render_template(
            "remediations_en_attente.html",
            suggestions=suggestions,
            total_en_attente=total_en_attente,
            lang=lang,
            enseignant=enseignant
        )

    except Exception as e:
        print(f"Erreur dans remediations_en_attente: {e}")
        db.session.rollback()
        flash("Une erreur est survenue", "error")
        return redirect(url_for("dashboard_enseignant"))


@app.route("/enseignant/valider-remediation/<int:remediation_id>", methods=["GET", "POST"])
def valider_remediation(remediation_id):
    # ============================================================
    # AUTHENTIFICATION ENSEIGNANT
    # Système actuel : session["user_id"] + session["role"]
    # ============================================================

    if "user_id" not in session:
        flash("Veuillez vous connecter", "error")
        return redirect(url_for("login_enseignant"))

    if session.get("role") != "enseignant":
        flash("Accès réservé aux enseignants", "error")
        return redirect(url_for("login_enseignant"))

    enseignant = User.query.get(session["user_id"])

    if not enseignant or enseignant.role != "enseignant":
        session.clear()
        flash("Session enseignant invalide. Veuillez vous reconnecter.", "error")
        return redirect(url_for("login_enseignant"))

    lang = session.get("lang", "fr")

    # ============================================================
    # RÉCUPÉRER LA REMÉDIATION
    # ============================================================

    suggestion = RemediationSuggestion.query.get_or_404(remediation_id)

    # ============================================================
    # SÉCURITÉ : vérifier que l'élève appartient à cet enseignant
    # ============================================================

    if not suggestion.user:
        flash("Élève introuvable pour cette remédiation.", "error")
        return redirect(url_for("remediations_a_valider"))

    if suggestion.user.enseignant_referent_id != enseignant.id:
        flash("Accès non autorisé", "error")
        return redirect(url_for("remediations_a_valider"))

    # ============================================================
    # POST : VALIDATION DE LA REMÉDIATION
    # ============================================================

    if request.method == "POST":
        message = (request.form.get("message") or "").strip()
        question = (request.form.get("question") or "").strip()
        reponse = (request.form.get("reponse") or "").strip()
        explication = (request.form.get("explication") or "").strip()

        if not question or not reponse:
            flash("La question et la réponse attendue sont obligatoires.", "error")
            return render_template(
                "valider_remediation.html",
                suggestion=suggestion,
                lang=lang,
                question=question,
                reponse=reponse,
                explication=explication
            )

        if lang == "en":
            bloc = f"""Remediation:
- Question: {question}
- Expected answer: {reponse}
- Explanation: {explication}"""
        else:
            bloc = f"""Remédiation :
- Question : {question}
- Réponse attendue : {reponse}
- Explication : {explication}"""

        try:
            suggestion.message = message
            suggestion.exercice_suggere = bloc
            suggestion.statut = "valide"

            db.session.commit()

            flash("✅ Remédiation validée avec succès", "success")
            return redirect(url_for("remediations_a_valider"))

        except Exception as e:
            db.session.rollback()
            print(f"Erreur validation remédiation : {e}")
            flash("Une erreur est survenue lors de la validation.", "error")
            return redirect(url_for("remediations_a_valider"))

    # ============================================================
    # GET : PRÉREMPLIR LE FORMULAIRE
    # ============================================================

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
        explication=explication_text,
        enseignant=enseignant
    )


@app.route("/enseignant/remediations-a-valider", methods=["GET"])
def remediations_a_valider():
    # ============================================================
    # AUTHENTIFICATION ENSEIGNANT
    # Système actuel : session["user_id"] + session["role"]
    # ============================================================

    if "user_id" not in session:
        flash("Veuillez vous connecter", "error")
        return redirect(url_for("login_enseignant"))

    if session.get("role") != "enseignant":
        flash("Accès réservé aux enseignants", "error")
        return redirect(url_for("login_enseignant"))

    enseignant = User.query.get(session["user_id"])

    if not enseignant or enseignant.role != "enseignant":
        session.clear()
        flash("Session enseignant invalide. Veuillez vous reconnecter.", "error")
        return redirect(url_for("login_enseignant"))

    # ============================================================
    # FILTRES
    # ============================================================

    niveau_filtre = request.args.get("niveau", "").strip()
    statut_filtre = request.args.get("statut", "en_attente").strip()
    lang = session.get("lang", "fr")

    if statut_filtre not in ["en_attente", "valide", "tous"]:
        statut_filtre = "en_attente"

    try:
        # ============================================================
        # REQUÊTE PRINCIPALE
        # L'enseignant voit uniquement les remédiations de ses élèves
        # ============================================================

        query = (
            RemediationSuggestion.query
            .join(User, RemediationSuggestion.user_id == User.id)
            .options(
                joinedload(RemediationSuggestion.user)
                .joinedload(User.niveau)
            )
            .filter(User.enseignant_referent_id == enseignant.id)
        )

        # Filtre niveau
        if niveau_filtre:
            query = query.filter(User.niveau.has(nom=niveau_filtre))

        # Filtre statut
        if statut_filtre != "tous":
            query = query.filter(RemediationSuggestion.statut == statut_filtre)
        else:
            query = query.filter(RemediationSuggestion.statut != "supprime")

        suggestions = (
            query
            .order_by(RemediationSuggestion.timestamp.desc())
            .all()
        )

        # ============================================================
        # NIVEAUX DISPONIBLES POUR LES ÉLÈVES DE CET ENSEIGNANT
        # ============================================================

        niveaux = (
            db.session.query(Niveau.nom)
            .join(User, User.niveau_id == Niveau.id)
            .filter(User.enseignant_referent_id == enseignant.id)
            .filter(User.role.in_(["eleve", "élève"]))
            .distinct()
            .order_by(Niveau.nom.asc())
            .all()
        )

        statuts = ["en_attente", "valide", "tous"]

        return render_template(
            "enseignant_remediations_validation.html",
            suggestions=suggestions,
            niveaux=[n[0] for n in niveaux],
            niveau_filtre=niveau_filtre,
            statut_filtre=statut_filtre,
            statuts=statuts,
            lang=lang,
            enseignant=enseignant
        )

    except Exception as e:
        db.session.rollback()
        print(f"Erreur dans remediations_a_valider: {e}")
        flash("Une erreur est survenue lors du chargement des remédiations.", "error")
        return redirect(url_for("dashboard_enseignant"))


@app.route("/enseignant/remediation/<int:remediation_id>")
def view_remediation(remediation_id):
    # ✅ CORRECTION : utiliser "user_id"
    if "user_id" not in session or session.get("role") != "enseignant":
        return redirect(url_for("login_enseignant"))

    lang = session.get("lang", "fr")
    suggestion = RemediationSuggestion.query.get_or_404(remediation_id)
    
    # ✅ Vérifier que cette remédiation appartient bien à un élève de cet enseignant
    if suggestion.user.enseignant_referent_id != session["user_id"]:
        flash("Accès non autorisé", "error")
        return redirect(url_for("remediations_a_valider"))
    
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

from datetime import datetime, timedelta
from flask import render_template, request, session, redirect, url_for, flash, jsonify
# Importez tous vos modèles depuis models.py
from models import db, User, Lecon, StudentResponse, RemediationSuggestion, \
                   Commission, VersementManuel, InfoVersementEnseignant


@app.route("/login-enseignant", methods=["GET", "POST"])
def login_enseignant():
    """Page de connexion pour les enseignants"""
    try:
        lang = session.get("lang", "fr")
        
        if request.method == "POST":
            email = request.form.get("email")
            mot_de_passe = request.form.get("mot_de_passe")
            
            if not email or not mot_de_passe:
                flash("Email et mot de passe requis" if lang == "fr" else "Email and password required", "error")
                return redirect(url_for("login_enseignant"))
            
            # Chercher l'enseignant
            enseignant = User.query.filter_by(email=email, role="enseignant").first()
            
            if not enseignant:
                flash("Email ou mot de passe incorrect" if lang == "fr" else "Incorrect email or password", "error")
                return redirect(url_for("login_enseignant"))
            
            # Vérifier le mot de passe
            if not enseignant.verifier_mot_de_passe(mot_de_passe):
                flash("Email ou mot de passe incorrect" if lang == "fr" else "Incorrect email or password", "error")
                return redirect(url_for("login_enseignant"))
            
            # Connexion réussie - METTRE À JOUR CETTE LIGNE
            session["user_id"] = enseignant.id
            session["role"] = "enseignant"
            session["nom_complet"] = enseignant.nom_complet  # CORRIGÉ: nom_complet au lieu de nom_complet
            session["lang"] = enseignant.langue if enseignant.langue else "fr"
            
            flash("Connexion réussie !" if lang == "fr" else "Login successful!", "success")
            return redirect(url_for("dashboard_enseignant"))
        
        # GET request - afficher le formulaire
        return render_template("login_enseignant.html", lang=lang)
        
    except Exception as e:
        print(f"Erreur login_enseignant: {e}")
        flash("Une erreur est survenue lors de la connexion", "error")
        return redirect(url_for("login_enseignant"))

def calculer_alertes_pedagogiques_enseignant(enseignant_id, limite_traces=300):
    """
    Calcule les alertes pédagogiques pour le dashboard enseignant.

    Objectif :
    - repérer les élèves à risque ;
    - repérer les notions problématiques ;
    - repérer les élèves en progression ;
    - donner des messages courts utilisables dans le dashboard.
    """

    from collections import defaultdict, Counter
    from models import User, TraceApprentissage

    alertes = {
        "eleves_risque_eleve": [],
        "eleves_risque_moyen": [],
        "notions_problematiques": [],
        "eleves_progression": [],
        "messages": [],
        "resume": {
            "nb_eleves_risque_eleve": 0,
            "nb_eleves_risque_moyen": 0,
            "nb_notions_problematiques": 0,
            "nb_eleves_progression": 0
        }
    }

    try:
        # ============================================================
        # 1. RÉCUPÉRER LES ÉLÈVES DE L'ENSEIGNANT
        # ============================================================

        eleves = (
            User.query
            .filter(
                User.role.in_(["eleve", "élève"]),
                User.enseignant_referent_id == enseignant_id
            )
            .all()
        )

        if not eleves and hasattr(User, "enseignant_id"):
            eleves = (
                User.query
                .filter(
                    User.role.in_(["eleve", "élève"]),
                    User.enseignant_id == enseignant_id
                )
                .all()
            )

        eleves_ids = [eleve.id for eleve in eleves]

        if not eleves_ids:
            return alertes

        eleves_map = {
            eleve.id: eleve for eleve in eleves
        }

        # ============================================================
        # 2. RÉCUPÉRER LES TRACES RÉCENTES
        # ============================================================

        traces = (
            TraceApprentissage.query
            .filter(TraceApprentissage.user_id.in_(eleves_ids))
            .order_by(TraceApprentissage.created_at.desc())
            .limit(limite_traces)
            .all()
        )

        if not traces:
            return alertes

        traces_par_eleve = defaultdict(list)
        traces_par_notion = defaultdict(list)

        for trace in traces:
            traces_par_eleve[trace.user_id].append(trace)

            notion = (
                trace.notion_cible
                or (trace.meta_json or {}).get("notion_cible")
                or "Notion non précisée"
            )

            traces_par_notion[notion].append(trace)

        # ============================================================
        # 3. ALERTES ÉLÈVES À RISQUE
        # ============================================================

        for eleve_id, traces_eleve in traces_par_eleve.items():
            eleve = eleves_map.get(eleve_id)

            if not eleve:
                continue

            nb_risque_eleve = sum(
                1 for trace in traces_eleve
                if trace.niveau_risque == "élevé"
            )

            nb_risque_moyen = sum(
                1 for trace in traces_eleve
                if trace.niveau_risque == "moyen"
            )

            scores = [
                trace.score for trace in traces_eleve
                if trace.score is not None
            ]

            score_moyen = round(sum(scores) / len(scores), 1) if scores else None

            notions = Counter(
                trace.notion_cible
                for trace in traces_eleve
                if trace.notion_cible
            )

            notion_principale = notions.most_common(1)[0][0] if notions else "Notion non précisée"

            if nb_risque_eleve >= 1:
                alertes["eleves_risque_eleve"].append({
                    "id": eleve.id,
                    "nom": eleve.nom_complet or eleve.username,
                    "username": eleve.username,
                    "score_moyen": score_moyen,
                    "nb_traces": len(traces_eleve),
                    "nb_risque_eleve": nb_risque_eleve,
                    "notion_principale": notion_principale
                })

            elif nb_risque_moyen >= 2:
                alertes["eleves_risque_moyen"].append({
                    "id": eleve.id,
                    "nom": eleve.nom_complet or eleve.username,
                    "username": eleve.username,
                    "score_moyen": score_moyen,
                    "nb_traces": len(traces_eleve),
                    "nb_risque_moyen": nb_risque_moyen,
                    "notion_principale": notion_principale
                })

        # ============================================================
        # 4. ALERTES NOTIONS PROBLÉMATIQUES
        # ============================================================

        for notion, traces_notion in traces_par_notion.items():
            eleves_concernes = set(trace.user_id for trace in traces_notion)

            nb_risque_eleve = sum(
                1 for trace in traces_notion
                if trace.niveau_risque == "élevé"
            )

            nb_risque_moyen = sum(
                1 for trace in traces_notion
                if trace.niveau_risque == "moyen"
            )

            scores = [
                trace.score for trace in traces_notion
                if trace.score is not None
            ]

            score_moyen = round(sum(scores) / len(scores), 1) if scores else None

            erreurs = Counter(
                trace.type_erreur
                for trace in traces_notion
                if trace.type_erreur
            )

            erreur_principale = erreurs.most_common(1)[0][0] if erreurs else None

            if len(eleves_concernes) >= 2 and (nb_risque_eleve >= 1 or nb_risque_moyen >= 2):
                alertes["notions_problematiques"].append({
                    "notion": notion,
                    "nb_eleves": len(eleves_concernes),
                    "nb_traces": len(traces_notion),
                    "score_moyen": score_moyen,
                    "nb_risque_eleve": nb_risque_eleve,
                    "nb_risque_moyen": nb_risque_moyen,
                    "erreur_principale": erreur_principale
                })

        # ============================================================
        # 5. ALERTES PROGRESSION
        # ============================================================

        for eleve_id, traces_eleve in traces_par_eleve.items():
            eleve = eleves_map.get(eleve_id)

            if not eleve:
                continue

            traces_notees = [
                trace for trace in traces_eleve
                if trace.score is not None
            ]

            if len(traces_notees) < 4:
                continue

            # Les traces sont déjà triées du plus récent au plus ancien.
            recentes = traces_notees[:2]
            anciennes = traces_notees[-2:]

            moyenne_recente = sum(t.score for t in recentes) / len(recentes)
            moyenne_ancienne = sum(t.score for t in anciennes) / len(anciennes)

            progression = round(moyenne_recente - moyenne_ancienne, 1)

            if progression >= 15:
                alertes["eleves_progression"].append({
                    "id": eleve.id,
                    "nom": eleve.nom_complet or eleve.username,
                    "username": eleve.username,
                    "progression": progression,
                    "moyenne_recente": round(moyenne_recente, 1),
                    "moyenne_ancienne": round(moyenne_ancienne, 1)
                })

        # ============================================================
        # 6. LIMITER ET CLASSER
        # ============================================================

        alertes["eleves_risque_eleve"] = sorted(
            alertes["eleves_risque_eleve"],
            key=lambda x: (x["nb_risque_eleve"], -(x["score_moyen"] or 0)),
            reverse=True
        )[:5]

        alertes["eleves_risque_moyen"] = sorted(
            alertes["eleves_risque_moyen"],
            key=lambda x: x["nb_risque_moyen"],
            reverse=True
        )[:5]

        alertes["notions_problematiques"] = sorted(
            alertes["notions_problematiques"],
            key=lambda x: (x["nb_risque_eleve"], x["nb_eleves"], x["nb_traces"]),
            reverse=True
        )[:5]

        alertes["eleves_progression"] = sorted(
            alertes["eleves_progression"],
            key=lambda x: x["progression"],
            reverse=True
        )[:5]

        # ============================================================
        # 7. RÉSUMÉ
        # ============================================================

        alertes["resume"] = {
            "nb_eleves_risque_eleve": len(alertes["eleves_risque_eleve"]),
            "nb_eleves_risque_moyen": len(alertes["eleves_risque_moyen"]),
            "nb_notions_problematiques": len(alertes["notions_problematiques"]),
            "nb_eleves_progression": len(alertes["eleves_progression"])
        }

        # ============================================================
        # 8. MESSAGES COURTS POUR DASHBOARD
        # ============================================================

        if alertes["eleves_risque_eleve"]:
            alertes["messages"].append({
                "type": "danger",
                "titre": "Élèves à risque élevé",
                "texte": f"{len(alertes['eleves_risque_eleve'])} élève(s) nécessitent une attention prioritaire."
            })

        if alertes["notions_problematiques"]:
            alertes["messages"].append({
                "type": "warning",
                "titre": "Notions à reprendre",
                "texte": f"{len(alertes['notions_problematiques'])} notion(s) semblent poser problème dans le groupe."
            })

        if alertes["eleves_progression"]:
            alertes["messages"].append({
                "type": "success",
                "titre": "Progressions positives",
                "texte": f"{len(alertes['eleves_progression'])} élève(s) montrent une progression notable."
            })

        if not alertes["messages"]:
            alertes["messages"].append({
                "type": "info",
                "titre": "Aucune alerte critique",
                "texte": "Les traces récentes ne montrent pas de signal pédagogique urgent."
            })

        return alertes

    except Exception as e:
        print(f"⚠️ Erreur calcul alertes pédagogiques enseignant : {e}")
        return alertes


@app.route("/dashboard-enseignant", methods=["GET", "POST"])
def dashboard_enseignant():
    """Dashboard enseignant - version légère avec suivi pédagogique intelligent"""

    try:
        # ============================================================
        # AUTHENTIFICATION ENSEIGNANT
        # ============================================================

        if "user_id" not in session:
            return redirect(url_for("login_enseignant"))

        if session.get("role") != "enseignant":
            flash("Accès réservé aux enseignants", "error")
            return redirect(url_for("login_enseignant"))

        enseignant = db.session.get(User, session["user_id"])

        if not enseignant or not enseignant.est_enseignant():
            session.clear()
            flash("Session enseignant invalide. Veuillez vous reconnecter.", "error")
            return redirect(url_for("login_enseignant"))

        # ============================================================
        # GESTION DE LA LANGUE
        # ============================================================

        if request.method == "POST":
            selected_lang = request.form.get("lang")

            if selected_lang in ["fr", "en"]:
                session["lang"] = selected_lang
                session.modified = True

            return redirect(url_for("dashboard_enseignant"))

        lang = session.get("lang", getattr(enseignant, "langue", None) or "fr")

        # ============================================================
        # RÉCUPÉRER LES ÉLÈVES DE L'ENSEIGNANT
        # Système actuel : enseignant_referent_id
        # ============================================================

        eleves = (
            User.query
            .filter(
                User.role.in_(["eleve", "élève"]),
                User.enseignant_referent_id == enseignant.id
            )
            .all()
        )

        # Fallback si certains élèves utilisent encore enseignant_id
        if not eleves and hasattr(User, "enseignant_id"):
            eleves = (
                User.query
                .filter(
                    User.role.in_(["eleve", "élève"]),
                    User.enseignant_id == enseignant.id
                )
                .all()
            )

        total_students = len(eleves)
        eleves_ids = [e.id for e in eleves]

        # ============================================================
        # STATISTIQUES ÉLÈVES
        # Version optimisée : on ne charge pas toutes les réponses
        # ============================================================

        stats = []
        noms_eleves = []
        moyennes = []
        niveau_counts = {}
        all_stars = []

        if eleves_ids:
            from sqlalchemy import func

            moyennes_par_eleve = dict(
                db.session.query(
                    StudentResponse.user_id,
                    func.avg(StudentResponse.etoiles)
                )
                .filter(
                    StudentResponse.user_id.in_(eleves_ids),
                    StudentResponse.etoiles.isnot(None)
                )
                .group_by(StudentResponse.user_id)
                .all()
            )

            total_reponses_par_eleve = dict(
                db.session.query(
                    StudentResponse.user_id,
                    func.count(StudentResponse.id)
                )
                .filter(
                    StudentResponse.user_id.in_(eleves_ids),
                    StudentResponse.etoiles.isnot(None)
                )
                .group_by(StudentResponse.user_id)
                .all()
            )
        else:
            moyennes_par_eleve = {}
            total_reponses_par_eleve = {}

        for eleve in eleves:
            moyenne = moyennes_par_eleve.get(eleve.id, 0)
            moyenne = round(float(moyenne or 0), 2)

            if moyenne > 0:
                all_stars.append(moyenne)

            niveau_nom = eleve.niveau.nom if eleve.niveau else "Non défini"

            stats.append({
                "id": eleve.id,
                "nom": eleve.nom_complet,
                "username": eleve.username,
                "niveau": niveau_nom,
                "moyenne": moyenne,
                "total": total_reponses_par_eleve.get(eleve.id, 0)
            })

            noms_eleves.append((eleve.nom_complet or eleve.username or "Élève")[:15])
            moyennes.append(moyenne if moyenne <= 3 else 3)

            niveau_counts[niveau_nom] = niveau_counts.get(niveau_nom, 0) + 1

        avg_stars = round(sum(all_stars) / len(all_stars), 1) if all_stars else 0

        niveaux = list(niveau_counts.keys())
        counts = list(niveau_counts.values())

        # ============================================================
        # REMÉDIATIONS EN ATTENTE
        # ============================================================

        nv_count = 0

        try:
            if eleves_ids:
                nv_count = (
                    RemediationSuggestion.query
                    .filter(
                        RemediationSuggestion.user_id.in_(eleves_ids),
                        RemediationSuggestion.statut == "en_attente"
                    )
                    .count()
                )
        except Exception as ex:
            print(f"Erreur comptage remédiations dashboard enseignant : {ex}")
            nv_count = 0

        # ============================================================
        # SUIVI PÉDAGOGIQUE INTELLIGENT : TRACES D'APPRENTISSAGE
        # ============================================================

        traces_total = 0
        traces_risque_eleve = 0
        traces_risque_moyen = 0
        traces_risque_faible = 0
        eleves_risque_dashboard = []
        notions_a_surveiller_dashboard = []

        try:
            from models import TraceApprentissage
            from sqlalchemy import func

            if eleves_ids:
                traces_total = (
                    TraceApprentissage.query
                    .filter(TraceApprentissage.user_id.in_(eleves_ids))
                    .count()
                )

                traces_risque_eleve = (
                    TraceApprentissage.query
                    .filter(
                        TraceApprentissage.user_id.in_(eleves_ids),
                        TraceApprentissage.niveau_risque == "élevé"
                    )
                    .count()
                )

                traces_risque_moyen = (
                    TraceApprentissage.query
                    .filter(
                        TraceApprentissage.user_id.in_(eleves_ids),
                        TraceApprentissage.niveau_risque == "moyen"
                    )
                    .count()
                )

                traces_risque_faible = (
                    TraceApprentissage.query
                    .filter(
                        TraceApprentissage.user_id.in_(eleves_ids),
                        TraceApprentissage.niveau_risque == "faible"
                    )
                    .count()
                )

                # Dernières traces à risque pour affichage rapide dans le dashboard
                traces_a_risque = (
                    TraceApprentissage.query
                    .join(User, TraceApprentissage.user_id == User.id)
                    .filter(
                        TraceApprentissage.user_id.in_(eleves_ids),
                        TraceApprentissage.niveau_risque.in_(["élevé", "moyen"])
                    )
                    .order_by(TraceApprentissage.created_at.desc())
                    .limit(5)
                    .all()
                )

                for trace in traces_a_risque:
                    eleves_risque_dashboard.append({
                        "id": trace.user.id if trace.user else trace.user_id,
                        "nom": trace.user.nom_complet if trace.user else "Élève",
                        "username": trace.user.username if trace.user else "",
                        "risque": trace.niveau_risque or "—",
                        "notion": trace.notion_cible or "Notion non précisée",
                        "score": trace.score if trace.score is not None else None,
                        "date": trace.created_at
                    })

                # Notions les plus fréquentes dans les traces à risque
                notions_query = (
                    db.session.query(
                        TraceApprentissage.notion_cible,
                        func.count(TraceApprentissage.id)
                    )
                    .filter(
                        TraceApprentissage.user_id.in_(eleves_ids),
                        TraceApprentissage.niveau_risque.in_(["élevé", "moyen"]),
                        TraceApprentissage.notion_cible.isnot(None),
                        TraceApprentissage.notion_cible != ""
                    )
                    .group_by(TraceApprentissage.notion_cible)
                    .order_by(func.count(TraceApprentissage.id).desc())
                    .limit(5)
                    .all()
                )

                notions_a_surveiller_dashboard = [
                    {
                        "notion": notion,
                        "count": count
                    }
                    for notion, count in notions_query
                ]

        except Exception as ex:
            print(f"⚠️ Erreur stats traces dashboard enseignant : {ex}")
            traces_total = 0
            traces_risque_eleve = 0
            traces_risque_moyen = 0
            traces_risque_faible = 0
            eleves_risque_dashboard = []
            notions_a_surveiller_dashboard = []

        # ============================================================
        # COMMISSIONS
        # Version optimisée avec agrégats SQL
        # ============================================================

        total_commissions = 0
        commissions_pending = 0
        commissions_paid = 0
        commissions_available = 0
        interac_configure = False

        try:
            from sqlalchemy import func, case

            commission_stats = (
                db.session.query(
                    func.coalesce(
                        func.sum(
                            case(
                                (Commission.statut != "cancelled", Commission.montant_commission),
                                else_=0
                            )
                        ),
                        0
                    ).label("total_commissions"),

                    func.coalesce(
                        func.sum(
                            case(
                                (Commission.statut == "pending", 1),
                                else_=0
                            )
                        ),
                        0
                    ).label("commissions_pending"),

                    func.coalesce(
                        func.sum(
                            case(
                                (Commission.statut == "paid", Commission.montant_commission),
                                else_=0
                            )
                        ),
                        0
                    ).label("commissions_paid"),

                    func.coalesce(
                        func.sum(
                            case(
                                (Commission.statut == "pending", Commission.montant_commission),
                                else_=0
                            )
                        ),
                        0
                    ).label("commissions_available")
                )
                .filter(Commission.enseignant_id == enseignant.id)
                .first()
            )

            if commission_stats:
                total_commissions = float(commission_stats.total_commissions or 0)
                commissions_pending = int(commission_stats.commissions_pending or 0)
                commissions_paid = float(commission_stats.commissions_paid or 0)
                commissions_available = float(commission_stats.commissions_available or 0)

            info_versement = (
                InfoVersementEnseignant.query
                .filter_by(enseignant_id=enseignant.id)
                .first()
            )

            interac_configure = bool(info_versement and info_versement.email_interac)

        except Exception as ex:
            print(f"Erreur commissions dashboard enseignant : {ex}")
            total_commissions = 0
            commissions_pending = 0
            commissions_paid = 0
            commissions_available = 0
            interac_configure = False

        # ============================================================
        # ÉLÈVES PAYANTS / ESSAI
        # ============================================================

        eleves_payants = 0
        eleves_essai = 0

        for eleve in eleves:
            statut = getattr(eleve, "statut_paiement", "")

            if statut == "essai_gratuit":
                eleves_essai += 1
            else:
                eleves_payants += 1

        # ============================================================
        # RENDU FINAL
        # ============================================================

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
            total_students=total_students,
            avg_stars=avg_stars,

            total_commissions=total_commissions,
            commissions_pending=commissions_pending,
            commissions_paid=commissions_paid,
            commissions_available=commissions_available,
            interac_configure=interac_configure,

            eleves_payants=eleves_payants,
            eleves_essai=eleves_essai,
            commissions_implemented=True,

            traces_total=traces_total,
            traces_risque_eleve=traces_risque_eleve,
            traces_risque_moyen=traces_risque_moyen,
            traces_risque_faible=traces_risque_faible,
            eleves_risque_dashboard=eleves_risque_dashboard,
            notions_a_surveiller_dashboard=notions_a_surveiller_dashboard
        )

    except Exception as e:
        db.session.rollback()
        print(f"Erreur dashboard_enseignant: {e}")
        flash("Une erreur est survenue sur le dashboard.", "error")
        return redirect(url_for("login_enseignant"))

def calculer_alertes_pedagogiques_enseignant(enseignant_id, limite_traces=300):
    """
    Calcule les alertes pédagogiques pour le dashboard enseignant.

    Objectif :
    - repérer les élèves à risque ;
    - repérer les notions problématiques ;
    - repérer les élèves en progression ;
    - donner des messages courts utilisables dans le dashboard.
    """

    from collections import defaultdict, Counter
    from models import User, TraceApprentissage

    alertes = {
        "eleves_risque_eleve": [],
        "eleves_risque_moyen": [],
        "notions_problematiques": [],
        "eleves_progression": [],
        "messages": [],
        "resume": {
            "nb_eleves_risque_eleve": 0,
            "nb_eleves_risque_moyen": 0,
            "nb_notions_problematiques": 0,
            "nb_eleves_progression": 0
        }
    }

    try:
        # ============================================================
        # 1. RÉCUPÉRER LES ÉLÈVES DE L'ENSEIGNANT
        # ============================================================

        eleves = (
            User.query
            .filter(
                User.role.in_(["eleve", "élève"]),
                User.enseignant_referent_id == enseignant_id
            )
            .all()
        )

        if not eleves and hasattr(User, "enseignant_id"):
            eleves = (
                User.query
                .filter(
                    User.role.in_(["eleve", "élève"]),
                    User.enseignant_id == enseignant_id
                )
                .all()
            )

        eleves_ids = [eleve.id for eleve in eleves]

        if not eleves_ids:
            return alertes

        eleves_map = {
            eleve.id: eleve for eleve in eleves
        }

        # ============================================================
        # 2. RÉCUPÉRER LES TRACES RÉCENTES
        # ============================================================

        traces = (
            TraceApprentissage.query
            .filter(TraceApprentissage.user_id.in_(eleves_ids))
            .order_by(TraceApprentissage.created_at.desc())
            .limit(limite_traces)
            .all()
        )

        if not traces:
            return alertes

        traces_par_eleve = defaultdict(list)
        traces_par_notion = defaultdict(list)

        for trace in traces:
            traces_par_eleve[trace.user_id].append(trace)

            notion = (
                trace.notion_cible
                or (trace.meta_json or {}).get("notion_cible")
                or "Notion non précisée"
            )

            traces_par_notion[notion].append(trace)

        # ============================================================
        # 3. ALERTES ÉLÈVES À RISQUE
        # ============================================================

        for eleve_id, traces_eleve in traces_par_eleve.items():
            eleve = eleves_map.get(eleve_id)

            if not eleve:
                continue

            nb_risque_eleve = sum(
                1 for trace in traces_eleve
                if trace.niveau_risque == "élevé"
            )

            nb_risque_moyen = sum(
                1 for trace in traces_eleve
                if trace.niveau_risque == "moyen"
            )

            scores = [
                trace.score for trace in traces_eleve
                if trace.score is not None
            ]

            score_moyen = round(sum(scores) / len(scores), 1) if scores else None

            notions = Counter(
                trace.notion_cible
                for trace in traces_eleve
                if trace.notion_cible
            )

            notion_principale = notions.most_common(1)[0][0] if notions else "Notion non précisée"

            if nb_risque_eleve >= 1:
                alertes["eleves_risque_eleve"].append({
                    "id": eleve.id,
                    "nom": eleve.nom_complet or eleve.username,
                    "username": eleve.username,
                    "score_moyen": score_moyen,
                    "nb_traces": len(traces_eleve),
                    "nb_risque_eleve": nb_risque_eleve,
                    "notion_principale": notion_principale
                })

            elif nb_risque_moyen >= 2:
                alertes["eleves_risque_moyen"].append({
                    "id": eleve.id,
                    "nom": eleve.nom_complet or eleve.username,
                    "username": eleve.username,
                    "score_moyen": score_moyen,
                    "nb_traces": len(traces_eleve),
                    "nb_risque_moyen": nb_risque_moyen,
                    "notion_principale": notion_principale
                })

        # ============================================================
        # 4. ALERTES NOTIONS PROBLÉMATIQUES
        # ============================================================

        for notion, traces_notion in traces_par_notion.items():
            eleves_concernes = set(trace.user_id for trace in traces_notion)

            nb_risque_eleve = sum(
                1 for trace in traces_notion
                if trace.niveau_risque == "élevé"
            )

            nb_risque_moyen = sum(
                1 for trace in traces_notion
                if trace.niveau_risque == "moyen"
            )

            scores = [
                trace.score for trace in traces_notion
                if trace.score is not None
            ]

            score_moyen = round(sum(scores) / len(scores), 1) if scores else None

            erreurs = Counter(
                trace.type_erreur
                for trace in traces_notion
                if trace.type_erreur
            )

            erreur_principale = erreurs.most_common(1)[0][0] if erreurs else None

            if len(eleves_concernes) >= 2 and (nb_risque_eleve >= 1 or nb_risque_moyen >= 2):
                alertes["notions_problematiques"].append({
                    "notion": notion,
                    "nb_eleves": len(eleves_concernes),
                    "nb_traces": len(traces_notion),
                    "score_moyen": score_moyen,
                    "nb_risque_eleve": nb_risque_eleve,
                    "nb_risque_moyen": nb_risque_moyen,
                    "erreur_principale": erreur_principale
                })

        # ============================================================
        # 5. ALERTES PROGRESSION
        # ============================================================

        for eleve_id, traces_eleve in traces_par_eleve.items():
            eleve = eleves_map.get(eleve_id)

            if not eleve:
                continue

            traces_notees = [
                trace for trace in traces_eleve
                if trace.score is not None
            ]

            if len(traces_notees) < 4:
                continue

            # Les traces sont déjà triées du plus récent au plus ancien.
            recentes = traces_notees[:2]
            anciennes = traces_notees[-2:]

            moyenne_recente = sum(t.score for t in recentes) / len(recentes)
            moyenne_ancienne = sum(t.score for t in anciennes) / len(anciennes)

            progression = round(moyenne_recente - moyenne_ancienne, 1)

            if progression >= 15:
                alertes["eleves_progression"].append({
                    "id": eleve.id,
                    "nom": eleve.nom_complet or eleve.username,
                    "username": eleve.username,
                    "progression": progression,
                    "moyenne_recente": round(moyenne_recente, 1),
                    "moyenne_ancienne": round(moyenne_ancienne, 1)
                })

        # ============================================================
        # 6. LIMITER ET CLASSER
        # ============================================================

        alertes["eleves_risque_eleve"] = sorted(
            alertes["eleves_risque_eleve"],
            key=lambda x: (x["nb_risque_eleve"], -(x["score_moyen"] or 0)),
            reverse=True
        )[:5]

        alertes["eleves_risque_moyen"] = sorted(
            alertes["eleves_risque_moyen"],
            key=lambda x: x["nb_risque_moyen"],
            reverse=True
        )[:5]

        alertes["notions_problematiques"] = sorted(
            alertes["notions_problematiques"],
            key=lambda x: (x["nb_risque_eleve"], x["nb_eleves"], x["nb_traces"]),
            reverse=True
        )[:5]

        alertes["eleves_progression"] = sorted(
            alertes["eleves_progression"],
            key=lambda x: x["progression"],
            reverse=True
        )[:5]

        # ============================================================
        # 7. RÉSUMÉ
        # ============================================================

        alertes["resume"] = {
            "nb_eleves_risque_eleve": len(alertes["eleves_risque_eleve"]),
            "nb_eleves_risque_moyen": len(alertes["eleves_risque_moyen"]),
            "nb_notions_problematiques": len(alertes["notions_problematiques"]),
            "nb_eleves_progression": len(alertes["eleves_progression"])
        }

        # ============================================================
        # 8. MESSAGES COURTS POUR DASHBOARD
        # ============================================================

        if alertes["eleves_risque_eleve"]:
            alertes["messages"].append({
                "type": "danger",
                "titre": "Élèves à risque élevé",
                "texte": f"{len(alertes['eleves_risque_eleve'])} élève(s) nécessitent une attention prioritaire."
            })

        if alertes["notions_problematiques"]:
            alertes["messages"].append({
                "type": "warning",
                "titre": "Notions à reprendre",
                "texte": f"{len(alertes['notions_problematiques'])} notion(s) semblent poser problème dans le groupe."
            })

        if alertes["eleves_progression"]:
            alertes["messages"].append({
                "type": "success",
                "titre": "Progressions positives",
                "texte": f"{len(alertes['eleves_progression'])} élève(s) montrent une progression notable."
            })

        if not alertes["messages"]:
            alertes["messages"].append({
                "type": "info",
                "titre": "Aucune alerte critique",
                "texte": "Les traces récentes ne montrent pas de signal pédagogique urgent."
            })

        return alertes

    except Exception as e:
        print(f"⚠️ Erreur calcul alertes pédagogiques enseignant : {e}")
        return alertes

@app.route("/enseignant/profil-eleve/<int:eleve_id>")
def enseignant_profil_eleve(eleve_id):
    import json
    from models import TraceApprentissage, User
    from sqlalchemy.orm import joinedload

    # ============================================================
    # 0. AUTHENTIFICATION ENSEIGNANT PAR SESSION
    # ============================================================

    if "user_id" not in session:
        flash("Veuillez vous connecter comme enseignant.", "warning")
        return redirect(url_for("login_enseignant"))

    if session.get("role") != "enseignant":
        flash("Accès réservé aux enseignants.", "danger")
        return redirect(url_for("login_enseignant"))

    enseignant = db.session.get(User, session["user_id"])

    if not enseignant:
        session.clear()
        flash("Session invalide. Veuillez vous reconnecter.", "warning")
        return redirect(url_for("login_enseignant"))

    if getattr(enseignant, "role", None) != "enseignant":
        session.clear()
        flash("Accès réservé aux enseignants.", "danger")
        return redirect(url_for("login_enseignant"))

    lang = session.get("lang", getattr(enseignant, "langue", None) or "fr")

    # ============================================================
    # 1. VÉRIFIER QUE L'ÉLÈVE APPARTIENT À CET ENSEIGNANT
    # ============================================================

    eleve = (
        User.query
        .filter(
            User.id == eleve_id,
            User.role.in_(["eleve", "élève"]),
            User.enseignant_referent_id == enseignant.id
        )
        .first()
    )

    # Fallback si certains élèves utilisent encore enseignant_id
    if not eleve and hasattr(User, "enseignant_id"):
        eleve = (
            User.query
            .filter(
                User.id == eleve_id,
                User.role.in_(["eleve", "élève"]),
                User.enseignant_id == enseignant.id
            )
            .first()
        )

    if not eleve:
        flash("Élève introuvable ou non rattaché à votre compte.", "danger")
        return redirect(url_for("dashboard_enseignant"))

    # ============================================================
    # 2. CHARGER LES TRACES DE L'ÉLÈVE
    # ============================================================

    traces = (
        TraceApprentissage.query
        .options(
            joinedload(TraceApprentissage.matiere),
            joinedload(TraceApprentissage.unite),
            joinedload(TraceApprentissage.lecon),
            joinedload(TraceApprentissage.exercice)
        )
        .filter(TraceApprentissage.user_id == eleve.id)
        .order_by(TraceApprentissage.created_at.desc())
        .limit(100)
        .all()
    )

    # ============================================================
    # 3. PRÉPARER LES TRACES POUR AFFICHAGE LISIBLE
    # ============================================================

    for trace in traces:
        detail = {}

        try:
            if trace.analyse_ia:
                detail = json.loads(trace.analyse_ia)
        except Exception:
            detail = {}

        meta = trace.meta_json or {}

        trace.detail_ia = detail
        trace.feedback_lisible = detail.get("current_feedback", trace.analyse_ia or "")
        trace.score_sur_5 = detail.get("current_stars") or meta.get("score_sur_5")

        metadata = detail.get("metadata", {})

        trace.langue_trace = (
            metadata.get("language")
            or meta.get("lang")
            or lang
            or "fr"
        )

        trace.question_lisible = (
            meta.get("question_en")
            if trace.langue_trace == "en"
            else meta.get("question_fr")
        )

        if not trace.question_lisible and trace.exercice:
            trace.question_lisible = (
                trace.exercice.question_en
                if trace.langue_trace == "en" and trace.exercice.question_en
                else trace.exercice.question_fr
            )

        trace.reponse_attendue_lisible = (
            meta.get("reponse_attendue_en")
            if trace.langue_trace == "en"
            else meta.get("reponse_attendue_fr")
        )

        if not trace.reponse_attendue_lisible and trace.exercice:
            trace.reponse_attendue_lisible = (
                trace.exercice.reponse_en
                if trace.langue_trace == "en" and trace.exercice.reponse_en
                else trace.exercice.reponse_fr
            )

    # ============================================================
    # 4. CALCULS DE SYNTHÈSE
    # ============================================================

    total_traces = len(traces)

    scores = [
        trace.score for trace in traces
        if trace.score is not None
    ]

    score_moyen = round(sum(scores) / len(scores), 1) if scores else 0

    risques = {
        "faible": 0,
        "moyen": 0,
        "élevé": 0
    }

    notions = {}
    erreurs = {}
    activites_par_matiere = {}

    derniere_trace = traces[0] if traces else None

    for trace in traces:
        if trace.niveau_risque in risques:
            risques[trace.niveau_risque] += 1

        if trace.notion_cible:
            notions[trace.notion_cible] = notions.get(trace.notion_cible, 0) + 1

        if trace.type_erreur:
            erreurs[trace.type_erreur] = erreurs.get(trace.type_erreur, 0) + 1

        meta = trace.meta_json or {}
        matiere_nom = (
            meta.get("matiere_fr")
            or (trace.matiere.nom if trace.matiere else "Matière non précisée")
        )

        activites_par_matiere[matiere_nom] = activites_par_matiere.get(matiere_nom, 0) + 1

    notions_frequentes = sorted(
        notions.items(),
        key=lambda x: x[1],
        reverse=True
    )[:8]

    erreurs_frequentes = sorted(
        erreurs.items(),
        key=lambda x: x[1],
        reverse=True
    )[:8]

    matieres_frequentes = sorted(
        activites_par_matiere.items(),
        key=lambda x: x[1],
        reverse=True
    )[:5]

    if risques["élevé"] > 0:
        risque_dominant = "élevé"
    elif risques["moyen"] > 0:
        risque_dominant = "moyen"
    elif risques["faible"] > 0:
        risque_dominant = "faible"
    else:
        risque_dominant = "non défini"

    # ============================================================
    # 5. RECOMMANDATION SIMPLE POUR L'ENSEIGNANT
    # ============================================================

    if risque_dominant == "élevé":
        recommandation_enseignant = (
            "Prévoir une remédiation courte et guidée. Reprendre la notion avec un exemple simple avant de proposer un nouvel exercice."
            if lang == "fr"
            else "Plan a short guided remediation. Review the concept with a simple example before assigning a new exercise."
        )
    elif risque_dominant == "moyen":
        recommandation_enseignant = (
            "Vérifier la démarche de l’élève et proposer un exercice similaire avec une aide progressive."
            if lang == "fr"
            else "Check the student’s reasoning and assign a similar exercise with progressive support."
        )
    elif risque_dominant == "faible":
        recommandation_enseignant = (
            "L’élève semble progresser. Proposer un exercice de consolidation ou un défi légèrement plus avancé."
            if lang == "fr"
            else "The student seems to be progressing. Offer a consolidation exercise or a slightly more advanced challenge."
        )
    else:
        recommandation_enseignant = (
            "Pas encore assez de traces pour proposer une recommandation fiable."
            if lang == "fr"
            else "Not enough traces yet to provide a reliable recommendation."
        )

    # ============================================================
    # 6. RENDU
    # ============================================================

    return render_template(
        "enseignant_profil_eleve.html",
        enseignant=enseignant,
        eleve=eleve,
        traces=traces,

        total_traces=total_traces,
        score_moyen=score_moyen,
        risques=risques,
        risque_dominant=risque_dominant,
        notions_frequentes=notions_frequentes,
        erreurs_frequentes=erreurs_frequentes,
        matieres_frequentes=matieres_frequentes,
        derniere_trace=derniere_trace,
        recommandation_enseignant=recommandation_enseignant,

        lang=lang
    )


@app.route("/enseignant/synthese-notions")
def enseignant_synthese_notions():
    import json
    from models import TraceApprentissage, User
    from sqlalchemy.orm import joinedload

    # ============================================================
    # 0. AUTHENTIFICATION ENSEIGNANT PAR SESSION
    # ============================================================

    if "user_id" not in session:
        flash("Veuillez vous connecter comme enseignant.", "warning")
        return redirect(url_for("login_enseignant"))

    if session.get("role") != "enseignant":
        flash("Accès réservé aux enseignants.", "danger")
        return redirect(url_for("login_enseignant"))

    enseignant = db.session.get(User, session["user_id"])

    if not enseignant:
        session.clear()
        flash("Session invalide. Veuillez vous reconnecter.", "warning")
        return redirect(url_for("login_enseignant"))

    if getattr(enseignant, "role", None) != "enseignant":
        session.clear()
        flash("Accès réservé aux enseignants.", "danger")
        return redirect(url_for("login_enseignant"))

    lang = session.get("lang", getattr(enseignant, "langue", None) or "fr")

    # ============================================================
    # 1. PARAMÈTRES
    # ============================================================

    q = request.args.get("q", "").strip()
    risque_filtre = request.args.get("risque", "tous")
    sort = request.args.get("sort", "risque")

    # ============================================================
    # 2. RÉCUPÉRER LES ÉLÈVES RATTACHÉS À L'ENSEIGNANT
    # ============================================================

    eleves = (
        User.query
        .filter(
            User.role.in_(["eleve", "élève"]),
            User.enseignant_referent_id == enseignant.id
        )
        .all()
    )

    # Fallback si certains élèves utilisent encore enseignant_id
    if not eleves and hasattr(User, "enseignant_id"):
        eleves = (
            User.query
            .filter(
                User.role.in_(["eleve", "élève"]),
                User.enseignant_id == enseignant.id
            )
            .all()
        )

    eleves_ids = [eleve.id for eleve in eleves]

    if not eleves_ids:
        return render_template(
            "enseignant_synthese_notions.html",
            notions_synthese=[],
            total_notions=0,
            total_traces=0,
            total_eleves=len(eleves),
            q=q,
            risque=risque_filtre,
            sort=sort,
            lang=lang
        )

    # ============================================================
    # 3. CHARGER LES TRACES DES ÉLÈVES
    # ============================================================

    traces = (
        TraceApprentissage.query
        .options(
            joinedload(TraceApprentissage.user),
            joinedload(TraceApprentissage.matiere),
            joinedload(TraceApprentissage.unite),
            joinedload(TraceApprentissage.lecon),
            joinedload(TraceApprentissage.exercice)
        )
        .filter(TraceApprentissage.user_id.in_(eleves_ids))
        .order_by(TraceApprentissage.created_at.desc())
        .limit(1500)
        .all()
    )

    # ============================================================
    # 4. OUTIL INTERNE : MÉTA JSON SÉCURISÉ
    # ============================================================

    def lire_meta_json(trace):
        meta = trace.meta_json or {}

        if isinstance(meta, dict):
            return meta

        if isinstance(meta, str):
            try:
                return json.loads(meta)
            except Exception:
                return {}

        return {}

    # ============================================================
    # 5. AGRÉGER PAR NOTION
    # ============================================================

    notions = {}

    for trace in traces:
        meta = lire_meta_json(trace)

        notion = (
            trace.notion_cible
            or meta.get("notion_cible")
            or "Notion non précisée"
        )

        notion = str(notion).strip() or "Notion non précisée"

        if notion not in notions:
            notions[notion] = {
                "notion": notion,
                "traces_count": 0,
                "eleves_ids": set(),
                "eleves": {},
                "scores": [],
                "risques": {
                    "faible": 0,
                    "moyen": 0,
                    "élevé": 0
                },
                "erreurs": {},
                "matieres": {},
                "lecons": {},
                "dernieres_traces": [],
                "derniere_date": None
            }

        bloc = notions[notion]

        bloc["traces_count"] += 1
        bloc["eleves_ids"].add(trace.user_id)

        if trace.user:
            bloc["eleves"][trace.user_id] = {
                "id": trace.user_id,
                "nom": trace.user.nom_complet,
                "username": trace.user.username
            }
        else:
            bloc["eleves"][trace.user_id] = {
                "id": trace.user_id,
                "nom": f"Élève {trace.user_id}",
                "username": ""
            }

        if trace.score is not None:
            bloc["scores"].append(trace.score)

        if trace.niveau_risque in bloc["risques"]:
            bloc["risques"][trace.niveau_risque] += 1

        type_erreur = trace.type_erreur or meta.get("type_erreur")

        if type_erreur:
            type_erreur = str(type_erreur).strip()
            bloc["erreurs"][type_erreur] = bloc["erreurs"].get(type_erreur, 0) + 1

        matiere_nom = (
            meta.get("matiere_fr")
            or meta.get("matiere_en")
            or (trace.matiere.nom if trace.matiere else None)
            or "Matière non précisée"
        )

        bloc["matieres"][matiere_nom] = bloc["matieres"].get(matiere_nom, 0) + 1

        lecon_nom = (
            meta.get("lecon_fr")
            or meta.get("lecon_en")
            or (trace.lecon.titre_fr if trace.lecon else None)
            or "Leçon non précisée"
        )

        bloc["lecons"][lecon_nom] = bloc["lecons"].get(lecon_nom, 0) + 1

        if trace.created_at:
            if not bloc["derniere_date"] or trace.created_at > bloc["derniere_date"]:
                bloc["derniere_date"] = trace.created_at

        if len(bloc["dernieres_traces"]) < 5:
            bloc["dernieres_traces"].append(trace)

    # ============================================================
    # 6. TRANSFORMER EN LISTE LISIBLE
    # ============================================================

    notions_synthese = []

    for notion, bloc in notions.items():
        scores = bloc["scores"]

        score_moyen = round(sum(scores) / len(scores), 1) if scores else 0

        if bloc["risques"]["élevé"] > 0:
            risque_dominant = "élevé"
        elif bloc["risques"]["moyen"] > 0:
            risque_dominant = "moyen"
        elif bloc["risques"]["faible"] > 0:
            risque_dominant = "faible"
        else:
            risque_dominant = "non défini"

        erreurs_frequentes = sorted(
            bloc["erreurs"].items(),
            key=lambda x: x[1],
            reverse=True
        )[:3]

        matieres_frequentes = sorted(
            bloc["matieres"].items(),
            key=lambda x: x[1],
            reverse=True
        )[:2]

        lecons_frequentes = sorted(
            bloc["lecons"].items(),
            key=lambda x: x[1],
            reverse=True
        )[:2]

        eleves_liste = list(bloc["eleves"].values())

        if risque_dominant == "élevé":
            recommandation = (
                "Prévoir une remédiation de groupe ou un retour guidé sur cette notion."
                if lang == "fr"
                else "Plan a group remediation or a guided review on this concept."
            )
        elif risque_dominant == "moyen":
            recommandation = (
                "Proposer quelques exercices de consolidation et vérifier les démarches."
                if lang == "fr"
                else "Assign consolidation exercises and check students’ reasoning."
            )
        elif risque_dominant == "faible":
            recommandation = (
                "La notion semble globalement maîtrisée. Proposer un défi ou une consolidation légère."
                if lang == "fr"
                else "The concept seems mostly mastered. Offer a challenge or light consolidation."
            )
        else:
            recommandation = (
                "Données insuffisantes pour recommander une action."
                if lang == "fr"
                else "Not enough data to recommend an action."
            )

        item = {
            "notion": notion,
            "traces_count": bloc["traces_count"],
            "eleves_count": len(bloc["eleves_ids"]),
            "eleves": eleves_liste,
            "score_moyen": score_moyen,
            "risque_dominant": risque_dominant,
            "risques": bloc["risques"],
            "erreurs_frequentes": erreurs_frequentes,
            "matieres_frequentes": matieres_frequentes,
            "lecons_frequentes": lecons_frequentes,
            "dernieres_traces": bloc["dernieres_traces"],
            "derniere_date": bloc["derniere_date"],
            "recommandation": recommandation
        }

        notions_synthese.append(item)

    # ============================================================
    # 7. FILTRES
    # ============================================================

    if q:
        q_lower = q.lower()

        notions_synthese = [
            item for item in notions_synthese
            if (
                q_lower in item["notion"].lower()
                or any(q_lower in matiere.lower() for matiere, _ in item["matieres_frequentes"])
                or any(q_lower in erreur.lower() for erreur, _ in item["erreurs_frequentes"])
            )
        ]

    if risque_filtre != "tous":
        notions_synthese = [
            item for item in notions_synthese
            if item["risque_dominant"] == risque_filtre
        ]

    # ============================================================
    # 8. TRI
    # ============================================================

    if sort == "score_asc":
        notions_synthese.sort(key=lambda x: x["score_moyen"])

    elif sort == "score_desc":
        notions_synthese.sort(key=lambda x: x["score_moyen"], reverse=True)

    elif sort == "traces":
        notions_synthese.sort(key=lambda x: x["traces_count"], reverse=True)

    elif sort == "eleves":
        notions_synthese.sort(key=lambda x: x["eleves_count"], reverse=True)

    elif sort == "date":
        notions_synthese.sort(
            key=lambda x: x["derniere_date"] or datetime.min,
            reverse=True
        )

    else:
        # Tri par urgence pédagogique
        ordre_risque = {
            "élevé": 3,
            "moyen": 2,
            "faible": 1,
            "non défini": 0
        }

        notions_synthese.sort(
            key=lambda x: (
                ordre_risque.get(x["risque_dominant"], 0),
                x["eleves_count"],
                x["traces_count"]
            ),
            reverse=True
        )

    # ============================================================
    # 9. RENDU
    # ============================================================

    return render_template(
        "enseignant_synthese_notions.html",
        notions_synthese=notions_synthese,
        total_notions=len(notions_synthese),
        total_traces=len(traces),
        total_eleves=len(eleves),
        q=q,
        risque=risque_filtre,
        sort=sort,
        lang=lang
    )


@app.route("/enseignant/matiere/<int:matiere_id>")
def enseignant_matiere_detail(matiere_id):
    """Voir les détails d'une matière pour les élèves de l'enseignant connecté"""

    from models import EnseignantMatiere, Matiere, User, Unite, EleveMatiere

    # ============================================================
    # AUTHENTIFICATION ENSEIGNANT
    # Système actuel : session["user_id"] + session["role"]
    # ============================================================

    if "user_id" not in session:
        flash("Veuillez vous connecter", "error")
        return redirect(url_for("login_enseignant"))

    if session.get("role") != "enseignant":
        flash("Accès réservé aux enseignants", "error")
        return redirect(url_for("login_enseignant"))

    enseignant = User.query.get(session["user_id"])

    if not enseignant or enseignant.role != "enseignant":
        session.clear()
        flash("Session enseignant invalide. Veuillez vous reconnecter.", "error")
        return redirect(url_for("login_enseignant"))

    lang = session.get("lang", "fr")

    # ============================================================
    # MATIÈRE
    # ============================================================

    matiere = Matiere.query.get(matiere_id)

    if not matiere:
        flash("Matière non trouvée", "error")
        return redirect(url_for("dashboard_enseignant"))

    niveau = matiere.niveau

    # ============================================================
    # VÉRIFIER QUE L'ENSEIGNANT ENSEIGNE CETTE MATIÈRE
    # ============================================================

    enseignant_matiere = (
        EnseignantMatiere.query
        .filter(
            EnseignantMatiere.enseignant_id == enseignant.id,
            EnseignantMatiere.matiere_id == matiere.id
        )
        .first()
    )

    if not enseignant_matiere:
        flash("Vous n'avez pas accès à cette matière.", "error")
        return redirect(url_for("dashboard_enseignant"))

    # ============================================================
    # ÉLÈVES DE CET ENSEIGNANT QUI ONT CETTE MATIÈRE
    # ============================================================

    eleves = (
        User.query
        .join(EleveMatiere, EleveMatiere.eleve_id == User.id)
        .filter(
            User.role.in_(["eleve", "élève"]),
            User.enseignant_referent_id == enseignant.id,
            EleveMatiere.matiere_id == matiere.id
        )
        .order_by(User.nom_complet.asc())
        .all()
    )

    eleves_data = []

    for eleve in eleves:
        eleves_data.append({
            "id": eleve.id,
            "nom": eleve.nom_complet,
            "email": eleve.email,
            "niveau": eleve.niveau.nom if eleve.niveau else ""
        })

    # ============================================================
    # UNITÉS DE CETTE MATIÈRE
    # On garde les unités de la matière, mais la page reste limitée
    # aux élèves de l'enseignant qui ont cette matière.
    # ============================================================

    unites = (
        Unite.query
        .filter_by(matiere_id=matiere.id)
        .order_by(Unite.nom.asc())
        .all()
    )

    unites_data = []

    for unite in unites:
        unite_nom = unite.nom_en if lang == "en" and unite.nom_en else unite.nom

        unites_data.append({
            "id": unite.id,
            "nom": unite_nom
        })

    total_unites = len(unites_data)

    return render_template(
        "enseignant_matiere_detail.html",
        matiere=matiere,
        niveau=niveau,
        unites=unites_data,
        total_unites=total_unites,
        eleves=eleves_data,
        total_eleves=len(eleves_data),
        enseignant=enseignant,
        lang=lang
    )

@app.route("/api/unite/<int:unite_id>/lecons")
def api_unite_lecons(unite_id):
    """API pour charger les leçons d'une unité (chargement progressif)"""
    from models import Unite, Lecon
    
    unite = Unite.query.get(unite_id)
    if not unite:
        return jsonify({'success': False, 'error': 'Unité non trouvée'})
    
    lang = request.args.get('lang', 'fr')
    
    lecons = Lecon.query.filter_by(unite_id=unite_id).all()
    
    lecons_data = []
    for lecon in lecons:
        lecon_nom = lecon.titre_en if lang == 'en' and lecon.titre_en else lecon.titre_fr
        lecons_data.append({
            'id': lecon.id,
            'nom': lecon_nom
        })
    
    return jsonify({
        'success': True,
        'unite_id': unite_id,
        'lecons': lecons_data
    })


@app.route("/api/lecon/<int:lecon_id>/exercices")
def api_lecon_exercices(lecon_id):
    """API pour charger les exercices d'une leçon (chargement progressif)"""
    from models import Lecon, Exercice
    
    lecon = Lecon.query.get(lecon_id)
    if not lecon:
        return jsonify({'success': False, 'error': 'Leçon non trouvée'})
    
    lang = request.args.get('lang', 'fr')
    
    exercices = Exercice.query.filter_by(lecon_id=lecon_id).all()
    
    exercices_data = []
    for exo in exercices:
        exercices_data.append({
            'id': exo.id,
            'titre': exo.titre,
            'enonce': exo.enonce[:150] + '...' if len(exo.enonce) > 150 else exo.enonce
        })
    
    return jsonify({
        'success': True,
        'lecon_id': lecon_id,
        'exercices': exercices_data
    })


@app.route("/api/eleve/<int:eleve_id>/matiere/<int:matiere_id>/progress")
def api_eleve_matiere_progress(eleve_id, matiere_id):
    """API pour charger la progression d'un élève dans une matière"""
    from models import User, EleveMatiere, StudentResponse, Exercice, Lecon, Unite
    
    eleve = User.query.get(eleve_id)
    if not eleve:
        return jsonify({'success': False, 'error': 'Élève non trouvé'})
    
    # Vérifier que l'élève a cette matière
    eleve_matiere = EleveMatiere.query.filter_by(
        eleve_id=eleve_id,
        matiere_id=matiere_id
    ).first()
    
    if not eleve_matiere:
        return jsonify({'success': False, 'error': 'Élève non assigné à cette matière'})
    
    # Récupérer tous les exercices de la matière
    exercices_matiere = db.session.query(Exercice).join(
        Lecon, Lecon.id == Exercice.lecon_id
    ).join(
        Unite, Unite.id == Lecon.unite_id
    ).filter(
        Unite.matiere_id == matiere_id
    ).all()
    
    exercice_ids = [ex.id for ex in exercices_matiere]
    total = len(exercice_ids)
    
    # Récupérer les réponses de l'élève
    reponses = StudentResponse.query.filter(
        StudentResponse.user_id == eleve_id,
        StudentResponse.exercice_id.in_(exercice_ids)
    ).all()
    
    completed = len(reponses)
    moyenne_etoiles = sum(r.etoiles for r in reponses) / completed if completed > 0 else 0
    progression = (completed / total * 100) if total > 0 else 0
    
    # Détails par exercice
    exercices_details = []
    for exo in exercices_matiere:
        reponse = next((r for r in reponses if r.exercice_id == exo.id), None)
        exercices_details.append({
            'id': exo.id,
            'titre': exo.titre,
            'statut': 'completed' if reponse else 'pending',
            'score': reponse.etoiles if reponse else 0,
            'date': reponse.date_soumission.strftime('%d/%m/%Y') if reponse else None
        })
    
    return jsonify({
        'success': True,
        'eleve_id': eleve_id,
        'total_exercices': total,
        'completed': completed,
        'progression': progression,
        'moyenne_etoiles': round(moyenne_etoiles, 1),
        'exercices': exercices_details
    })


@app.route("/enseignant/matieres")
def enseignant_matieres():
    """Gérer les matières de l'enseignant (voir et modifier)"""
    from models import EnseignantMatiere, Matiere, Niveau
    
    if "user_id" not in session or session.get("role") != "enseignant":
        return redirect(url_for("login_enseignant"))
    
    enseignant = User.query.get(session["user_id"])
    if not enseignant:
        return redirect(url_for("login_enseignant"))
    
    lang = session.get("lang", "fr")
    
    # Récupérer TOUTES les matières disponibles par niveau
    niveaux = Niveau.query.all()
    
    niveaux_data = []
    for niveau in niveaux:
        niveau_nom = niveau.nom_en if lang == 'en' and niveau.nom_en else niveau.nom
        
        matieres_disponibles = []
        for matiere in niveau.matieres:
            # Vérifier si l'enseignant enseigne déjà cette matière
            enseigne = EnseignantMatiere.query.filter_by(
                enseignant_id=enseignant.id,
                matiere_id=matiere.id
            ).first()
            
            matieres_disponibles.append({
                'id': matiere.id,
                'nom': matiere.nom_en if lang == 'en' and matiere.nom_en else matiere.nom,
                'enseigne': enseigne is not None
            })
        
        niveaux_data.append({
            'id': niveau.id,
            'nom': niveau_nom,
            'matieres': matieres_disponibles
        })
    
    # Récupérer les matières actuellement enseignées
    matieres_enseignees = db.session.query(Matiere).join(
        EnseignantMatiere
    ).filter(
        EnseignantMatiere.enseignant_id == enseignant.id
    ).all()
    
    return render_template(
        "enseignant_matieres.html",
        niveaux=niveaux_data,
        matieres_enseignees=matieres_enseignees,
        lang=lang
    )


@app.route("/enseignant/matieres/ajouter", methods=["POST"])
def enseignant_matieres_ajouter():
    """Ajouter ou mettre à jour les matières enseignées par l'enseignant"""

    # ============================================================
    # AUTHENTIFICATION ENSEIGNANT
    # Système actuel : session["user_id"] + session["role"]
    # ============================================================

    if "user_id" not in session:
        flash("Veuillez vous connecter", "error")
        return redirect(url_for("login_enseignant"))

    if session.get("role") != "enseignant":
        flash("Accès réservé aux enseignants", "error")
        return redirect(url_for("login_enseignant"))

    enseignant = User.query.get(session["user_id"])

    if not enseignant or enseignant.role != "enseignant":
        session.clear()
        flash("Session enseignant invalide. Veuillez vous reconnecter.", "error")
        return redirect(url_for("login_enseignant"))

    try:
        # Les cases cochées dans le formulaire
        matiere_ids = request.form.getlist("matieres")

        if not matiere_ids:
            flash("Veuillez sélectionner au moins une matière.", "error")
            return redirect(url_for("enseignant_matieres"))

        # Nettoyer les valeurs reçues
        matiere_ids_int = []

        for matiere_id in matiere_ids:
            try:
                matiere_ids_int.append(int(matiere_id))
            except ValueError:
                pass

        if not matiere_ids_int:
            flash("Aucune matière valide sélectionnée.", "error")
            return redirect(url_for("enseignant_matieres"))

        # ============================================================
        # SUPPRIMER LES ANCIENNES MATIÈRES DE CET ENSEIGNANT
        # Puis recréer proprement avec niveau_id
        # ============================================================

        EnseignantMatiere.query.filter_by(
            enseignant_id=enseignant.id
        ).delete()

        # ============================================================
        # AJOUTER LES NOUVELLES MATIÈRES
        # niveau_id vient directement de la matière
        # ============================================================

        matieres = (
            Matiere.query
            .filter(Matiere.id.in_(matiere_ids_int))
            .all()
        )

        for matiere in matieres:
            if not matiere.niveau_id:
                print(f"⚠️ Matière sans niveau_id ignorée : {matiere.id} - {matiere.nom}")
                continue

            lien = EnseignantMatiere(
                enseignant_id=enseignant.id,
                niveau_id=matiere.niveau_id,
                matiere_id=matiere.id
            )

            db.session.add(lien)

        db.session.commit()

        flash("✅ Matières mises à jour avec succès.", "success")
        return redirect(url_for("enseignant_matieres"))

    except Exception as e:
        db.session.rollback()
        print(f"Erreur ajout matières enseignant : {e}")
        flash("Une erreur est survenue lors de la mise à jour des matières.", "error")
        return redirect(url_for("enseignant_matieres"))


@app.route("/enseignant/matieres/supprimer/<int:matiere_id>")
def enseignant_matieres_supprimer(matiere_id):
    """Supprimer une matière de l'enseignant"""
    from models import EnseignantMatiere
    
    if "user_id" not in session or session.get("role") != "enseignant":
        return redirect(url_for("login_enseignant"))
    
    enseignant = User.query.get(session["user_id"])
    if not enseignant:
        return redirect(url_for("login_enseignant"))
    
    association = EnseignantMatiere.query.filter_by(
        enseignant_id=enseignant.id,
        matiere_id=matiere_id
    ).first()
    
    if association:
        db.session.delete(association)
        db.session.commit()
        flash("Matière retirée avec succès", "success")
    
    return redirect(url_for("enseignant_matieres"))


@app.route("/modifier-matieres-enseignant")
def modifier_matieres_enseignant():
    """Page temporaire pour gérer les matières de l'enseignant"""
    if "user_id" not in session or session.get("role") != "enseignant":
        return redirect(url_for("login_enseignant"))
    
    flash("Fonctionnalité en cours de développement", "info")
    return redirect(url_for("dashboard_enseignant"))


@app.route("/enseignant/commissions", methods=["GET"])
def enseignant_commissions():
    """Tableau de bord des commissions pour l'enseignant"""
    if "user_id" not in session:
        return redirect(url_for("login"))
    
    if session.get("role") != "enseignant":
        flash("Accès réservé aux enseignants", "error")
        return redirect("/")
    
    enseignant = User.query.get(session["user_id"])
    
    if not enseignant or enseignant.role != "enseignant":
        flash("Enseignant non trouvé", "error")
        return redirect(url_for("login"))
    
    # Récupérer les commissions
    commissions = Commission.query.filter_by(enseignant_id=enseignant.id)\
        .order_by(Commission.date_paiement_eleve.desc()).all()
    
    info_versement = InfoVersementEnseignant.query.filter_by(enseignant_id=enseignant.id).first()
    
    versements = VersementManuel.query.filter_by(enseignant_id=enseignant.id)\
        .order_by(VersementManuel.date_demande.desc()).all()
    
    # Calculs - CORRECTION DES NOMS DE VARIABLES
    total_commissions = sum(c.montant_commission for c in commissions if c.statut != 'cancelled')
    commissions_available = sum(c.montant_commission for c in commissions if c.statut == 'pending')  # Ancien total_attente
    commissions_paid = sum(c.montant_commission for c in commissions if c.statut == 'paid')  # Ancien total_verse
    commissions_pending = len([c for c in commissions if c.statut == 'pending'])
    
    # Configuration seuil
    seuil_minimum = 25.00  # Changé de 50 à 25 pour correspondre au modèle
    frais_interac = 1.00
    
    if info_versement and info_versement.seuil_minimum:
        seuil_minimum = info_versement.seuil_minimum
    
    # Récupérer les élèves pour calculer eleves_payants
    eleves = User.query.filter_by(enseignant_referent_id=enseignant.id).all()
    eleves_payants = len([e for e in eleves if hasattr(e, 'statut_paiement') and e.statut_paiement == 'paye'])
    
    # Préparer les commissions pour l'affichage avec nom d'élève
    commissions_display = []
    for com in commissions:
        eleve = User.query.get(com.eleve_id)
        commissions_display.append({
            'id': com.id,
            'eleve_nom': eleve.nom_complet if eleve else 'Élève inconnu',
            'eleve_id': com.eleve_id,
            'type_abonnement': com.type_abonnement,
            'montant_total': com.montant_total,
            'montant_commission': com.montant_commission,
            'taux_base': com.taux_base,
            'details_bonus': com.details_bonus,
            'statut': com.statut,
            'date_paiement_eleve': com.date_paiement_eleve,
            'date_versement_manuel': com.date_versement_manuel,
            'reference_interac': com.reference_interac
        })
    
    # Calculer la répartition par type d'abonnement
    commissions_by_type = {
        'monthly': {'count': 0, 'amount': 0},
        'quarterly': {'count': 0, 'amount': 0},
        'annual': {'count': 0, 'amount': 0}
    }
    
    for com in commissions:
        if com.type_abonnement in commissions_by_type:
            commissions_by_type[com.type_abonnement]['count'] += 1
            commissions_by_type[com.type_abonnement]['amount'] += com.montant_commission
    
    lang = session.get('lang', 'fr')
    
    return render_template(
        'enseignant/commissions_simple.html',  # Le template que j'ai corrigé
        enseignant=enseignant,
        commissions=commissions_display,  # Utiliser commissions_display au lieu de commissions
        total_commissions=total_commissions,  # Ancien total_brut
        commissions_available=commissions_available,  # Ancien total_attente - CORRECTION IMPORTANTE
        commissions_paid=commissions_paid,  # Ancien total_verse
        commissions_pending=commissions_pending,
        info_versement=info_versement,
        versements=versements,
        seuil_minimum=seuil_minimum,
        frais_interac=frais_interac,
        eleves_payants=eleves_payants,
        commissions_by_type=commissions_by_type,
        lang=lang
    )


# 🔥 AJOUT : Route pour configurer les informations de versement
@app.route("/enseignant/commissions/configurer", methods=["GET", "POST"])
def configurer_commissions():
    """Configuration des informations de versement pour l'enseignant"""
    if "user_id" not in session or session.get("role") != "enseignant":
        flash("Accès réservé aux enseignants", "error")
        return redirect(url_for("login"))
    
    enseignant = User.query.get(session["user_id"])
    
    if not enseignant or enseignant.role != "enseignant":
        flash("Enseignant non trouvé", "error")
        return redirect(url_for("login"))
    
    # Récupérer ou créer les infos de versement
    info_versement = InfoVersementEnseignant.query.filter_by(enseignant_id=enseignant.id).first()
    
    if request.method == "POST":
        try:
            if not info_versement:
                info_versement = InfoVersementEnseignant(enseignant_id=enseignant.id)
                db.session.add(info_versement)
            
            # Mettre à jour les informations
            info_versement.methode_versement = request.form.get("methode_versement", "interac")
            info_versement.email_interac = request.form.get("email_interac", "")
            info_versement.nom_complet_interac = request.form.get("nom_complet_interac", enseignant.nom_complet)
            info_versement.email_paypal = request.form.get("email_paypal", "")
            info_versement.frequence_versement = request.form.get("frequence_versement", "mensuel")
            
            seuil = request.form.get("seuil_minimum", "25.00")
            try:
                info_versement.seuil_minimum = float(seuil)
            except:
                info_versement.seuil_minimum = 25.00
            
            info_versement.date_mise_a_jour = datetime.utcnow()
            
            # Mettre à jour aussi dans le modèle User pour la cohérence
            enseignant.methode_versement = info_versement.methode_versement
            enseignant.email_interac_paiement = info_versement.email_interac
            enseignant.nom_complet_interac = info_versement.nom_complet_interac
            enseignant.email_paypal = info_versement.email_paypal
            enseignant.frequence_versement = info_versement.frequence_versement
            enseignant.seuil_minimum_paiement = info_versement.seuil_minimum
            
            db.session.commit()
            
            flash("Configuration sauvegardée avec succès", "success")
            return redirect(url_for("enseignant_commissions"))
            
        except Exception as e:
            db.session.rollback()
            flash(f"Erreur lors de la sauvegarde: {str(e)}", "error")
    
    lang = session.get('lang', 'fr')
    
    return render_template(
        'enseignant/configurer_commissions.html',
        enseignant=enseignant,
        info_versement=info_versement,
        lang=lang
    )


# 🔥 AJOUT : Route pour demander un versement manuel
@app.route("/enseignant/commissions/demander-versement", methods=["POST"])
def demander_versement_manuel():
    """Demande de versement manuel par l'enseignant"""
    if "user_id" not in session or session.get("role") != "enseignant":
        return jsonify({"success": False, "error": "Non autorisé"}), 401
    
    enseignant_id = session["user_id"]
    enseignant = User.query.get(enseignant_id)
    
    if not enseignant:
        return jsonify({"success": False, "error": "Enseignant non trouvé"}), 404
    
    try:
        # Vérifier que l'enseignant a configuré son email Interac
        info_versement = InfoVersementEnseignant.query.filter_by(enseignant_referent_id=enseignant_id).first()
        if not info_versement or not info_versement.email_interac:
            error_msg = "Veuillez d'abord configurer votre email Interac" if session.get('lang', 'fr') == 'fr' else "Please configure your Interac email first"
            return jsonify({"success": False, "error": error_msg}), 400
        
        # Récupérer les commissions en attente
        commissions_pending = Commission.query.filter_by(
            enseignant_referent_id=enseignant_id,
            statut='pending'
        ).all()
        
        montant_total = sum(c.montant_commission for c in commissions_pending)
        
        # Vérifier le seuil minimum
        seuil_minimum = info_versement.seuil_minimum or 25.00
        
        if montant_total < seuil_minimum:
            error_msg = f"Montant insuffisant. Minimum: {seuil_minimum}$" if session.get('lang', 'fr') == 'fr' else f"Insufficient amount. Minimum: {seuil_minimum}$"
            return jsonify({"success": False, "error": error_msg}), 400
        
        # Calculer les frais de transaction
        frais_transaction = 1.00
        montant_net = montant_total - frais_transaction
        
        # Créer le versement manuel
        versement = VersementManuel(
            enseignant_referent_id=enseignant_id,
            montant_total=montant_total,
            frais_transaction=frais_transaction,
            montant_net=montant_net,
            email_interac=info_versement.email_interac,
            date_demande=datetime.utcnow(),
            statut='demande'
        )
        
        db.session.add(versement)
        
        # Marquer les commissions comme "processing"
        for commission in commissions_pending:
            commission.statut = 'processing'
        
        db.session.commit()
        
        success_msg = "Demande de versement envoyée avec succès" if session.get('lang', 'fr') == 'fr' else "Payment request sent successfully"
        return jsonify({
            "success": True,
            "message": success_msg,
            "montant": montant_total,
            "montant_net": montant_net,
            "frais": frais_transaction
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


# 🔥 AJOUT : Route de déconnexion enseignant
@app.route("/logout-enseignant")
def logout_enseignant():
    """Déconnexion enseignant"""
    session.pop("user_id", None)
    session.pop("username", None)
    session.pop("nom_complet", None)
    session.pop("role", None)
    session.pop("email", None)
    session.pop("enseignant_id", None)
    flash("Vous avez été déconnecté avec succès", "success")
    return redirect(url_for("login"))

def creer_demande_versement(enseignant_id):
    """Créer une demande de versement Interac"""
    try:
        enseignant = User.query.get(enseignant_id)
        if not enseignant:
            return {'success': False, 'error': 'Enseignant non trouvé'}
        
        # Vérifier les commissions en attente
        commissions = Commission.query.filter_by(
            enseignant_id=enseignant_id,
            statut='pending'
        ).all()
        
        if not commissions:
            return {'success': False, 'error': 'Aucune commission en attente'}
        
        # Calculer le total
        montant_total = sum(c.montant_commission for c in commissions)
        
        # Vérifier le seuil minimum
        seuil_minimum = getattr(enseignant, 'seuil_minimum_paiement', 25.00)
        if montant_total < seuil_minimum:
            return {
                'success': False,
                'error': f'Montant insuffisant. Minimum: {seuil_minimum:.2f}$'
            }
        
        # Récupérer l'email Interac
        email_interac = None
        if hasattr(enseignant, 'email_interac_paiement') and enseignant.email_interac_paiement:
            email_interac = enseignant.email_interac_paiement
        else:
            info_versement = InfoVersementEnseignant.query.filter_by(enseignant_id=enseignant_id).first()
            if info_versement and info_versement.email_interac:
                email_interac = info_versement.email_interac
        
        if not email_interac:
            return {'success': False, 'error': 'Email Interac non configuré'}
        
        # Calculer les frais (1$ par défaut)
        frais_transaction = 1.00
        montant_net = montant_total - frais_transaction
        
        # Créer le versement
        versement = VersementManuel(
            enseignant_id=enseignant_id,
            montant_total=montant_total,
            frais_transaction=frais_transaction,
            montant_net=montant_net,
            email_interac=email_interac,
            statut='demande'
        )
        
        db.session.add(versement)
        
        # Marquer les commissions comme "en traitement"
        for commission in commissions:
            commission.statut = 'processing'
        
        db.session.commit()
        
        # TODO: Envoyer notification email à l'admin
        
        return {
            'success': True,
            'versement_id': versement.id,
            'montant_net': montant_net,
            'message': 'Demande créée avec succès'
        }
        
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': str(e)}

def envoyer_notification_versement(versement_id):
    """Envoyer des emails de notification"""
    versement = VersementManuel.query.get(versement_id)
    if not versement:
        return
    
    # Email à l'admin
    admin_email = "admin@tutoratai.ca"
    admin_subject = f"Nouvelle demande Interac - #{versement.id}"
    admin_body = f"""
    Nouvelle demande de versement Interac :
    
    ID: #{versement.id}
    Enseignant: {versement.enseignant.nom_complet}
    Montant net: {versement.montant_net:.2f}$
    Email: {versement.email_interac}
    
    Connectez-vous pour traiter : {url_for('admin_versements_interac', _external=True)}
    """
    # send_email(admin_email, admin_subject, admin_body)
    
    # Email à l'enseignant
    enseignant_email = versement.enseignant.email
    enseignant_subject = "Demande de versement Interac créée"
    enseignant_body = f"""
    Bonjour {versement.enseignant.nom_complet},
    
    Votre demande de versement Interac a été créée :
    Montant: {versement.montant_net:.2f}$
    
    Le traitement prend généralement 2-3 jours ouvrables.
    
    Vous recevrez une confirmation une fois le virement envoyé.
    """
    # send_email(enseignant_email, enseignant_subject, enseignant_body)


@app.route("/api/enseignant/demande-versement", methods=["POST"])
def api_demande_versement():
    """API pour créer une demande de versement"""
    if "user_id" not in session:
        return jsonify({'success': False, 'error': 'Non authentifié'}), 401
    
    if session.get("role") != "enseignant":
        return jsonify({'success': False, 'error': 'Accès refusé'}), 403
    
    result = creer_demande_versement(session["user_id"])
    return jsonify(result)


@app.route("/enseignant/config-versement", methods=["GET", "POST"])
def enseignant_config_versement():
    """Configuration des versements pour l'enseignant"""
    # Vérifier l'authentification
    if "user_id" not in session:
        return redirect(url_for("login"))
    
    if session.get("role") != "enseignant":
        flash("Accès réservé aux enseignants", "error")
        return redirect("/")
    
    enseignant = User.query.get(session["user_id"])
    
    if not enseignant or enseignant.role != "enseignant":
        flash("Enseignant non trouvé", "error")
        return redirect(url_for("login"))
    
    # Récupérer les informations existantes
    info_versement = InfoVersementEnseignant.query.filter_by(enseignant_id=enseignant.id).first()
    
    # Si c'est une soumission POST
    if request.method == "POST":
        try:
            email_interac = request.form.get("email_interac")
            nom_complet_interac = request.form.get("nom_complet_interac")
            methode_versement = request.form.get("methode_versement")
            frequence_versement = request.form.get("frequence_versement")
            seuil_minimum = request.form.get("seuil_minimum", 25.00)
            
            # Validation
            if not email_interac:
                flash("L'email Interac est obligatoire", "error")
                return redirect("/enseignant/config-versement")
            
            # Mettre à jour ou créer
            if info_versement:
                info_versement.email_interac = email_interac
                info_versement.nom_complet_interac = nom_complet_interac
                info_versement.methode_versement = methode_versement
                info_versement.frequence_versement = frequence_versement
                info_versement.seuil_minimum = float(seuil_minimum)
                info_versement.date_mise_a_jour = datetime.utcnow()
            else:
                info_versement = InfoVersementEnseignant(
                    enseignant_id=enseignant.id,
                    email_interac=email_interac,
                    nom_complet_interac=nom_complet_interac,
                    methode_versement=methode_versement,
                    frequence_versement=frequence_versement,
                    seuil_minimum=float(seuil_minimum)
                )
                db.session.add(info_versement)
            
            # Mettre à jour aussi le modèle User pour compatibilité
            enseignant.email_interac_paiement = email_interac
            enseignant.nom_complet_interac = nom_complet_interac
            enseignant.methode_versement = methode_versement
            enseignant.frequence_versement = frequence_versement
            enseignant.seuil_minimum_paiement = float(seuil_minimum)
            
            db.session.commit()
            flash("Configuration Interac sauvegardée avec succès", "success")
            return redirect(url_for("enseignant_commissions"))
            
        except Exception as e:
            db.session.rollback()
            flash(f"Erreur lors de la sauvegarde: {str(e)}", "error")
    
    # GET : Afficher le formulaire
    lang = session.get('lang', 'fr')
    
    return render_template(
        "enseignant/config_versement.html",
        enseignant=enseignant,
        info_versement=info_versement,
        lang=lang
    )


@app.route("/admin/versements-manuels")
def admin_versements():
    """Interface admin pour gérer les versements manuels"""
    
    # ✅ CORRECTION ESSENTIELLE : Charger la relation enseignant
    statut = request.args.get('statut', 'tous')
    
    query = VersementManuel.query.options(
        db.joinedload(VersementManuel.enseignant)  # ⚠️ C'EST LA CLÉ !
    )
    
    if statut != 'tous':
        query = query.filter_by(statut=statut)
    
    versements = query.order_by(VersementManuel.date_demande.desc()).all()
    
    # ✅ Ajouter les enseignants pour le formulaire
    teachers = User.query.filter_by(role='enseignant').order_by(User.nom_complet).all()
    
    # ✅ CORRECTION : Utiliser les bons noms de champs pour les statistiques
    total_demandes = VersementManuel.query.filter_by(statut='demande').count()
    total_en_cours = VersementManuel.query.filter_by(statut='en_cours').count()
    total_complete = VersementManuel.query.filter_by(statut='complete').count()
    
    # ✅ CORRECTION : Utiliser le BON nom de template
    return render_template(
        'admin/versements_manuels.html',  # ✅ Votre template
        versements=versements,
        teachers=teachers,  # ✅ Nécessaire pour le formulaire
        total_demandes=total_demandes,
        total_en_cours=total_en_cours,
        total_complete=total_complete,
        statut_selectionne=statut,
        lang=session.get('lang', 'fr')
    )

from datetime import datetime
from models import db, VersementManuel, Commission

def traiter_versement_manuel(versement_id, reference_interac, preuve_versement=None):
    """
    Traiter un versement manuel (marquer comme payé)
    
    Args:
        versement_id: ID du versement à traiter
        reference_interac: Référence de transaction Interac
        preuve_versement: URL ou chemin de la preuve de versement
    
    Returns:
        dict: Résultat de l'opération
    """
    try:
        # Récupérer le versement
        versement = VersementManuel.query.get(versement_id)
        if not versement:
            return {'error': 'Versement non trouvé', 'success': False}
        
        # Vérifier le statut
        if versement.statut == 'paye':
            return {'error': 'Ce versement a déjà été payé', 'success': False}
        
        if versement.statut != 'demande':
            return {'error': f'Statut invalide: {versement.statut}', 'success': False}
        
        # Mettre à jour le versement
        versement.statut = 'paye'
        versement.date_versement = datetime.utcnow()
        versement.reference_interac = reference_interac
        
        if preuve_versement:
            versement.preuve_versement = preuve_versement
        
        # Mettre à jour les commissions associées
        # Trouver toutes les commissions de cet enseignant avec statut 'processing'
        commissions = Commission.query.filter_by(
            enseignant_id=versement.enseignant_id,
            statut='processing'
        ).all()
        
        # Marquer les commissions comme payées
        for commission in commissions:
            commission.statut = 'paid'
            commission.date_versement_manuel = datetime.utcnow()
            commission.reference_interac = reference_interac
        
        db.session.commit()
        
        return {
            'success': True,
            'message': f'Versement #{versement_id} traité avec succès',
            'versement_id': versement_id,
            'enseignant_id': versement.enseignant_id,
            'montant_total': versement.montant_total,
            'montant_net': versement.montant_net,
            'commissions_traitees': len(commissions),
            'reference_interac': reference_interac
        }
        
    except Exception as e:
        db.session.rollback()
        return {'error': f'Erreur lors du traitement: {str(e)}', 'success': False}

@app.route("/api/admin/versement/<int:versement_id>/traiter", methods=["POST"])
def api_traiter_versement(versement_id):
    """Admin: Marquer un versement comme traité"""
    
    data = request.json
    reference = data.get('reference_interac')
    preuve_url = data.get('preuve_versement')
    
    result = traiter_versement_manuel(versement_id, reference, preuve_url)
    
    if 'error' in result:
        return jsonify(result), 400
    
    return jsonify(result)

@app.route("/admin/versements-manuels/add", methods=["POST"])
@admin_required
def add_manual_payment():
    """Ajouter un paiement manuel"""
    try:
        data = request.form
        
        # Récupérer les modèles
        UserModel = get_user_model()
        VersementManuelModel = get_model('VersementManuel')
        
        # Validation des champs
        enseignant_id = data.get('enseignant_id')
        montant = float(data.get('montant', 0))
        email_interac = data.get('email_interac')
        
        if not enseignant_id or montant <= 0:
            return jsonify({
                'success': False,
                'message': 'Enseignant et montant sont requis'
            }), 400
        
        # Vérifier que l'enseignant existe
        enseignant = UserModel.query.filter_by(id=enseignant_id, role="enseignant").first()
        if not enseignant:
            return jsonify({
                'success': False,
                'message': 'Enseignant non trouvé'
            }), 400
        
        # Calculer les frais (1$ par défaut)
        frais_transaction = float(data.get('frais_transaction', 1.00))
        montant_net = montant - frais_transaction
        
        # Créer le versement manuel
        new_payment = VersementManuelModel(
            enseignant_id=enseignant_id,
            montant_total=montant,
            montant_net=montant_net,
            frais_transaction=frais_transaction,
            email_interac=email_interac or enseignant.email_interac_paiement or enseignant.email,
            methode_paiement=data.get('methode_paiement', 'interac'),
            statut=data.get('statut', 'demande'),
            reference_interac=data.get('reference'),
            date_demande=datetime.utcnow(),
            date_versement=datetime.strptime(data.get('date_versement'), '%Y-%m-%d') if data.get('date_versement') else None,
            notes_admin=data.get('notes_admin', '')
        )
        
        # Si statut est "complete", mettre la date actuelle
        if new_payment.statut == 'complete' and not new_payment.date_versement:
            new_payment.date_versement = datetime.utcnow()
        
        db.session.add(new_payment)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Paiement ajouté avec succès',
            'payment_id': new_payment.id
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors de l'ajout du paiement manuel: {e}")
        return jsonify({
            'success': False,
            'message': f'Erreur: {str(e)}'
        }), 400


@app.route("/admin/versements-manuels/<int:payment_id>/approve", methods=["POST"])
@admin_required
def approve_manual_payment(payment_id):
    """Passer un versement de 'demande' à 'en_cours'"""
    try:
        payment = VersementManuel.query.get_or_404(payment_id)
        payment.statut = 'en_cours'
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Payment processing started'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': str(e)
        }), 400



@app.route("/admin/versements-manuels/<int:payment_id>/reject", methods=["POST"])
@admin_required
def reject_manual_payment(payment_id):
    """Rejeter un paiement manuel"""
    try:
        data = request.json
        payment = VersementManuel.query.get_or_404(payment_id)
        payment.statut = 'rejected'
        payment.notes_rejet = data.get('reason', '')
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Payment rejected successfully'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': str(e)
        }), 400


@app.route("/admin/versements-manuels/<int:payment_id>/complete", methods=["POST"])
@admin_required
def complete_manual_payment(payment_id):
    """Marquer un paiement comme complété"""
    try:
        payment = VersementManuel.query.get_or_404(payment_id)
        payment.statut = 'complete'
        payment.date_versement = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Payment marked as completed'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': str(e)
        }), 400


@app.route("/admin/versements-manuels/<int:payment_id>/delete", methods=["POST"])
@admin_required
def delete_manual_payment(payment_id):
    """Supprimer un paiement manuel"""
    try:
        payment = VersementManuel.query.get_or_404(payment_id)
        db.session.delete(payment)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Payment deleted successfully'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': str(e)
        }), 400


@app.route("/fix-versement-model")
def fix_versement_model():
    """Force la mise à jour du modèle VersementManuel"""
    import importlib
    import sys
    from sqlalchemy.orm import configure_mappers
    
    try:
        print("=== DÉBUT FIX VERSEMENT MODEL ===")
        
        # 1. Réinitialiser les métadonnées
        db.metadata.clear()
        
        # 2. Réfléchir la structure actuelle de la base
        db.metadata.reflect(bind=db.engine)
        
        # 3. Afficher les colonnes actuelles
        table = db.metadata.tables.get('versements_manuels')
        if table:
            columns = [c.name for c in table.columns]
            print(f"Colonnes dans la base: {columns}")
        else:
            print("Table versements_manuels non trouvée dans les métadonnées")
        
        # 4. Réimporter le module des modèles
        import models  # ou le nom de votre fichier de modèles
        importlib.reload(models)
        
        # 5. Forcer la reconfiguration des mappers
        configure_mappers()
        
        # 6. Vérifier le modèle Python
        from models import VersementManuel  # Ajustez selon votre structure
        
        model_columns = [column.key for column in VersementManuel.__table__.columns]
        print(f"Colonnes dans le modèle: {model_columns}")
        
        # 7. Tester la création
        test_versement = VersementManuel(
            enseignant_id=1,
            montant_total=100.0,
            frais_transaction=1.0,
            montant_net=99.0,
            email_interac="test_fix@example.com",
            methode_paiement="interac",  # Ceci devrait maintenant fonctionner
            statut="demande"
        )
        
        print(f"Test objet créé: methode_paiement = {test_versement.methode_paiement}")
        
        return f"""
        <h1>✅ Réparation effectuée</h1>
        <p>Colonnes base: {columns if table else 'N/A'}</p>
        <p>Colonnes modèle: {model_columns}</p>
        <p>Test création: OK (methode_paiement = {test_versement.methode_paiement})</p>
        <p><a href="/admin/versements-manuels">Tester la page</a></p>
        """
        
    except Exception as e:
        import traceback
        error_msg = traceback.format_exc()
        print(f"Erreur: {error_msg}")
        return f"""
        <h1>❌ Erreur lors de la réparation</h1>
        <pre>{error_msg}</pre>
        """

@app.route("/debug-versement-model")
def debug_versement_model():
    """Affiche les détails du modèle VersementManuel"""
    try:
        # Importez votre modèle
        from models import VersementManuel  # Ajustez l'import
        
        result = f"""
        <h1>Debug Modèle VersementManuel</h1>
        <h2>1. Métadonnées SQLAlchemy</h2>
        <pre>
        Table name: {VersementManuel.__tablename__}
        Columns: {[c.key for c in VersementManuel.__table__.columns]}
        </pre>
        
        <h2>2. Définition des colonnes</h2>
        <table border="1">
        <tr><th>Nom</th><th>Type</th><th>Nullable</th><th>Default</th></tr>
        """
        
        for column in VersementManuel.__table__.columns:
            result += f"""
            <tr>
                <td>{column.key}</td>
                <td>{column.type}</td>
                <td>{'✓' if column.nullable else '✗'}</td>
                <td>{column.default}</td>
            </tr>
            """
        
        result += "</table>"
        
        # Vérifier si methode_paiement existe
        has_methode_paiement = any(c.key == 'methode_paiement' for c in VersementManuel.__table__.columns)
        
        result += f"""
        <h2>3. Vérification champ 'methode_paiement'</h2>
        <p style="color:{'green' if has_methode_paiement else 'red'}">
        {'✅ Champ methode_paiement présent dans le modèle' 
         if has_methode_paiement else 
         '❌ Champ methode_paiement ABSENT du modèle'}
        </p>
        """
        
        # Tester la création
        result += "<h2>4. Test de création</h2>"
        try:
            test_obj = VersementManuel(
                enseignant_id=1,
                montant_total=100.0,
                frais_transaction=1.0,
                montant_net=99.0,
                email_interac="debug@test.com",
                statut="demande"
            )
            
            # Essayer d'accéder à methode_paiement
            try:
                methode_value = test_obj.methode_paiement
                result += f"<p>✅ methode_paiement accessible: {methode_value}</p>"
            except AttributeError:
                result += "<p style='color:red'>❌ methode_paiement non accessible (AttributeError)</p>"
            
            # Tester avec la valeur
            try:
                test_obj2 = VersementManuel(
                    enseignant_id=1,
                    montant_total=100.0,
                    frais_transaction=1.0,
                    montant_net=99.0,
                    email_interac="debug2@test.com",
                    methode_paiement="interac",
                    statut="demande"
                )
                result += f"<p>✅ Création avec methode_paiement='interac' réussie</p>"
            except Exception as e:
                result += f"<p style='color:red'>❌ Erreur création: {e}</p>"
                
        except Exception as e:
            result += f"<p style='color:red'>❌ Erreur test: {e}</p>"
        
        result += f"""
        <h2>5. Actions recommandées</h2>
        <ol>
            <li><a href="/fix-versement-model">Exécuter le fix</a></li>
            <li><a href="/admin/versements-manuels">Tester la page versements</a></li>
            <li>Redémarrer le serveur Flask</li>
        </ol>
        """
        
        return result
        
    except ImportError as e:
        return f"<h1>❌ Erreur d'import</h1><p>{e}</p><p>Vérifiez le chemin d'import de votre modèle.</p>"

@app.route("/admin/versements-manuels/<int:payment_id>/details", methods=["GET"])
@admin_required
def get_payment_details(payment_id):
    """Obtenir les détails d'un paiement"""
    try:
        payment = VersementManuel.query.get_or_404(payment_id)
        
        return jsonify({
            'success': True,
            'payment': {
                'id': payment.id,
                'enseignant_id': payment.enseignant_id,
                'enseignant_nom': payment.enseignant.nom_complet if payment.enseignant else 'N/A',
                'montant': float(payment.montant) if payment.montant else 0,
                'methode_paiement': payment.methode_paiement or '',
                'statut': payment.statut or '',
                'reference': payment.reference or '',
                'date_demande': payment.date_demande.strftime('%Y-%m-%d') if payment.date_demande else '',
                'date_versement': payment.date_versement.strftime('%Y-%m-%d') if payment.date_versement else '',
                'notes_rejet': payment.notes_rejet or ''
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 400

def completer_versement_manuel(versement_id, notes_admin=None):
    """
    Marquer un versement comme complété (pour archive)
    
    Args:
        versement_id: ID du versement
        notes_admin: Notes optionnelles de l'admin
    
    Returns:
        dict: Résultat de l'opération
    """
    try:
        versement = VersementManuel.query.get(versement_id)
        if not versement:
            return {'error': 'Versement non trouvé', 'success': False}
        
        if versement.statut != 'paye':
            return {'error': 'Le versement doit être payé avant d\'être complété', 'success': False}
        
        versement.statut = 'complete'
        if notes_admin:
            versement.notes_admin = notes_admin
        
        db.session.commit()
        
        return {
            'success': True,
            'message': f'Versement #{versement_id} marqué comme complété',
            'versement_id': versement_id
        }
        
    except Exception as e:
        db.session.rollback()
        return {'error': f'Erreur: {str(e)}', 'success': False}
        
@app.route("/api/admin/versement/<int:versement_id>/completer", methods=["POST"])
def api_completer_versement(versement_id):
    """Admin: Marquer versement comme complété"""
    
    result = completer_versement_manuel(versement_id)
    
    if 'error' in result:
        return jsonify(result), 400
    
    return jsonify(result)


@app.route("/api/admin/rapport-versements", methods=["GET"])
def api_rapport_versements():
    """Rapport des versements pour déclaration T4A"""
    
    annee = request.args.get('annee', datetime.now().year)
    
    debut = datetime(int(annee), 1, 1)
    fin = datetime(int(annee), 12, 31, 23, 59, 59)
    
    versements = VersementManuel.query.filter(
        VersementManuel.date_versement.between(debut, fin),
        VersementManuel.statut == 'complete'
    ).all()
    
    rapport = {}
    for versement in versements:
        ens_id = versement.enseignant_id
        if ens_id not in rapport:
            rapport[ens_id] = {
                'enseignant': versement.enseignant.nom_complet,
                'email': versement.enseignant.email,
                'email_interac': versement.email_interac,
                'total_verse': 0,
                'nombre_versements': 0,
                'versements': []
            }
        
        rapport[ens_id]['total_verse'] += versement.montant_net
        rapport[ens_id]['nombre_versements'] += 1
        rapport[ens_id]['versements'].append({
            'date': versement.date_versement.strftime('%Y-%m-%d'),
            'montant': versement.montant_net,
            'reference': versement.reference_interac
        })
    
    return jsonify({
        'success': True,
        'annee': annee,
        'rapport': rapport,
        'total_general': sum(v['total_verse'] for v in rapport.values())
    })


# Fonction pour intégrer dans vos routes de paiement existantes
def integrer_commission(eleve_id, plan_type, montant):
    """À appeler après un paiement réussi d'élève"""
    return creer_commission_apres_paiement(eleve_id, plan_type, montant)


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
    from sqlalchemy import func
    from sqlalchemy.orm import joinedload, selectinload
    from models import EleveMatiere

    username = request.args.get("username")
    lang = request.args.get("lang", "fr")

    # ============================================================
    # 1. RÉCUPÉRER L'ÉLÈVE
    # ============================================================

    eleve = (
        User.query
        .options(joinedload(User.niveau))
        .filter_by(username=username)
        .first_or_404()
    )

    # Sécurité minimale
    if not eleve.niveau_id:
        print("⚠️ Élève sans niveau associé.")
        return render_template(
            "choisir_sequence.html",
            eleve=eleve,
            unites=[],
            lecons=[],
            matiere_data={},
            completed_test_ids=set(),
            lang=lang
        )

    # ============================================================
    # 2. CHARGER LES MATIÈRES DE L'ÉLÈVE
    # ============================================================
    # On ne charge PAS Lecon.exercices ici.
    # Sinon la page peut devenir très lente avec plusieurs milliers d'exercices.

    matieres_eleve = (
        db.session.query(Matiere)
        .join(EleveMatiere, EleveMatiere.matiere_id == Matiere.id)
        .filter(EleveMatiere.eleve_id == eleve.id)
        .options(
            selectinload(Matiere.unites).selectinload(Unite.lecons),
            selectinload(Matiere.unites).selectinload(Unite.tests)
        )
        .order_by(Matiere.nom.asc())
        .all()
    )

    source_matieres = "matieres_choisies"

    # ============================================================
    # 3. FALLBACK IMPORTANT
    # ============================================================
    # Si aucune matière n'a été choisie pour cet élève,
    # on affiche les matières de son niveau.

    if not matieres_eleve:
        print("⚠️ Aucune matière choisie pour cet élève.")
        print("➡️ Fallback : affichage des matières du niveau de l'élève.")

        matieres_eleve = (
            Matiere.query
            .filter(Matiere.niveau_id == eleve.niveau_id)
            .options(
                selectinload(Matiere.unites).selectinload(Unite.lecons),
                selectinload(Matiere.unites).selectinload(Unite.tests)
            )
            .order_by(Matiere.nom.asc())
            .all()
        )

        source_matieres = "niveau_eleve"

    # ============================================================
    # 4. RÉCUPÉRER LES IDS DES LEÇONS ET UNITÉS VISIBLES
    # ============================================================

    lecon_ids = []
    unite_ids = []

    for matiere in matieres_eleve:
        for unite in matiere.unites:
            unite_ids.append(unite.id)

            for lecon in unite.lecons:
                lecon_ids.append(lecon.id)

    # ============================================================
    # 5. COMPTER LES EXERCICES PAR LEÇON
    # ============================================================
    # Une seule requête groupée au lieu de charger tous les exercices.

    exercices_par_lecon = {}

    if lecon_ids:
        exercices_par_lecon = dict(
            db.session.query(
                Exercice.lecon_id,
                func.count(Exercice.id)
            )
            .filter(Exercice.lecon_id.in_(lecon_ids))
            .group_by(Exercice.lecon_id)
            .all()
        )

    # ============================================================
    # 6. COMPTER LES EXERCICES TERMINÉS PAR LEÇON
    # ============================================================
    # On compte les exercices distincts pour éviter les doublons
    # si un élève répond plusieurs fois au même exercice.

    completed_par_lecon = {}

    if lecon_ids:
        completed_par_lecon = dict(
            db.session.query(
                Exercice.lecon_id,
                func.count(func.distinct(StudentResponse.exercice_id))
            )
            .join(StudentResponse, StudentResponse.exercice_id == Exercice.id)
            .filter(StudentResponse.user_id == eleve.id)
            .filter(Exercice.lecon_id.in_(lecon_ids))
            .filter(StudentResponse.exercice_id.isnot(None))
            .group_by(Exercice.lecon_id)
            .all()
        )

    # ============================================================
    # 7. RÉCUPÉRER LES TESTS TERMINÉS
    # ============================================================

    completed_tests = (
        TestResponse.query
        .filter_by(user_id=eleve.id)
        .with_entities(TestResponse.test_id)
        .all()
    )

    completed_test_ids = {test[0] for test in completed_tests if test[0]}

    # ============================================================
    # 8. ORGANISER LES DONNÉES POUR LE TEMPLATE
    # ============================================================

    matiere_data = {}
    unites_list = []
    lecons_filtrees = []

    for matiere in matieres_eleve:
        matiere_nom = (
            matiere.nom_en
            if lang == "en" and getattr(matiere, "nom_en", None)
            else matiere.nom
        )

        matiere_data[matiere_nom] = {
            "matiere_obj": matiere,
            "unites": [],
            "stats": {
                "total_unites": 0,
                "total_lecons": 0,
                "total_exercises": 0,
                "completed_exercises": 0
            }
        }

        for unite in matiere.unites:
            unites_list.append(unite)

            unit_stats = {
                "unite": unite,
                "total_lecons": 0,
                "total_exercises": 0,
                "completed_exercises": 0,
                "tests": [],
                "lecons": []
            }

            # ------------------------------------------------------------
            # Tests de l'unité
            # ------------------------------------------------------------

            for test in unite.tests:
                test.completed = test.id in completed_test_ids

                # Compatibilité avec ton template actuel :
                # choisir_sequence.html utilise test.nom_fr et test.nom_en,
                # mais ton modèle TestSommatif ne les définit pas toujours.
                if not hasattr(test, "nom_fr"):
                    test.nom_fr = f"Test sommatif - {unite.nom}"

                if not hasattr(test, "nom_en"):
                    test.nom_en = f"Final assessment - {unite.nom_en or unite.nom}"

                unit_stats["tests"].append(test)

            # ------------------------------------------------------------
            # Leçons de l'unité
            # ------------------------------------------------------------

            for lecon in unite.lecons:
                total_exos = exercices_par_lecon.get(lecon.id, 0)
                completed_count = completed_par_lecon.get(lecon.id, 0)

                # On n'affiche pas les leçons sans exercice
                if total_exos <= 0:
                    continue

                progress = (
                    completed_count / total_exos * 100
                    if total_exos > 0
                    else 0
                )

                lecon_stats = {
                    "lecon": lecon,
                    "total_exercises": total_exos,
                    "completed_exercises": completed_count,
                    "progress": progress
                }

                unit_stats["lecons"].append(lecon_stats)
                unit_stats["total_lecons"] += 1
                unit_stats["total_exercises"] += total_exos
                unit_stats["completed_exercises"] += completed_count

                lecons_filtrees.append(lecon)

            # ------------------------------------------------------------
            # Ajouter l'unité seulement si elle contient quelque chose
            # ------------------------------------------------------------

            if unit_stats["lecons"] or unit_stats["tests"]:
                matiere_data[matiere_nom]["unites"].append(unit_stats)

                matiere_data[matiere_nom]["stats"]["total_unites"] += 1
                matiere_data[matiere_nom]["stats"]["total_lecons"] += unit_stats["total_lecons"]
                matiere_data[matiere_nom]["stats"]["total_exercises"] += unit_stats["total_exercises"]
                matiere_data[matiere_nom]["stats"]["completed_exercises"] += unit_stats["completed_exercises"]

        # Si la matière n'a aucun contenu visible, on la retire
        if not matiere_data[matiere_nom]["unites"]:
            matiere_data.pop(matiere_nom)

    # ============================================================
    # 9. LOGS POUR DIAGNOSTIC
    # ============================================================

    print("========== CHOISIR SÉQUENCE ==========")
    print(f"👤 Élève : {eleve.username} | ID : {eleve.id}")
    print(f"🎓 Niveau ID : {eleve.niveau_id}")
    print(f"📚 Source matières : {source_matieres}")
    print(f"✅ Matières chargées : {len(matieres_eleve)}")
    print(f"✅ Unités trouvées : {len(unites_list)}")
    print(f"✅ Leçons analysées : {len(lecon_ids)}")
    print(f"✅ Leçons avec exercices : {len(lecons_filtrees)}")
    print(f"✅ Matières affichées : {len(matiere_data)}")
    print("=======================================")

    # ============================================================
    # 10. RENDU TEMPLATE
    # ============================================================

    return render_template(
        "choisir_sequence.html",
        eleve=eleve,
        unites=unites_list,
        lecons=lecons_filtrees,
        matiere_data=matiere_data,
        completed_test_ids=completed_test_ids,
        lang=lang
    )

@app.route("/admin/profils-apprenants")
@admin_required
def admin_profils_apprenants():
    from sqlalchemy import desc, or_
    from sqlalchemy.orm import joinedload

    # ============================================================
    # PARAMÈTRES DE FILTRE
    # ============================================================

    user_id = request.args.get("user_id", "").strip()
    lecon_id = request.args.get("lecon_id", "").strip()
    risque = request.args.get("risque", "").strip()
    recommandation = request.args.get("recommandation", "").strip()
    tendance = request.args.get("tendance", "").strip()
    recherche = request.args.get("q", "").strip()

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    if per_page not in [10, 20, 50, 100]:
        per_page = 20

    # ============================================================
    # REQUÊTE PRINCIPALE
    # ============================================================

    query = (
        ProfilApprenant.query
        .options(
            joinedload(ProfilApprenant.user),
            joinedload(ProfilApprenant.lecon)
                .joinedload(Lecon.unite)
                .joinedload(Unite.matiere)
        )
    )

    # Élève
    if user_id:
        try:
            user_id_int = int(user_id)
            query = query.filter(ProfilApprenant.user_id == user_id_int)
        except ValueError:
            pass

    # Leçon
    if lecon_id:
        try:
            lecon_id_int = int(lecon_id)
            query = query.filter(ProfilApprenant.lecon_id == lecon_id_int)
        except ValueError:
            pass

    # Risque
    if risque:
        query = query.filter(ProfilApprenant.niveau_risque == risque)

    # Recommandation
    if recommandation:
        query = query.filter(ProfilApprenant.recommandation == recommandation)

    # Tendance
    if tendance:
        query = query.filter(ProfilApprenant.tendance == tendance)

    # Recherche notion / compétence / élève
    if recherche:
        like = f"%{recherche}%"
        query = (
            query
            .join(User, ProfilApprenant.user_id == User.id)
            .filter(
                or_(
                    ProfilApprenant.notion_cible.ilike(like),
                    ProfilApprenant.competence_cible.ilike(like),
                    User.username.ilike(like),
                    User.nom_complet.ilike(like),
                    User.email.ilike(like)
                )
            )
        )

    query = query.order_by(
        desc(ProfilApprenant.updated_at),
        ProfilApprenant.niveau_risque.desc(),
        ProfilApprenant.notion_cible.asc()
    )

    pagination = query.paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )

    profils = pagination.items

    # ============================================================
    # LISTES POUR LES FILTRES
    # ============================================================

    eleves = (
        User.query
        .filter_by(role="eleve")
        .order_by(User.nom_complet.asc())
        .all()
    )

    lecons = (
        Lecon.query
        .options(joinedload(Lecon.unite).joinedload(Unite.matiere))
        .order_by(Lecon.titre_fr.asc())
        .all()
    )

    # ============================================================
    # STATISTIQUES GLOBALES
    # ============================================================

    total_profils = ProfilApprenant.query.count()

    total_risque_eleve = (
        ProfilApprenant.query
        .filter(ProfilApprenant.niveau_risque == "élevé")
        .count()
    )

    total_risque_moyen = (
        ProfilApprenant.query
        .filter(ProfilApprenant.niveau_risque == "moyen")
        .count()
    )

    total_risque_faible = (
        ProfilApprenant.query
        .filter(ProfilApprenant.niveau_risque == "faible")
        .count()
    )

    moyenne_maitrise = (
        db.session.query(db.func.avg(ProfilApprenant.maitrise_estimee))
        .scalar()
    )

    moyenne_maitrise = round(float(moyenne_maitrise or 0), 1)

    stats = {
        "total_profils": total_profils,
        "total_risque_eleve": total_risque_eleve,
        "total_risque_moyen": total_risque_moyen,
        "total_risque_faible": total_risque_faible,
        "moyenne_maitrise": moyenne_maitrise
    }

    return render_template(
        "admin/profils_apprenants.html",
        profils=profils,
        pagination=pagination,
        eleves=eleves,
        lecons=lecons,
        stats=stats,
        filtres={
            "user_id": user_id,
            "lecon_id": lecon_id,
            "risque": risque,
            "recommandation": recommandation,
            "tendance": tendance,
            "q": recherche,
            "per_page": per_page
        }
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
    """
    Dashboard élève avec recommandations personnalisées Naima.

    Version optimisée :
    - compatible SQLAlchemy 2 ;
    - évite User.query.get ;
    - évite de charger toutes les réponses inutilement ;
    - réduit le coût du graphique Matplotlib ;
    - garde les mêmes variables envoyées au template.
    """

    from datetime import datetime
    from sqlalchemy import func, case, and_, select
    from sqlalchemy.orm import joinedload

    # ============================================================
    # AUTHENTIFICATION
    # ============================================================

    if "user_id" not in session:
        return redirect(url_for("login_eleve"))

    user_role = session.get("role")

    if user_role not in ["élève", "eleve"]:
        flash("Accès réservé aux élèves", "error")
        return redirect(url_for("login_eleve"))

    user_id = session.get("user_id")

    eleve = db.session.execute(
        select(User)
        .options(joinedload(User.niveau))
        .where(User.id == user_id)
    ).scalar_one_or_none()

    if not eleve or eleve.role not in ["élève", "eleve"]:
        flash("Élève non trouvé", "error")
        return redirect(url_for("login_eleve"))

    # ============================================================
    # VÉRIFICATION ACCÈS - ESSAI GRATUIT EXPIRÉ
    # ============================================================

    if (
        hasattr(eleve, "essai_est_expire")
        and eleve.essai_est_expire()
        and eleve.statut_paiement != "paye"
    ):
        flash(
            "Votre période d'essai gratuit de 48h est terminée. "
            "Veuillez choisir un abonnement pour continuer.",
            "warning"
        )
        return redirect(url_for("upgrade_options"))

    session["current_student"] = eleve.username

    lang = request.args.get("lang") or session.get("lang", "fr")
    session["lang"] = lang

    # ============================================================
    # REMÉDIATIONS NON LUES
    # ============================================================

    remediations_non_lues = []

    try:
        remediations_non_lues = (
            RemediationSuggestion.query
            .filter_by(
                user_id=eleve.id,
                statut="valide",
                vue_par_eleve=False
            )
            .order_by(RemediationSuggestion.timestamp.desc())
            .limit(1)
            .all()
        )
    except Exception as e:
        print(f"⚠️ Erreur chargement remédiations non lues: {e}")

    # ============================================================
    # STATISTIQUES OPTIMISÉES
    # ============================================================

    total_reponses = 0
    moyenne_etoiles = 0
    bonnes_reponses = 0
    taux_reussite = 0

    try:
        total_reponses, moyenne_etoiles, bonnes_reponses = db.session.query(
            func.count(StudentResponse.id),
            func.coalesce(func.avg(StudentResponse.etoiles), 0),
            func.coalesce(
                func.sum(
                    case(
                        (StudentResponse.etoiles >= 3, 1),
                        else_=0
                    )
                ),
                0
            )
        ).filter(
            StudentResponse.user_id == eleve.id
        ).one()

        total_reponses = int(total_reponses or 0)
        moyenne_etoiles = float(moyenne_etoiles or 0)
        bonnes_reponses = int(bonnes_reponses or 0)

        taux_reussite = round(
            (bonnes_reponses / total_reponses) * 100,
            1
        ) if total_reponses else 0

    except Exception as e:
        print(f"⚠️ Erreur calcul statistiques dashboard élève: {e}")

    stats = {
        "total": total_reponses,
        "average": round(moyenne_etoiles, 1),
        "success": taux_reussite
    }

    # ============================================================
    # RÉPONSES RÉCENTES SEULEMENT
    # ============================================================

    reponses_eleve = []

    try:
        reponses_eleve = (
            StudentResponse.query
            .filter_by(user_id=eleve.id)
            .order_by(StudentResponse.timestamp.desc())
            .limit(80)
            .all()
        )

        reponses_eleve = list(reversed(reponses_eleve))

    except Exception as e:
        print(f"⚠️ Erreur chargement réponses récentes: {e}")
        reponses_eleve = []

    # ============================================================
    # STATISTIQUES PAR MATIÈRE
    # ============================================================

    stats_par_matiere = []

    try:
        # À adapter plus tard si les réponses sont liées directement aux matières.
        pass
    except Exception as e:
        print(f"⚠️ Erreur stats par matière: {e}")

    if stats_par_matiere:
        stats["par_matiere"] = stats_par_matiere

    # ============================================================
    # GRAPHIQUE DE PROGRESSION OPTIMISÉ
    # ============================================================

    courbe_progression = None

    if reponses_eleve:
        try:
            import matplotlib
            matplotlib.use("Agg")

            import matplotlib.pyplot as plt
            import io
            import base64

            reponses_par_jour = {}

            for reponse in reponses_eleve:
                if not reponse.timestamp:
                    continue

                date_str = reponse.timestamp.strftime("%Y-%m-%d")

                if date_str not in reponses_par_jour:
                    reponses_par_jour[date_str] = []

                reponses_par_jour[date_str].append(reponse.etoiles or 0)

            dates_ordonnees = sorted(reponses_par_jour.keys())[-30:]
            moyennes_journalieres = []

            for date_str in dates_ordonnees:
                etoiles_du_jour = reponses_par_jour[date_str]
                moyenne_jour = sum(etoiles_du_jour) / len(etoiles_du_jour)
                moyennes_journalieres.append(round(moyenne_jour, 2))

            dates_formatees = [
                datetime.strptime(date_str, "%Y-%m-%d").strftime("%d/%m")
                for date_str in dates_ordonnees
            ]

            if dates_formatees and moyennes_journalieres:
                fig = plt.figure(figsize=(8, 4), dpi=120)
                ax = fig.add_subplot(111)

                x_values = list(range(len(dates_formatees)))

                primary_color = "#3498db"
                secondary_color = "#2ecc71"
                text_color = "#2c3e50"
                grid_color = "#ecf0f1"

                titre = (
                    "Moyenne des étoiles par jour"
                    if lang == "fr"
                    else "Daily average stars"
                )

                label_y = "Étoiles" if lang == "fr" else "Stars"

                ax.plot(
                    x_values,
                    moyennes_journalieres,
                    marker="o",
                    color=primary_color,
                    linewidth=2.2,
                    markersize=6,
                    markerfacecolor="white",
                    markeredgecolor=primary_color,
                    markeredgewidth=1.5,
                    alpha=0.9
                )

                ax.fill_between(
                    x_values,
                    moyennes_journalieres,
                    alpha=0.08,
                    color=primary_color
                )

                ax.set_title(
                    titre,
                    fontsize=13,
                    fontweight="bold",
                    color=text_color,
                    pad=12
                )

                ax.set_ylabel(
                    label_y,
                    fontweight="bold",
                    fontsize=11,
                    color=text_color
                )

                ax.set_ylim(0, 5.5)

                ax.set_xticks(x_values)
                ax.set_xticklabels(dates_formatees, rotation=45, ha="right")

                ax.tick_params(axis="both", which="major", labelsize=9, colors=text_color)
                ax.grid(True, alpha=0.25, linestyle="--", linewidth=0.5, color=grid_color)

                for i, valeur in enumerate(moyennes_journalieres):
                    ax.annotate(
                        f"{valeur:.1f}",
                        (i, valeur),
                        textcoords="offset points",
                        xytext=(0, 10),
                        ha="center",
                        fontsize=8,
                        fontweight="bold",
                        color=primary_color
                    )

                moyenne_generale = stats["average"]

                ax.axhline(
                    y=moyenne_generale,
                    color=secondary_color,
                    linestyle="--",
                    linewidth=1.2,
                    alpha=0.7,
                    label=f"Moyenne: {moyenne_generale:.1f}"
                )

                ax.legend(loc="upper right", fontsize=9, framealpha=0.9)

                fig.tight_layout(pad=2.0)

                buf = io.BytesIO()
                fig.savefig(
                    buf,
                    format="png",
                    dpi=120,
                    bbox_inches="tight",
                    facecolor=fig.get_facecolor(),
                    edgecolor="none"
                )

                buf.seek(0)
                courbe_progression = base64.b64encode(buf.read()).decode("utf-8")
                buf.close()
                plt.close(fig)

        except Exception as e:
            print(f"⚠️ Erreur création graphique dashboard élève: {e}")
            courbe_progression = None

    # ============================================================
    # TEMPS RESTANT ESSAI GRATUIT
    # ============================================================

    temps_restant = None
    pourcentage_temps_restant = 100
    total_seconds = 0

    if (
        hasattr(eleve, "est_en_essai_gratuit")
        and eleve.est_en_essai_gratuit()
        and hasattr(eleve, "date_fin_essai")
        and eleve.date_fin_essai
    ):
        maintenant = datetime.utcnow()

        if maintenant < eleve.date_fin_essai:
            temps_restant = eleve.date_fin_essai - maintenant
            total_seconds = int(temps_restant.total_seconds())

            if hasattr(eleve, "date_inscription") and eleve.date_inscription:
                duree_totale = eleve.date_fin_essai - eleve.date_inscription
                temps_ecoule = maintenant - eleve.date_inscription

                if duree_totale.total_seconds() > 0:
                    pourcentage_temps_restant = max(
                        0,
                        min(
                            100,
                            100 - (
                                temps_ecoule.total_seconds()
                                / duree_totale.total_seconds()
                                * 100
                            )
                        )
                    )

    # ============================================================
    # OBJECTIFS DU JOUR
    # ============================================================

    remediations_completees = 0

    try:
        remediations_completees = RemediationSuggestion.query.filter(
            and_(
                RemediationSuggestion.user_id == eleve.id,
                RemediationSuggestion.statut == "valide",
                RemediationSuggestion.reponse_eleve.isnot(None)
            )
        ).count()

    except Exception as e:
        print(f"⚠️ Erreur calcul remédiations complétées: {e}")
        remediations_completees = 0

    objectifs_du_jour = []

    objectif1_completed = stats["total"] > 0
    objectif1_progress = (
        f"({stats['total']} complété(s))"
        if lang == "fr"
        else f"({stats['total']} completed)"
    )

    objectifs_du_jour.append({
        "text": "Compléter 1 exercice" if lang == "fr" else "Complete 1 exercise",
        "completed": objectif1_completed,
        "progress": objectif1_progress
    })

    objectif2_completed = stats["average"] >= 3
    objectif2_progress = (
        f"(Actuel : {stats['average']}/5)"
        if lang == "fr"
        else f"(Current: {stats['average']}/5)"
    )

    objectifs_du_jour.append({
        "text": "Moyenne 3+ étoiles" if lang == "fr" else "3+ star average",
        "completed": objectif2_completed,
        "progress": objectif2_progress
    })

    objectif3_completed = remediations_completees > 0
    objectif3_progress = (
        f"({remediations_completees} complétée(s))"
        if lang == "fr"
        else f"({remediations_completees} completed)"
    )

    objectifs_du_jour.append({
        "text": "Compléter 1 remédiation" if lang == "fr" else "Complete 1 remediation",
        "completed": objectif3_completed,
        "progress": objectif3_progress
    })

    total_objectifs = len(objectifs_du_jour)
    objectifs_completes = sum(1 for obj in objectifs_du_jour if obj["completed"])

    progression_percent = (
        int((objectifs_completes / total_objectifs) * 100)
        if total_objectifs > 0
        else 0
    )

    progression_quotidienne = {
        "completed": objectifs_completes,
        "total": total_objectifs,
        "percent": progression_percent
    }

    # ============================================================
    # STATUT DE PAIEMENT
    # ============================================================

    statut_paiement_info = {
        "est_en_essai": hasattr(eleve, "est_en_essai_gratuit") and eleve.est_en_essai_gratuit(),
        "est_paye": eleve.statut_paiement == "paye",
        "essai_expire": hasattr(eleve, "essai_est_expire") and eleve.essai_est_expire(),
        "jours_restants_abonnement": (
            eleve.jours_restants_abonnement()
            if hasattr(eleve, "jours_restants_abonnement")
            else 0
        )
    }

    # ============================================================
    # RECOMMANDATIONS NAIMA PERSONNALISÉES
    # ============================================================

    naima_recommendations = []
    naima_recommendations_count = 0

    if stats["total"] == 0:
        naima_recommendations.append({
            "icon": "fas fa-play-circle",
            "titre": "Commence ton premier exercice !" if lang == "fr" else "Start your first exercise!",
            "description": (
                "Naima est là pour t'aider à faire tes premiers pas. "
                "Pose-lui une question ou commence un exercice par leçon."
                if lang == "fr"
                else
                "Naima is here to help you take your first steps. "
                "Ask her a question or start a lesson exercise."
            ),
            "theme": "Débutant" if lang == "fr" else "Beginner",
            "lien": "/enseignant-virtuel"
        })

        naima_recommendations_count = 1

    elif stats["average"] < 3:
        naima_recommendations.append({
            "icon": "fas fa-chart-line",
            "titre": "Progressons ensemble !" if lang == "fr" else "Let's improve together!",
            "description": (
                f"Ta moyenne est de {stats['average']}/5. "
                "Naima peut t'aider à comprendre tes erreurs et à t'améliorer."
                if lang == "fr"
                else
                f"Your average is {stats['average']}/5. "
                "Naima can help you understand your mistakes and improve."
            ),
            "theme": "Progression" if lang == "fr" else "Improvement",
            "lien": "/enseignant-virtuel"
        })

        naima_recommendations_count = 1

        if remediations_non_lues:
            naima_recommendations.append({
                "icon": "fas fa-tools",
                "titre": "Remédiation disponible" if lang == "fr" else "Remediation available",
                "description": (
                    "Des exercices ciblés t'attendent pour renforcer tes compétences "
                    "sur les sujets difficiles."
                    if lang == "fr"
                    else
                    "Targeted exercises await to strengthen your skills on difficult topics."
                ),
                "theme": "Remédiation" if lang == "fr" else "Remediation",
                "lien": "/eleve/remediations"
            })

            naima_recommendations_count = 2

    elif stats["average"] >= 4:
        naima_recommendations.append({
            "icon": "fas fa-trophy",
            "titre": "Excellent travail !" if lang == "fr" else "Excellent work!",
            "description": (
                "Tu progresses très bien ! Naima peut te proposer des défis plus avancés "
                "pour continuer à te dépasser."
                if lang == "fr"
                else
                "You're doing great! Naima can offer you more advanced challenges "
                "to keep pushing yourself."
            ),
            "theme": "Défi" if lang == "fr" else "Challenge",
            "lien": "/enseignant-virtuel"
        })

        naima_recommendations_count = 1

    else:
        naima_recommendations.append({
            "icon": "fas fa-star",
            "titre": "Bon travail !" if lang == "fr" else "Good work!",
            "description": (
                "Tu fais du bon travail. Continue comme ça ! "
                "Naima est là si tu as des questions."
                if lang == "fr"
                else
                "You're doing good work. Keep it up! "
                "Naima is here if you have questions."
            ),
            "theme": "Encouragement" if lang == "fr" else "Encouragement",
            "lien": "/enseignant-virtuel"
        })

        naima_recommendations_count = 1

        if remediations_non_lues:
            naima_recommendations.append({
                "icon": "fas fa-tools",
                "titre": "Remédiation disponible" if lang == "fr" else "Remediation available",
                "description": (
                    "Des exercices de renforcement t'attendent pour consolider tes acquis."
                    if lang == "fr"
                    else
                    "Reinforcement exercises await to consolidate your knowledge."
                ),
                "theme": "Renforcement" if lang == "fr" else "Reinforcement",
                "lien": "/eleve/remediations"
            })

            naima_recommendations_count = 2

    # ============================================================
    # RENDU TEMPLATE
    # ============================================================

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
        objectifs_du_jour=objectifs_du_jour,
        progression_quotidienne=progression_quotidienne,
        remediations_completees=remediations_completees,
        date_du_jour=datetime.utcnow(),
        statut_paiement_info=statut_paiement_info,
        naima_recommendations=naima_recommendations,
        naima_recommendations_count=naima_recommendations_count
    )

import re

def parse_bilingual_exercises(text, default_time=120):
    """Parse les exercices au format bilingue"""
    exercises = []
    
    # Sépare les exercices par '---' sur ligne seule
    # Important: split sur '\n---\n' exactement
    raw_exercises = []
    current_exercise = []
    
    for line in text.strip().split('\n'):
        line = line.strip()
        if line == '---':
            if current_exercise:
                raw_exercises.append('\n'.join(current_exercise))
                current_exercise = []
        else:
            if line or current_exercise:  # Garder les lignes vides à l'intérieur
                current_exercise.append(line)
    
    # Ajouter le dernier exercice
    if current_exercise:
        raw_exercises.append('\n'.join(current_exercise))
    
    # Si pas de '---', tout est un exercice
    if not raw_exercises:
        raw_exercises = [text.strip()]
    
    for raw in raw_exercises:
        if not raw.strip():
            continue
            
        exercise = {
            'question_fr': '',
            'question_en': '',
            'options_fr': '',
            'options_en': '',
            'reponse_fr': '',
            'reponse_en': '',
            'explication_fr': '',
            'explication_en': '',
            'temps': default_time
        }
        
        lines = raw.strip().split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip().lower()
                value = value.strip()
                
                if key == 'question_fr':
                    exercise['question_fr'] = value
                elif key == 'question_en':
                    exercise['question_en'] = value
                elif key == 'options_fr':
                    exercise['options_fr'] = value
                elif key == 'options_en':
                    exercise['options_en'] = value
                elif key == 'réponse_fr' or key == 'reponse_fr':
                    exercise['reponse_fr'] = value
                elif key == 'réponse_en' or key == 'reponse_en':
                    exercise['reponse_en'] = value
                elif key == 'explication_fr':
                    exercise['explication_fr'] = value
                elif key == 'explication_en':
                    exercise['explication_en'] = value
                elif key == 'temps' or key == 'time':
                    try:
                        exercise['temps'] = int(value)
                    except:
                        exercise['temps'] = default_time
        
        if exercise['question_fr'] or exercise['question_en']:
            exercises.append(exercise)
    
    return exercises


def parse_bilingual_lessons(text):
    """
    Parse les leçons au format bilingue avec objectifs d'apprentissage
    
    Format attendu:
    titre_fr: Titre français
    titre_en: Titre anglais
    objectif_fr: Objectif d'apprentissage en français
    objectif_en: Learning objective in English
    --- (séparateur entre les leçons)
    """
    lessons = []
    
    # Sépare les leçons par '---' sur ligne seule
    raw_lessons = []
    current_lesson = []
    
    for line in text.strip().split('\n'):
        line = line.rstrip()  # Garder les espaces à droite pour le formatage
        if line == '---':
            if current_lesson:
                raw_lessons.append('\n'.join(current_lesson))
                current_lesson = []
        else:
            if line or current_lesson:  # Garder les lignes vides à l'intérieur
                current_lesson.append(line)
    
    # Ajouter la dernière leçon
    if current_lesson:
        raw_lessons.append('\n'.join(current_lesson))
    
    # Si pas de '---', tout est une leçon
    if not raw_lessons:
        raw_lessons = [text.strip()]
    
    for raw in raw_lessons:
        if not raw.strip():
            continue
            
        lesson = {
            'titre_fr': '',
            'titre_en': '',
            'objectif_fr': '',
            'objectif_en': '',
            'description_fr': '',  # Optionnel
            'description_en': '',  # Optionnel
            'keywords_fr': '',     # Optionnel
            'keywords_en': ''      # Optionnel
        }
        
        lines = raw.strip().split('\n')
        current_field = None
        current_text = []
        
        for line in lines:
            line = line.rstrip()
            if not line:
                if current_field and current_text:
                    # Ajouter une ligne vide dans le texte multiligne
                    current_text.append('')
                continue
                
            # Cherche un nouveau champ
            if ':' in line and len(line.split(':', 1)[0].strip().split()) <= 2:
                # Si on a déjà un champ en cours, le sauvegarder
                if current_field and current_text:
                    lesson[current_field] = '\n'.join(current_text).strip()
                
                # Démarrer un nouveau champ
                key, value = line.split(':', 1)
                key = key.strip().lower()
                value = value.strip()
                
                # Mapping des clés
                field_map = {
                    'titre_fr': 'titre_fr',
                    'titre_français': 'titre_fr',
                    'titre_francais': 'titre_fr',
                    'french_title': 'titre_fr',
                    'fr_title': 'titre_fr',
                    
                    'titre_en': 'titre_en',
                    'titre_anglais': 'titre_en',
                    'english_title': 'titre_en',
                    'en_title': 'titre_en',
                    'title_en': 'titre_en',
                    
                    'objectif_fr': 'objectif_fr',
                    'objectif_français': 'objectif_fr',
                    'objectif_francais': 'objectif_fr',
                    'french_objective': 'objectif_fr',
                    'fr_objective': 'objectif_fr',
                    'learning_objective_fr': 'objectif_fr',
                    
                    'objectif_en': 'objectif_en',
                    'objectif_anglais': 'objectif_en',
                    'english_objective': 'objectif_en',
                    'en_objective': 'objectif_en',
                    'learning_objective_en': 'objectif_en',
                    
                    'description_fr': 'description_fr',
                    'description_français': 'description_fr',
                    'description_francais': 'description_fr',
                    'french_description': 'description_fr',
                    
                    'description_en': 'description_en',
                    'description_anglais': 'description_en',
                    'english_description': 'description_en',
                    
                    'mots_cles_fr': 'keywords_fr',
                    'keywords_fr': 'keywords_fr',
                    'french_keywords': 'keywords_fr',
                    
                    'mots_cles_en': 'keywords_en',
                    'keywords_en': 'keywords_en',
                    'english_keywords': 'keywords_en'
                }
                
                current_field = field_map.get(key)
                if current_field:
                    current_text = [value] if value else []
                else:
                    current_field = None
                    current_text = []
            else:
                # Ligne de continuation pour le champ en cours
                if current_field:
                    current_text.append(line)
                elif line and line != '---':
                    # Si on n'a pas de champ défini, c'est peut-être un format simple
                    # On essaye de deviner le type de contenu
                    if not lesson['titre_fr']:
                        lesson['titre_fr'] = line
                    elif not lesson['titre_en']:
                        lesson['titre_en'] = line
                    elif not lesson['objectif_fr']:
                        lesson['objectif_fr'] = line
                    elif not lesson['objectif_en']:
                        lesson['objectif_en'] = line
        
        # Sauvegarder le dernier champ
        if current_field and current_text:
            lesson[current_field] = '\n'.join(current_text).strip()
        
        # Validation et nettoyage
        # Si titre_en est vide mais titre_fr existe, copier titre_fr
        if lesson['titre_fr'] and not lesson['titre_en']:
            lesson['titre_en'] = lesson['titre_fr']
        
        # Si objectif_en est vide mais objectif_fr existe, copier objectif_fr
        if lesson['objectif_fr'] and not lesson['objectif_en']:
            lesson['objectif_en'] = lesson['objectif_fr']
        
        # Vérifier qu'on a au moins un titre
        if lesson['titre_fr'] or lesson['titre_en']:
            lessons.append(lesson)
    
    return lessons


def import_lessons_from_text(text, unite_id, db_session, Lecon):
    """
    Importe des leçons depuis un texte formaté vers la base de données
    
    Args:
        text: Texte formaté avec les leçons
        unite_id: ID de l'unité cible
        db_session: Session SQLAlchemy
        Lecon: Modèle Lecon à importer
    
    Returns:
        dict: Résultat de l'importation
    """
    lessons_data = parse_bilingual_lessons(text)
    
    if not lessons_data:
        return {
            'success': False,
            'message': 'Aucune leçon valide trouvée dans le texte',
            'lessons_added': 0
        }
    
    added_lessons = []
    skipped_lessons = []
    
    try:
        for i, lesson_data in enumerate(lessons_data):
            # Vérifier si une leçon avec ce titre existe déjà
            existing = db_session.query(Lecon).filter_by(
                titre_fr=lesson_data['titre_fr'],
                unite_id=unite_id
            ).first()
            
            if existing:
                skipped_lessons.append({
                    'index': i + 1,
                    'titre': lesson_data['titre_fr'],
                    'reason': 'Leçon déjà existante'
                })
                continue
            
            # Créer la nouvelle leçon
            new_lesson = Lecon(
                titre_fr=lesson_data['titre_fr'],
                titre_en=lesson_data['titre_en'],
                objectif_fr=lesson_data['objectif_fr'],
                objectif_en=lesson_data['objectif_en'],
                unite_id=unite_id
            )
            
            db_session.add(new_lesson)
            db_session.flush()  # Pour obtenir l'ID
            
            added_lessons.append({
                'id': new_lesson.id,
                'titre_fr': new_lesson.titre_fr,
                'titre_en': new_lesson.titre_en
            })
        
        db_session.commit()
        
        return {
            'success': True,
            'message': f'{len(added_lessons)} leçon(s) ajoutée(s) avec succès',
            'lessons_added': len(added_lessons),
            'skipped': len(skipped_lessons),
            'added_lessons': added_lessons,
            'skipped_lessons': skipped_lessons
        }
        
    except Exception as e:
        db_session.rollback()
        return {
            'success': False,
            'message': f'Erreur lors de l\'importation: {str(e)}',
            'lessons_added': 0
        }


def get_lesson_template():
    """
    Retourne un modèle de texte pour les leçons
    """
    return """titre_fr: Les fractions simples
titre_en: Simple fractions
objectif_fr: Comprendre le concept de fraction et sa représentation visuelle
objectif_en: Understand the concept of fractions and their visual representation
description_fr: Cette leçon introduit le concept de fraction comme partie d'un tout.
description_en: This lesson introduces the concept of fractions as parts of a whole.

---
titre_fr: Addition de fractions
titre_en: Fraction addition
objectif_fr: Savoir additionner des fractions avec le même dénominateur
objectif_en: Know how to add fractions with the same denominator
description_fr: Apprendre à combiner des fractions ayant le même dénominateur.
description_en: Learn to combine fractions with the same denominator.

---
titre_fr: Fractions équivalentes
titre_en: Equivalent fractions
objectif_fr: Identifier et créer des fractions équivalentes
objectif_en: Identify and create equivalent fractions"""


def format_lessons_for_display(lessons):
    """
    Formate les leçons pour un affichage lisible
    """
    if not lessons:
        return "Aucune leçon à afficher"
    
    output = []
    for i, lesson in enumerate(lessons, 1):
        output.append(f"Leçon {i}:")
        output.append(f"  🇫🇷 Titre: {lesson['titre_fr']}")
        output.append(f"  🇬🇧 Title: {lesson['titre_en']}")
        
        if lesson['objectif_fr']:
            output.append(f"  🎯 Objectif FR: {lesson['objectif_fr']}")
        if lesson['objectif_en']:
            output.append(f"  🎯 Objective EN: {lesson['objectif_en']}")
        
        if lesson.get('description_fr'):
            output.append(f"  📝 Description FR: {lesson['description_fr']}")
        if lesson.get('description_en'):
            output.append(f"  📝 Description EN: {lesson['description_en']}")
        
        if i < len(lessons):
            output.append("─" * 40)
    
    return '\n'.join(output)


def parse_simple_lesson_format(text):
    """
    Format simplifié : 4 lignes par leçon
    Ligne 1: Titre français
    Ligne 2: Titre anglais
    Ligne 3: Objectif français
    Ligne 4: Objectif anglais
    """
    lessons = []
    lines = [line.strip() for line in text.strip().split('\n') if line.strip()]
    
    for i in range(0, len(lines), 4):
        if i + 3 < len(lines):
            lesson = {
                'titre_fr': lines[i],
                'titre_en': lines[i + 1],
                'objectif_fr': lines[i + 2],
                'objectif_en': lines[i + 3]
            }
            lessons.append(lesson)
    
    return lessons

# Dans votre app.py ou routes.py
@app.route('/admin/import-lessons', methods=['GET', 'POST'])
def admin_import_lessons():
    """Page d'importation de leçons en lot"""
    
    # 🔐 VÉRIFICATION D'AUTHENTIFICATION
    if not session.get('is_admin') and not session.get('user_id'):
        flash('Veuillez vous connecter en tant qu\'administrateur', 'error')
        return redirect(url_for('login_admin'))
    
    if request.method == 'GET':
        # ID d'unité passé en paramètre
        unite_id = request.args.get('unite_id')
        
        # Récupérer TOUTES les données nécessaires
        niveaux = Niveau.query.order_by(Niveau.id).all()
        matieres = Matiere.query.all()
        unites = Unite.query.all()
        
        # Formater les données pour le template
        niveaux_data = []
        for niveau in niveaux:
            niveaux_data.append({
                'id': niveau.id,
                'nom': niveau.nom
            })
        
        matieres_data = []
        for matiere in matieres:
            matieres_data.append({
                'id': matiere.id,
                'nom': matiere.nom,
                'niveau_id': matiere.niveau_id
            })
        
        unites_data = []
        for unite in unites:
            unites_data.append({
                'id': unite.id,
                'nom': unite.nom,
                'matiere_id': unite.matiere_id,
                'matiere_nom': unite.matiere.nom if unite.matiere else '',
                'matiere_niveau_nom': unite.matiere.niveau.nom if unite.matiere and unite.matiere.niveau else '',
                'lecons_count': len(unite.lecons) if unite.lecons else 0
            })
        
        template = """titre_fr: Les fractions simples
titre_en: Simple fractions
objectif_fr: Comprendre le concept de fraction et sa représentation
objectif_en: Understand the concept of fractions and their representation

---
titre_fr: Addition de fractions
titre_en: Fraction addition
objectif_fr: Savoir additionner des fractions avec même dénominateur
objectif_en: Know how to add fractions with the same denominator

---
titre_fr: Fractions équivalentes
titre_en: Equivalent fractions
objectif_fr: Identifier et créer des fractions équivalentes
objectif_en: Identify and create equivalent fractions"""
        
        # AJOUTER TOUTES LES VARIABLES AU TEMPLATE
        return render_template('import_lessons.html', 
                             niveaux=niveaux_data,        # <-- IMPORTANT
                             matieres=matieres_data,      # <-- IMPORTANT
                             unites=unites_data,          # <-- IMPORTANT
                             unite_id=unite_id,
                             template=template,
                             lang=session.get('lang', 'fr'))
    
    # POST: Importer les leçons
    unite_id = request.form.get('unite_id')
    lessons_text = request.form.get('lessons_text')
    
    if not unite_id or not lessons_text:
        return jsonify({
            'success': False,
            'message': 'Unité ID et texte des leçons requis'
        }), 400
    
    result = import_lessons_from_text(lessons_text, int(unite_id), db.session, Lecon)
    
    return jsonify(result)


@app.route('/admin/parse-lessons-preview', methods=['POST'])
def parse_lessons_preview():
    """Prévisualiser le parsing des leçons"""
    
    # Même vérification d'authentification
    if not session.get('is_admin') and not session.get('user_id'):
        return jsonify({
            'success': False,
            'message': 'Non autorisé'
        }), 403
    
    lessons_text = request.form.get('lessons_text', '')
    
    if not lessons_text:
        return jsonify({
            'count': 0,
            'lessons': [],
            'formatted': 'Aucun texte fourni'
        })
    
    lessons = parse_bilingual_lessons(lessons_text)
    
    # Formater pour l'affichage
    formatted = ""
    for i, lesson in enumerate(lessons[:5], 1):  # Limiter à 5 pour l'aperçu
        formatted += f"Leçon {i}:\n"
        formatted += f"  🇫🇷 {lesson['titre_fr']}\n"
        formatted += f"  🇬🇧 {lesson['titre_en']}\n"
        if lesson['objectif_fr']:
            formatted += f"  🎯 FR: {lesson['objectif_fr'][:100]}{'...' if len(lesson['objectif_fr']) > 100 else ''}\n"
        if lesson['objectif_en']:
            formatted += f"  🎯 EN: {lesson['objectif_en'][:100]}{'...' if len(lesson['objectif_en']) > 100 else ''}\n"
        formatted += "-" * 40 + "\n"
    
    return jsonify({
        'count': len(lessons),
        'lessons': lessons[:10],  # Limiter à 10 pour l'aperçu
        'formatted': formatted
    })

@app.route('/admin/batch-create-exercises')
def redirect_to_batch_import():
    return redirect(url_for('batch_create_exercises_admin'))

from flask_wtf.csrf import generate_csrf
@app.route('/admin/exercises/batch-import', methods=['GET', 'POST'])
def batch_create_exercises_admin():
    """Importation d'exercices en lot par l'admin"""
    
    # VÉRIFICATION AVEC LES DEUX CLÉS POSSIBLES (is_admin ET user_id)
    if not session.get('is_admin') and not session.get('user_id'):
        flash('Veuillez vous connecter en tant qu\'administrateur', 'error')
        return redirect(url_for('login_admin'))
    
    # Récupérer tous les niveaux pour le menu déroulant
    niveaux = Niveau.query.order_by(Niveau.id).all()
    matieres = []
    unites = []
    lecons = []
    
    # Initialiser les sélections
    selected_niveau = None
    selected_matiere = None
    selected_unite = None
    selected_lecon = None
    
    # Récupérer les paramètres GET pour la hiérarchie
    niveau_id = request.args.get('niveau_id', type=int)
    matiere_id = request.args.get('matiere_id', type=int)
    unite_id = request.args.get('unite_id', type=int)
    lecon_id = request.args.get('lecon_id', type=int)
    
    # Récupérer les données en fonction des sélections
    if niveau_id:
        selected_niveau = Niveau.query.get(niveau_id)
        matieres = Matiere.query.filter_by(niveau_id=niveau_id).order_by(Matiere.id).all()
    
    if matiere_id:
        selected_matiere = Matiere.query.get(matiere_id)
        unites = Unite.query.filter_by(matiere_id=matiere_id).order_by(Unite.id).all()
    
    if unite_id:
        selected_unite = Unite.query.get(unite_id)
        lecons = Lecon.query.filter_by(unite_id=unite_id).order_by(Lecon.id).all()
    
    if lecon_id:
        selected_lecon = Lecon.query.get(lecon_id)
    
    if request.method == 'POST':
        # Vérifier qu'une leçon est sélectionnée
        lecon_id = request.form.get('lecon_id', type=int)
        if not lecon_id:
            flash('Veuillez sélectionner une leçon', 'error')
            return render_template('batch_exercises_admin.html',
                                 lang=session.get('lang', 'fr'),
                                 niveaux=niveaux,
                                 matieres=matieres,
                                 unites=unites,
                                 lecons=lecons,
                                 selected_niveau=selected_niveau,
                                 selected_matiere=selected_matiere,
                                 selected_unite=selected_unite,
                                 selected_lecon=selected_lecon)
        
        selected_lecon = Lecon.query.get_or_404(lecon_id)
        exercises_text = request.form.get('exercises_text', '').strip()
        default_time = request.form.get('temps_defaut', 120, type=int)
        
        if not exercises_text:
            flash('Veuillez saisir des exercices', 'error')
            return render_template('batch_exercises_admin.html',
                                 lang=session.get('lang', 'fr'),
                                 niveaux=niveaux,
                                 matieres=matieres,
                                 unites=unites,
                                 lecons=lecons,
                                 selected_niveau=selected_niveau,
                                 selected_matiere=selected_matiere,
                                 selected_unite=selected_unite,
                                 selected_lecon=selected_lecon)
        
        try:
            # Parser les exercices
            exercises = parse_bilingual_exercises(exercises_text, default_time)
            
            if not exercises:
                flash('Aucun exercice valide détecté', 'error')
                return render_template('batch_exercises_admin.html',
                                     lang=session.get('lang', 'fr'),
                                     niveaux=niveaux,
                                     matieres=matieres,
                                     unites=unites,
                                     lecons=lecons,
                                     selected_niveau=selected_niveau,
                                     selected_matiere=selected_matiere,
                                     selected_unite=selected_unite,
                                     selected_lecon=selected_lecon)
            
            # Validation des champs obligatoires
            valid_exercises = []
            invalid_count = 0
            
            for i, ex in enumerate(exercises):
                if not ex['question_fr']:
                    flash(f'Exercice {i+1}: Question_fr manquante', 'warning')
                    invalid_count += 1
                elif not ex['question_en']:
                    flash(f'Exercice {i+1}: Question_en manquante', 'warning')
                    invalid_count += 1
                else:
                    valid_exercises.append(ex)
            
            if not valid_exercises:
                flash('Aucun exercice valide avec les versions française et anglaise', 'error')
                return render_template('batch_exercises_admin.html',
                                     lang=session.get('lang', 'fr'),
                                     niveaux=niveaux,
                                     matieres=matieres,
                                     unites=unites,
                                     lecons=lecons,
                                     selected_niveau=selected_niveau,
                                     selected_matiere=selected_matiere,
                                     selected_unite=selected_unite,
                                     selected_lecon=selected_lecon)
            
            # Créer les exercices dans la base de données
            created_count = 0
            errors = []
            
            for ex in valid_exercises:
                try:
                    exercice = Exercice(
                        lecon_id=lecon_id,
                        question_fr=ex['question_fr'],
                        question_en=ex['question_en'],
                        options_fr=ex['options_fr'],
                        options_en=ex['options_en'],
                        reponse_fr=ex['reponse_fr'],
                        reponse_en=ex['reponse_en'],
                        explication_fr=ex['explication_fr'],
                        explication_en=ex['explication_en'],
                        temps=ex['temps']
                    )
                    
                    db.session.add(exercice)
                    created_count += 1
                    
                except Exception as e:
                    errors.append(f"Exercice {ex.get('numero', 'N/A')}: {str(e)}")
            
            db.session.commit()
            
            # Statistiques
            with_options = sum(1 for ex in valid_exercises if ex['options_fr'] or ex['options_en'])
            with_explanations = sum(1 for ex in valid_exercises if ex['explication_fr'] or ex['explication_en'])
            avg_time = sum(ex['temps'] for ex in valid_exercises) // len(valid_exercises) if valid_exercises else 0
            
            flash(f'{created_count} exercice(s) importé(s) avec succès!', 'success')
            
            if invalid_count > 0:
                flash(f'{invalid_count} exercice(s) ignoré(s) car incomplets', 'warning')
            
            if errors:
                flash(f"Quelques erreurs: {' | '.join(errors[:2])}", 'warning')
            
            # Afficher la page de confirmation
            return render_template('batch_exercises_confirm.html',
                                 lang=session.get('lang', 'fr'),
                                 count=created_count,
                                 lecon=selected_lecon,
                                 niveau=selected_niveau,
                                 matiere=selected_matiere,
                                 unite=selected_unite,
                                 with_options=with_options,
                                 with_explanations=with_explanations,
                                 avg_time=avg_time)
            
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de l\'importation: {str(e)}', 'error')
    
    # GET request ou POST avec erreurs
    return render_template('batch_exercises_admin.html',
                         lang=session.get('lang', 'fr'),
                         niveaux=niveaux,
                         matieres=matieres,
                         unites=unites,
                         lecons=lecons,
                         selected_niveau=selected_niveau,
                         selected_matiere=selected_matiere,
                         selected_unite=selected_unite,
                         selected_lecon=selected_lecon)
    
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
    import json
    from sqlalchemy import func
    from sqlalchemy.orm import joinedload

    username = request.args.get("username")
    lecon_id = request.args.get("lecon_id")
    lang = request.args.get("lang", "fr")
    show_feedback = request.args.get("show_feedback", "false").lower() == "true"

    exercice_id_param = request.args.get("exercice_id")
    index_param = request.args.get("index", "0")

    try:
        index = int(index_param)
    except (ValueError, TypeError):
        index = 0

    # ============================================================
    # MESSAGES BILINGUES
    # ============================================================

    msg_param_manquant = (
        "Missing parameters to access the exercise."
        if lang == "en"
        else "Paramètres manquants pour accéder à l'exercice."
    )

    msg_eleve_introuvable = (
        "Student not found."
        if lang == "en"
        else "Élève non trouvé."
    )

    msg_acces_refuse = (
        "Access denied. Your subscription or trial may have expired."
        if lang == "en"
        else "Accès refusé. Votre abonnement ou essai a peut-être expiré."
    )

    msg_lecon_introuvable = (
        "Lesson not found."
        if lang == "en"
        else "Leçon non trouvée."
    )

    msg_aucun_exercice = (
        "No exercise is available for this lesson."
        if lang == "en"
        else "Aucun exercice disponible pour cette leçon."
    )

    libelle_bouton_continuer = (
        "Continue with the recommended exercise"
        if lang == "en"
        else "Continuer avec l’exercice recommandé"
    )

    libelle_mode = (
        "AI-guided mode"
        if lang == "en"
        else "Mode accompagné par IA"
    )

    # ============================================================
    # 1. VALIDATION DES PARAMÈTRES
    # ============================================================

    if not username or not lecon_id:
        flash(msg_param_manquant, "danger")
        return redirect(url_for("index", lang=lang))

    eleve = (
        User.query
        .options(joinedload(User.niveau))
        .filter_by(username=username)
        .first()
    )

    if not eleve:
        flash(msg_eleve_introuvable, "danger")
        return redirect(url_for("index", lang=lang))

    if not eleve.a_acces_plateforme():
        flash(msg_acces_refuse, "danger")
        return redirect(url_for("dashboard_eleve", username=username, lang=lang))

    try:
        lecon_id_int = int(lecon_id)
    except (ValueError, TypeError):
        flash(msg_lecon_introuvable, "danger")
        return redirect(url_for("dashboard_eleve", username=username, lang=lang))

    lecon = (
        Lecon.query
        .options(joinedload(Lecon.unite).joinedload(Unite.matiere))
        .filter(Lecon.id == lecon_id_int)
        .first()
    )

    if not lecon:
        flash(msg_lecon_introuvable, "danger")
        return redirect(url_for("dashboard_eleve", username=username, lang=lang))

    # ============================================================
    # 2. LISTE LÉGÈRE DES IDS DES EXERCICES
    # ============================================================

    exercice_ids = [
        row[0]
        for row in (
            db.session.query(Exercice.id)
            .filter(Exercice.lecon_id == lecon.id)
            .order_by(
                func.coalesce(Exercice.ordre_progression, 999999).asc(),
                Exercice.id.asc()
            )
            .all()
        )
    ]

    total_exercices = len(exercice_ids)

    if total_exercices == 0:
        flash(msg_aucun_exercice, "info")
        return redirect(url_for("dashboard_eleve", username=username, lang=lang))

    # ============================================================
    # 3. RÉPONSES DÉJÀ COMPLÉTÉES EN UNE SEULE REQUÊTE
    # ============================================================

    completed_exercise_ids = {
        row[0]
        for row in (
            db.session.query(StudentResponse.exercice_id)
            .filter(StudentResponse.user_id == eleve.id)
            .filter(StudentResponse.exercice_id.in_(exercice_ids))
            .filter(StudentResponse.exercice_id.isnot(None))
            .distinct()
            .all()
        )
        if row[0]
    }

    exercices_completes = len(completed_exercise_ids)

    progression_pourcentage = (
        int((exercices_completes / total_exercices) * 100)
        if total_exercices > 0
        else 0
    )

    reponses_status = [
        "completed" if ex_id in completed_exercise_ids else "not_started"
        for ex_id in exercice_ids
    ]

    # ============================================================
    # 4. DÉTERMINER L’EXERCICE ACTUEL
    # ============================================================
    # Règles :
    # - Si exercice_id est fourni, on affiche cet exercice.
    # - S’il est déjà fait, on affiche sa réponse et sa rétroaction.
    # - Si aucun exercice_id n’est fourni, on reprend au premier exercice non fait.
    # - Si tous les exercices sont faits, on affiche le dernier exercice fait avec rétroaction.

    exercice_actuel = None
    reprise_automatique = False

    if exercice_id_param:
        try:
            exercice_id_int = int(exercice_id_param)
        except (ValueError, TypeError):
            exercice_id_int = None

        if exercice_id_int and exercice_id_int in exercice_ids:
            exercice_actuel = (
                Exercice.query
                .filter(
                    Exercice.id == exercice_id_int,
                    Exercice.lecon_id == lecon.id
                )
                .first()
            )
            index = exercice_ids.index(exercice_id_int)

    if not exercice_actuel:
        premier_non_fait_id = None

        for ex_id in exercice_ids:
            if ex_id not in completed_exercise_ids:
                premier_non_fait_id = ex_id
                break

        if premier_non_fait_id:
            exercice_actuel = db.session.get(Exercice, premier_non_fait_id)
            index = exercice_ids.index(premier_non_fait_id)
            reprise_automatique = True
        else:
            if index < 0:
                index = 0

            if index >= total_exercices:
                index = total_exercices - 1

            exercice_actuel = db.session.get(Exercice, exercice_ids[index])

    if not exercice_actuel:
        flash(msg_aucun_exercice, "info")
        return redirect(url_for("dashboard_eleve", username=username, lang=lang))

    # ============================================================
    # 5. RÉPONSE EXISTANTE ET RÉTROACTION PROPRE
    # ============================================================

    reponse = StudentResponse.query.filter_by(
        user_id=eleve.id,
        exercice_id=exercice_actuel.id
    ).first()

    exercice_deja_fait = reponse is not None

    # Anti-gaspillage de tokens : un exercice déjà fait n’est jamais resoumis.
    # On force l’affichage direct de la réponse et de la rétroaction.
    if exercice_deja_fait:
        show_feedback = True

    reponse_existante = None
    feedback_data = None
    feedback_a_afficher = None

    if reponse:
        reponse_existante = reponse.reponse_eleve

        try:
            if reponse.analyse_ia and reponse.analyse_ia.strip().startswith("{"):
                feedback_data = json.loads(reponse.analyse_ia)
            elif reponse.analyse_ia:
                feedback_data = {
                    "current_feedback": reponse.analyse_ia,
                    "current_stars": reponse.etoiles or 0,
                    "symbolic_verification": {},
                    "adaptive_next": {},
                    "bayesian_diagnostic": {},
                    "metadata": {}
                }
        except Exception as e:
            print(f"⚠️ Erreur parsing feedback exercice {exercice_actuel.id}: {e}")
            feedback_data = {
                "current_feedback": (
                    "La rétroaction existe, mais elle n’a pas pu être lue correctement."
                    if lang == "fr"
                    else "Feedback exists, but it could not be read correctly."
                ),
                "current_stars": reponse.etoiles or 0,
                "symbolic_verification": {},
                "adaptive_next": {},
                "bayesian_diagnostic": {},
                "metadata": {}
            }

    if feedback_data:
        feedback_a_afficher = {
            "analyse": feedback_data.get("current_feedback", ""),
            "etoiles": feedback_data.get("current_stars", 0),
            "symbolic": feedback_data.get("symbolic_verification", {}),
            "adaptive": feedback_data.get("adaptive_next", {}),
            "bayesian": feedback_data.get("bayesian_diagnostic", {}),
            "metadata": feedback_data.get("metadata", {})
        }

    if exercice_deja_fait and not feedback_a_afficher:
        feedback_a_afficher = {
            "analyse": (
                "La réponse a déjà été enregistrée. La rétroaction détaillée n’est pas disponible pour le moment, mais aucun nouveau calcul ne sera lancé."
                if lang == "fr"
                else "This answer has already been saved. Detailed feedback is not available right now, but no new calculation will be launched."
            ),
            "etoiles": reponse.etoiles if reponse else 0,
            "symbolic": {},
            "adaptive": {},
            "bayesian": {},
            "metadata": {}
        }

    # ============================================================
    # 6. NAVIGATION ADAPTATIVE AVEC SÉCURITÉ
    # ============================================================
    # Les exercices déjà faits peuvent être revus depuis la progression,
    # mais les exercices non faits restent verrouillés en mode IA.

    bouton_precedent = None
    bouton_suivant = None
    prochain_non_fait_id = None

    prochain_adaptatif = session.get("prochain_exercice_adaptatif")

    # 1. Prochain exercice recommandé par le moteur adaptatif
    if (
        show_feedback
        and prochain_adaptatif
        and prochain_adaptatif.get("lecon_id") == lecon.id
        and prochain_adaptatif.get("exercice_source_id") == exercice_actuel.id
        and prochain_adaptatif.get("prochain_exercice_id")
    ):
        prochain_exercice_id = prochain_adaptatif.get("prochain_exercice_id")

        try:
            prochain_exercice_id = int(prochain_exercice_id)
        except (ValueError, TypeError):
            prochain_exercice_id = None

        if (
            prochain_exercice_id
            and prochain_exercice_id in exercice_ids
            and prochain_exercice_id not in completed_exercise_ids
        ):
            bouton_suivant = url_for(
                "exercice_sequentiel_progressif",
                username=username,
                lecon_id=lecon.id,
                lang=lang,
                exercice_id=prochain_exercice_id
            )

    # 2. Sécurité : si aucun prochain exercice adaptatif n'est disponible,
    # proposer le premier exercice non encore fait.
    #
    # IMPORTANT :
    # si la stratégie actuelle est "verification", on peut permettre à
    # l'élève de continuer, mais on NE DOIT PAS remplacer cette stratégie
    # par "fallback", car cela ferait perdre l'information qu'une réponse
    # précédente nécessite une vérification.

    if show_feedback and not bouton_suivant:

        prochain_non_fait_id = None

        strategie_actuelle = None
        requires_review = False

        if isinstance(prochain_adaptatif, dict):
            strategie_actuelle = prochain_adaptatif.get("strategie")
            requires_review = bool(
                prochain_adaptatif.get("requires_review", False)
            )

        for ex_id in exercice_ids:
            if (
                ex_id != exercice_actuel.id
                and ex_id not in completed_exercise_ids
            ):
                prochain_non_fait_id = ex_id
                break

        if prochain_non_fait_id:

            bouton_suivant = url_for(
                "exercice_sequentiel_progressif",
                username=username,
                lecon_id=lecon.id,
                lang=lang,
                exercice_id=prochain_non_fait_id
            )

            # ====================================================
            # CAS 1 : LA RÉPONSE PRÉCÉDENTE EST À VÉRIFIER
            # ====================================================

            if (
                strategie_actuelle == "verification"
                or requires_review
            ):

                session["prochain_exercice_adaptatif"] = {
                    "lecon_id": lecon.id,
                    "exercice_source_id": exercice_actuel.id,
                    "prochain_exercice_id": prochain_non_fait_id,

                    "strategie": "verification",

                    "raison": (
                        "La réponse précédente nécessite une vérification. "
                        "L'élève peut néanmoins continuer avec un exercice "
                        "non encore fait, sans remédiation ni baisse de difficulté."
                        if lang == "fr"
                        else
                        "The previous answer requires review. "
                        "The student may continue with an unfinished exercise "
                        "without remediation or a reduction in difficulty."
                    ),

                    "niveau_cible": (
                        prochain_adaptatif.get("niveau_cible")
                        if isinstance(prochain_adaptatif, dict)
                        else exercice_actuel.niveau_difficulte
                    ),

                    "notion_cible": (
                        prochain_adaptatif.get("notion_cible")
                        if isinstance(prochain_adaptatif, dict)
                        else exercice_actuel.notion_cible
                    ),

                    "requires_review": True,
                    "adaptation_bloquee": True,

                    "validation_verdict": (
                        prochain_adaptatif.get("validation_verdict", "uncertain")
                        if isinstance(prochain_adaptatif, dict)
                        else "uncertain"
                    ),

                    "validation_confidence": (
                        prochain_adaptatif.get("validation_confidence")
                        if isinstance(prochain_adaptatif, dict)
                        else None
                    ),

                    "validation_method": (
                        prochain_adaptatif.get("validation_method")
                        if isinstance(prochain_adaptatif, dict)
                        else None
                    )
                }

                if feedback_a_afficher is not None:

                    feedback_a_afficher["adaptive"] = {
                        "strategie": "verification",

                        "raison": (
                            "Cette réponse nécessite une vérification. "
                            "Elle n'a pas été considérée comme fausse et "
                            "n'a déclenché aucune remédiation."
                            if lang == "fr"
                            else
                            "This answer requires review. "
                            "It was not marked incorrect and did not trigger remediation."
                        ),

                        "prochain_exercice_id": prochain_non_fait_id,

                        "requires_review": True
                    }

                print(
                    f"⚠️ Réponse à vérifier : "
                    f"poursuite autorisée vers l'exercice "
                    f"{prochain_non_fait_id}, sans remédiation."
                )

            # ====================================================
            # CAS 2 : AUCUNE RECOMMANDATION ADAPTATIVE
            # ====================================================

            else:

                session["prochain_exercice_adaptatif"] = {
                    "lecon_id": lecon.id,
                    "exercice_source_id": exercice_actuel.id,
                    "prochain_exercice_id": prochain_non_fait_id,

                    "strategie": "fallback",

                    "raison": (
                        "Prochain exercice non encore fait, utilisé car "
                        "aucune recommandation adaptative n'était disponible."
                        if lang == "fr"
                        else
                        "Next unfinished exercise used because no adaptive "
                        "recommendation was available."
                    ),

                    "requires_review": False,
                    "adaptation_bloquee": False
                }

                if feedback_a_afficher is not None:

                    feedback_a_afficher["adaptive"] = {
                        "strategie": "fallback",

                        "raison": (
                            "Le système propose maintenant le prochain "
                            "exercice non encore fait."
                            if lang == "fr"
                            else
                            "The system now suggests the next unfinished exercise."
                        ),

                        "prochain_exercice_id": prochain_non_fait_id,

                        "requires_review": False
                    }

            session.modified = True

    bouton_terminer = url_for("dashboard_eleve", username=username, lang=lang)

    # ============================================================
    # 7. INFORMATIONS BILINGUES
    # ============================================================

    question = (
        exercice_actuel.question_en
        if lang == "en" and exercice_actuel.question_en
        else exercice_actuel.question_fr
    )

    # ============================================================
    # 7A. OPTIONS DE QCM POUR L'INTERFACE ÉLÈVE
    # ============================================================
    #
    # Les options sont stockées dans options_fr / options_en sous
    # une forme comme :
    #
    #   A) -4/3, B) 3/4, C) 4/3, D) -3/4
    #
    # On les transforme ici en une liste structurée afin que le
    # template puisse les afficher comme de vrais choix cliquables.
    #
    # IMPORTANT :
    # la réponse libre reste disponible. Un élève peut donc choisir
    # "B" OU écrire "3/4", "0.75", etc.
    # ============================================================

    options_brutes = (
        exercice_actuel.options_en
        if lang == "en" and exercice_actuel.options_en
        else exercice_actuel.options_fr
    )

    options_affichees = []

    if options_brutes:
        import re

        motif_options = re.compile(
            r"(?:^|,\s*)"
            r"([A-H])\s*[\)\].:\-]\s*"
            r"(.*?)"
            r"(?=,\s*[A-H]\s*[\)\].:\-]\s*|$)",
            re.IGNORECASE | re.DOTALL
        )

        for match in motif_options.finditer(options_brutes.strip()):
            lettre = match.group(1).upper()
            texte_option = match.group(2).strip()

            if texte_option:
                options_affichees.append({
                    "label": lettre,
                    "value": texte_option,
                    "display": f"{lettre}) {texte_option}"
                })

        # Fallback prudent si le format ne contient pas explicitement
        # A), B), C)... mais reste une liste séparée par des virgules.
        if not options_affichees:
            morceaux = [
                morceau.strip()
                for morceau in options_brutes.split(",")
                if morceau.strip()
            ]

            for position, morceau in enumerate(morceaux[:8]):
                lettre = chr(ord("A") + position)

                options_affichees.append({
                    "label": lettre,
                    "value": morceau,
                    "display": f"{lettre}) {morceau}"
                })

    corrige_disponible = bool(
        exercice_actuel.reponse_en
        if lang == "en" and exercice_actuel.reponse_en
        else exercice_actuel.reponse_fr
    )

    titre_lecon = (
        lecon.titre_en
        if lang == "en" and lecon.titre_en
        else lecon.titre_fr
    )

    nom_matiere = None

    if lecon.unite and lecon.unite.matiere:
        nom_matiere = (
            lecon.unite.matiere.nom_en
            if lang == "en" and lecon.unite.matiere.nom_en
            else lecon.unite.matiere.nom
        )

    # ============================================================
    # 8. LOGS
    # ============================================================

    print("========== EXERCICE SÉQUENTIEL ADAPTATIF ==========")
    print(f"👤 Élève : {eleve.username} | ID : {eleve.id}")
    print(f"📘 Leçon : {lecon.id} - {titre_lecon}")
    print(f"📚 Matière : {nom_matiere}")
    print(f"🧩 Exercice actuel : {exercice_actuel.id}")
    print(f"🔘 Options QCM affichées : {len(options_affichees)}")
    print(f"📊 Position : {index + 1}/{total_exercices}")
    print(f"✅ Complétés : {exercices_completes}/{total_exercices}")
    print(f"🔒 Exercice déjà fait : {exercice_deja_fait}")
    print(f"🔁 Reprise automatique : {reprise_automatique}")
    print(f"🧠 Prochain adaptatif : {session.get('prochain_exercice_adaptatif')}")
    print(f"➡️ Bouton suivant : {bouton_suivant}")
    print("===================================================")

    # ============================================================
    # 9. RENDU TEMPLATE
    # ============================================================

    return render_template(
        "exercice_sequentiel_progressif.html",
        eleve=eleve,
        username=username,
        lecon=lecon,
        titre_lecon=titre_lecon,
        nom_matiere=nom_matiere,
        exercice=exercice_actuel,
        question=question,
        options_affichees=options_affichees,
        options_brutes=options_brutes,
        index=index,
        total=total_exercices,
        total_exercices=total_exercices,
        exercice_ids=exercice_ids,
        progression_pourcentage=progression_pourcentage,
        exercices_completes=exercices_completes,
        reponse_existante=reponse_existante,
        reponse=reponse,
        reponses_status=reponses_status,
        corrige_disponible=corrige_disponible,
        feedback=feedback_a_afficher,
        show_feedback=show_feedback,
        lang=lang,
        bouton_precedent=bouton_precedent,
        bouton_suivant=bouton_suivant,
        bouton_terminer=bouton_terminer,
        mode_parcours="ia_guided",
        navigation_libre=False,
        libelle_mode=libelle_mode,
        libelle_bouton_continuer=libelle_bouton_continuer,
        exercice_deja_fait=exercice_deja_fait
    )


@app.route("/exercices-papier-crayon")
def exercices_papier_crayon():
    import re
    from sqlalchemy import func
    from sqlalchemy.orm import joinedload

    username = request.args.get("username")
    lecon_id = request.args.get("lecon_id")
    lang = request.args.get("lang", "fr")
    exercice_id_param = request.args.get("exercice_id")
    index_param = request.args.get("index", "0")
    show_corrige = request.args.get("show_corrige", "false").lower() == "true"

    try:
        index = int(index_param)
    except (ValueError, TypeError):
        index = 0

    msg_param_manquant = (
        "Missing parameters."
        if lang == "en"
        else "Paramètres manquants."
    )

    msg_eleve_introuvable = (
        "Student not found."
        if lang == "en"
        else "Élève non trouvé."
    )

    msg_acces_refuse = (
        "Access denied. Your subscription or trial may have expired."
        if lang == "en"
        else "Accès refusé. Votre abonnement ou essai a peut-être expiré."
    )

    msg_lecon_introuvable = (
        "Lesson not found."
        if lang == "en"
        else "Leçon non trouvée."
    )

    msg_aucun_exercice = (
        "No exercise is available for this lesson."
        if lang == "en"
        else "Aucun exercice disponible pour cette leçon."
    )

    if not username or not lecon_id:
        flash(msg_param_manquant, "danger")
        return redirect(url_for("index", lang=lang))

    eleve = (
        User.query
        .options(joinedload(User.niveau))
        .filter_by(username=username)
        .first()
    )

    if not eleve:
        flash(msg_eleve_introuvable, "danger")
        return redirect(url_for("index", lang=lang))

    if not eleve.a_acces_plateforme():
        flash(msg_acces_refuse, "danger")
        return redirect(url_for("dashboard_eleve", username=username, lang=lang))

    try:
        lecon_id_int = int(lecon_id)
    except (ValueError, TypeError):
        flash(msg_lecon_introuvable, "danger")
        return redirect(url_for("dashboard_eleve", username=username, lang=lang))

    lecon = (
        Lecon.query
        .options(joinedload(Lecon.unite).joinedload(Unite.matiere))
        .filter(Lecon.id == lecon_id_int)
        .first()
    )

    if not lecon:
        flash(msg_lecon_introuvable, "danger")
        return redirect(url_for("dashboard_eleve", username=username, lang=lang))

    exercice_ids = [
        row[0]
        for row in (
            db.session.query(Exercice.id)
            .filter(Exercice.lecon_id == lecon.id)
            .order_by(
                func.coalesce(Exercice.ordre_progression, 999999).asc(),
                Exercice.id.asc()
            )
            .all()
        )
    ]

    total_exercices = len(exercice_ids)

    if total_exercices == 0:
        flash(msg_aucun_exercice, "info")
        return redirect(url_for("dashboard_eleve", username=username, lang=lang))

    exercice_actuel = None

    if exercice_id_param:
        try:
            exercice_id_int = int(exercice_id_param)
        except (ValueError, TypeError):
            exercice_id_int = None

        if exercice_id_int and exercice_id_int in exercice_ids:
            exercice_actuel = (
                Exercice.query
                .filter(
                    Exercice.id == exercice_id_int,
                    Exercice.lecon_id == lecon.id
                )
                .first()
            )
            index = exercice_ids.index(exercice_id_int)

    if not exercice_actuel:
        if index < 0:
            index = 0

        if index >= total_exercices:
            index = total_exercices - 1

        exercice_actuel = db.session.get(Exercice, exercice_ids[index])

    if not exercice_actuel:
        flash(msg_aucun_exercice, "info")
        return redirect(url_for("dashboard_eleve", username=username, lang=lang))

    question = (
        exercice_actuel.question_en
        if lang == "en" and exercice_actuel.question_en
        else exercice_actuel.question_fr
    )

    # ============================================================
    # OPTIONS QCM - MODE PAPIER-CRAYON
    # ============================================================
    #
    # Même logique que le mode séquentiel :
    # les options sont transformées en une liste structurée
    # afin que le template les affiche proprement.
    #
    # Exemple attendu dans la base :
    #   A) -4/3, B) 3/4, C) 4/3, D) -3/4
    # ============================================================

    options_brutes = (
        exercice_actuel.options_en
        if lang == "en" and exercice_actuel.options_en
        else exercice_actuel.options_fr
    )

    options_affichees = []

    if options_brutes:
        motif_options = re.compile(
            r"(?:^|,\s*)"
            r"([A-H])\s*[\)\].:\-]\s*"
            r"(.*?)"
            r"(?=,\s*[A-H]\s*[\)\].:\-]\s*|$)",
            re.IGNORECASE | re.DOTALL
        )

        for match in motif_options.finditer(str(options_brutes).strip()):
            lettre = match.group(1).upper()
            texte_option = match.group(2).strip()

            if texte_option:
                options_affichees.append({
                    "label": lettre,
                    "value": texte_option,
                    "display": f"{lettre}) {texte_option}"
                })

        # Fallback prudent :
        # si les lettres A), B), C)... ne sont pas présentes,
        # on traite le contenu comme une liste séparée par virgules.
        if not options_affichees:
            morceaux = [
                morceau.strip()
                for morceau in str(options_brutes).split(",")
                if morceau.strip()
            ]

            for position, morceau in enumerate(morceaux[:8]):
                lettre = chr(ord("A") + position)

                options_affichees.append({
                    "label": lettre,
                    "value": morceau,
                    "display": f"{lettre}) {morceau}"
                })

    reponse_attendue = (
        exercice_actuel.reponse_en
        if lang == "en" and exercice_actuel.reponse_en
        else exercice_actuel.reponse_fr
    )

    corrige = (
        exercice_actuel.explication_en
        if lang == "en" and exercice_actuel.explication_en
        else exercice_actuel.explication_fr
    )

    corrige_disponible = bool(corrige)

    bouton_precedent = None
    bouton_suivant = None

    if index > 0:
        bouton_precedent = url_for(
            "exercices_papier_crayon",
            username=username,
            lecon_id=lecon.id,
            lang=lang,
            index=index - 1
        )

    if index < total_exercices - 1:
        bouton_suivant = url_for(
            "exercices_papier_crayon",
            username=username,
            lecon_id=lecon.id,
            lang=lang,
            index=index + 1
        )

    bouton_terminer = url_for("dashboard_eleve", username=username, lang=lang)

    titre_lecon = (
        lecon.titre_en
        if lang == "en" and lecon.titre_en
        else lecon.titre_fr
    )

    nom_matiere = None

    if lecon.unite and lecon.unite.matiere:
        nom_matiere = (
            lecon.unite.matiere.nom_en
            if lang == "en" and lecon.unite.matiere.nom_en
            else lecon.unite.matiere.nom
        )

    print("========== MODE PAPIER-CRAYON ==========")
    print(f"👤 Élève : {eleve.username} | ID : {eleve.id}")
    print(f"📘 Leçon : {lecon.id} - {titre_lecon}")
    print(f"🧩 Exercice actuel : {exercice_actuel.id}")
    print(f"🔘 Options QCM affichées : {len(options_affichees)}")
    print(f"📊 Position : {index + 1}/{total_exercices}")
    print(f"📝 Corrigé disponible : {corrige_disponible}")
    print("========================================")

    return render_template(
        "exercices_papier_crayon.html",
        eleve=eleve,
        username=username,
        lecon=lecon,
        titre_lecon=titre_lecon,
        nom_matiere=nom_matiere,
        exercice=exercice_actuel,
        question=question,
        options_affichees=options_affichees,
        options_brutes=options_brutes,
        reponse_attendue=reponse_attendue,
        corrige=corrige,
        corrige_disponible=corrige_disponible,
        show_corrige=show_corrige,
        index=index,
        total=total_exercices,
        total_exercices=total_exercices,
        exercice_ids=exercice_ids,
        lang=lang,
        bouton_precedent=bouton_precedent,
        bouton_suivant=bouton_suivant,
        bouton_terminer=bouton_terminer,
        mode_parcours="papier_crayon",
        navigation_libre=True
    )



@app.route("/generer-corrige-papier-crayon", methods=["POST"])
def generer_corrige_papier_crayon():
    username = request.form.get("username")
    lecon_id = request.form.get("lecon_id")
    exercice_id = request.form.get("exercice_id")
    lang = request.form.get("lang", "fr")
    index = request.form.get("index", "0")

    msg_erreur = (
        "Unable to generate the correction."
        if lang == "en"
        else "Impossible de générer le corrigé."
    )

    msg_succes = (
        "Correction generated and saved."
        if lang == "en"
        else "Corrigé généré et enregistré."
    )

    eleve = User.query.filter_by(username=username).first()

    if not eleve:
        flash("Élève non trouvé." if lang == "fr" else "Student not found.", "danger")
        return redirect(url_for("index", lang=lang))

    if not eleve.a_acces_plateforme():
        flash(
            "Accès refusé." if lang == "fr" else "Access denied.",
            "danger"
        )
        return redirect(url_for("dashboard_eleve", username=username, lang=lang))

    try:
        lecon_id_int = int(lecon_id)
        exercice_id_int = int(exercice_id)
    except (ValueError, TypeError):
        flash(msg_erreur, "danger")
        return redirect(url_for("dashboard_eleve", username=username, lang=lang))

    lecon = db.session.get(Lecon, lecon_id_int)
    exercice = db.session.get(Exercice, exercice_id_int)

    if not lecon or not exercice or exercice.lecon_id != lecon.id:
        flash(msg_erreur, "danger")
        return redirect(url_for("dashboard_eleve", username=username, lang=lang))

    corrige_existant = (
        exercice.explication_en
        if lang == "en" and exercice.explication_en
        else exercice.explication_fr
    )

    if corrige_existant:
        return redirect(url_for(
            "exercices_papier_crayon",
            username=username,
            lecon_id=lecon.id,
            lang=lang,
            exercice_id=exercice.id,
            index=index,
            show_corrige=True
        ))

    question = (
        exercice.question_en
        if lang == "en" and exercice.question_en
        else exercice.question_fr
    )

    reponse_attendue = (
        exercice.reponse_en
        if lang == "en" and exercice.reponse_en
        else exercice.reponse_fr
    )

    if lang == "en":
        prompt = f"""
You are a math teacher preparing a clear correction for a student who worked on paper.

Exercise:
{question}

Expected answer, if available:
{reponse_attendue or "Not provided"}

Write a complete correction in English.

Requirements:
- Explain the method step by step.
- Use simple language.
- Show the final answer clearly.
- If the exercise involves calculations, show the important calculations.
- Do not mention that you are an AI.
- Do not ask the student a question.
""".strip()
    else:
        prompt = f"""
Tu es un enseignant de mathématiques qui prépare un corrigé clair pour un élève qui a travaillé sur papier.

Exercice :
{question}

Réponse attendue, si disponible :
{reponse_attendue or "Non fournie"}

Rédige un corrigé complet en français.

Exigences :
- Explique la méthode étape par étape.
- Utilise un langage simple.
- Donne clairement la réponse finale.
- Si l’exercice contient des calculs, montre les calculs importants.
- Ne dis pas que tu es une IA.
- Ne pose pas de question à l’élève.
""".strip()

    try:
        completion = client.chat.completions.create(
            model=os.getenv("OPENAI_SIMPLE_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=1200
        )

        corrige_genere = completion.choices[0].message.content.strip()

        if lang == "en":
            exercice.explication_en = corrige_genere
        else:
            exercice.explication_fr = corrige_genere

        db.session.commit()

        flash(msg_succes, "success")

    except Exception as e:
        db.session.rollback()
        print(f"❌ Erreur génération corrigé papier-crayon : {e}")
        flash(msg_erreur, "danger")

    return redirect(url_for(
        "exercices_papier_crayon",
        username=username,
        lecon_id=lecon.id,
        lang=lang,
        exercice_id=exercice.id,
        index=index,
        show_corrige=True
    ))


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

@app.route("/eleve/retroactions-bayesiennes")
def eleve_retroactions_bayesiennes():
    """
    Page élève : progrès et conseils.

    Cette page transforme les données internes en messages simples pour l'élève.
    On évite les mots techniques comme :
    - bayésien ;
    - réseau bayésien ;
    - diagnostic ;
    - probabilité.

    L'élève doit simplement comprendre :
    - ce qu'il réussit ;
    - ce qu'il doit encore travailler ;
    - quoi faire ensuite.
    """

    from datetime import datetime
    import json

    # ------------------------------------------------------------
    # AUTHENTIFICATION ÉLÈVE
    # ------------------------------------------------------------

    if "user_id" not in session and "eleve_id" not in session:
        return redirect(url_for("login_eleve"))

    user_id = session.get("user_id") or session.get("eleve_id")

    lang = request.args.get("lang") or session.get("lang", "fr")
    session["lang"] = lang

    eleve = db.session.get(User, user_id)

    if not eleve or eleve.role not in ["eleve", "élève"]:
        flash("Accès réservé aux élèves.", "error")
        return redirect(url_for("login_eleve"))

    # ------------------------------------------------------------
    # RÉCUPÉRATION DU MODÈLE INTERNE
    # ------------------------------------------------------------

    DiagnosticBayesienModel = None

    try:
        DiagnosticBayesienModel = get_model("DiagnosticBayesien")
    except Exception:
        DiagnosticBayesienModel = None

    if DiagnosticBayesienModel is None:
        try:
            from models import DiagnosticBayesien as DiagnosticBayesienModel
        except Exception as e:
            print(f"⚠️ Modèle DiagnosticBayesien introuvable : {e}")
            flash("Les conseils de progression ne sont pas encore disponibles.", "warning")
            return redirect(url_for("dashboard_eleve", lang=lang))

    # ------------------------------------------------------------
    # CHARGEMENT DES DONNÉES RÉCENTES
    # ------------------------------------------------------------

    diagnostics = []

    try:
        query = DiagnosticBayesienModel.query.filter_by(user_id=eleve.id)

        if hasattr(DiagnosticBayesienModel, "created_at"):
            diagnostics = (
                query
                .order_by(DiagnosticBayesienModel.created_at.desc())
                .limit(30)
                .all()
            )
        elif hasattr(DiagnosticBayesienModel, "timestamp"):
            diagnostics = (
                query
                .order_by(DiagnosticBayesienModel.timestamp.desc())
                .limit(30)
                .all()
            )
        else:
            diagnostics = (
                query
                .order_by(DiagnosticBayesienModel.id.desc())
                .limit(30)
                .all()
            )

    except Exception as e:
        print(f"⚠️ Erreur chargement des conseils élève : {e}")
        diagnostics = []

    # ------------------------------------------------------------
    # OUTILS INTERNES
    # ------------------------------------------------------------

    def convertir_en_dict(valeur):
        """
        Convertit une valeur JSON ou un texte JSON en dictionnaire.
        """

        if not valeur:
            return {}

        if isinstance(valeur, dict):
            return valeur

        if isinstance(valeur, str):
            try:
                return json.loads(valeur)
            except Exception:
                return {}

        return {}

    def normaliser_risque(niveau):
        """
        Garde une valeur interne stable pour le traitement.
        """

        niveau = (niveau or "").lower().strip()

        if niveau in ["élevé", "eleve", "elevé", "high", "haut"]:
            return "élevé"

        if niveau in ["moyen", "moyenne", "medium", "modéré", "modere", "moderate"]:
            return "moyen"

        if niveau in ["faible", "low", "bas"]:
            return "faible"

        return "inconnu"

    def traduire_valeur_signal(valeur):
        """
        Traduit les petites valeurs venant du backend.
        Exemple :
        - moyenne -> medium en anglais
        - rapide -> fast en anglais
        - peu -> few en anglais
        """

        if valeur is None:
            return "—"

        texte_original = str(valeur).strip()
        texte = texte_original.lower()

        traductions = {
            "fr": {
                "faible": "faible",
                "low": "faible",

                "moyen": "moyen",
                "moyenne": "moyen",
                "medium": "moyen",
                "moderate": "moyen",
                "modéré": "moyen",
                "modere": "moyen",

                "élevé": "élevé",
                "eleve": "élevé",
                "elevé": "élevé",
                "high": "élevé",
                "haut": "élevé",

                "rapide": "rapide",
                "fast": "rapide",

                "lent": "lent",
                "lente": "lent",
                "slow": "lent",

                "peu": "peu",
                "few": "peu",
                "low errors": "peu",

                "beaucoup": "beaucoup",
                "many": "beaucoup",
                "high errors": "beaucoup",

                "aucune": "aucune",
                "aucun": "aucune",
                "none": "aucune",

                "correct": "correct",
                "incorrect": "incorrect",
                "partiel": "partiel",
                "partial": "partiel",
            },
            "en": {
                "faible": "low",
                "low": "low",

                "moyen": "medium",
                "moyenne": "medium",
                "medium": "medium",
                "moderate": "medium",
                "modéré": "medium",
                "modere": "medium",

                "élevé": "high",
                "eleve": "high",
                "elevé": "high",
                "high": "high",
                "haut": "high",

                "rapide": "fast",
                "fast": "fast",

                "lent": "slow",
                "lente": "slow",
                "slow": "slow",

                "peu": "few",
                "few": "few",
                "low errors": "few",

                "beaucoup": "many",
                "many": "many",
                "high errors": "many",

                "aucune": "none",
                "aucun": "none",
                "none": "none",

                "correct": "correct",
                "incorrect": "incorrect",
                "partiel": "partial",
                "partial": "partial",
            }
        }

        langue = "en" if lang == "en" else "fr"
        return traductions.get(langue, {}).get(texte, texte_original)

    def badge_risque(niveau):
        """
        Sert seulement au style visuel.
        """

        niveau = normaliser_risque(niveau)

        if niveau == "élevé":
            return "danger"

        if niveau == "moyen":
            return "warning"

        if niveau == "faible":
            return "success"

        return "secondary"

    def titre_risque(niveau):
        """
        Titre simple pour l'élève.
        """

        niveau = normaliser_risque(niveau)

        if lang == "en":
            if niveau == "élevé":
                return "Needs more practice"
            if niveau == "moyen":
                return "Almost there"
            if niveau == "faible":
                return "Good progress"
            return "Keep practicing"

        if niveau == "élevé":
            return "À retravailler"
        if niveau == "moyen":
            return "Presque acquis"
        if niveau == "faible":
            return "Bonne progression"
        return "Continue à pratiquer"

    def message_eleve(niveau):
        """
        Message court et simple.
        On évite de répéter le conseil ici.
        """

        niveau = normaliser_risque(niveau)

        if lang == "en":
            if niveau == "élevé":
                return "This part is still difficult for you."
            if niveau == "moyen":
                return "You are starting to understand this part."
            if niveau == "faible":
                return "You seem to understand this part well."
            return "Keep practicing so we can give you better advice."

        if niveau == "élevé":
            return "Cette partie est encore difficile pour toi."

        if niveau == "moyen":
            return "Tu commences à comprendre cette partie."

        if niveau == "faible":
            return "Tu sembles bien comprendre cette partie."

        return "Continue à pratiquer pour recevoir de meilleurs conseils."

    def conseil_eleve(niveau):
        """
        Une seule action claire pour l'élève.
        """

        niveau = normaliser_risque(niveau)

        if lang == "en":
            if niveau == "élevé":
                return "Ask Naima to explain it step by step, then try an easier exercise."
            if niveau == "moyen":
                return "Review your steps, explain your reasoning, then try a similar exercise."
            if niveau == "faible":
                return "Try to explain your answer, then move to a slightly harder exercise."
            return "Do a few more exercises so we can better guide you."

        if niveau == "élevé":
            return (
                "Demande à Naima de reprendre étape par étape, "
                "puis commence par un exercice plus simple."
            )

        if niveau == "moyen":
            return (
                "Revois tes étapes, explique ton raisonnement, "
                "puis essaie un exercice semblable."
            )

        if niveau == "faible":
            return (
                "Essaie d’expliquer ta réponse, puis passe à un exercice un peu plus difficile."
            )

        return (
            "Fais encore quelques exercices pour recevoir des conseils plus précis."
        )

    def phrase_bilan_eleve(niveau, maitrise, erreurs, rythme):
        """
        Résume les trois signaux en une seule phrase.
        Cela remplace l'affichage séparé :
        - Compréhension ;
        - Erreurs ;
        - Rythme de travail.
        """

        niveau = normaliser_risque(niveau)

        maitrise = traduire_valeur_signal(maitrise)
        erreurs = traduire_valeur_signal(erreurs)
        rythme = traduire_valeur_signal(rythme)

        if lang == "en":
            if niveau == "faible":
                return (
                    f"Overall, you are doing well: your understanding is {maitrise}, "
                    f"you made {erreurs} mistakes, and your work rhythm is {rythme}."
                )

            if niveau == "moyen":
                return (
                    f"You are making progress: your understanding is {maitrise}, "
                    f"you made {erreurs} mistakes, and your work rhythm is {rythme}."
                )

            if niveau == "élevé":
                return (
                    f"This part needs more attention: your understanding is {maitrise}, "
                    f"you made {erreurs} mistakes, and your work rhythm is {rythme}."
                )

            return "Keep practicing so we can better understand what helps you learn."

        if niveau == "faible":
            return (
                f"Dans l’ensemble, tu avances bien : ta compréhension est {maitrise}, "
                f"tu fais {erreurs} d’erreurs et ton rythme de travail est {rythme}."
            )

        if niveau == "moyen":
            return (
                f"Tu progresses : ta compréhension est {maitrise}, "
                f"tu fais {erreurs} d’erreurs et ton rythme de travail est {rythme}."
            )

        if niveau == "élevé":
            return (
                f"Cette partie demande plus d’attention : ta compréhension est {maitrise}, "
                f"tu fais {erreurs} d’erreurs et ton rythme de travail est {rythme}."
            )

        return "Continue à pratiquer pour que les conseils soient plus précis."

    def format_date(valeur):
        if not valeur:
            return "—"

        try:
            return valeur.strftime("%d/%m/%Y %H:%M")
        except Exception:
            return str(valeur)

    def extraire_date(diagnostic):
        for champ in ["created_at", "timestamp", "date_creation", "date"]:
            valeur = getattr(diagnostic, champ, None)
            if valeur:
                return valeur

        return None

    def nettoyer_pourcentage(pourcentage, probabilite):
        try:
            if pourcentage is not None:
                valeur = float(pourcentage)
            elif probabilite is not None:
                valeur = float(probabilite) * 100
            else:
                valeur = 0

            if valeur < 0:
                valeur = 0

            if valeur > 100:
                valeur = 100

            return round(valeur, 1)

        except Exception:
            return 0

    def traduire_notion(notion):
        """
        Pour l'instant, on garde la notion telle qu'elle vient du backend.
        Plus tard, on pourra ajouter une vraie table de traduction des notions.
        """

        if not notion:
            return "Learning topic" if lang == "en" else "Notion à travailler"

        return notion

    def traduire_source(source):
        """
        Rend la source plus simple pour l'élève.
        """

        if not source:
            return "Practice" if lang == "en" else "Exercice"

        source_texte = str(source).lower().strip()

        if lang == "en":
            if source_texte in ["naima", "enseignant_virtuel"]:
                return "Naima"
            if source_texte in ["exercice", "exercice_sequentiel", "sequence"]:
                return "Exercise"
            if source_texte in ["diagnostic"]:
                return "Practice"
            return source

        if source_texte in ["naima", "enseignant_virtuel"]:
            return "Naima"
        if source_texte in ["exercice", "exercice_sequentiel", "sequence"]:
            return "Exercice"
        if source_texte in ["diagnostic"]:
            return "Pratique"

        return source

    # ------------------------------------------------------------
    # CONSTRUCTION DES RÉTROACTIONS LISIBLES
    # ------------------------------------------------------------

    retroactions = []

    for diagnostic in diagnostics:
        diagnostic_complet = convertir_en_dict(
            getattr(diagnostic, "diagnostic_complet", None)
        )

        analyse_pedagogique = convertir_en_dict(
            getattr(diagnostic, "analyse_pedagogique_ia", None)
        )

        signaux = {}

        if isinstance(diagnostic_complet, dict):
            signaux = diagnostic_complet.get("signaux", {}) or {}

        verification_calcul = (
            convertir_en_dict(getattr(diagnostic, "verification_calcul", None))
            or diagnostic_complet.get("verification_calcul", {})
            or {}
        )

        processus_naima = {}

        if isinstance(diagnostic_complet, dict):
            processus_naima = (
                diagnostic_complet.get("processus_naima", {})
                or diagnostic_complet.get("processus", {})
                or {}
            )

        niveau_risque_interne = normaliser_risque(
            getattr(diagnostic, "niveau_risque", None)
        )

        probabilite = getattr(diagnostic, "probabilite_difficulte", None)
        pourcentage = getattr(diagnostic, "pourcentage_difficulte", None)

        notion_cible = (
            getattr(diagnostic, "notion_cible", None)
            or analyse_pedagogique.get("notion_cible")
            or getattr(diagnostic, "matiere", None)
            or None
        )

        # Valeurs qui peuvent venir en français ou en anglais depuis le backend
        valeur_maitrise = (
            getattr(diagnostic, "maitrise_cours", None)
            or signaux.get("maitrise_cours")
            or signaux.get("understanding")
            or "—"
        )

        valeur_erreurs = (
            getattr(diagnostic, "erreurs", None)
            or signaux.get("erreurs")
            or signaux.get("mistakes")
            or "—"
        )

        valeur_temps = (
            getattr(diagnostic, "temps_reponse", None)
            or signaux.get("temps_reponse")
            or signaux.get("work_rhythm")
            or signaux.get("rythme")
            or "—"
        )

        bilan_simple = phrase_bilan_eleve(
            niveau_risque_interne,
            valeur_maitrise,
            valeur_erreurs,
            valeur_temps
        )

        retroactions.append({
            "id": getattr(diagnostic, "id", None),
            "date": format_date(extraire_date(diagnostic)),

            # Titre simple
            "titre": titre_risque(niveau_risque_interne),

            # Valeur affichée à l'élève
            "niveau_risque": traduire_valeur_signal(niveau_risque_interne),

            # Valeur utile pour le style
            "badge": badge_risque(niveau_risque_interne),

            "pourcentage": nettoyer_pourcentage(pourcentage, probabilite),

            "notion_cible": traduire_notion(notion_cible),

            # Messages simples
            "message": message_eleve(niveau_risque_interne),
            "bilan_simple": bilan_simple,
            "conseil": conseil_eleve(niveau_risque_interne),

            # Valeurs gardées au cas où tu veux encore les afficher ailleurs
            "maitrise_cours": traduire_valeur_signal(valeur_maitrise),
            "erreurs": traduire_valeur_signal(valeur_erreurs),
            "temps_reponse": traduire_valeur_signal(valeur_temps),

            # On les garde pour l'enseignant/admin, mais on ne les affiche pas forcément à l'élève
            "recommandation": getattr(diagnostic, "recommandation", None),
            "recommandation_enseignant": getattr(diagnostic, "recommandation_enseignant", None),
            "niveau_intervention": getattr(diagnostic, "niveau_intervention", None),
            "exercice_remediation_suggere": getattr(diagnostic, "exercice_remediation_suggere", None),

            "verification_calcul": verification_calcul,
            "processus_naima": processus_naima,
            "source": traduire_source(getattr(diagnostic, "source", None))
        })

    # ------------------------------------------------------------
    # RÉSUMÉ GLOBAL
    # ------------------------------------------------------------

    resume = {
        "total": len(retroactions),
        "faible": sum(1 for r in retroactions if r["badge"] == "success"),
        "moyen": sum(1 for r in retroactions if r["badge"] == "warning"),
        "eleve": sum(1 for r in retroactions if r["badge"] == "danger"),
    }

    return render_template(
        "eleve_retroactions_bayesiennes.html",
        eleve=eleve,
        lang=lang,
        retroactions=retroactions,
        resume=resume,
        date_du_jour=datetime.utcnow()
    )


@app.route("/enseignant/profils-apprenants")
def enseignant_profils_apprenants():
    from sqlalchemy import desc, or_
    from sqlalchemy.orm import joinedload
    from models import db, ProfilApprenant, User, Lecon, Unite

    # ============================================================
    # AUTHENTIFICATION ENSEIGNANT
    # Même logique que le dashboard_enseignant récent :
    # session["user_id"] + session["role"] == "enseignant"
    # ============================================================

    if "user_id" not in session:
        print("❌ Pas de user_id dans la session :", dict(session))
        return redirect(url_for("login_enseignant"))

    if session.get("role") != "enseignant":
        print("❌ Rôle incorrect pour profils apprenants :", dict(session))
        flash("Accès réservé aux enseignants", "error")
        return redirect("/")

    enseignant = User.query.get(session["user_id"])

    if not enseignant or not enseignant.est_enseignant():
        print("❌ Enseignant introuvable ou rôle invalide :", session.get("user_id"))
        flash("Enseignant non trouvé", "error")
        return redirect(url_for("login_enseignant"))

    print("✅ Enseignant connecté profils apprenants :", enseignant.id, enseignant.email)

    # ============================================================
    # ÉLÈVES DE CET ENSEIGNANT
    # On utilise la même logique que enseignant_eleves :
    # nouveau système : enseignant_referent_id
    # fallback ancien système : enseignant_id si le champ existe
    # ============================================================

    eleves = (
        User.query
        .options(joinedload(User.niveau))
        .filter(
            User.role.in_(["eleve", "élève"]),
            User.enseignant_referent_id == enseignant.id
        )
        .order_by(User.nom_complet.asc())
        .all()
    )

    if not eleves and hasattr(User, "enseignant_id"):
        eleves = (
            User.query
            .options(joinedload(User.niveau))
            .filter(
                User.role.in_(["eleve", "élève"]),
                User.enseignant_id == enseignant.id
            )
            .order_by(User.nom_complet.asc())
            .all()
        )

    eleves_ids = [eleve.id for eleve in eleves]

    print("👥 Élèves trouvés pour profils apprenants :", eleves_ids)

    # ============================================================
    # PARAMÈTRES DE FILTRE
    # ============================================================

    user_id = request.args.get("user_id", "").strip()
    lecon_id = request.args.get("lecon_id", "").strip()
    risque = request.args.get("risque", "").strip()
    recommandation = request.args.get("recommandation", "").strip()
    tendance = request.args.get("tendance", "").strip()
    recherche = request.args.get("q", "").strip()

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    if per_page not in [10, 20, 50, 100]:
        per_page = 20

    # ============================================================
    # CAS : AUCUN ÉLÈVE RATTACHÉ À CET ENSEIGNANT
    # ============================================================

    if not eleves_ids:
        pagination = (
            ProfilApprenant.query
            .filter(False)
            .paginate(
                page=page,
                per_page=per_page,
                error_out=False
            )
        )

        stats = {
            "total_profils": 0,
            "total_risque_eleve": 0,
            "total_risque_moyen": 0,
            "total_risque_faible": 0,
            "moyenne_maitrise": 0
        }

        return render_template(
            "enseignant/profils_apprenants.html",
            profils=[],
            pagination=pagination,
            eleves=eleves,
            lecons=[],
            stats=stats,
            filtres={
                "user_id": user_id,
                "lecon_id": lecon_id,
                "risque": risque,
                "recommandation": recommandation,
                "tendance": tendance,
                "q": recherche,
                "per_page": per_page
            }
        )

    # ============================================================
    # REQUÊTE PRINCIPALE
    # Sécurité : l'enseignant ne voit que les profils de ses élèves
    # ============================================================

    query = (
        ProfilApprenant.query
        .options(
            joinedload(ProfilApprenant.user),
            joinedload(ProfilApprenant.lecon)
                .joinedload(Lecon.unite)
                .joinedload(Unite.matiere)
        )
        .filter(ProfilApprenant.user_id.in_(eleves_ids))
    )

    # Filtre élève
    if user_id:
        try:
            user_id_int = int(user_id)

            if user_id_int in eleves_ids:
                query = query.filter(ProfilApprenant.user_id == user_id_int)

        except ValueError:
            pass

    # Filtre leçon
    if lecon_id:
        try:
            lecon_id_int = int(lecon_id)
            query = query.filter(ProfilApprenant.lecon_id == lecon_id_int)
        except ValueError:
            pass

    # Filtre risque
    if risque:
        query = query.filter(ProfilApprenant.niveau_risque == risque)

    # Filtre recommandation
    if recommandation:
        query = query.filter(ProfilApprenant.recommandation == recommandation)

    # Filtre tendance
    if tendance:
        query = query.filter(ProfilApprenant.tendance == tendance)

    # Recherche texte
    if recherche:
        like = f"%{recherche}%"

        query = (
            query
            .join(User, ProfilApprenant.user_id == User.id)
            .filter(
                or_(
                    ProfilApprenant.notion_cible.ilike(like),
                    ProfilApprenant.competence_cible.ilike(like),
                    User.username.ilike(like),
                    User.nom_complet.ilike(like),
                    User.email.ilike(like)
                )
            )
        )

    query = query.order_by(
        desc(ProfilApprenant.updated_at),
        ProfilApprenant.notion_cible.asc()
    )

    pagination = query.paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )

    profils = pagination.items

    # ============================================================
    # LEÇONS DES PROFILS DES ÉLÈVES DE CET ENSEIGNANT
    # ============================================================

    lecons = (
        Lecon.query
        .options(
            joinedload(Lecon.unite)
                .joinedload(Unite.matiere)
        )
        .join(ProfilApprenant, ProfilApprenant.lecon_id == Lecon.id)
        .filter(ProfilApprenant.user_id.in_(eleves_ids))
        .distinct()
        .order_by(Lecon.titre_fr.asc())
        .all()
    )

    # ============================================================
    # STATISTIQUES
    # ============================================================

    total_profils = (
        ProfilApprenant.query
        .filter(ProfilApprenant.user_id.in_(eleves_ids))
        .count()
    )

    total_risque_eleve = (
        ProfilApprenant.query
        .filter(
            ProfilApprenant.user_id.in_(eleves_ids),
            ProfilApprenant.niveau_risque == "élevé"
        )
        .count()
    )

    total_risque_moyen = (
        ProfilApprenant.query
        .filter(
            ProfilApprenant.user_id.in_(eleves_ids),
            ProfilApprenant.niveau_risque == "moyen"
        )
        .count()
    )

    total_risque_faible = (
        ProfilApprenant.query
        .filter(
            ProfilApprenant.user_id.in_(eleves_ids),
            ProfilApprenant.niveau_risque == "faible"
        )
        .count()
    )

    moyenne_maitrise = (
        db.session.query(db.func.avg(ProfilApprenant.maitrise_estimee))
        .filter(ProfilApprenant.user_id.in_(eleves_ids))
        .scalar()
    )

    moyenne_maitrise = round(float(moyenne_maitrise or 0), 1)

    stats = {
        "total_profils": total_profils,
        "total_risque_eleve": total_risque_eleve,
        "total_risque_moyen": total_risque_moyen,
        "total_risque_faible": total_risque_faible,
        "moyenne_maitrise": moyenne_maitrise
    }

    print("✅ Profils apprenants trouvés :", total_profils)

    return render_template(
        "enseignant/profils_apprenants.html",
        profils=profils,
        pagination=pagination,
        eleves=eleves,
        lecons=lecons,
        stats=stats,
        filtres={
            "user_id": user_id,
            "lecon_id": lecon_id,
            "risque": risque,
            "recommandation": recommandation,
            "tendance": tendance,
            "q": recherche,
            "per_page": per_page
        }
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
    """Supprimer une remédiation (soft delete ou hard delete)"""
    # ✅ CORRECTION : utiliser "user_id" au lieu de "enseignant_id"
    if "user_id" not in session:
        flash("Veuillez vous connecter", "error")
        return redirect(url_for("login_enseignant"))
    
    if session.get("role") != "enseignant":
        flash("Accès non autorisé", "error")
        return redirect(url_for("login_enseignant"))

    try:
        suggestion = RemediationSuggestion.query.get_or_404(id)
        
        # ✅ Vérifier que cette remédiation appartient bien à un élève de cet enseignant
        if suggestion.user.enseignant_referent_id != session["user_id"]:
            flash("Vous n'êtes pas autorisé à supprimer cette remédiation", "error")
            return redirect(url_for("remediations_a_valider"))
        
        # Option 1: Suppression physique (hard delete)
        db.session.delete(suggestion)
        
        # Option 2: Suppression logique (soft delete) - si tu préfères
        # suggestion.statut = "supprime"
        
        db.session.commit()
        flash("✅ Remédiation supprimée avec succès", "success")

    except Exception as e:
        db.session.rollback()
        flash(f"Erreur lors de la suppression: {str(e)}", "error")
    
    lang = session.get("lang", "fr")
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
        print(f"Données reçues: {json.dumps(data, indent=2, ensure_ascii=False)}")
        
        # 1. Récupérer la réponse existante
        reponse_id = data.get('reponse_id')
        if not reponse_id:
            return jsonify({'success': False, 'message': 'ID de réponse manquant'})
        
        reponse = StudentResponse.query.get(reponse_id)
        if not reponse:
            return jsonify({'success': False, 'message': 'Réponse non trouvée'})
        
        # Sauvegarder l'ancienne note pour référence
        old_stars = reponse.etoiles
        
        # 2. Récupérer l'exercice et les informations
        exercice = Exercice.query.get(reponse.exercice_id)
        eleve = User.query.get(reponse.user_id)
        
        if not exercice or not eleve:
            return jsonify({'success': False, 'message': 'Exercice ou élève non trouvé'})
        
        # 3. PRÉPARER LE PROMPT POUR L'IA
        lang = data.get('lang', 'fr')
        question = exercice.question_fr if lang == 'fr' else exercice.question_en
        
        # Fonction pour extraire le texte de l'analyse
        def extract_analysis_text(analysis_text):
            if not analysis_text:
                return "Aucune analyse disponible"
            
            # Si c'est du JSON
            if analysis_text.strip().startswith('{'):
                try:
                    analysis_json = json.loads(analysis_text)
                    if 'current_feedback' in analysis_json:
                        return analysis_json['current_feedback']
                    elif 'original' in analysis_json:
                        return analysis_json['original']
                except json.JSONDecodeError:
                    pass
            
            # Sinon retourner le texte brut
            return analysis_text
        
        analysis_text = extract_analysis_text(reponse.analyse_ia)
        
        print(f"📝 Question: {question[:100]}...")
        print(f"📝 Réponse élève: {reponse.reponse_eleve[:100]}...")
        print(f"📝 Justification: {data.get('justification', '')[:100]}...")
        
        # 4. TENTATIVE D'APPEL À L'IA
        new_analysis = None
        new_stars = old_stars
        evaluation_method = "local_fallback"
        
        try:
            from openai import OpenAI
            import os
            
            # Récupérer la clé API depuis les variables d'environnement
            api_key = os.environ.get("OPENAI_API_KEY")
            
            if not api_key:
                print("❌ Clé API OpenAI non trouvée dans les variables d'environnement")
                raise Exception("OPENAI_API_KEY not configured")
            
            print(f"🔑 Clé API trouvée: {api_key[:5]}...{api_key[-5:]}")
            
            client = OpenAI(api_key=api_key)
            
            if lang == 'en':
                prompt = f"""
RE-EVALUATE a student's answer considering their contestation arguments.

📘 ORIGINAL PROBLEM:
{question}

📜 STUDENT'S ORIGINAL ANSWER:
{reponse.reponse_eleve}

🎯 ORIGINAL AI CORRECTION (current grade: {old_stars}/5):
{analysis_text}

📝 STUDENT'S CONTESTATION ARGUMENTS:
"{data.get('justification', '')}"

⭐ STUDENT'S PROPOSED GRADE: {data.get('proposed_stars', old_stars)}/5

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

🎯 CORRECTION IA ORIGINALE (note actuelle : {old_stars}/5) :
{analysis_text}

📝 ARGUMENTS DE CONTESTATION DE L'ÉLÈVE :
"{data.get('justification', '')}"

⭐ NOTE PROPOSÉE PAR L'ÉLÈVE : {data.get('proposed_stars', old_stars)}/5

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
            print(f"📤 Longueur du prompt: {len(prompt)} caractères")
            
            chat_completion = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1000
            )
            
            new_analysis = chat_completion.choices[0].message.content.strip()
            evaluation_method = "ai"
            print(f"✅ Réévaluation IA reçue avec succès")
            print(f"📥 Réponse IA (premiers 200 chars): {new_analysis[:200]}...")
            
            # 5. EXTRACTION DE LA NOUVELLE NOTE
            import re
            
            # Chercher la nouvelle note dans la réponse de l'IA
            match = re.search(r"(?:New grade|Nouvelle note|Grade|Note)\s*:\s*(\d)(?:\s*/?\s*5)?", new_analysis, re.IGNORECASE)
            if match:
                new_stars = int(match.group(1))
                print(f"⭐ Nouvelle note extraite: {new_stars}/5")
            else:
                # Fallback - chercher d'autres formats
                match = re.search(r"\b(\d)(?:\s*[/\\]\s*5)?\s*(?:⭐|stars|étoiles)", new_analysis, re.IGNORECASE)
                if match:
                    new_stars = min(int(match.group(1)), 5)
                    print(f"⭐ Nouvelle note extraite (format alternatif): {new_stars}/5")
                else:
                    match = re.search(r"\bgrade\s*:\s*(\d)\b", new_analysis, re.IGNORECASE)
                    if match:
                        new_stars = int(match.group(1))
                    else:
                        new_stars = old_stars
                        print(f"⭐ Note non trouvée, maintien de la note actuelle: {new_stars}/5")
            
            # S'assurer que la note est entre 1 et 5
            new_stars = max(1, min(5, new_stars))
            
        except Exception as e:
            print(f"❌ Erreur lors de l'appel IA: {str(e)}")
            import traceback
            traceback.print_exc()
            
            # FALLBACK SIMPLIFIÉ - sans dépendances externes
            print("⚠️ Utilisation du fallback local simplifié")
            evaluation_method = "local_fallback"
            
            justification = data.get('justification', '').lower()
            proposed = data.get('proposed_stars', old_stars)
            
            # Logique simple d'évaluation locale
            new_stars = old_stars
            reason = "Nous n'avons pas pu contacter l'IA pour réévaluer votre réponse."
            
            # Mots-clés pour différents cas
            positive_keywords = ['bonne réponse', 'juste', 'correct', 'équivalent', 'alternative valide', 'bon raisonnement']
            partial_keywords = ['erreur mineure', 'petite erreur', 'étourderie', 'calcul']
            negative_keywords = ['mal évalué', 'injuste', 'trop sévère']
            
            if any(word in justification for word in positive_keywords):
                new_stars = min(old_stars + 1, 5)
                if proposed > old_stars:
                    new_stars = min(proposed, 5)
                reason = "Votre argument suggère que la réponse mérite une meilleure évaluation."
            elif any(word in justification for word in partial_keywords):
                if old_stars < 3:
                    new_stars = min(old_stars + 1, 5)
                    reason = "Nous prenons en compte les erreurs mineures pour ajuster la note."
            elif any(word in justification for word in negative_keywords):
                reason = "Nous allons examiner votre demande plus attentivement."
            else:
                reason = "Arguments insuffisants pour justifier un changement de note."
            
            # Générer une réponse locale
            if lang == 'en':
                new_analysis = f"""
⚠️ **Temporary Review (AI Unavailable)**

**Your arguments:** {data.get('justification', '')}

**Temporary decision:** Grade {'adjusted to' if new_stars != old_stars else 'maintained at'} {new_stars}/5 stars
**Previous grade:** {old_stars}/5

**Reason:** {reason}

Our AI system is temporarily unavailable. Your contestation has been logged and will be reviewed by a teacher.
"""
            else:
                new_analysis = f"""
⚠️ **Révision Temporaire (IA Indisponible)**

**Vos arguments :** {data.get('justification', '')}

**Décision temporaire :** Note {'ajustée à' if new_stars != old_stars else 'maintenue à'} {new_stars}/5 étoiles
**Note précédente :** {old_stars}/5

**Raison :** {reason}

Notre système IA est temporairement indisponible. Votre contestation a été enregistrée et sera examinée par un professeur.
"""
        
        # 6. METTRE À JOUR LA BASE DE DONNÉES
        try:
            # Récupérer l'analyse existante
            existing_analysis = {}
            if reponse.analyse_ia and reponse.analyse_ia.strip().startswith('{'):
                try:
                    existing_analysis = json.loads(reponse.analyse_ia)
                except json.JSONDecodeError:
                    existing_analysis = {}
            
            # Créer un nouvel objet JSON avec l'historique
            if not existing_analysis:
                existing_analysis = {
                    "original": analysis_text,
                    "history": [],
                    "current_feedback": analysis_text,
                    "current_stars": old_stars
                }
            
            # Ajouter la contestation à l'historique
            from datetime import datetime
            
            contestation_entry = {
                "type": "contestation",
                "date": datetime.now().isoformat(),
                "justification": data.get('justification', ''),
                "proposed_stars": data.get('proposed_stars', old_stars),
                "previous_stars": old_stars,
                "new_stars": new_stars,
                "ai_response": new_analysis,
                "evaluation_method": evaluation_method
            }
            
            if "history" not in existing_analysis:
                existing_analysis["history"] = []
            
            existing_analysis["history"].append(contestation_entry)
            existing_analysis["current_feedback"] = new_analysis
            existing_analysis["current_stars"] = new_stars
            existing_analysis["last_contestation_date"] = datetime.now().isoformat()
            
            # Mettre à jour la base de données
            reponse.analyse_ia = json.dumps(existing_analysis, ensure_ascii=False, indent=2)
            reponse.etoiles = new_stars
            reponse.date_modification = datetime.now()
            
            db.session.commit()
            print(f"✅ Base de données mise à jour. Nouvelle note: {new_stars}/5 (était: {old_stars}/5)")
            
        except Exception as db_error:
            db.session.rollback()
            print(f"❌ Erreur lors de la mise à jour DB: {str(db_error)}")
            # Continuer malgré l'erreur DB pour retourner une réponse
        
        # 7. PRÉPARER LA RÉPONSE
        stars_changed = new_stars != old_stars
        
        if lang == 'en':
            if stars_changed:
                message = f"✅ Grade changed from {old_stars} to {new_stars}/5 stars!"
            else:
                message = f"ℹ️ Grade maintained at {new_stars}/5 stars."
        else:
            if stars_changed:
                message = f"✅ Note changée de {old_stars} à {new_stars}/5 étoiles !"
            else:
                message = f"ℹ️ Note maintenue à {new_stars}/5 étoiles."
        
        return jsonify({
            'success': True,
            'new_stars': new_stars,
            'new_feedback': new_analysis,
            'old_stars': old_stars,
            'stars_changed': stars_changed,
            'message': message,
            'has_ai_reassessment': evaluation_method == 'ai',
            'evaluation_method': evaluation_method
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Erreur fatale dans contest_evaluation: {str(e)}")
        import traceback
        traceback.print_exc()
        
        error_message = "Erreur interne du serveur"
        lang = request.json.get('lang', 'fr') if request.json else 'fr'
        if lang == 'en':
            error_message = "Internal server error"
            
        return jsonify({
            'success': False, 
            'message': f'{error_message}: {str(e)}'
        }), 500


# Ajoutez ces imports en haut du fichier si nécessaire
from datetime import datetime

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

@app.route("/admin/traces-apprentissage")
def admin_traces_apprentissage():
    import json
    from models import TraceApprentissage, User
    from sqlalchemy.orm import joinedload

    sort = request.args.get("sort", "date_desc")
    risque = request.args.get("risque", "tous")
    action = request.args.get("action", "tous")
    q = request.args.get("q", "").strip()

    query = (
        TraceApprentissage.query
        .options(
            joinedload(TraceApprentissage.user),
            joinedload(TraceApprentissage.matiere),
            joinedload(TraceApprentissage.unite),
            joinedload(TraceApprentissage.lecon),
            joinedload(TraceApprentissage.exercice)
        )
    )

    if risque != "tous":
        query = query.filter(TraceApprentissage.niveau_risque == risque)

    if action != "tous":
        query = query.filter(TraceApprentissage.type_action == action)

    if q:
        query = (
            query
            .outerjoin(User, TraceApprentissage.user_id == User.id)
            .filter(
                db.or_(
                    User.nom_complet.ilike(f"%{q}%"),
                    User.username.ilike(f"%{q}%"),
                    TraceApprentissage.notion_cible.ilike(f"%{q}%"),
                    TraceApprentissage.source.ilike(f"%{q}%"),
                    TraceApprentissage.type_action.ilike(f"%{q}%")
                )
            )
        )

    if sort == "date_asc":
        query = query.order_by(TraceApprentissage.created_at.asc())
    elif sort == "score_desc":
        query = query.order_by(TraceApprentissage.score.desc().nullslast())
    elif sort == "score_asc":
        query = query.order_by(TraceApprentissage.score.asc().nullsfirst())
    elif sort == "risque":
        query = query.order_by(TraceApprentissage.niveau_risque.asc())
    elif sort == "eleve":
        query = query.outerjoin(User, TraceApprentissage.user_id == User.id).order_by(User.nom_complet.asc())
    elif sort == "notion":
        query = query.order_by(TraceApprentissage.notion_cible.asc().nullslast())
    else:
        query = query.order_by(TraceApprentissage.created_at.desc())

    traces = query.limit(100).all()

    for trace in traces:
        detail = {}

        try:
            if trace.analyse_ia:
                detail = json.loads(trace.analyse_ia)
        except Exception:
            detail = {}

        trace.detail_ia = detail
        trace.feedback_lisible = detail.get("current_feedback", trace.analyse_ia or "")
        trace.score_sur_5 = detail.get("current_stars")

        metadata = detail.get("metadata", {})
        trace.langue_trace = metadata.get("language") or (trace.meta_json or {}).get("lang") or "fr"

        trace.question_lisible = (
            (trace.meta_json or {}).get("question_en")
            if trace.langue_trace == "en"
            else (trace.meta_json or {}).get("question_fr")
        )

        trace.reponse_attendue_lisible = (
            (trace.meta_json or {}).get("reponse_attendue_en")
            if trace.langue_trace == "en"
            else (trace.meta_json or {}).get("reponse_attendue_fr")
        )

        trace.correction_symbolique = (
            detail.get("symbolic_verification", {}).get("feedback")
            or (trace.meta_json or {}).get("symbolic_feedback")
            or ""
        )

        trace.prochain_adaptatif = (
            detail.get("adaptive_next")
            or (trace.meta_json or {}).get("adaptive_next")
            or {}
        )

    return render_template(
        "admin_traces_apprentissage.html",
        traces=traces,
        sort=sort,
        risque=risque,
        action=action,
        q=q
    )

@app.route("/admin/synthese-notions")
@admin_required
def admin_synthese_notions():
    import json
    from datetime import datetime
    from models import TraceApprentissage, User
    from sqlalchemy.orm import joinedload

    # ============================================================
    # 1. PARAMÈTRES
    # ============================================================

    q = request.args.get("q", "").strip()
    risque_filtre = request.args.get("risque", "tous")
    sort = request.args.get("sort", "risque")
    lang = session.get("lang", "fr")

    # ============================================================
    # 2. CHARGER LES TRACES GLOBALES
    # ============================================================

    traces = (
        TraceApprentissage.query
        .options(
            joinedload(TraceApprentissage.user),
            joinedload(TraceApprentissage.matiere),
            joinedload(TraceApprentissage.unite),
            joinedload(TraceApprentissage.lecon),
            joinedload(TraceApprentissage.exercice)
        )
        .order_by(TraceApprentissage.created_at.desc())
        .limit(3000)
        .all()
    )

    # ============================================================
    # 3. OUTILS INTERNES
    # ============================================================

    def lire_meta_json(trace):
        meta = trace.meta_json or {}

        if isinstance(meta, dict):
            return meta

        if isinstance(meta, str):
            try:
                return json.loads(meta)
            except Exception:
                return {}

        return {}

    enseignants_cache = {}

    def trouver_enseignant_pour_eleve(eleve):
        if not eleve:
            return None

        enseignant_id = (
            getattr(eleve, "enseignant_referent_id", None)
            or getattr(eleve, "enseignant_id", None)
        )

        if not enseignant_id:
            return None

        if enseignant_id in enseignants_cache:
            return enseignants_cache[enseignant_id]

        enseignant = db.session.get(User, enseignant_id)
        enseignants_cache[enseignant_id] = enseignant

        return enseignant

    # ============================================================
    # 4. AGRÉGER PAR NOTION
    # ============================================================

    notions = {}

    for trace in traces:
        meta = lire_meta_json(trace)

        notion = (
            trace.notion_cible
            or meta.get("notion_cible")
            or "Notion non précisée"
        )

        notion = str(notion).strip() or "Notion non précisée"

        if notion not in notions:
            notions[notion] = {
                "notion": notion,
                "traces_count": 0,

                "eleves_ids": set(),
                "eleves": {},

                "enseignants_ids": set(),
                "enseignants": {},

                "scores": [],
                "risques": {
                    "faible": 0,
                    "moyen": 0,
                    "élevé": 0
                },
                "erreurs": {},
                "matieres": {},
                "lecons": {},
                "dernieres_traces": [],
                "derniere_date": None
            }

        bloc = notions[notion]
        bloc["traces_count"] += 1

        # ------------------------------------------------------------
        # Élève
        # ------------------------------------------------------------

        if trace.user_id:
            bloc["eleves_ids"].add(trace.user_id)

        if trace.user:
            bloc["eleves"][trace.user_id] = {
                "id": trace.user_id,
                "nom": trace.user.nom_complet or trace.user.username or f"Élève {trace.user_id}",
                "username": trace.user.username or "",
                "email": getattr(trace.user, "email", "") or ""
            }
        elif trace.user_id:
            bloc["eleves"][trace.user_id] = {
                "id": trace.user_id,
                "nom": f"Élève {trace.user_id}",
                "username": "",
                "email": ""
            }

        # ------------------------------------------------------------
        # Enseignant associé à l'élève
        # ------------------------------------------------------------

        enseignant = trouver_enseignant_pour_eleve(trace.user)

        if enseignant:
            bloc["enseignants_ids"].add(enseignant.id)
            bloc["enseignants"][enseignant.id] = {
                "id": enseignant.id,
                "nom": enseignant.nom_complet or enseignant.username or f"Enseignant {enseignant.id}",
                "username": enseignant.username or "",
                "email": enseignant.email or ""
            }

        # ------------------------------------------------------------
        # Score
        # ------------------------------------------------------------

        if trace.score is not None:
            bloc["scores"].append(trace.score)

        # ------------------------------------------------------------
        # Risque
        # ------------------------------------------------------------

        if trace.niveau_risque in bloc["risques"]:
            bloc["risques"][trace.niveau_risque] += 1

        # ------------------------------------------------------------
        # Erreurs
        # ------------------------------------------------------------

        type_erreur = (
            trace.type_erreur
            or meta.get("type_erreur")
        )

        if type_erreur:
            type_erreur = str(type_erreur).strip()
            bloc["erreurs"][type_erreur] = bloc["erreurs"].get(type_erreur, 0) + 1

        # ------------------------------------------------------------
        # Matière
        # ------------------------------------------------------------

        matiere_nom = (
            meta.get("matiere_fr")
            or meta.get("matiere_en")
            or (trace.matiere.nom if trace.matiere else None)
            or "Matière non précisée"
        )

        bloc["matieres"][matiere_nom] = bloc["matieres"].get(matiere_nom, 0) + 1

        # ------------------------------------------------------------
        # Leçon
        # ------------------------------------------------------------

        lecon_nom = (
            meta.get("lecon_fr")
            or meta.get("lecon_en")
            or (trace.lecon.titre_fr if trace.lecon else None)
            or (trace.lecon.nom if trace.lecon and hasattr(trace.lecon, "nom") else None)
            or "Leçon non précisée"
        )

        bloc["lecons"][lecon_nom] = bloc["lecons"].get(lecon_nom, 0) + 1

        # ------------------------------------------------------------
        # Date
        # ------------------------------------------------------------

        if trace.created_at:
            if not bloc["derniere_date"] or trace.created_at > bloc["derniere_date"]:
                bloc["derniere_date"] = trace.created_at

        if len(bloc["dernieres_traces"]) < 5:
            bloc["dernieres_traces"].append(trace)

    # ============================================================
    # 5. TRANSFORMER EN LISTE LISIBLE
    # ============================================================

    notions_synthese = []

    for notion, bloc in notions.items():
        scores = bloc["scores"]
        score_moyen = round(sum(scores) / len(scores), 1) if scores else 0

        if bloc["risques"]["élevé"] > 0:
            risque_dominant = "élevé"
        elif bloc["risques"]["moyen"] > 0:
            risque_dominant = "moyen"
        elif bloc["risques"]["faible"] > 0:
            risque_dominant = "faible"
        else:
            risque_dominant = "non défini"

        erreurs_frequentes = sorted(
            bloc["erreurs"].items(),
            key=lambda x: x[1],
            reverse=True
        )[:5]

        matieres_frequentes = sorted(
            bloc["matieres"].items(),
            key=lambda x: x[1],
            reverse=True
        )[:5]

        lecons_frequentes = sorted(
            bloc["lecons"].items(),
            key=lambda x: x[1],
            reverse=True
        )[:5]

        eleves_liste = list(bloc["eleves"].values())
        enseignants_liste = list(bloc["enseignants"].values())

        if risque_dominant == "élevé":
            recommandation = (
                "Notion à surveiller fortement : plusieurs traces indiquent un risque élevé. Une analyse pédagogique ou une remédiation ciblée peut être nécessaire."
                if lang == "fr"
                else "High-priority concept: several traces indicate high risk. A pedagogical review or targeted remediation may be needed."
            )
        elif risque_dominant == "moyen":
            recommandation = (
                "Notion à suivre : des difficultés apparaissent. Il peut être utile d’observer les erreurs fréquentes et les enseignants concernés."
                if lang == "fr"
                else "Concept to monitor: difficulties are emerging. It may be useful to review frequent errors and concerned teachers."
            )
        elif risque_dominant == "faible":
            recommandation = (
                "Notion globalement maîtrisée selon les traces disponibles."
                if lang == "fr"
                else "Concept mostly mastered based on available traces."
            )
        else:
            recommandation = (
                "Données insuffisantes pour tirer une conclusion fiable."
                if lang == "fr"
                else "Not enough data to draw a reliable conclusion."
            )

        item = {
            "notion": notion,
            "traces_count": bloc["traces_count"],

            "eleves_count": len(bloc["eleves_ids"]),
            "eleves": eleves_liste,

            "enseignants_count": len(bloc["enseignants_ids"]),
            "enseignants": enseignants_liste,

            "score_moyen": score_moyen,
            "risque_dominant": risque_dominant,
            "risques": bloc["risques"],

            "erreurs_frequentes": erreurs_frequentes,
            "matieres_frequentes": matieres_frequentes,
            "lecons_frequentes": lecons_frequentes,

            "dernieres_traces": bloc["dernieres_traces"],
            "derniere_date": bloc["derniere_date"],

            "recommandation": recommandation
        }

        notions_synthese.append(item)

    # ============================================================
    # 6. FILTRES
    # ============================================================

    if q:
        q_lower = q.lower()

        notions_synthese = [
            item for item in notions_synthese
            if (
                q_lower in item["notion"].lower()
                or any(q_lower in matiere.lower() for matiere, _ in item["matieres_frequentes"])
                or any(q_lower in lecon.lower() for lecon, _ in item["lecons_frequentes"])
                or any(q_lower in erreur.lower() for erreur, _ in item["erreurs_frequentes"])
                or any(q_lower in (eleve.get("nom", "").lower()) for eleve in item["eleves"])
                or any(q_lower in (eleve.get("username", "").lower()) for eleve in item["eleves"])
                or any(q_lower in (enseignant.get("nom", "").lower()) for enseignant in item["enseignants"])
                or any(q_lower in (enseignant.get("email", "").lower()) for enseignant in item["enseignants"])
            )
        ]

    if risque_filtre != "tous":
        notions_synthese = [
            item for item in notions_synthese
            if item["risque_dominant"] == risque_filtre
        ]

    # ============================================================
    # 7. TRI
    # ============================================================

    if sort == "score_asc":
        notions_synthese.sort(key=lambda x: x["score_moyen"])

    elif sort == "score_desc":
        notions_synthese.sort(key=lambda x: x["score_moyen"], reverse=True)

    elif sort == "traces":
        notions_synthese.sort(key=lambda x: x["traces_count"], reverse=True)

    elif sort == "eleves":
        notions_synthese.sort(key=lambda x: x["eleves_count"], reverse=True)

    elif sort == "date":
        notions_synthese.sort(
            key=lambda x: x["derniere_date"] or datetime.min,
            reverse=True
        )

    else:
        ordre_risque = {
            "élevé": 3,
            "moyen": 2,
            "faible": 1,
            "non défini": 0
        }

        notions_synthese.sort(
            key=lambda x: (
                ordre_risque.get(x["risque_dominant"], 0),
                x["eleves_count"],
                x["traces_count"]
            ),
            reverse=True
        )

    # ============================================================
    # 8. STATISTIQUES GLOBALES AFFICHÉES
    # ============================================================

    eleves_uniques = set()
    enseignants_uniques = set()

    for item in notions_synthese:
        for eleve in item["eleves"]:
            if eleve.get("id"):
                eleves_uniques.add(eleve["id"])

        for enseignant in item["enseignants"]:
            if enseignant.get("id"):
                enseignants_uniques.add(enseignant["id"])

    # ============================================================
    # 9. RENDU
    # ============================================================

    return render_template(
        "admin_synthese_notions.html",
        notions_synthese=notions_synthese,

        total_notions=len(notions_synthese),
        total_traces=sum(item["traces_count"] for item in notions_synthese),
        total_eleves=len(eleves_uniques),
        total_enseignants=len(enseignants_uniques),

        q=q,
        risque=risque_filtre,
        sort=sort,
        lang=lang
    )

@app.route("/enseignant/traces-apprentissage")
def enseignant_traces_apprentissage():
    import json
    from models import TraceApprentissage, User
    from sqlalchemy.orm import joinedload
    from sqlalchemy import or_

    # ============================================================
    # AUTHENTIFICATION ENSEIGNANT PAR SESSION
    # ============================================================

    if "user_id" not in session:
        flash("Veuillez vous connecter comme enseignant.", "warning")
        return redirect(url_for("login_enseignant"))

    if session.get("role") != "enseignant":
        flash("Accès réservé aux enseignants.", "danger")
        return redirect(url_for("login_enseignant"))

    enseignant = db.session.get(User, session["user_id"])

    if not enseignant:
        session.clear()
        flash("Session invalide. Veuillez vous reconnecter.", "warning")
        return redirect(url_for("login_enseignant"))

    if getattr(enseignant, "role", None) != "enseignant":
        session.clear()
        flash("Accès réservé aux enseignants.", "danger")
        return redirect(url_for("login_enseignant"))

    # ============================================================
    # PARAMÈTRES
    # ============================================================

    sort = request.args.get("sort", "date_desc")
    risque = request.args.get("risque", "tous")
    q = request.args.get("q", "").strip()
    lang = session.get("lang", getattr(enseignant, "langue", None) or "fr")

    # ============================================================
    # ÉLÈVES RATTACHÉS À L'ENSEIGNANT
    # ============================================================

    eleves = User.query.filter(
        User.role.in_(["eleve", "élève"]),
        User.enseignant_referent_id == enseignant.id
    ).all()

    if not eleves and hasattr(User, "enseignant_id"):
        eleves = User.query.filter(
            User.role.in_(["eleve", "élève"]),
            User.enseignant_id == enseignant.id
        ).all()

    eleves_ids = [eleve.id for eleve in eleves]

    if not eleves_ids:
        return render_template(
            "enseignant_traces_apprentissage.html",
            traces=[],
            sort=sort,
            risque=risque,
            q=q,
            lang=lang
        )

    # ============================================================
    # REQUÊTE PRINCIPALE
    # ============================================================

    query = (
        TraceApprentissage.query
        .options(
            joinedload(TraceApprentissage.user),
            joinedload(TraceApprentissage.matiere),
            joinedload(TraceApprentissage.unite),
            joinedload(TraceApprentissage.lecon),
            joinedload(TraceApprentissage.exercice)
        )
        .outerjoin(User, TraceApprentissage.user_id == User.id)
        .filter(TraceApprentissage.user_id.in_(eleves_ids))
    )

    if risque != "tous":
        query = query.filter(TraceApprentissage.niveau_risque == risque)

    if q:
        query = query.filter(
            or_(
                User.nom_complet.ilike(f"%{q}%"),
                User.username.ilike(f"%{q}%"),
                TraceApprentissage.notion_cible.ilike(f"%{q}%"),
                TraceApprentissage.source.ilike(f"%{q}%"),
                TraceApprentissage.type_action.ilike(f"%{q}%")
            )
        )

    # ============================================================
    # TRI
    # ============================================================

    if sort == "date_asc":
        query = query.order_by(TraceApprentissage.created_at.asc())

    elif sort == "score_desc":
        query = query.order_by(TraceApprentissage.score.desc().nullslast())

    elif sort == "score_asc":
        query = query.order_by(TraceApprentissage.score.asc().nullsfirst())

    elif sort == "risque":
        query = query.order_by(TraceApprentissage.niveau_risque.asc())

    elif sort == "eleve":
        query = query.order_by(User.nom_complet.asc())

    elif sort == "notion":
        query = query.order_by(TraceApprentissage.notion_cible.asc().nullslast())

    else:
        query = query.order_by(TraceApprentissage.created_at.desc())

    traces = query.limit(100).all()

    # ============================================================
    # PRÉPARATION DES DÉTAILS LISIBLES
    # ============================================================

    for trace in traces:
        detail = {}

        try:
            if trace.analyse_ia:
                detail = json.loads(trace.analyse_ia)
        except Exception:
            detail = {}

        trace.detail_ia = detail
        trace.feedback_lisible = detail.get("current_feedback", trace.analyse_ia or "")
        trace.score_sur_5 = detail.get("current_stars")

        metadata = detail.get("metadata", {})
        meta = trace.meta_json or {}

        trace.langue_trace = (
            metadata.get("language")
            or meta.get("lang")
            or lang
            or "fr"
        )

        trace.question_lisible = (
            meta.get("question_en")
            if trace.langue_trace == "en"
            else meta.get("question_fr")
        )

        if not trace.question_lisible and trace.exercice:
            trace.question_lisible = (
                trace.exercice.question_en
                if trace.langue_trace == "en" and trace.exercice.question_en
                else trace.exercice.question_fr
            )

        trace.reponse_attendue_lisible = (
            meta.get("reponse_attendue_en")
            if trace.langue_trace == "en"
            else meta.get("reponse_attendue_fr")
        )

        if not trace.reponse_attendue_lisible and trace.exercice:
            trace.reponse_attendue_lisible = (
                trace.exercice.reponse_en
                if trace.langue_trace == "en" and trace.exercice.reponse_en
                else trace.exercice.reponse_fr
            )

        trace.correction_symbolique = (
            detail.get("symbolic_verification", {}).get("feedback")
            or meta.get("symbolic_feedback")
            or ""
        )

        trace.prochain_adaptatif = (
            detail.get("adaptive_next")
            or meta.get("adaptive_next")
            or {}
        )

    return render_template(
        "enseignant_traces_apprentissage.html",
        traces=traces,
        sort=sort,
        risque=risque,
        q=q,
        lang=lang
    )

@app.route("/soumettre-sequentiel", methods=["POST"])
def soumettre_sequentiel():
    import json
    import re
    from datetime import datetime, timezone
    from time import perf_counter

    _perf_t0 = perf_counter()
    _perf_last = _perf_t0

    def _perf_mark(label):
        nonlocal _perf_last
        now = perf_counter()
        step = now - _perf_last
        total = now - _perf_t0
        print(
            f"⏱️ PERF SOUMISSION | {label:<34} "
            f"| étape={step:6.3f}s | total={total:6.3f}s"
        )
        _perf_last = now

    print("=== 📝 SOUMISSION SÉQUENTIELLE ADAPTATIVE ===")
    print(f"🔍 Données formulaire: {dict(request.form)}")

    username = request.form.get("username")
    lang = request.form.get("lang", "fr")
    lecon_id = request.form.get("lecon_id")
    exercice_id = request.form.get("exercice_id")
    reponse_eleve = request.form.get("reponse_eleve", "").strip()
    index_str = request.form.get("index", "0")

    try:
        index = int(index_str)
    except (ValueError, TypeError):
        index = 0

    msg_user_not_found = (
        "User not found."
        if lang == "en"
        else "Utilisateur non trouvé."
    )

    msg_access_denied = (
        "Access denied. Your subscription or trial may have expired."
        if lang == "en"
        else "Accès refusé. Votre abonnement ou essai a peut-être expiré."
    )

    msg_missing = (
        "Lesson or exercise not found."
        if lang == "en"
        else "Leçon ou exercice introuvable."
    )

    msg_empty_answer = (
        "Please provide an answer."
        if lang == "en"
        else "Veuillez fournir une réponse."
    )

    msg_save_error = (
        "An error occurred while saving your answer."
        if lang == "en"
        else "Erreur lors de la sauvegarde de votre réponse."
    )

    eleve = User.query.filter_by(username=username).first()

    if not eleve:
        flash(msg_user_not_found, "danger")
        return redirect(url_for("index", lang=lang))

    if not eleve.a_acces_plateforme():
        flash(msg_access_denied, "danger")
        return redirect(url_for("dashboard_eleve", username=username, lang=lang))

    try:
        lecon_id_int = int(lecon_id)
        exercice_id_int = int(exercice_id)
    except (ValueError, TypeError):
        flash(msg_missing, "danger")
        return redirect(url_for("dashboard_eleve", username=username, lang=lang))

    lecon = db.session.get(Lecon, lecon_id_int)
    exercice = db.session.get(Exercice, exercice_id_int)

    if not lecon or not exercice or exercice.lecon_id != lecon.id:
        flash(msg_missing, "danger")
        return redirect(url_for("dashboard_eleve", username=username, lang=lang))

    # ============================================================
    # CONTEXTE PÉDAGOGIQUE BILINGUE
    # ============================================================

    unite = lecon.unite if lecon and lecon.unite else None
    matiere = unite.matiere if unite and unite.matiere else None
    niveau = matiere.niveau if matiere and matiere.niveau else eleve.niveau

    matiere_fr = matiere.nom if matiere else None
    matiere_en = matiere.nom_en if matiere and matiere.nom_en else matiere_fr

    unite_fr = unite.nom if unite else None
    unite_en = unite.nom_en if unite and unite.nom_en else unite_fr

    lecon_fr = lecon.titre_fr if lecon else None
    lecon_en = lecon.titre_en if lecon and lecon.titre_en else lecon_fr

    matiere_affichee = matiere_en if lang == "en" and matiere_en else matiere_fr
    lecon_affichee = lecon_en if lang == "en" and lecon_en else lecon_fr

    # ============================================================
    # 0. SÉCURITÉ ANTI-RESOUMISSION
    # ============================================================

    reponse_existante = StudentResponse.query.filter_by(
        user_id=eleve.id,
        exercice_id=exercice.id
    ).first()

    if reponse_existante:
        print(
            f"🔒 Exercice déjà fait. Aucune nouvelle correction IA. "
            f"Élève={eleve.id}, exercice={exercice.id}"
        )

        return redirect(url_for(
            "exercice_sequentiel_progressif",
            username=username,
            lecon_id=lecon.id,
            lang=lang,
            exercice_id=exercice.id,
            show_feedback=True
        ))

    if not reponse_eleve:
        flash(msg_empty_answer, "warning")
        return redirect(url_for(
            "exercice_sequentiel_progressif",
            username=username,
            lecon_id=lecon.id,
            lang=lang,
            exercice_id=exercice.id
        ))

    question = (
        exercice.question_en
        if lang == "en" and exercice.question_en
        else exercice.question_fr
    )

    options_exercice = (
        exercice.options_en
        if lang == "en" and exercice.options_en
        else exercice.options_fr
    )

    reponse_attendue = (
        exercice.reponse_en
        if lang == "en" and exercice.reponse_en
        else exercice.reponse_fr
    )

    explication_existante = (
        exercice.explication_en
        if lang == "en" and exercice.explication_en
        else exercice.explication_fr
    )

    _perf_mark("chargement contexte + contrôles")

    # ============================================================
    # 1A. RÉPONSE ATTENDUE : STRATÉGIE ADAPTATIVE
    # ============================================================
    #
    # RÈGLE :
    #
    # 1. Si la réponse attendue existe déjà dans la base :
    #       -> réutilisation immédiate ;
    #       -> aucun appel IA.
    #
    # 2. Si elle est absente et que l'exercice est COURT / SIMPLE :
    #       -> une première génération contrôlée est autorisée ;
    #       -> on essaie d'abord une vérification LOCALE ;
    #       -> si la preuve locale est suffisante, on enregistre ;
    #       -> sinon, un deuxième contrôle indépendant reste possible
    #          uniquement pour ce petit exercice.
    #
    # 3. Si elle est absente et que l'exercice est LONG / COMPLEXE :
    #       -> aucune double résolution synchrone ;
    #       -> verdict non pénalisant "uncertain" ;
    #       -> pas de baisse du profil, pas de remédiation ;
    #       -> prévention des WORKER TIMEOUT / 502 Render.
    #
    # IMPORTANT :
    # cette logique ne s'applique QUE si la réponse attendue est absente.
    # ============================================================

    reference_answer_source = "database"
    reference_answer_generated = False
    reference_generation_failed = False
    reference_generation_reason = None
    reference_second_answer = None
    reference_comparison_method = None

    reference_complexity = {
        "is_long_or_complex": False,
        "reasons": [],
        "character_count": len(question or ""),
        "word_count": len((question or "").split()),
        "numbered_subquestions": 0,
        "question_marks": (question or "").count("?"),
        "line_count": len((question or "").splitlines())
    }

    def _extract_json_object(raw_text):
        if not raw_text:
            return None

        cleaned = raw_text.strip()

        if cleaned.startswith("```"):
            cleaned = re.sub(
                r"^```(?:json)?\s*",
                "",
                cleaned,
                flags=re.IGNORECASE
            )
            cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            return json.loads(cleaned)

        except Exception:
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)

            if not match:
                return None

            try:
                return json.loads(match.group(0))
            except Exception:
                return None

    def _normalize_reference_text(value):
        value = (value or "").strip()
        value = value.replace("\\$", "$")
        value = value.replace("\u00a0", " ")
        value = re.sub(r"\s+", " ", value)
        return value

    def _parse_reference_number(value):
        """
        Retourne un float seulement si toute la référence
        est essentiellement une valeur scalaire.
        """
        raw = _normalize_reference_text(value)

        match = re.fullmatch(
            r"\s*([-+]?(?:\d+(?:[.,]\d+)?|\d*[.,]\d+)"
            r"(?:\s*/\s*[-+]?\d+(?:[.,]\d+)?)?\s*%?)"
            r"\s*(?:\$|€|£|cad|usd|dollars?|euros?)?\s*",
            raw,
            re.IGNORECASE,
        )

        if not match:
            return None

        token = match.group(1).replace(" ", "")
        is_percent = token.endswith("%")

        if is_percent:
            token = token[:-1]

        token = token.replace(",", ".")

        try:
            if "/" in token:
                numerator, denominator = token.split("/", 1)
                denominator_value = float(denominator)

                if denominator_value == 0:
                    return None

                numeric_value = (
                    float(numerator) / denominator_value
                )

            else:
                numeric_value = float(token)

            if is_percent:
                numeric_value = numeric_value / 100.0

            return numeric_value

        except (
            TypeError,
            ValueError,
            ZeroDivisionError
        ):
            return None

    def _references_equivalent(
        first_answer,
        second_answer,
        options_raw
    ):
        """
        Comparaison prudente de deux résolutions indépendantes.
        Utilisée seulement si aucune preuve locale suffisante
        n'a pu confirmer la première génération.
        """
        import unicodedata
        from difflib import SequenceMatcher

        first = _normalize_reference_text(first_answer)
        second = _normalize_reference_text(second_answer)

        if options_raw:
            first_label = first.upper().strip(" .):")
            second_label = second.upper().strip(" .):")

            if (
                re.fullmatch(r"[A-Z]", first_label)
                and re.fullmatch(r"[A-Z]", second_label)
            ):
                return (
                    first_label == second_label,
                    "mcq_label_comparison"
                )

        first_number = _parse_reference_number(first)
        second_number = _parse_reference_number(second)

        if (
            first_number is not None
            and second_number is not None
        ):
            tolerance = max(
                1e-9,
                1e-9 * max(
                    abs(first_number),
                    abs(second_number),
                    1.0
                )
            )

            return (
                abs(first_number - second_number)
                <= tolerance,
                "numeric_reference_comparison"
            )

        def _canonical_reference_text(value):
            txt = str(value or "")
            txt = unicodedata.normalize("NFKC", txt)

            txt = (
                txt.replace("−", "-")
                   .replace("–", "-")
                   .replace("—", "-")
            )

            txt = txt.casefold().strip()
            txt = re.sub(r"\s+", " ", txt)

            txt = re.sub(
                r"\s*([,;:{}()\[\]=+\-*/<>])\s*",
                r"\1",
                txt
            )

            txt = re.sub(r"[.!?]+$", "", txt)

            return txt.strip()

        first_text = _canonical_reference_text(first)
        second_text = _canonical_reference_text(second)

        if first_text == second_text:
            return (
                True,
                "canonical_text_reference_comparison"
            )

        number_pattern = (
            r"(?<![\w.])-?\d+(?:[.,]\d+)?"
        )

        first_numbers = re.findall(
            number_pattern,
            first_text
        )

        second_numbers = re.findall(
            number_pattern,
            second_text
        )

        if first_numbers != second_numbers:
            return (
                False,
                "text_reference_numeric_mismatch"
            )

        negation_pattern = (
            r"\b(?:ne|n'|non|pas|jamais|aucun|aucune|"
            r"not|never|no|none)\b"
        )

        first_negations = re.findall(
            negation_pattern,
            first_text,
            flags=re.IGNORECASE
        )

        second_negations = re.findall(
            negation_pattern,
            second_text,
            flags=re.IGNORECASE
        )

        if first_negations != second_negations:
            return (
                False,
                "text_reference_negation_mismatch"
            )

        similarity = SequenceMatcher(
            None,
            first_text,
            second_text
        ).ratio()

        if similarity >= 0.95:
            return (
                True,
                "high_similarity_text_reference_comparison"
            )

        return (
            False,
            "normalized_text_reference_comparison"
        )

    def _estimate_reference_complexity(
        question_text,
        options_raw
    ):
        """
        Détecteur volontairement conservateur.

        On classe LONG / COMPLEXE lorsqu'un exercice risque de
        demander plusieurs réponses ou une résolution textuelle
        importante pendant la requête HTTP.
        """
        raw = question_text or ""
        normalized = raw.replace("\r\n", "\n")

        char_count = len(normalized)
        words = normalized.split()
        word_count = len(words)
        line_count = len(normalized.splitlines())
        question_marks = normalized.count("?")

        # Sous-questions telles que :
        # 1- ..., 2- ...
        # 1. ..., 2. ...
        # 1) ..., 2) ...
        numbered_matches = re.findall(
            r"(?m)(?:^|\n)\s*(\d{1,2})\s*[\-\.\)]\s*",
            normalized
        )

        # Variante où plusieurs sous-questions sont sur une seule ligne.
        inline_numbered_matches = re.findall(
            r"(?<!\d)(\d{1,2})\s*[\-\)]\s+",
            normalized
        )

        numbered_subquestions = max(
            len(numbered_matches),
            len(inline_numbered_matches)
        )

        reasons = []

        # Seuils prudents pour éviter les gros appels synchrones.
        if char_count > 1200:
            reasons.append(
                f"énoncé très long ({char_count} caractères)"
            )

        if word_count > 190:
            reasons.append(
                f"énoncé très verbeux ({word_count} mots)"
            )

        if line_count > 14:
            reasons.append(
                f"beaucoup de lignes ({line_count})"
            )

        if numbered_subquestions >= 4:
            reasons.append(
                f"plusieurs sous-questions ({numbered_subquestions})"
            )

        if question_marks >= 4:
            reasons.append(
                f"plusieurs questions ({question_marks})"
            )

        # Beaucoup d'options peuvent aussi rendre la tâche lourde.
        if options_raw and len(str(options_raw)) > 1800:
            reasons.append(
                "bloc de choix très volumineux"
            )

        # Plusieurs verbes de consigne peuvent signaler une activité
        # composite, surtout si l'énoncé est déjà relativement long.
        instruction_markers = re.findall(
            r"\b(?:calcule|calculer|détermine|determiner|"
            r"explique|justifie|compare|complète|complete|"
            r"solve|calculate|explain|justify|compare)\b",
            normalized,
            flags=re.IGNORECASE
        )

        if (
            len(instruction_markers) >= 4
            and char_count > 700
        ):
            reasons.append(
                "plusieurs consignes distinctes"
            )

        return {
            "is_long_or_complex": bool(reasons),
            "reasons": reasons,
            "character_count": char_count,
            "word_count": word_count,
            "numbered_subquestions": numbered_subquestions,
            "question_marks": question_marks,
            "line_count": line_count
        }

    def _try_local_reference_confirmation(
        question_text,
        generated_answer
    ):
        """
        Essaie de confirmer localement une référence générée
        pour les cas mathématiques simples.

        Retour :
        {
            "confirmed": bool,
            "method": str,
            "details": dict
        }

        Une absence de preuve locale n'est PAS un échec :
        le second contrôle indépendant peut alors prendre le relais,
        seulement pour les exercices courts.
        """
        result = {
            "confirmed": False,
            "method": None,
            "details": {}
        }

        if not generated_answer:
            return result

        # --------------------------------------------------------
        # 1. ÉQUATION SIMPLE : validation par substitution.
        # --------------------------------------------------------
        try:
            from services.math_verification import (
                verifier_solution_equation_fractionnaire
            )

            equation_result = (
                verifier_solution_equation_fractionnaire(
                    equation_initiale=question_text,
                    reponse_eleve=generated_answer
                )
            )

            if (
                isinstance(equation_result, dict)
                and equation_result.get(
                    "verification_contextuelle"
                )
                and equation_result.get(
                    "est_correct"
                ) is True
            ):
                result["confirmed"] = True
                result["method"] = (
                    "local_equation_reference_confirmation"
                )
                result["details"] = equation_result
                return result

        except Exception as e:
            result["details"][
                "equation_local_error"
            ] = str(e)

        # --------------------------------------------------------
        # 2. CALCUL NUMÉRIQUE SIMPLE : comparaison contextuelle.
        # --------------------------------------------------------
        try:
            from services.math_verification import (
                verifier_resultat_expression_contextuelle
            )

            numeric_result = (
                verifier_resultat_expression_contextuelle(
                    objectif_initial=question_text,
                    reponse_eleve=generated_answer
                )
            )

            if (
                isinstance(numeric_result, dict)
                and numeric_result.get(
                    "calcul_verifie"
                )
                and numeric_result.get(
                    "est_correct"
                ) is True
            ):
                result["confirmed"] = True
                result["method"] = (
                    "local_numeric_reference_confirmation"
                )
                result["details"] = numeric_result
                return result

        except Exception as e:
            result["details"][
                "numeric_local_error"
            ] = str(e)

        return result

    # ============================================================
    # RÉPONSE ABSENTE : CLASSIFICATION AVANT TOUT APPEL IA
    # ============================================================

    if not reponse_attendue or not str(reponse_attendue).strip():

        reference_complexity = (
            _estimate_reference_complexity(
                question,
                options_exercice
            )
        )

        print(
            "📏 Complexité de la référence : "
            f"{reference_complexity}"
        )

        # ========================================================
        # CAS LONG / COMPLEXE
        # ========================================================

        if reference_complexity["is_long_or_complex"]:

            reference_answer_source = (
                "missing_complex_no_sync_generation"
            )

            reference_generation_failed = True

            reference_generation_reason = (
                "La réponse attendue est absente et l'exercice a été "
                "classé long ou complexe. Afin d'éviter une double "
                "résolution IA synchrone susceptible de dépasser le "
                "temps disponible sur le serveur, aucune référence "
                "n'est fabriquée pendant cette soumission. "
                "La réponse de l'élève est conservée sans pénalité. "
                "Critères : "
                + "; ".join(
                    reference_complexity["reasons"]
                )
            )

            print(
                f"🛑 Exercice {exercice.id} classé LONG/COMPLEXE : "
                "aucune génération de référence synchrone."
            )

        # ========================================================
        # CAS COURT / SIMPLE
        # ========================================================

        else:

            reference_answer_source = (
                "generated_simple_first_use"
            )

            print(
                f"🧩 Réponse attendue absente pour l'exercice "
                f"{exercice.id}, mais exercice classé COURT/SIMPLE : "
                "génération contrôlée autorisée."
            )

            if lang == "en":
                prompt_reference = f"""
You are creating the canonical reusable reference answer for a short mathematics exercise.

EXERCISE:
{question}

MULTIPLE-CHOICE OPTIONS:
{options_exercice or "None"}

EXISTING OFFICIAL EXPLANATION:
{explication_existante or "None"}

Return ONLY valid JSON with exactly these fields:
{{
  "expected_answer": "...",
  "correction": "...",
  "confidence": 0.0,
  "reason": "..."
}}

Rules:
- Solve the exercise yourself.
- If multiple-choice options are provided, expected_answer MUST be only the correct option letter.
- If there are no options, expected_answer must be a concise canonical final answer.
- correction must be reusable and independent of any student.
- confidence must reflect your confidence in the mathematical result.
""".strip()

            else:
                prompt_reference = f"""
Tu dois créer la réponse de référence canonique et réutilisable d'un exercice court de mathématiques.

ÉNONCÉ :
{question}

CHOIX DE RÉPONSES :
{options_exercice or "Aucun"}

CORRIGÉ OFFICIEL DÉJÀ PRÉSENT :
{explication_existante or "Aucun"}

Retourne UNIQUEMENT un JSON valide avec exactement ces champs :
{{
  "expected_answer": "...",
  "correction": "...",
  "confidence": 0.0,
  "reason": "..."
}}

Règles :
- Résous toi-même l'exercice.
- Si des choix sont fournis, expected_answer DOIT contenir uniquement la lettre correcte.
- S'il n'y a pas de choix, expected_answer doit être une réponse finale canonique et concise.
- correction doit être réutilisable et indépendante de tout élève.
- confidence doit refléter ta confiance dans le résultat mathématique.
""".strip()

            try:
                generation_completion = (
                    client.chat.completions.create(
                        model="gpt-4",
                        messages=[
                            {
                                "role": "user",
                                "content": prompt_reference
                            }
                        ],
                        temperature=0.0
                    )
                )

                generation_raw = (
                    generation_completion.choices[0]
                    .message.content
                    .strip()
                )

                generation_data = (
                    _extract_json_object(
                        generation_raw
                    )
                )

                generated_answer = (
                    str(
                        generation_data.get(
                            "expected_answer",
                            ""
                        )
                    ).strip()
                    if isinstance(
                        generation_data,
                        dict
                    )
                    else ""
                )

                generated_correction = (
                    str(
                        generation_data.get(
                            "correction",
                            ""
                        )
                    ).strip()
                    if isinstance(
                        generation_data,
                        dict
                    )
                    else ""
                )

                try:
                    generation_confidence = float(
                        generation_data.get(
                            "confidence",
                            0.0
                        )
                        if isinstance(
                            generation_data,
                            dict
                        )
                        else 0.0
                    )

                except (
                    TypeError,
                    ValueError
                ):
                    generation_confidence = 0.0

                generation_reason = (
                    str(
                        generation_data.get(
                            "reason",
                            ""
                        )
                    ).strip()
                    if isinstance(
                        generation_data,
                        dict
                    )
                    else ""
                )

                # ------------------------------------------------
                # Première exigence :
                # réponse générée + confiance élevée.
                # ------------------------------------------------

                if (
                    generated_answer
                    and generation_confidence >= 0.97
                ):

                    local_confirmation = (
                        _try_local_reference_confirmation(
                            question,
                            generated_answer
                        )
                    )

                    print(
                        "🧮 Confirmation locale de référence : "
                        f"{local_confirmation}"
                    )

                    reference_confirmed = False

                    # =============================================
                    # 1. PREUVE LOCALE SUFFISANTE
                    # =============================================

                    if local_confirmation["confirmed"]:

                        reference_confirmed = True
                        reference_comparison_method = (
                            local_confirmation["method"]
                        )

                        print(
                            "✅ Référence confirmée localement : "
                            "aucun deuxième appel IA nécessaire."
                        )

                    # =============================================
                    # 2. PAS DE PREUVE LOCALE :
                    #    SECOND CONTRÔLE UNIQUEMENT POUR
                    #    LE PETIT EXERCICE.
                    # =============================================

                    else:

                        print(
                            "ℹ️ Aucune preuve locale suffisante. "
                            "Deuxième contrôle indépendant autorisé "
                            "car l'exercice est court/simple."
                        )

                        if lang == "en":
                            prompt_verify_reference = f"""
Solve this short mathematics exercise independently.

EXERCISE:
{question}

MULTIPLE-CHOICE OPTIONS:
{options_exercice or "None"}

Return ONLY valid JSON:
{{
  "expected_answer": "...",
  "confidence": 0.0,
  "reason": "..."
}}

Rules:
- Solve the exercise yourself.
- Do not assume any proposed answer.
- If multiple-choice options are provided, expected_answer MUST contain only the correct option letter.
- Otherwise expected_answer must be a concise canonical final answer.
""".strip()

                        else:
                            prompt_verify_reference = f"""
Résous indépendamment cet exercice court de mathématiques.

ÉNONCÉ :
{question}

CHOIX DE RÉPONSES :
{options_exercice or "Aucun"}

Retourne UNIQUEMENT un JSON valide :
{{
  "expected_answer": "...",
  "confidence": 0.0,
  "reason": "..."
}}

Règles :
- Résous toi-même l'exercice.
- Ne suppose aucune réponse proposée.
- Si des choix sont fournis, expected_answer DOIT contenir uniquement la lettre correcte.
- Sinon expected_answer doit être une réponse finale canonique et concise.
""".strip()

                        verify_completion = (
                            client.chat.completions.create(
                                model="gpt-4",
                                messages=[
                                    {
                                        "role": "user",
                                        "content": (
                                            prompt_verify_reference
                                        )
                                    }
                                ],
                                temperature=0.0
                            )
                        )

                        verify_raw = (
                            verify_completion.choices[0]
                            .message.content
                            .strip()
                        )

                        verify_data = (
                            _extract_json_object(
                                verify_raw
                            )
                        )

                        verify_answer = (
                            str(
                                verify_data.get(
                                    "expected_answer",
                                    ""
                                )
                            ).strip()
                            if isinstance(
                                verify_data,
                                dict
                            )
                            else ""
                        )

                        try:
                            verify_confidence = float(
                                verify_data.get(
                                    "confidence",
                                    0.0
                                )
                                if isinstance(
                                    verify_data,
                                    dict
                                )
                                else 0.0
                            )

                        except (
                            TypeError,
                            ValueError
                        ):
                            verify_confidence = 0.0

                        verify_reason = (
                            str(
                                verify_data.get(
                                    "reason",
                                    ""
                                )
                            ).strip()
                            if isinstance(
                                verify_data,
                                dict
                            )
                            else ""
                        )

                        (
                            references_match,
                            reference_comparison_method
                        ) = _references_equivalent(
                            generated_answer,
                            verify_answer,
                            options_exercice
                        )

                        reference_second_answer = (
                            verify_answer
                        )

                        print(
                            "🔎 Double résolution courte : "
                            f"réponse_1={generated_answer!r} | "
                            f"réponse_2={verify_answer!r} | "
                            f"méthode={reference_comparison_method} | "
                            f"équivalentes={references_match}"
                        )

                        reference_confirmed = (
                            bool(verify_answer)
                            and verify_confidence >= 0.95
                            and references_match
                        )

                        if not reference_confirmed:
                            reference_generation_reason = (
                                "Le petit exercice n'a pas pu être "
                                "confirmé avec suffisamment de fiabilité. "
                                f"Première réponse={generated_answer!r}; "
                                f"deuxième réponse={verify_answer!r}; "
                                f"méthode={reference_comparison_method}; "
                                f"confiance_2={verify_confidence}. "
                                f"{verify_reason}"
                            )

                    # =============================================
                    # PERSISTANCE UNIQUEMENT APRÈS CONFIRMATION
                    # =============================================

                    if reference_confirmed:

                        reponse_attendue = generated_answer
                        reference_answer_generated = True

                        if lang == "en":
                            exercice.reponse_en = (
                                generated_answer
                            )
                        else:
                            exercice.reponse_fr = (
                                generated_answer
                            )

                        if (
                            generated_correction
                            and (
                                not explication_existante
                                or not str(
                                    explication_existante
                                ).strip()
                            )
                        ):
                            if lang == "en":
                                exercice.explication_en = (
                                    generated_correction
                                )
                            else:
                                exercice.explication_fr = (
                                    generated_correction
                                )

                            explication_existante = (
                                generated_correction
                            )

                        try:
                            db.session.commit()

                            print(
                                "💾 Réponse attendue confirmée et "
                                f"enregistrée pour l'exercice "
                                f"{exercice.id} : "
                                f"{reponse_attendue}"
                            )

                        except Exception as e:
                            db.session.rollback()

                            reference_generation_failed = True
                            reference_generation_reason = (
                                "Référence confirmée mais impossible "
                                f"à enregistrer : {e}"
                            )

                    else:
                        reference_generation_failed = True

                        if not reference_generation_reason:
                            reference_generation_reason = (
                                "La référence générée n'a pas pu être "
                                "confirmée avec suffisamment de fiabilité."
                            )

                else:
                    reference_generation_failed = True
                    reference_generation_reason = (
                        "La première génération de référence pour "
                        "ce petit exercice n'a pas atteint le seuil "
                        f"de confiance requis. {generation_reason}"
                    )

            except Exception as e:
                reference_generation_failed = True
                reference_generation_reason = (
                    "Erreur pendant la génération contrôlée "
                    f"de la réponse attendue : {e}"
                )

    else:

        # ========================================================
        # RÉPONSE DÉJÀ EN BASE : CHEMIN LE PLUS RAPIDE
        # ========================================================

        reponse_attendue = str(
            reponse_attendue
        ).strip()

        reference_answer_source = "database"

        print(
            f"♻️ Réponse attendue déjà disponible pour "
            f"l'exercice {exercice.id} : "
            "aucune génération IA."
        )

    _perf_mark("référence attendue prête")

    # ============================================================
    # 1B. MOTEUR HYBRIDE DE VALIDATION
    # ============================================================

    from validation.engine import ValidationEngine
    from validation.result import ValidationResult

    validation_engine = ValidationEngine()

    if reference_generation_failed or not reponse_attendue:

        validation_result = ValidationResult.uncertain(
            confidence=0.0,
            method="reference_answer_generation_failed",
            reason=(
                reference_generation_reason
                or "La réponse attendue est absente et n'a pas pu être générée avec suffisamment de fiabilité."
            ),
            normalized_student_answer=reponse_eleve,
            normalized_expected_answer=reponse_attendue
        )

    else:

        try:
            validation_result = validation_engine.validate(
                student_answer=reponse_eleve,
                expected_answer=reponse_attendue,
                question=question or "",
                options=options_exercice
            )

        except Exception as e:
            print(f"⚠️ Erreur moteur hybride : {e}")

            validation_result = ValidationResult.uncertain(
                confidence=0.0,
                method="validation_engine_error",
                reason=(
                    "Le moteur de validation a rencontré une erreur technique. "
                    "La réponse ne doit pas être pénalisée automatiquement."
                ),
                normalized_student_answer=reponse_eleve,
                normalized_expected_answer=reponse_attendue
            )

    validation_verdict = validation_result.verdict
    validation_confidence = validation_result.confidence
    validation_method = validation_result.method

    # Tout verdict autre que correct/incorrect est NON PÉNALISANT.
    # Cela couvre uncertain, unsupported, error et toute future
    # catégorie technique non concluante.
    validation_requires_review = (
        validation_verdict not in {"correct", "incorrect"}
    )

    print("==============================================")
    print("🧠 MOTEUR HYBRIDE")
    print(f"Verdict     : {validation_verdict}")
    print(f"Confiance   : {validation_confidence}")
    print(f"Méthode     : {validation_method}")
    print(f"Raison      : {validation_result.reason}")
    print("==============================================")

    # ----------------------------------------------------------------
    # Compatibilité temporaire avec le reste de l'interface existante.
    #
    # IMPORTANT :
    # symbolic_correct n'est plus produit directement par SymPy.
    # Il représente maintenant le verdict FINAL du moteur hybride.
    # ----------------------------------------------------------------

    if validation_verdict == "correct":
        symbolic_correct = True

    elif validation_verdict == "incorrect":
        symbolic_correct = False

    else:
        symbolic_correct = None

    validation_details = validation_result.details or {}

    symbolic_result = {
        "verified": validation_verdict in {"correct", "incorrect"},
        "is_correct": symbolic_correct,
        "verdict": validation_verdict,
        "confidence": validation_confidence,
        "method": validation_method,
        "reason": validation_result.reason,
        "result_correct": validation_result.result_correct,
        "reasoning_correct": validation_result.reasoning_correct,
        "error_type": validation_result.error_type,
        "details": validation_details
    }

    if lang == "en":
        if validation_verdict == "correct":
            symbolic_feedback = (
                "✅ Mathematical validation: CORRECT\n"
                f"Method: {validation_method}\n"
                f"Confidence: {validation_confidence:.2f}"
            )

        elif validation_verdict == "incorrect":
            symbolic_feedback = (
                "❌ Mathematical validation: INCORRECT\n"
                f"Method: {validation_method}\n"
                f"Confidence: {validation_confidence:.2f}"
            )

        else:
            symbolic_feedback = (
                "⚠️ Mathematical validation: UNCERTAIN\n"
                "The answer has not been automatically marked incorrect."
            )

    else:
        if validation_verdict == "correct":
            symbolic_feedback = (
                "✅ Vérification mathématique : CORRECTE\n"
                f"Méthode : {validation_method}\n"
                f"Confiance : {validation_confidence:.2f}"
            )

        elif validation_verdict == "incorrect":
            symbolic_feedback = (
                "❌ Vérification mathématique : INCORRECTE\n"
                f"Méthode : {validation_method}\n"
                f"Confiance : {validation_confidence:.2f}"
            )

        else:
            symbolic_feedback = (
                "⚠️ Vérification mathématique : INCERTAINE\n"
                "La réponse n'est pas automatiquement considérée comme fausse."
            )

    _perf_mark("validation hybride terminée")

    # ============================================================
    # 2. CORRIGÉ PARTAGÉ + RÉTROACTION PÉDAGOGIQUE
    # ============================================================
    #
    # RÈGLE HISTORIQUE DE TUTORATAI :
    #
    # 1. Si le corrigé générique de l'exercice existe déjà dans
    #    explication_fr / explication_en :
    #       => on le réutilise.
    #
    # 2. S'il n'existe pas encore :
    #       => il est généré UNE SEULE FOIS ;
    #       => il est enregistré dans la table Exercice ;
    #       => les élèves suivants réutilisent le même corrigé.
    #
    # 3. Le corrigé générique est distinct de la rétroaction
    #    individuelle sur la réponse de l'élève.
    #
    # 4. QCM déterministe :
    #       => pas d'IA supplémentaire pour la rétroaction individuelle.
    #
    # 5. Réponse libre :
    #       => rétroaction individuelle IA conservée si nécessaire.
    # ============================================================

    analyse_ia = ""
    etoiles_gpt = None

    explication_exercice = (
        exercice.explication_en
        if lang == "en" and exercice.explication_en
        else exercice.explication_fr
    )

    options_exercice = (
        exercice.options_en
        if lang == "en" and exercice.options_en
        else exercice.options_fr
    )

    correction_source = "database"

    # ============================================================
    # 2A. GÉNÉRATION PARESSEUSE DU CORRIGÉ GÉNÉRIQUE
    # ============================================================
    #
    # RÈGLES :
    #
    # 1. Si un corrigé existe déjà :
    #       -> on le réutilise ;
    #       -> aucun appel IA.
    #
    # 2. Si le verdict est certain (correct / incorrect)
    #    et qu'aucun corrigé n'existe :
    #       -> génération unique du corrigé ;
    #       -> sauvegarde dans Exercice ;
    #       -> réutilisation pour tous les élèves suivants.
    #
    # 3. Si le verdict nécessite une vérification :
    #       -> NE PAS générer de nouveau corrigé IA ;
    #       -> NE PAS présenter une solution non confirmée
    #          comme corrigé officiel ;
    #       -> rétroaction neutre et non pénalisante.
    #
    # Cela évite notamment un troisième appel IA lorsque
    # la génération de la réponse de référence a déjà échoué.
    # ============================================================

    if not explication_exercice or not explication_exercice.strip():

        # ========================================================
        # CAS 1 : VALIDATION INCERTAINE
        # ========================================================
        #
        # On ne fabrique pas de corrigé officiel lorsqu'on ne
        # dispose pas d'une référence suffisamment fiable.
        # ========================================================

        if validation_requires_review:

            correction_source = "skipped_uncertain_validation"
            explication_exercice = ""

            print(
                "⚠️ Corrigé générique non généré : "
                "le verdict nécessite une vérification. "
                "Aucun appel IA supplémentaire."
            )

        # ========================================================
        # CAS 2 : VALIDATION CONCLUANTE
        # ========================================================

        else:

            correction_source = "generated_first_use"

            if lang == "en":

                prompt_corrige = f"""
Create the reusable official correction for this mathematics exercise.

EXERCISE:
{question}

POSSIBLE CHOICES:
{options_exercice or "No multiple-choice options"}

EXPECTED ANSWER:
{reponse_attendue}

Write a concise but pedagogically complete correction.
Explain the mathematical reasoning and state the final answer.
Do not mention any specific student.
Do not score a student response.
This correction will be stored and reused for future students.
""".strip()

            else:

                prompt_corrige = f"""
Crée le corrigé officiel réutilisable de cet exercice de mathématiques.

ÉNONCÉ :
{question}

CHOIX ÉVENTUELS :
{options_exercice or "Aucun choix multiple"}

RÉPONSE ATTENDUE :
{reponse_attendue}

Rédige un corrigé concis mais pédagogiquement complet.
Explique le raisonnement mathématique et donne clairement la réponse finale.
Ne parle d'aucun élève en particulier.
Ne donne aucune note à une réponse d'élève.
Ce corrigé sera enregistré et réutilisé pour les prochains élèves.
""".strip()

            try:

                correction_completion = client.chat.completions.create(
                    model="gpt-4",
                    messages=[
                        {
                            "role": "user",
                            "content": prompt_corrige
                        }
                    ],
                    temperature=0.1
                )

                explication_exercice = (
                    correction_completion.choices[0]
                    .message.content
                    .strip()
                )

                if explication_exercice:

                    if lang == "en":
                        exercice.explication_en = explication_exercice
                    else:
                        exercice.explication_fr = explication_exercice

                    try:

                        db.session.commit()

                        print(
                            "💾 Corrigé générique généré et enregistré "
                            f"pour l'exercice {exercice.id}."
                        )

                    except Exception as e:

                        db.session.rollback()

                        print(
                            "⚠️ Corrigé généré mais non enregistré "
                            f"dans Exercice : {e}"
                        )

            except Exception as e:

                correction_source = "generation_failed"

                print(
                    f"⚠️ Impossible de générer le corrigé générique : {e}"
                )

                explication_exercice = ""

    else:

        correction_source = "database"

        print(
            f"♻️ Corrigé générique déjà présent : "
            f"réutilisation pour l'exercice {exercice.id}."
        )

    # ============================================================
    # 2B. DÉTERMINER SI LE CAS EST UN QCM DÉTERMINISTE
    # ============================================================

    methodes_qcm_deterministes = {
        "normalized_exact_match",
        "mcq_label_mismatch",
        "mcq_resolved_exact_match",
        "numeric_equivalence",
        "numeric_match",
        "equation_equivalence",
        "symbolic_equivalence"
    }

    methodes_libres_deterministes = {
        "free_numeric_verified_equality",
        "free_numeric_verified_equality_mismatch",
        "free_numeric_explicit_final",
        "free_numeric_explicit_final_mismatch",
        "free_numeric_single_value",
        "free_numeric_single_value_mismatch"
    }

    feedback_qcm_local = (
        bool(options_exercice)
        and validation_method in methodes_qcm_deterministes
        and validation_verdict in {"correct", "incorrect"}
    )

    feedback_libre_local = (
        not bool(options_exercice)
        and validation_method in methodes_libres_deterministes
        and validation_verdict in {"correct", "incorrect"}
    )

    # ============================================================
    # CAS A : VERDICT INCERTAIN
    # ============================================================

    if validation_requires_review:

        if lang == "en":
            analyse_ia = (
                "Analysis:\n"
                "Your answer could not be validated with sufficient certainty. "
                "It has not been marked incorrect and does not negatively affect "
                "your learner profile.\n\n"
                "Score: pending review\n\n"
                "Correction:\n"
            )

            if explication_exercice:
                analyse_ia += explication_exercice
            else:
                analyse_ia += (
                    "A mathematical or pedagogical review is recommended "
                    "before this answer affects the learner diagnostic."
                )

        else:
            analyse_ia = (
                "Analyse :\n"
                "Ta réponse n'a pas pu être validée avec suffisamment de certitude. "
                "Elle n'est pas considérée comme fausse et n'affecte pas négativement "
                "ton profil d'apprentissage.\n\n"
                "Note : en attente de vérification\n\n"
                "Correction :\n"
            )

            if explication_exercice:
                analyse_ia += explication_exercice
            else:
                analyse_ia += (
                    "Une vérification mathématique ou pédagogique est recommandée "
                    "avant que cette réponse influence le diagnostic."
                )

    # ============================================================
    # CAS B : QCM DÉTERMINISTE
    # ============================================================

    elif feedback_qcm_local:

        if validation_verdict == "correct":

            etoiles_gpt = 5

            if lang == "en":
                analyse_ia = (
                    "Analysis:\n"
                    "Your answer is correct.\n\n"
                    "Score: 5/5\n\n"
                    "Correction:\n"
                    f"{explication_exercice or 'The selected answer matches the official answer key.'}"
                )
            else:
                analyse_ia = (
                    "Analyse :\n"
                    "Ta réponse est correcte.\n\n"
                    "Note : 5/5\n\n"
                    "Correction :\n"
                    f"{explication_exercice or 'Le choix sélectionné correspond à la réponse officielle.'}"
                )

        else:

            etoiles_gpt = 0

            if lang == "en":
                analyse_ia = (
                    "Analysis:\n"
                    "Your selected answer is incorrect.\n\n"
                    "Score: 0/5\n\n"
                    "Correction:\n"
                    f"{explication_exercice or 'Review the expected answer and the proposed choices.'}"
                )
            else:
                analyse_ia = (
                    "Analyse :\n"
                    "La réponse choisie est incorrecte.\n\n"
                    "Note : 0/5\n\n"
                    "Correction :\n"
                    f"{explication_exercice or 'Revois la réponse attendue et les choix proposés.'}"
                )

        print(
            "⚡ Rétroaction locale QCM : "
            f"méthode={validation_method}, "
            f"verdict={validation_verdict}, "
            "aucun appel IA individuel supplémentaire."
        )

    # ============================================================
    # CAS C : RÉPONSE LIBRE NUMÉRIQUE VALIDÉE DÉTERMINISTEMENT
    # ============================================================

    elif feedback_libre_local:

        if validation_verdict == "correct":

            # 5/5 : calcul explicite et arithmétiquement vérifié.
            # 4/5 : réponse finale correcte formulée clairement.
            # 3/5 : valeur correcte seule, sans démarche observable.
            if validation_method == "free_numeric_verified_equality":
                etoiles_gpt = 5

                if lang == "en":
                    analyse_locale = (
                        "Your numerical answer is correct and the calculation "
                        "you wrote is arithmetically consistent."
                    )
                else:
                    analyse_locale = (
                        "Ta réponse numérique est correcte et le calcul que tu "
                        "as écrit est arithmétiquement cohérent."
                    )

            elif validation_method == "free_numeric_explicit_final":
                etoiles_gpt = 4

                if lang == "en":
                    analyse_locale = (
                        "Your final numerical answer is correct and clearly stated. "
                        "Showing the calculation would make your reasoning more complete."
                    )
                else:
                    analyse_locale = (
                        "Ta réponse finale est correcte et clairement formulée. "
                        "Montrer le calcul rendrait ton raisonnement plus complet."
                    )

            else:
                etoiles_gpt = 3

                if lang == "en":
                    analyse_locale = (
                        "Your numerical answer is correct. "
                        "Add the calculation or reasoning to make your work clearer."
                    )
                else:
                    analyse_locale = (
                        "Ta réponse numérique est correcte. "
                        "Ajoute le calcul ou le raisonnement pour rendre ta démarche plus claire."
                    )

            if lang == "en":
                analyse_ia = (
                    "Analysis:\n"
                    f"{analyse_locale}\n\n"
                    f"Score: {etoiles_gpt}/5\n\n"
                    "Correction:\n"
                    f"{explication_exercice or 'The final numerical answer matches the official reference.'}"
                )
            else:
                analyse_ia = (
                    "Analyse :\n"
                    f"{analyse_locale}\n\n"
                    f"Note : {etoiles_gpt}/5\n\n"
                    "Correction :\n"
                    f"{explication_exercice or 'La réponse numérique finale correspond à la référence officielle.'}"
                )

        else:

            # 2/5 : calcul cohérent mais résultat final non conforme à la référence.
            # 1/5 : valeur finale explicite incorrecte.
            if validation_method == "free_numeric_verified_equality_mismatch":
                etoiles_gpt = 2

                if lang == "en":
                    analyse_locale = (
                        "The calculation you wrote is internally consistent, "
                        "but its final result does not answer the exercise correctly."
                    )
                else:
                    analyse_locale = (
                        "Le calcul que tu as écrit est cohérent en lui-même, "
                        "mais son résultat final ne répond pas correctement à l'exercice."
                    )

            else:
                etoiles_gpt = 1

                if lang == "en":
                    analyse_locale = (
                        "Your final numerical answer does not match the expected answer."
                    )
                else:
                    analyse_locale = (
                        "Ta réponse numérique finale ne correspond pas à la réponse attendue."
                    )

            if lang == "en":
                analyse_ia = (
                    "Analysis:\n"
                    f"{analyse_locale}\n\n"
                    f"Score: {etoiles_gpt}/5\n\n"
                    "Correction:\n"
                    f"{explication_exercice or 'Review the official calculation and expected result.'}"
                )
            else:
                analyse_ia = (
                    "Analyse :\n"
                    f"{analyse_locale}\n\n"
                    f"Note : {etoiles_gpt}/5\n\n"
                    "Correction :\n"
                    f"{explication_exercice or 'Revois le calcul officiel et le résultat attendu.'}"
                )

        print(
            "⚡ Rétroaction locale réponse libre numérique : "
            f"méthode={validation_method}, "
            f"verdict={validation_verdict}, "
            f"note={etoiles_gpt}/5, "
            "aucun appel IA individuel supplémentaire."
        )

    # ============================================================
    # CAS D : RÉPONSE LIBRE / VALIDATION SÉMANTIQUE
    # ============================================================

    else:

        if lang == "en":

            verdict_text = (
                "CORRECT"
                if validation_verdict == "correct"
                else "INCORRECT"
            )

            prompt = f"""
You are producing individualized pedagogical feedback after a separate
mathematical validation engine has already evaluated the student's answer.

EXERCISE:
{question}

OFFICIAL REUSABLE CORRECTION:
{explication_exercice or "Not available"}

EXPECTED ANSWER:
{reponse_attendue}

STUDENT ANSWER:
{reponse_eleve}

AUTHORITATIVE MATHEMATICAL VERDICT:
{verdict_text}

VALIDATION METHOD:
{validation_method}

VALIDATION CONFIDENCE:
{validation_confidence}

VALIDATION REASON:
{validation_result.reason or "Not provided"}

Do not contradict the authoritative verdict.
If CORRECT, score 3/5 to 5/5.
If INCORRECT, score 0/5 to 2/5.
Use the official reusable correction as the mathematical reference.
Do not replace it with a contradictory solution.

FORMAT:

Analysis:
[Individualized analysis]

Score: X/5

Correction:
[Use or summarize the official correction]
""".strip()

        else:

            verdict_text = (
                "CORRECT"
                if validation_verdict == "correct"
                else "INCORRECT"
            )

            prompt = f"""
Tu produis une rétroaction pédagogique individualisée APRÈS qu'un moteur
de validation mathématique séparé a déjà évalué la réponse de l'élève.

ÉNONCÉ :
{question}

CORRIGÉ OFFICIEL RÉUTILISABLE :
{explication_exercice or "Non disponible"}

RÉPONSE ATTENDUE :
{reponse_attendue}

RÉPONSE DE L'ÉLÈVE :
{reponse_eleve}

VERDICT MATHÉMATIQUE AUTORITAIRE :
{verdict_text}

MÉTHODE DE VALIDATION :
{validation_method}

CONFIANCE :
{validation_confidence}

RAISON DE VALIDATION :
{validation_result.reason or "Non fournie"}

Ne contredis jamais le verdict autoritaire.
Si CORRECT, note de 3/5 à 5/5.
Si INCORRECT, note de 0/5 à 2/5.
Utilise le corrigé officiel réutilisable comme référence mathématique.
Ne le remplace pas par une solution contradictoire.

FORMAT :

Analyse :
[Analyse individualisée]

Note : X/5

Correction :
[Utilise ou résume le corrigé officiel]
""".strip()

        try:
            completion = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.2
            )

            analyse_ia = (
                completion.choices[0]
                .message.content
                .strip()
            )

        except Exception as e:

            print(f"❌ Erreur IA rétroaction : {e}")

            if validation_verdict == "correct":
                analyse_ia = (
                    "Analysis:\nAnswer mathematically validated as correct.\n\nCorrection:\n"
                    + (explication_exercice or "")
                    if lang == "en"
                    else
                    "Analyse :\nRéponse mathématiquement validée comme correcte.\n\nCorrection :\n"
                    + (explication_exercice or "")
                )
            else:
                analyse_ia = (
                    "Analysis:\nAnswer mathematically validated as incorrect.\n\nCorrection:\n"
                    + (explication_exercice or "")
                    if lang == "en"
                    else
                    "Analyse :\nRéponse mathématiquement validée comme incorrecte.\n\nCorrection :\n"
                    + (explication_exercice or "")
                )

    # ============================================================
    # 3. EXTRACTION ET CONTRAINTE DE LA NOTE
    # ============================================================

    if not validation_requires_review:

        match = re.search(
            r"(Note|Score)\s*:\s*(\d)",
            analyse_ia,
            re.IGNORECASE
        )

        if match:
            etoiles_gpt = min(
                int(match.group(2)),
                5
            )

        # --------------------------------------------------------
        # Le score généré par l'IA est SECONDAIRE.
        # Le verdict mathématique est prioritaire.
        # --------------------------------------------------------

        if validation_verdict == "correct":

            if etoiles_gpt is None:
                etoiles_finales = 5
            else:
                etoiles_finales = max(
                    etoiles_gpt,
                    3
                )

        else:

            if etoiles_gpt is None:
                etoiles_finales = 1
            else:
                etoiles_finales = min(
                    etoiles_gpt,
                    2
                )

        score_final = etoiles_finales * 20

    else:

        # --------------------------------------------------------
        # CAS CRITIQUE :
        #
        # Un verdict incertain ne doit PAS créer artificiellement
        # une mauvaise note.
        # --------------------------------------------------------

        etoiles_finales = None
        score_final = None

    print(f"⭐ Note finale : {etoiles_finales}")
    print(f"📊 Score final : {score_final}")
    _perf_mark("corrigé + rétroaction + note")

    # ============================================================
    # 4. DIAGNOSTIC DE DIFFICULTÉ PROTÉGÉ
    # ============================================================

    if validation_requires_review:

        # Ne pas dégrader le diagnostic de l'élève.
        niveau_risque = "à vérifier"
        probabilite_difficulte = None

    elif validation_verdict == "incorrect":

        if etoiles_finales is not None and etoiles_finales <= 1:
            niveau_risque = "élevé"
            probabilite_difficulte = 0.85
        else:
            niveau_risque = "moyen"
            probabilite_difficulte = 0.55

    else:

        # Réponse validée correcte.
        if etoiles_finales is not None and etoiles_finales >= 4:
            niveau_risque = "faible"
            probabilite_difficulte = 0.20
        else:
            # Résultat correct mais raisonnement éventuellement incomplet.
            niveau_risque = "moyen"
            probabilite_difficulte = 0.40

    diagnostic_bayesien = {
        "niveau_risque": niveau_risque,

        "probabilite_difficulte": (
            probabilite_difficulte
            if probabilite_difficulte is not None
            else None
        ),

        "pourcentage_difficulte": (
            round(probabilite_difficulte * 100, 1)
            if probabilite_difficulte is not None
            else None
        ),

        "notion_cible": exercice.notion_cible,
        "competence_cible": exercice.competence_cible,
        "niveau_difficulte": exercice.niveau_difficulte,
        "type_exercice": exercice.type_exercice,

        "source": "exercice",

        # Nouvelle information essentielle
        "validation_verdict": validation_verdict,
        "validation_confidence": validation_confidence,
        "validation_method": validation_method,

        # Un cas incertain ne doit pas influencer négativement
        # les estimations de maîtrise.
        "excluded_from_negative_update": (
            validation_requires_review
        )
    }

    # ============================================================
    # 5. SAUVEGARDE RÉPONSE ÉLÈVE
    # ============================================================

    now = datetime.now(timezone.utc).isoformat()

    feedback_json = {

        "current_feedback": analyse_ia,

        "current_stars": etoiles_finales,

        # --------------------------------------------------------
        # On conserve ce nom pour ne pas casser le template actuel,
        # mais il contient désormais le moteur HYBRIDE complet.
        # --------------------------------------------------------

        "symbolic_verification": {

            "was_verified": (
                validation_verdict
                in {"correct", "incorrect"}
            ),

            "is_correct": symbolic_correct,

            "result": symbolic_result,

            "feedback": symbolic_feedback,

            "verdict": validation_verdict,

            "confidence": validation_confidence,

            "method": validation_method,

            "requires_review": (
                validation_requires_review
            )
        },

        "bayesian_diagnostic": diagnostic_bayesien,

        "metadata": {

            "exercise_id": exercice.id,
            "student_id": eleve.id,
            "lesson_id": lecon.id,
            "language": lang,

            "gpt_score": etoiles_gpt,
            "final_score": etoiles_finales,
            "score_100": score_final,

            "updated_at": now,

            "correction_method": (
                "hybrid_validation_engine_adaptive"
            ),

            "validation_verdict": validation_verdict,
            "validation_confidence": validation_confidence,
            "validation_method": validation_method,
            "validation_reason": validation_result.reason,

            "validation_result_correct": (
                validation_result.result_correct
            ),

            "validation_reasoning_correct": (
                validation_result.reasoning_correct
            ),

            "validation_error_type": (
                validation_result.error_type
            ),

            "validation_details": (
                validation_details
            ),

            "reference_answer_source": reference_answer_source,
            "reference_answer_generated": reference_answer_generated,
            "reference_generation_failed": reference_generation_failed,
            "reference_generation_reason": reference_generation_reason,
            "reference_second_answer": reference_second_answer,
            "reference_comparison_method": reference_comparison_method,

            "reference_complexity": reference_complexity,

            "correction_source": correction_source,
            "correction_reused": correction_source == "database",
            "feedback_source": (
                "local_qcm"
                if feedback_qcm_local
                else "local_free_numeric"
                if feedback_libre_local
                else "review_required"
                if validation_requires_review
                else "openai_individual"
            ),

            "requires_review": (
                validation_requires_review
            ),

            "notion_cible": exercice.notion_cible,
            "competence_cible": exercice.competence_cible,
            "niveau_difficulte": exercice.niveau_difficulte,
            "type_exercice": exercice.type_exercice,

            "options_source": (
                "options_en"
                if lang == "en" and exercice.options_en
                else "options_fr"
            ),
            "options_presentes": bool(options_exercice),

            "matiere_fr": matiere_fr,
            "matiere_en": matiere_en,
            "unite_fr": unite_fr,
            "unite_en": unite_en,
            "lecon_fr": lecon_fr,
            "lecon_en": lecon_en
        },

        "adaptive_next": {},

        "history": []
    }

    # ============================================================
    # TYPE D'ERREUR
    # ============================================================

    if validation_verdict == "incorrect":

        type_erreur_final = (
            validation_result.error_type
            or "erreur_mathématique"
        )

    elif (
        validation_verdict == "correct"
        and validation_result.reasoning_correct is False
    ):

        type_erreur_final = (
            validation_result.error_type
            or "raisonnement_à_améliorer"
        )

    else:

        type_erreur_final = None

    # ============================================================
    # CRÉATION STUDENT RESPONSE
    # ============================================================

    reponse = StudentResponse(

        user_id=eleve.id,

        exercice_id=exercice.id,

        reponse_eleve=reponse_eleve,

        analyse_ia=json.dumps(
            feedback_json,
            ensure_ascii=False,
            indent=2
        ),

        etoiles=etoiles_finales,

        score=score_final,

        type_erreur=type_erreur_final,

        niveau_difficulte=exercice.niveau_difficulte,

        aide_utilisee=False,

        feedback_ia_structure=feedback_json,

        timestamp=datetime.now(timezone.utc)
    )

    db.session.add(reponse)

    try:

        db.session.commit()

        print("✅ Réponse sauvegardée.")
        _perf_mark("commit StudentResponse")

    except Exception as e:

        db.session.rollback()

        print(
            f"❌ Erreur sauvegarde réponse : {e}"
        )

        flash(
            msg_save_error,
            "danger"
        )

        return redirect(
            url_for(
                "exercice_sequentiel_progressif",
                username=username,
                lecon_id=lecon.id,
                lang=lang,
                exercice_id=exercice.id
            )
        )

    # ============================================================
    # 6. ENREGISTREMENT DIAGNOSTIC BAYÉSIEN
    # ============================================================

    diagnostic_record = None

    # ------------------------------------------------------------
    # CAS INCERTAIN :
    # on ne doit surtout pas dégrader le diagnostic de l'élève.
    # ------------------------------------------------------------

    if validation_requires_review:

        print(
            "⚠️ Verdict non concluant : "
            "aucune mise à jour bayésienne négative."
        )

        diagnostic_record = None

    else:

        try:
            matiere_nom = matiere_affichee

            diagnostic_record = DiagnosticBayesien(
                user_id=eleve.id,
                exercice_id=exercice.id,
                lecon_id=lecon.id,
                matiere=matiere_nom,

                # ------------------------------------------------
                # Probabilité de difficulté calculée uniquement
                # lorsque le verdict est suffisamment fiable.
                # ------------------------------------------------
                probabilite_difficulte=probabilite_difficulte,

                pourcentage_difficulte=(
                    round(probabilite_difficulte * 100, 1)
                    if probabilite_difficulte is not None
                    else None
                ),

                niveau_risque=niveau_risque,

                maitrise_cours=(
                    "faible"
                    if niveau_risque == "élevé"

                    else "moyenne"
                    if niveau_risque == "moyen"

                    else "bonne"
                ),

                # ------------------------------------------------
                # IMPORTANT :
                # on ne déduit plus l'erreur à partir de SymPy
                # ou simplement de la note.
                #
                # Seul un verdict FINAL "incorrect" du moteur
                # hybride signifie qu'une erreur est confirmée.
                # ------------------------------------------------
                erreurs=(
                    "oui"
                    if validation_verdict == "incorrect"
                    else "non"
                ),

                temps_reponse="normal",

                # ------------------------------------------------
                # On conserve le champ existant pour compatibilité,
                # mais il contient maintenant le résultat complet
                # du moteur hybride.
                # ------------------------------------------------
                verification_calcul=symbolic_result,

                recommandation=(
                    "Remediation recommended."
                    if lang == "en"
                    and niveau_risque == "élevé"

                    else "Consolidation recommended."
                    if lang == "en"
                    and niveau_risque == "moyen"

                    else "Progression recommended."
                    if lang == "en"

                    else "Remédiation recommandée."
                    if niveau_risque == "élevé"

                    else "Consolidation recommandée."
                    if niveau_risque == "moyen"

                    else "Progression recommandée."
                ),

                notion_cible=exercice.notion_cible,

                # ------------------------------------------------
                # Une notion n'est considérée non maîtrisée
                # que si le moteur a réellement confirmé
                # un problème.
                # ------------------------------------------------
                notions_non_maitrisees=(
                    [exercice.notion_cible]
                    if (
                        validation_verdict == "incorrect"
                        and niveau_risque in ["élevé", "moyen"]
                        and exercice.notion_cible
                    )
                    else []
                ),

                # ------------------------------------------------
                # Une notion est considérée maîtrisée seulement
                # lorsque la réponse est validée correcte
                # avec un risque faible.
                # ------------------------------------------------
                notions_maitrisees=(
                    [exercice.notion_cible]
                    if (
                        validation_verdict == "correct"
                        and niveau_risque == "faible"
                        and exercice.notion_cible
                    )
                    else []
                ),

                # ------------------------------------------------
                # Une erreur probable ne doit être enregistrée
                # que sur verdict incorrect confirmé.
                # ------------------------------------------------
                erreurs_probables=(
                    [exercice.competence_cible]
                    if (
                        validation_verdict == "incorrect"
                        and niveau_risque in ["élevé", "moyen"]
                        and exercice.competence_cible
                    )
                    else []
                ),

                niveau_intervention=(
                    "remediation"
                    if (
                        validation_verdict == "incorrect"
                        and niveau_risque == "élevé"
                    )

                    else "consolidation"
                    if (
                        niveau_risque == "moyen"
                    )

                    else "progression"
                ),

                # ------------------------------------------------
                # Le diagnostic complet contient désormais
                # les informations du nouveau moteur hybride.
                # ------------------------------------------------
                diagnostic_complet=diagnostic_bayesien,

                source="exercice",

                created_at=datetime.utcnow()
            )

            db.session.add(diagnostic_record)

            # Flush uniquement : attribue l'ID sans clôturer
            # la transaction PostgreSQL.
            db.session.flush()

            print("✅ Diagnostic bayésien préparé.")

            print(
                f"🧠 Diagnostic : "
                f"verdict={validation_verdict}, "
                f"risque={niveau_risque}, "
                f"probabilité={probabilite_difficulte}"
            )
            _perf_mark("flush DiagnosticBayesien")

        except Exception as e:

            db.session.rollback()

            print(
                f"⚠️ Diagnostic bayésien non enregistré: {e}"
            )

    # ============================================================
    # 7. MISE À JOUR DU PROFIL APPRENANT
    # ============================================================

    profil_apprenant = None

    # Un verdict incertain ne doit jamais diminuer artificiellement
    # la maîtrise estimée de l'élève.
    if validation_requires_review:

        print(
            "⚠️ Profil apprenant non modifié : "
            "le verdict de validation nécessite une vérification."
        )

    else:

        try:
            from services.profil_apprenant_service import mettre_a_jour_profil_apprenant

            profil_apprenant = mettre_a_jour_profil_apprenant(
                user_id=eleve.id,
                lecon_id=lecon.id,
                notion_cible=exercice.notion_cible or "notion non précisée",
                competence_cible=exercice.competence_cible,
                score=score_final,
                etoiles=etoiles_finales,
                diagnostic_bayesien=diagnostic_bayesien,
                type_exercice=exercice.type_exercice,
                niveau_difficulte=exercice.niveau_difficulte,
                commit_changes=False
            )

            if profil_apprenant:
                print(
                    f"✅ Profil apprenant mis à jour : "
                    f"{profil_apprenant.notion_cible} | "
                    f"maîtrise={profil_apprenant.maitrise_estimee}% | "
                    f"risque={profil_apprenant.niveau_risque} | "
                    f"recommandation={profil_apprenant.recommandation}"
                )

            _perf_mark("mise à jour profil apprenant")

        except Exception as e:
            db.session.rollback()
            print(f"⚠️ Profil apprenant non mis à jour : {e}")


    # ============================================================
    # 7. PROTECTION + CHOIX DU PROCHAIN EXERCICE ADAPTATIF
    # ============================================================

    prochain_exercice = None
    resultat_adaptatif = None

    adaptation_bloquee = validation_requires_review

    # ============================================================
    # CAS 1 : VERDICT INCERTAIN
    # ============================================================
    # IMPORTANT :
    # On ne lance PAS le moteur adaptatif.
    # On ne déclenche PAS de remédiation.
    # On ne baisse PAS la difficulté.
    # On ne marque PAS la notion comme non maîtrisée.
    # ============================================================

    if adaptation_bloquee:

        adaptive_next = {
            "lecon_id": lecon.id,
            "exercice_source_id": exercice.id,
            "prochain_exercice_id": None,

            "strategie": "verification",

            "validation_verdict": validation_verdict,
            "validation_confidence": validation_confidence,
            "validation_method": validation_method,

            "raison": (
                "La réponse n'a pas pu être évaluée avec suffisamment "
                "de certitude. Aucune remédiation ni baisse de difficulté "
                "n'est déclenchée automatiquement."
            ),

            "niveau_cible": exercice.niveau_difficulte,
            "notion_cible": exercice.notion_cible,

            "requires_review": True,
            "adaptation_bloquee": True
        }

        session["prochain_exercice_adaptatif"] = adaptive_next

        feedback_json["adaptive_next"] = adaptive_next

        if "metadata" not in feedback_json:
            feedback_json["metadata"] = {}

        feedback_json["metadata"]["requires_review"] = True
        feedback_json["metadata"]["adaptation_bloquee"] = True

        # On resynchronise la réponse déjà enregistrée.
        reponse.analyse_ia = json.dumps(
            feedback_json,
            ensure_ascii=False,
            indent=2
        )

        reponse.feedback_ia_structure = feedback_json

        # Sauvegarde différée jusqu'au commit final du pipeline.
        print(
            "⚠️ Adaptation suspendue : "
            "verdict incertain."
        )

        print(
            "✅ Aucune remédiation automatique "
            "et aucune baisse de difficulté."
        )

        session.modified = True

    # ============================================================
    # CAS 2 : VERDICT CORRECT OU INCORRECT CONFIRMÉ
    # ============================================================

    else:

        print(
            f"✅ Adaptation autorisée : "
            f"verdict={validation_verdict}"
        )

        try:
            from services.adaptive_exercise_service import (
                choisir_prochain_exercice_adaptatif
            )

            # ----------------------------------------------------
            # Compatibilité avec le service adaptatif existant.
            #
            # Cette information ne vient plus directement de SymPy.
            # Elle représente maintenant le verdict FINAL
            # du moteur hybride.
            # ----------------------------------------------------

            verification_calcul_adaptative = {
                "is_correct": (
                    True
                    if validation_verdict == "correct"
                    else False
                ),

                "verified": True,

                "verdict": validation_verdict,

                "confidence": validation_confidence,

                "method": validation_method,

                "reason": validation_result.reason
            }

            # ----------------------------------------------------
            # Appel du moteur adaptatif uniquement lorsque
            # le verdict est suffisamment fiable.
            # ----------------------------------------------------

            resultat_adaptatif = choisir_prochain_exercice_adaptatif(
                db=db,
                Exercice=Exercice,
                StudentResponse=StudentResponse,

                eleve_id=eleve.id,
                lecon_id=lecon.id,

                exercice_actuel=exercice,

                etoiles=etoiles_finales,
                score=score_final,

                diagnostic_bayesien=diagnostic_bayesien,

                verification_calcul=verification_calcul_adaptative,
                profil_apprenant=profil_apprenant
            )

            prochain_exercice = (
                resultat_adaptatif.get("exercice")
                if resultat_adaptatif
                else None
            )

            # ====================================================
            # SÉCURITÉ SUPPLÉMENTAIRE :
            #
            # Une stratégie "remediation" n'est autorisée
            # que lorsque le verdict final est INCORRECT.
            # ====================================================

            if resultat_adaptatif:

                strategie_adaptative = resultat_adaptatif.get(
                    "strategie"
                )

                if (
                    strategie_adaptative == "remediation"
                    and validation_verdict != "incorrect"
                ):

                    print(
                        "⚠️ Remédiation refusée : "
                        "le verdict final n'est pas incorrect."
                    )

                    # Pour une réponse correcte,
                    # on remplace la remédiation par consolidation.
                    resultat_adaptatif["strategie"] = "consolidation"

                    resultat_adaptatif["raison"] = (
                        "La réponse a été validée comme correcte. "
                        "La remédiation automatique a donc été annulée. "
                        "Une consolidation ou une progression est privilégiée."
                    )

            # ====================================================
            # UN PROCHAIN EXERCICE A ÉTÉ TROUVÉ
            # ====================================================

            if prochain_exercice:

                session["prochain_exercice_adaptatif"] = {
                    "lecon_id": lecon.id,

                    "exercice_source_id": exercice.id,

                    "prochain_exercice_id": prochain_exercice.id,

                    "strategie": (
                        resultat_adaptatif.get("strategie")
                        if resultat_adaptatif
                        else "progression"
                    ),

                    "raison": (
                        resultat_adaptatif.get("raison")
                        if resultat_adaptatif
                        else "Progression normale."
                    ),

                    "niveau_cible": (
                        resultat_adaptatif.get("niveau_cible")
                        if resultat_adaptatif
                        else exercice.niveau_difficulte
                    ),

                    "notion_cible": (
                        resultat_adaptatif.get("notion_cible")
                        if resultat_adaptatif
                        else exercice.notion_cible
                    ),

                    "validation_verdict": validation_verdict,

                    "validation_confidence": validation_confidence,

                    "validation_method": validation_method,

                    "requires_review": False,

                    "adaptation_bloquee": False
                }

                feedback_json["adaptive_next"] = (
                    session["prochain_exercice_adaptatif"]
                )

                reponse.analyse_ia = json.dumps(
                    feedback_json,
                    ensure_ascii=False,
                    indent=2
                )

                reponse.feedback_ia_structure = feedback_json

                # Commit différé : profil + adaptive_next + trace
                # seront enregistrés ensemble plus bas.
                print(
                    f"🧠 Prochain exercice adaptatif : "
                    f"{prochain_exercice.id}"
                )

                print(
                    f"🧭 Stratégie : "
                    f"{resultat_adaptatif.get('strategie')}"
                )

                print(
                    f"✅ Verdict ayant autorisé l'adaptation : "
                    f"{validation_verdict}"
                )

            # ====================================================
            # AUCUN PROCHAIN EXERCICE DISPONIBLE
            # ====================================================

            else:

                session["prochain_exercice_adaptatif"] = {
                    "lecon_id": lecon.id,

                    "exercice_source_id": exercice.id,

                    "prochain_exercice_id": None,

                    "strategie": (
                        resultat_adaptatif.get("strategie")
                        if resultat_adaptatif
                        else "fin_sequence"
                    ),

                    "raison": (
                        resultat_adaptatif.get("raison")
                        if resultat_adaptatif
                        else "Aucun exercice disponible."
                    ),

                    "niveau_cible": (
                        resultat_adaptatif.get("niveau_cible")
                        if resultat_adaptatif
                        else None
                    ),

                    "notion_cible": (
                        resultat_adaptatif.get("notion_cible")
                        if resultat_adaptatif
                        else exercice.notion_cible
                    ),

                    "validation_verdict": validation_verdict,

                    "validation_confidence": validation_confidence,

                    "validation_method": validation_method,

                    "requires_review": False,

                    "adaptation_bloquee": False
                }

                feedback_json["adaptive_next"] = (
                    session["prochain_exercice_adaptatif"]
                )

                reponse.analyse_ia = json.dumps(
                    feedback_json,
                    ensure_ascii=False,
                    indent=2
                )

                reponse.feedback_ia_structure = feedback_json

                # Commit différé : profil + adaptive_next + trace
                # seront enregistrés ensemble plus bas.
                print(
                    "ℹ️ Aucun exercice adaptatif supplémentaire "
                    "n'est disponible."
                )

            session.modified = True

        except Exception as e:

            print(
                f"⚠️ Sélection adaptative non disponible : {e}"
            )

            # ----------------------------------------------------
            # Si le moteur adaptatif plante, cela ne doit PAS
            # transformer la réponse en erreur.
            # ----------------------------------------------------

            session["prochain_exercice_adaptatif"] = {
                "lecon_id": lecon.id,

                "exercice_source_id": exercice.id,

                "prochain_exercice_id": None,

                "strategie": "fallback",

                "raison": (
                    "La sélection automatique du prochain exercice "
                    "n'est temporairement pas disponible."
                ),

                "niveau_cible": exercice.niveau_difficulte,

                "notion_cible": exercice.notion_cible,

                "validation_verdict": validation_verdict,

                "validation_confidence": validation_confidence,

                "validation_method": validation_method,

                "requires_review": False,

                "adaptation_bloquee": False
            }

            feedback_json["adaptive_next"] = (
                session["prochain_exercice_adaptatif"]
            )

            reponse.analyse_ia = json.dumps(
                feedback_json,
                ensure_ascii=False,
                indent=2
            )

            reponse.feedback_ia_structure = feedback_json

            # Sauvegarde différée jusqu'au commit final.
            session.modified = True

    _perf_mark("sélection + sauvegarde adaptation")

    # ============================================================
    # 9. TRACE D'APPRENTISSAGE UNIFIÉE
    # ============================================================

    try:
        from models import TraceApprentissage

        adaptive_next = session.get("prochain_exercice_adaptatif", {})

        pourcentage_difficulte_trace = (
            round(probabilite_difficulte * 100, 1)
            if probabilite_difficulte is not None
            else None
        )

        remediation_declenchee = (
            validation_verdict == "incorrect"
            and etoiles_finales is not None
            and etoiles_finales < 3
        )

        trace = TraceApprentissage(
            user_id=eleve.id,

            niveau_id=niveau.id if niveau else eleve.niveau_id,
            matiere_id=matiere.id if matiere else None,
            unite_id=unite.id if unite else None,
            lecon_id=lecon.id if lecon else None,
            exercice_id=exercice.id,

            type_action="exercice_sequentiel",
            source="soumettre_sequentiel",

            reponse_eleve=reponse_eleve,
            analyse_ia=json.dumps(
                feedback_json,
                ensure_ascii=False,
                indent=2
            ),
            score=score_final,

            niveau_risque=niveau_risque,
            difficulte_estimee=exercice.niveau_difficulte,
            notion_cible=exercice.notion_cible,

            # Utiliser le type calculé à partir du verdict final hybride.
            type_erreur=type_erreur_final,

            meta_json={
                "lang": lang,

                "student_response_id": reponse.id,
                "diagnostic_bayesien_id": (
                    diagnostic_record.id
                    if diagnostic_record
                    else None
                ),
                "profil_apprenant_id": (
                    profil_apprenant.id
                    if profil_apprenant
                    else None
                ),

                "username": eleve.username,
                "eleve_nom": eleve.nom_complet,

                "score_sur_5": etoiles_finales,
                "score_pourcentage": score_final,

                "niveau_risque": niveau_risque,
                "probabilite_difficulte": probabilite_difficulte,
                "pourcentage_difficulte": pourcentage_difficulte_trace,

                "question_fr": exercice.question_fr,
                "question_en": exercice.question_en,
                "reponse_attendue_fr": exercice.reponse_fr,
                "reponse_attendue_en": exercice.reponse_en,

                "matiere_fr": matiere_fr,
                "matiere_en": matiere_en,
                "unite_fr": unite_fr,
                "unite_en": unite_en,
                "lecon_fr": lecon_fr,
                "lecon_en": lecon_en,

                "notion_cible": exercice.notion_cible,
                "competence_cible": exercice.competence_cible,
                "niveau_difficulte": exercice.niveau_difficulte,
                "type_exercice": exercice.type_exercice,
                "classification_validee": exercice.classification_validee,

                # Compatibilité avec les vues historiques existantes.
                "symbolic_correct": symbolic_correct,
                "symbolic_result": symbolic_result,
                "symbolic_feedback": symbolic_feedback,

                # Nouvelle traçabilité du moteur hybride.
                "validation_verdict": validation_verdict,
                "validation_confidence": validation_confidence,
                "validation_method": validation_method,
                "validation_reason": validation_result.reason,
                "validation_result_correct": validation_result.result_correct,
                "validation_reasoning_correct": validation_result.reasoning_correct,
                "validation_error_type": validation_result.error_type,
                "validation_details": validation_details,
                "requires_review": validation_requires_review,

                "reference_answer_source": reference_answer_source,
                "reference_answer_generated": reference_answer_generated,
                "reference_generation_failed": reference_generation_failed,

                "correction_method": "hybrid_validation_engine_adaptive",
                "adaptive_next": adaptive_next,

                # Une remédiation n'est vraie que sur erreur confirmée.
                "remediation_declenchee": remediation_declenchee
            },

            created_at=datetime.utcnow()
        )

        db.session.add(trace)

        # La trace sera persistée avec le diagnostic, le profil,
        # adaptive_next et la remédiation éventuelle au commit final.
        print("✅ Trace d'apprentissage préparée.")
        print(
            f"🧠 TraceApprentissage : "
            f"élève={eleve.id}, exercice={exercice.id}, "
            f"verdict={validation_verdict}, "
            f"score={score_final}, risque={niveau_risque}"
        )
        _perf_mark("préparation TraceApprentissage")

    except Exception as e:
        db.session.rollback()
        print(f"⚠️ Trace d'apprentissage non enregistrée : {e}")

    # ============================================================
    # 10. REMÉDIATION UNIQUEMENT SI ERREUR CONFIRMÉE
    # ============================================================

    remediation_declenchee = (
        validation_verdict == "incorrect"
        and etoiles_finales is not None
        and etoiles_finales < 3
    )

    if remediation_declenchee:

        try:
            if lang == "en":
                message = (
                    f"Confirmed mathematical difficulty "
                    f"({etoiles_finales}/5)."
                )
            else:
                message = (
                    f"Difficulté mathématique confirmée "
                    f"({etoiles_finales}/5)."
                )

            suggestion = RemediationSuggestion(
                user_id=eleve.id,
                theme=matiere_affichee or exercice.theme,
                lecon=lecon_affichee or lecon.titre_fr,
                message=message,
                exercice_suggere=None,
                statut="en_attente",
                timestamp=datetime.now(timezone.utc)
            )

            db.session.add(suggestion)

            print(
                "📚 Remédiation préparée après "
                "un verdict incorrect confirmé."
            )

        except Exception as e:
            db.session.rollback()
            print(f"⚠️ Remédiation non enregistrée : {e}")

    elif validation_requires_review:

        print(
            "⚠️ Aucune remédiation créée : "
            "la réponse nécessite une vérification."
        )

    else:

        print(
            "✅ Aucune remédiation nécessaire : "
            f"verdict={validation_verdict}."
        )

    _perf_mark("remédiation éventuelle")
    print(
        f"⏱️ PERF SOUMISSION | TOTAL ROUTE                        "
        f"| total={perf_counter() - _perf_t0:6.3f}s"
    )

    # ============================================================
    # COMMIT FINAL PIPELINE PÉDAGOGIQUE
    # ============================================================
    #
    # StudentResponse a déjà été sécurisé par son commit initial.
    # Tout le pipeline secondaire est maintenant persisté ensemble :
    # - DiagnosticBayesien
    # - ProfilApprenant
    # - adaptive_next dans StudentResponse
    # - TraceApprentissage
    # - RemediationSuggestion éventuelle
    # ============================================================

    try:
        db.session.commit()
        print("✅ Commit final du pipeline pédagogique effectué.")
        _perf_mark("COMMIT FINAL pipeline pédagogique")

    except Exception as e:
        db.session.rollback()

        print(
            f"⚠️ Échec du commit final pédagogique : {e}"
        )

        print(
            "✅ La réponse élève principale reste sauvegardée."
        )

    # ============================================================
    # 11. RETOUR SUR LE MÊME EXERCICE AVEC FEEDBACK
    # ============================================================

    return redirect(url_for(
        "exercice_sequentiel_progressif",
        username=username,
        lecon_id=lecon.id,
        lang=lang,
        exercice_id=exercice.id,
        show_feedback=True
    ))

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
    """
    Historique optimisé d'un élève.

    Version rapide :
    - charge l'élève une seule fois ;
    - charge les réponses de l'élève une seule fois ;
    - charge les exercices avec la structure Matière → Unité → Leçon en une requête ;
    - évite les requêtes répétées dans les boucles.
    """

    from sqlalchemy.orm import joinedload
    from models import (
        db,
        User,
        Matiere,
        Unite,
        Lecon,
        Exercice,
        StudentResponse,
        EleveMatiere
    )

    # ============================================================
    # LANGUE
    # ============================================================

    lang = request.args.get("lang") or session.get("lang", "fr")

    if lang not in ["fr", "en"]:
        lang = "fr"

    session["lang"] = lang
    session.modified = True

    # ============================================================
    # UTILISATEUR CONNECTÉ
    # ============================================================

    current_user = None

    if session.get("user_id"):
        current_user = db.session.get(User, session["user_id"])

    # ============================================================
    # IDENTIFIER L'ÉLÈVE
    # ============================================================

    username = request.args.get("username")
    eleve_id_param = request.args.get("eleve_id", type=int)

    eleve_query = User.query.options(joinedload(User.niveau)).filter(
        User.role.in_(["eleve", "élève"])
    )

    if eleve_id_param:
        eleve = eleve_query.filter(User.id == eleve_id_param).first()
    elif username:
        eleve = eleve_query.filter(User.username == username).first()
    elif current_user and current_user.role in ["eleve", "élève"]:
        eleve = eleve_query.filter(User.id == current_user.id).first()
    elif session.get("eleve_id"):
        eleve = eleve_query.filter(User.id == session.get("eleve_id")).first()
    else:
        session_username = session.get("eleve_username") or session.get("username")
        if session_username:
            eleve = eleve_query.filter(User.username == session_username).first()
        else:
            eleve = None

    if not eleve:
        flash(
            "Élève introuvable." if lang == "fr" else "Student not found.",
            "danger"
        )

        if current_user and current_user.role == "enseignant":
            return redirect(url_for("dashboard_enseignant"))

        return redirect(url_for("dashboard_eleve"))

    # ============================================================
    # CONTRÔLE D'ACCÈS
    # ============================================================

    is_parent_access = False
    is_enseignant_access = False
    is_eleve_direct_access = False

    if session.get("parent_email"):
        is_parent_access = True

    if current_user and current_user.role in ["eleve", "élève"]:
        if current_user.id == eleve.id:
            is_eleve_direct_access = True

    if session.get("eleve_id") == eleve.id:
        is_eleve_direct_access = True

    if session.get("username") == eleve.username:
        is_eleve_direct_access = True

    if session.get("eleve_username") == eleve.username:
        is_eleve_direct_access = True

    if current_user and current_user.role == "enseignant":
        if getattr(eleve, "enseignant_referent_id", None) == current_user.id:
            is_enseignant_access = True
        else:
            flash(
                "Vous n'avez pas accès à l'historique de cet élève."
                if lang == "fr"
                else "You do not have access to this student's history.",
                "danger"
            )
            return redirect(url_for("dashboard_enseignant"))

    if not is_eleve_direct_access and not is_enseignant_access and not is_parent_access:
        flash(
            "Accès non autorisé à cet historique."
            if lang == "fr"
            else "Unauthorized access to this history.",
            "danger"
        )

        if current_user and current_user.role == "enseignant":
            return redirect(url_for("dashboard_enseignant"))

        return redirect(url_for("dashboard_eleve"))

    # ============================================================
    # NIVEAU
    # ============================================================

    niveau_eleve = eleve.niveau

    if not niveau_eleve:
        flash(
            "Le niveau de l'élève n'est pas défini."
            if lang == "fr"
            else "The student's level is not defined.",
            "warning"
        )

        if is_enseignant_access:
            return redirect(url_for("dashboard_enseignant"))

        return redirect(url_for("dashboard_eleve"))

    # ============================================================
    # MATIÈRES DE L'ÉLÈVE
    # 1. Matières choisies par l'élève.
    # 2. Sinon toutes les matières de son niveau.
    # ============================================================

    try:
        matiere_ids_selectionnees = [
            row[0]
            for row in db.session.query(EleveMatiere.matiere_id)
            .filter(EleveMatiere.eleve_id == eleve.id)
            .all()
        ]
    except Exception:
        matiere_ids_selectionnees = []

    if matiere_ids_selectionnees:
        matiere_ids = matiere_ids_selectionnees
    else:
        matiere_ids = [
            row[0]
            for row in db.session.query(Matiere.id)
            .filter(Matiere.niveau_id == niveau_eleve.id)
            .all()
        ]

    if not matiere_ids:
        return render_template(
            "historique_eleve.html",
            eleve=eleve,
            niveau_eleve=niveau_eleve,
            stats_matiere=[],
            total_exercices=0,
            completed_exercices=0,
            pourcentage_global=0,
            tests=[],
            is_parent_access=is_parent_access,
            is_enseignant_access=is_enseignant_access,
            is_eleve_direct_access=is_eleve_direct_access,
            lang=lang
        )

    # ============================================================
    # RÉPONSES DE L'ÉLÈVE
    # Une seule requête.
    # On garde la réponse la plus récente par exercice.
    # ============================================================

    reponses = (
        StudentResponse.query
        .filter(
            StudentResponse.user_id == eleve.id,
            StudentResponse.exercice_id.isnot(None)
        )
        .order_by(StudentResponse.timestamp.desc())
        .all()
    )

    reponse_par_exercice = {}

    for r in reponses:
        if r.exercice_id and r.exercice_id not in reponse_par_exercice:
            reponse_par_exercice[r.exercice_id] = r

    # ============================================================
    # EXERCICES + STRUCTURE
    # Une seule grande requête au lieu de requêtes dans les boucles.
    # ============================================================

    exercices = (
        Exercice.query
        .options(
            joinedload(Exercice.lecon)
            .joinedload(Lecon.unite)
            .joinedload(Unite.matiere)
        )
        .join(Lecon, Lecon.id == Exercice.lecon_id)
        .join(Unite, Unite.id == Lecon.unite_id)
        .join(Matiere, Matiere.id == Unite.matiere_id)
        .filter(Matiere.id.in_(matiere_ids))
        .order_by(Matiere.id.asc(), Unite.id.asc(), Lecon.id.asc(), Exercice.id.asc())
        .all()
    )

    # ============================================================
    # CONSTRUCTION DES DONNÉES POUR LE TEMPLATE
    # ============================================================

    matieres_map = {}
    total_exercices = 0
    completed_exercices = 0

    for exercice in exercices:
        if not exercice.lecon or not exercice.lecon.unite or not exercice.lecon.unite.matiere:
            continue

        lecon = exercice.lecon
        unite = lecon.unite
        matiere = unite.matiere

        total_exercices += 1

        matiere_nom = (
            matiere.nom_en
            if lang == "en" and getattr(matiere, "nom_en", None)
            else matiere.nom
        )

        unite_nom = (
            unite.nom_en
            if lang == "en" and getattr(unite, "nom_en", None)
            else unite.nom
        )

        lecon_nom = (
            lecon.titre_en
            if lang == "en" and lecon.titre_en
            else lecon.titre_fr
        )

        if matiere.id not in matieres_map:
            matieres_map[matiere.id] = {
                "id": matiere.id,
                "nom": matiere_nom,
                "total_exercices": 0,
                "completed_exercices": 0,
                "details": {}
            }

        matiere_data = matieres_map[matiere.id]
        matiere_data["total_exercices"] += 1

        if unite_nom not in matiere_data["details"]:
            matiere_data["details"][unite_nom] = {
                "total": 0,
                "completed": 0,
                "lecons": {}
            }

        unite_data = matiere_data["details"][unite_nom]
        unite_data["total"] += 1

        if lecon_nom not in unite_data["lecons"]:
            unite_data["lecons"][lecon_nom] = {
                "total": 0,
                "completed": 0,
                "exercices": []
            }

        lecon_data = unite_data["lecons"][lecon_nom]
        lecon_data["total"] += 1

        reponse = reponse_par_exercice.get(exercice.id)

        enonce = (
            exercice.question_en
            if lang == "en" and exercice.question_en
            else exercice.question_fr
        )

        if reponse:
            fait = True
            completed_exercices += 1
            matiere_data["completed_exercices"] += 1
            unite_data["completed"] += 1
            lecon_data["completed"] += 1

            exercice_data = {
                "id": exercice.id,
                "fait": True,
                "enonce": enonce or "",
                "reponse_eleve": reponse.reponse_eleve or "",
                "analyse_ia": reponse.analyse_ia or "",
                "etoiles": reponse.etoiles if reponse.etoiles is not None else 0,
                "date": reponse.timestamp.strftime("%d/%m/%Y %H:%M") if reponse.timestamp else ""
            }
        else:
            fait = False

            exercice_data = {
                "id": exercice.id,
                "fait": False,
                "enonce": enonce or "",
                "reponse_eleve": "",
                "analyse_ia": "",
                "etoiles": 0,
                "date": ""
            }

        lecon_data["exercices"].append(exercice_data)

    stats_matiere = []

    for matiere_data in matieres_map.values():
        total_matiere = matiere_data["total_exercices"]
        completed_matiere = matiere_data["completed_exercices"]

        matiere_data["pourcentage"] = (
            completed_matiere / total_matiere * 100
            if total_matiere > 0
            else 0
        )

        stats_matiere.append(matiere_data)

    pourcentage_global = (
        completed_exercices / total_exercices * 100
        if total_exercices > 0
        else 0
    )

    tests = []

    print("========== HISTORIQUE OPTIMISÉ ==========")
    print("Élève :", eleve.id, eleve.username, eleve.nom_complet)
    print("Niveau :", niveau_eleve.nom if niveau_eleve else None)
    print("Matières IDs :", matiere_ids)
    print("Total exercices :", total_exercices)
    print("Exercices complétés :", completed_exercices)
    print("Nombre matières affichées :", len(stats_matiere))
    print("=========================================")

    return render_template(
        "historique_eleve.html",
        eleve=eleve,
        niveau_eleve=niveau_eleve,
        stats_matiere=stats_matiere,
        total_exercices=total_exercices,
        completed_exercices=completed_exercices,
        pourcentage_global=pourcentage_global,
        tests=tests,
        is_parent_access=is_parent_access,
        is_enseignant_access=is_enseignant_access,
        is_eleve_direct_access=is_eleve_direct_access,
        lang=lang
    )

@app.route('/admin/lecon/supprimer/<int:id>', methods=['POST'])
@admin_required
def supprimer_lecon(id):
    """Supprimer une leçon avec tous les exercices et l'historique associé"""
    lecon = Lecon.query.get_or_404(id)
    
    try:
        # Si vous avez bien configuré les cascades dans les modèles,
        # cette simple suppression suffira
        db.session.delete(lecon)
        db.session.commit()
        
        if session.get("lang") == "en":
            flash("✅ Lesson and all associated exercises (including student history) deleted successfully", "success")
        else:
            flash('✅ Leçon, exercices et historique associés supprimés avec succès', 'success')
        
    except Exception as e:
        db.session.rollback()
        if session.get("lang") == "en":
            flash(f"❌ Error deleting: {str(e)}", "error")
        else:
            flash(f'❌ Erreur lors de la suppression: {str(e)}', 'error')
    
    return redirect(url_for('admin_dashboard'))

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

from flask import request, session, redirect, render_template, flash
from werkzeug.utils import secure_filename
import os
import random
from models import db, User, Niveau, Parent, ParentEleve
from functools import wraps




@app.route("/admin/creer-eleve", methods=["GET", "POST"])
@admin_required
def admin_creer_eleve():
    """Admin: Créer un nouvel élève - Adapté au nouveau système User"""
    # IMPORT DATETIME AU DÉBUT DE LA FONCTION
    from datetime import datetime
    import random
    
    # Récupérer tous les enseignants (utilisateurs avec rôle "enseignant")
    enseignants = User.query.filter_by(role="enseignant").all()
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
        
        # 🔥 NOUVEAU: Date de naissance
        date_naissance_str = request.form.get("date_naissance")
        date_naissance = None
        if date_naissance_str:
            try:
                date_naissance = datetime.strptime(date_naissance_str, "%Y-%m-%d").date()
            except:
                pass

        if not all([nom_complet, email, niveau_id, enseignant_id]):
            flash("Tous les champs sont obligatoires", "error")
            return redirect(url_for("admin_creer_eleve"))

        # Vérifier si l'email existe déjà
        if User.query.filter_by(email=email).first():
            flash("Un utilisateur avec cet email existe déjà", "error")
            return redirect(url_for("admin_creer_eleve"))

        # Vérifier que l'enseignant existe et est bien un enseignant
        enseignant = User.query.filter_by(id=enseignant_id, role="enseignant").first()
        if not enseignant:
            flash("Enseignant sélectionné non valide", "error")
            return redirect(url_for("admin_creer_eleve"))

        # Générer un mot de passe si non fourni
        if not mot_de_passe_clair:
            fruits = ["banane", "pomme", "mangue", "orange", "cerise", "kiwi", "raisin"]
            mot_de_passe_clair = random.choice(fruits) + str(random.randint(10, 99))

        # Générer un username unique
        i = 1
        while True:
            username = f"student_{i:03d}"
            if not User.query.filter_by(username=username).first():
                break
            i += 1

        # Créer l'élève avec le NOUVEAU système
        eleve = User(
            username=username,
            nom_complet=nom_complet,
            email=email,
            niveau_id=niveau_id,
            role="élève",  # 🔥 CORRIGÉ: "élève" AVEC accent pour être cohérent
            enseignant_referent_id=enseignant_id,
            telephone=telephone1,
            date_naissance=date_naissance,
            inscrit_par_admin=True,
            statut="actif",
            statut_paiement="non_paye"
        )
        eleve.mot_de_passe = mot_de_passe_clair
        
        # 🔥 NOUVEAU: Activer l'essai gratuit si configuré
        essai_gratuit = request.form.get("essai_gratuit", "non")
        if essai_gratuit == "oui":
            duree_heures = int(request.form.get("duree_essai", "48"))
            eleve.activer_essai_gratuit(duree_heures)
        
        db.session.add(eleve)
        db.session.commit()

        # Gérer les parents (optionnel)
        if parents_emails:
            emails = [e.strip() for e in parents_emails.split(",") if e.strip()]
            for index, email_parent in enumerate(emails):
                parent = Parent.query.filter_by(email=email_parent).first()
                if not parent:
                    tel = telephone1 if index == 0 else telephone2
                    parent_nom = request.form.get(f"parent_nom_{index}", f"Parent de {nom_complet}")
                    parent = Parent(
                        nom_complet=parent_nom,
                        email=email_parent,
                        telephone=tel
                    )
                    db.session.add(parent)
                    db.session.commit()

                # Vérifier si la relation existe déjà
                if not ParentEleve.query.filter_by(parent_id=parent.id, eleve_id=eleve.id).first():
                    lien = ParentEleve(parent_id=parent.id, eleve_id=eleve.id)
                    db.session.add(lien)

        db.session.commit()

        # 🔥 NOUVEAU: Message de succès selon la langue
        if lang == "fr":
            flash(f"Élève {nom_complet} créé avec succès!", "success")
        else:
            flash(f"Student {nom_complet} created successfully!", "success")

        return render_template(
            "eleve_cree.html",
            eleve=eleve,
            username=username,
            mot_de_passe=mot_de_passe_clair,
            enseignant=enseignant,
            lang=lang
        )

    # Date d'aujourd'hui pour le formulaire
    aujourdhui = datetime.utcnow().date().isoformat()
    
    return render_template(
        "admin_creer_eleve.html", 
        enseignants=enseignants, 
        niveaux=niveaux, 
        lang=lang,
        aujourdhui=aujourdhui  # 🔥 CORRIGÉ: datetime est maintenant défini
    )


# 🔥 AJOUT: Route pour modifier un élève existant
@app.route("/admin/modifier-eleve/<int:eleve_id>", methods=["GET", "POST"])
@admin_required
def admin_modifier_eleve(eleve_id):
    """Admin: Modifier un élève existant"""
    # Chercher l'élève avec différentes variantes de rôle
    eleve = User.query.filter(
        User.id == eleve_id,
        (User.role == "eleve") | (User.role == "élève") | (User.role == "ÚlÞve")
    ).first()
    
    if not eleve:
        flash("Élève non trouvé", "error")
        return redirect(url_for("admin_dashboard"))
    
    enseignants = User.query.filter_by(role="enseignant").all()
    niveaux = Niveau.query.all()
    lang = session.get("lang", "fr")
    
    # Récupérer les parents associés
    parents = Parent.query.join(ParentEleve).filter(ParentEleve.eleve_id == eleve_id).all()
    
    if request.method == "POST":
        print(f"\n=== DEBUG: Modification élève {eleve_id} ===")
        print(f"Données reçues: {dict(request.form)}")
        
        # Récupérer les données du formulaire
        nom_complet = request.form.get("nom_complet") or request.form.get("nom")
        email = request.form.get("email")
        username = request.form.get("username")
        niveau_id = request.form.get("niveau_id")
        # ATTENTION: Le formulaire envoie 'enseignant_id' mais le modèle a 'enseignant_referent_id'
        enseignant_id_form = request.form.get("enseignant_id")  # Nom dans le formulaire
        telephone = request.form.get("telephone")
        date_naissance_str = request.form.get("date_naissance")
        statut_paiement = request.form.get("statut_paiement")
        statut = request.form.get("statut")
        adresse = request.form.get("adresse")
        ville = request.form.get("ville")
        province = request.form.get("province")
        code_postal = request.form.get("code_postal")
        
        # Vérifier les champs obligatoires
        if not all([nom_complet, email, username, niveau_id]):
            flash("Nom, email, nom d'utilisateur et niveau sont obligatoires", "error")
            return redirect(url_for("admin_modifier_eleve", eleve_id=eleve_id))
        
        # Vérifier l'unicité de l'email
        autre_utilisateur = User.query.filter(
            User.email == email,
            User.id != eleve_id
        ).first()
        if autre_utilisateur:
            flash("Cet email est déjà utilisé par un autre utilisateur", "error")
            return redirect(url_for("admin_modifier_eleve", eleve_id=eleve_id))
        
        # Vérifier l'unicité du username
        autre_username = User.query.filter(
            User.username == username,
            User.id != eleve_id
        ).first()
        if autre_username:
            flash("Ce nom d'utilisateur est déjà pris", "error")
            return redirect(url_for("admin_modifier_eleve", eleve_id=eleve_id))
        
        # Mettre à jour les informations
        eleve.nom_complet = nom_complet
        eleve.email = email
        eleve.username = username
        
        # Convertir niveau_id en int ou None
        try:
            eleve.niveau_id = int(niveau_id) if niveau_id else None
        except:
            eleve.niveau_id = None
        
        # CORRECTION IMPORTANTE: Le formulaire envoie 'enseignant_id' 
        # mais le modèle a 'enseignant_referent_id'
        print(f"Enseignant ID depuis formulaire: {enseignant_id_form}")
        if enseignant_id_form and enseignant_id_form != "" and enseignant_id_form != "None":
            try:
                eleve.enseignant_referent_id = int(enseignant_id_form)
            except:
                eleve.enseignant_referent_id = None
        else:
            eleve.enseignant_referent_id = None
        
        # Informations de contact
        eleve.telephone = telephone if telephone else None
        eleve.adresse = adresse if adresse else None
        eleve.ville = ville if ville else None
        eleve.province = province if province else None
        eleve.code_postal = code_postal if code_postal else None
        
        # Statut
        if statut:
            eleve.statut = statut
        if statut_paiement:
            eleve.statut_paiement = statut_paiement
        
        # Corriger le rôle si nécessaire
        if eleve.role in ["ÚlÞve", "élève"]:
            eleve.role = "eleve"  # Standardiser
        
        # Gérer la date de naissance
        if date_naissance_str:
            try:
                from datetime import datetime
                eleve.date_naissance = datetime.strptime(date_naissance_str, "%Y-%m-%d").date()
            except:
                eleve.date_naissance = None
        
        # Gérer le mot de passe si fourni (vérifier le champ checkbox)
        changer_mdp = request.form.get("changer_mdp")
        if changer_mdp == "on" or changer_mdp == "true":
            nouveau_mdp = request.form.get("nouveau_mot_de_passe")
            if nouveau_mdp and nouveau_mdp.strip():
                eleve.mot_de_passe = nouveau_mdp.strip()
                print("✅ Mot de passe changé")
        
        print(f"Avant commit - Nom: {eleve.nom_complet}")
        print(f"Avant commit - Email: {eleve.email}")
        print(f"Avant commit - Username: {eleve.username}")
        print(f"Avant commit - enseignant_referent_id: {eleve.enseignant_referent_id}")
        print(f"Avant commit - niveau_id: {eleve.niveau_id}")
        
        try:
            db.session.commit()
            print("✅ Commit réussi!")
            flash("Élève mis à jour avec succès" if lang == "fr" else "Student updated successfully", "success")
        except Exception as e:
            print(f"❌ Erreur commit: {str(e)}")
            flash(f"Erreur lors de la sauvegarde: {str(e)}", "error")
            db.session.rollback()
        
        return redirect(url_for("admin_modifier_eleve", eleve_id=eleve_id))
    
    # Pour l'affichage GET
    date_naissance_iso = eleve.date_naissance.isoformat() if eleve.date_naissance else ""
    
    return render_template(
        "modifier_eleve.html",
        eleve=eleve,
        enseignants=enseignants,
        niveaux=niveaux,
        parents=parents,
        lang=lang,
        date_naissance=date_naissance_iso,
        current_niveau_id=eleve.niveau_id,
        # CORRECTION: utiliser eleve.enseignant_referent_id pour le template
        current_enseignant_id=eleve.enseignant_referent_id,
        current_statut_paiement=getattr(eleve, 'statut_paiement', 'non_paye'),
        current_username=eleve.username,
        current_statut=getattr(eleve, 'statut', 'actif')
    )
    
@app.route("/admin/assigner-eleves-enseignants", methods=["GET", "POST"])
@admin_required
def assigner_eleves_enseignants():
    """Assigner des élèves aux enseignants en masse"""
    try:
        from models import User, db
        
        enseignants = User.query.filter_by(role="enseignant").order_by(User.nom_complet).all()
        eleves = User.query.filter(
            (User.role == "eleve") | (User.role == "élève") | (User.role == "ÚlÞve")
        ).order_by(User.nom_complet).all()
        
        lang = session.get("lang", "fr")
        
        if request.method == "POST":
            # Récupérer les assignations
            assignments = {}
            for key in request.form:
                if key.startswith("enseignant_"):
                    eleve_id = key.replace("enseignant_", "")
                    enseignant_id = request.form.get(key)
                    if enseignant_id and enseignant_id != "none":
                        assignments[int(eleve_id)] = int(enseignant_id)
            
            # Appliquer les assignations
            updated_count = 0
            for eleve_id, enseignant_id in assignments.items():
                eleve = User.query.get(eleve_id)
                if eleve:
                    eleve.enseignant_referent_id = enseignant_id
                    # Corriger le rôle si nécessaire
                    if eleve.role == "ÚlÞve":
                        eleve.role = "élève"
                    updated_count += 1
            
            db.session.commit()
            
            flash(f"{updated_count} élèves assignés aux enseignants", "success")
            return redirect(url_for("assigner_eleves_enseignants"))
        
        # Préparer les données pour le template
        eleves_data = []
        for eleve in eleves:
            # Trouver l'enseignant actuel
            current_teacher = None
            if eleve.enseignant_referent_id:
                current_teacher = User.query.get(eleve.enseignant_referent_id)
            
            eleves_data.append({
                'id': eleve.id,
                'nom_complet': eleve.nom_complet,
                'email': eleve.email,
                'role': eleve.role,
                'current_teacher': current_teacher,
                'current_teacher_id': eleve.enseignant_referent_id
            })
        
        return render_template(
            "admin_assigner_eleves.html",
            enseignants=enseignants,
            eleves=eleves_data,
            total_eleves=len(eleves),
            total_enseignants=len(enseignants),
            lang=lang
        )
        
    except Exception as e:
        logger.error(f"Erreur assigner_eleves_enseignants: {e}")
        flash(f"Erreur: {str(e)}", "error")
        return redirect(url_for("admin_dashboard"))


# 🔥 AJOUT: Route pour désactiver/réactiver un élève
@app.route("/admin/toggle-eleve/<int:eleve_id>", methods=["POST"])
@admin_required
def admin_toggle_eleve(eleve_id):
    """Admin: Activer/désactiver un élève"""
    eleve = User.query.filter_by(id=eleve_id, role="eleve").first()
    if not eleve:
        return jsonify({"success": False, "error": "Élève non trouvé"})
    
    if eleve.statut == "actif":
        eleve.statut = "inactif"
        message_fr = "Élève désactivé"
        message_en = "Student deactivated"
    else:
        eleve.statut = "actif"
        message_fr = "Élève réactivé"
        message_en = "Student reactivated"
    
    db.session.commit()
    
    lang = session.get("lang", "fr")
    return jsonify({
        "success": True,
        "message": message_fr if lang == "fr" else message_en,
        "new_status": eleve.statut
    })


# 🔥 AJOUT: Route pour voir la liste des élèves



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
    """Page d'administration des élèves - VERSION CORRIGÉE"""
    try:
        from models import User, ParentEleve, Parent
        
        # ✅ CORRECTION: Chercher avec les DEUX variantes possibles
        from sqlalchemy import or_
        
        # 🔍 CHERCHER LES ÉLÈVES - VERSION CORRIGÉE
        eleves = User.query.filter(
            or_(User.role == "eleve", User.role == "élève")  # ✅ Recherche les deux
        ).options(
            db.joinedload(User.niveau)
        ).order_by(User.date_inscription.desc()).all()
        
        print(f"DEBUG: {len(eleves)} élèves trouvés")
        
        # DEBUG: Afficher tous les rôles existants pour vérifier
        if not eleves:
            print("=== DEBUG ROLES EXISTANTS ===")
            roles_distincts = db.session.query(User.role).distinct().all()
            print(f"Rôles distincts: {[r[0] for r in roles_distincts]}")
        
        # Pour chaque élève, charger les parents
        eleves_avec_parents = []
        for eleve in eleves:
            parents_query = Parent.query.join(ParentEleve).filter(
                ParentEleve.eleve_id == eleve.id
            ).all()
            eleve.parents = parents_query
            eleves_avec_parents.append(eleve)
        
        # Calculer les statistiques
        total_eleves = len(eleves_avec_parents)
        payes = sum(1 for e in eleves_avec_parents if getattr(e, 'statut_paiement', None) == 'paye')
        non_payes = sum(1 for e in eleves_avec_parents if getattr(e, 'statut_paiement', None) == 'non_paye')
        inscrits_admin = sum(1 for e in eleves_avec_parents if getattr(e, 'inscrit_par_admin', False))
        
        lang = session.get("lang", "fr")
        
        return render_template("admin_eleves.html", 
                             eleves=eleves_avec_parents,
                             lang=lang,
                             total_eleves=total_eleves,
                             payes=payes,
                             non_payes=non_payes,
                             inscrits_admin=inscrits_admin)
        
    except Exception as e:
        import traceback
        print(f"ERREUR CRITIQUE dans /admin/eleves: {e}")
        print(traceback.format_exc())
        flash(f"Erreur: {str(e)}", "error")
        return redirect(url_for("admin_dashboard"))


@app.route("/debug-error")
def debug_error():
    """Route pour déboguer l'erreur 'nom_complet'"""
    try:
        from models import Commission, User
        
        # Test 1: Vérifier une commission
        commission = Commission.query.first()
        if commission:
            test_result = f"Commission trouvée: ID {commission.id}<br>"
            test_result += f"Enseignant: {commission.enseignant_id}<br>"
            if commission.enseignant:
                test_result += f"Nom enseignant: {commission.enseignant.nom_complet}<br>"
                test_result += f"Champs disponibles: {list(commission.enseignant.__dict__.keys())}<br>"
        else:
            test_result = "Aucune commission trouvée<br>"
        
        # Test 2: Vérifier tous les champs d'un utilisateur
        user = User.query.first()
        if user:
            test_result += f"<br>Utilisateur test: {user.nom_complet}<br>"
            test_result += f"Champs: {[k for k in user.__dict__.keys() if not k.startswith('_')]}"
        
        return test_result
        
    except Exception as e:
        import traceback
        return f"<h1>ERREUR</h1><pre>{traceback.format_exc()}</pre>"

@app.before_request
def log_requests():
    """Log toutes les requêtes pour déboguer"""
    print(f"\n=== REQUEST: {request.method} {request.path} ===")
    if request.endpoint:
        print(f"Endpoint: {request.endpoint}")


@app.errorhandler(Exception)
def handle_error(e):
    """Gestionnaire d'erreurs global"""
    import traceback
    
    error_msg = str(e)
    tb = traceback.format_exc()
    
    print(f"\n=== ERREUR GLOBALE ===")
    print(f"URL: {request.url}")
    print(f"Endpoint: {request.endpoint}")
    print(f"Erreur: {error_msg}")
    print(f"Traceback:\n{tb}")
    
    # Renvoyer une page d'erreur simple
    return f"""
    <!DOCTYPE html>
    <html>
    <head><title>Erreur</title></head>
    <body>
        <h1>Une erreur s'est produite</h1>
        <p><strong>Erreur :</strong> {error_msg}</p>
        <p><strong>URL :</strong> {request.url}</p>
        <p><strong>Endpoint :</strong> {request.endpoint}</p>
        
        <h3>Débogage :</h3>
        <pre>{tb[:1000]}...</pre>
        
        <div style="margin-top: 20px;">
            <a href="/" style="padding: 10px; background: blue; color: white; text-decoration: none;">
                Retour à l'accueil
            </a>
            <button onclick="history.back()" style="padding: 10px; background: gray; color: white;">
                Retour en arrière
            </button>
        </div>
    </body>
    </html>
    """, 500

@app.route("/fix-all-nom-complet")
def fix_all_nom_complet():
    """Corriger toutes les occurrences de nom_complet"""
    import re
    
    fixes = []
    
    # Chercher et corriger dans app.py
    with open("app.py", "r", encoding="utf-8") as f:
        content = f.read()
        
    # Trouver toutes les occurrences
    pattern = r'\.nom_complet\b'
    matches = re.findall(pattern, content)
    
    if matches:
        # Remplacer toutes les occurrences
        new_content = re.sub(pattern, '.nom_complet', content)
        
        # Sauvegarder
        with open("app.py", "w", encoding="utf-8") as f:
            f.write(new_content)
        
        fixes.append(f"Corrigé {len(matches)} occurrences dans app.py")
    
    # Vérifier aussi dans les templates
    import os
    for root, dirs, files in os.walk("templates"):
        for file in files:
            if file.endswith(".html"):
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        template_content = f.read()
                    
                    if 'nom_complet' in template_content:
                        new_template = template_content.replace('nom_complet', 'nom_complet')
                        with open(filepath, "w", encoding="utf-8") as f:
                            f.write(new_template)
                        fixes.append(f"Corrigé dans template: {filepath}")
                except:
                    pass
    
    result = "<h1>Corrections appliquées</h1>"
    if fixes:
        result += "<ul>"
        for fix in fixes:
            result += f"<li>{fix}</li>"
        result += "</ul>"
    else:
        result += "<p>Aucune correction nécessaire</p>"
    
    result += "<p>Redémarrez Flask pour que les changements prennent effet.</p>"
    
    return result    

@app.route("/debug-eleves-urgence")
def debug_eleves_urgence():
    """Debug urgent pour voir où sont les élèves"""
    from models import User
    import json
    
    html = """
    <!DOCTYPE html>
    <html>
    <head><title>DEBUG Élèves - URGENCE</title></head>
    <body style="font-family: Arial; padding: 20px;">
    <h1>🔍 DEBUG Élèves - État actuel</h1>
    """
    
    # 1. Tous les utilisateurs
    all_users = User.query.all()
    html += f"<h2>1. Tous les utilisateurs ({len(all_users)})</h2>"
    html += "<table border='1' cellpadding='5' style='border-collapse: collapse;'>"
    html += "<tr><th>ID</th><th>Nom</th><th>Email</th><th>Rôle</th><th>Enseignant</th><th>Niveau</th></tr>"
    
    for user in all_users:
        enseignant = "Aucun"
        if user.enseignant_referent_id:
            ens = User.query.get(user.enseignant_referent_id)
            enseignant = ens.nom_complet if ens else f"ID:{user.enseignant_referent_id}"
        
        niveau = user.niveau.nom if user.niveau else "Aucun"
        
        html += f"""
        <tr>
            <td>{user.id}</td>
            <td><strong>{user.nom_complet}</strong></td>
            <td>{user.email}</td>
            <td style='background-color: {"#e6ffe6" if "eleve" in user.role.lower() else "#ffe6e6" if user.role=="enseignant" else "#e6e6ff"};'>
                <code>{user.role}</code>
            </td>
            <td>{enseignant}</td>
            <td>{niveau}</td>
        </tr>
        """
    
    html += "</table>"
    
    # 2. Recherche spécifique élèves
    html += "<h2>2. Recherche élèves par rôle</h2>"
    
    search_terms = ["élève", "eleve", "Eleve", "student", "Student"]
    for term in search_terms:
        users = User.query.filter_by(role=term).all()
        html += f"<h3>Rôle = '{term}' : {len(users)} trouvés</h3>"
        
        if users:
            html += "<ul>"
            for user in users:
                html += f"<li>{user.id}: {user.nom_complet} ({user.email})</li>"
            html += "</ul>"
        else:
            html += "<p style='color: red;'>Aucun</p>"
    
    # 3. Vérifier la base de données directement
    html += "<h2>3. Analyse complète</h2>"
    
    # Compter par rôle
    roles = {}
    for user in all_users:
        role = user.role
        if role not in roles:
            roles[role] = 0
        roles[role] += 1
    
    html += "<h3>Distribution par rôle :</h3>"
    html += "<table border='1' cellpadding='5'>"
    html += "<tr><th>Rôle</th><th>Nombre</th></tr>"
    for role, count in sorted(roles.items()):
        html += f"<tr><td><code>{role}</code></td><td>{count}</td></tr>"
    html += "</table>"
    
    # 4. Bouton pour corriger automatiquement
    html += """
    <h2>4. Actions correctives</h2>
    <div style='background: #f0f0f0; padding: 20px; border-radius: 10px;'>
        <p>Si les élèves existent mais avec un mauvais rôle :</p>
        <form action="/fix-roles-eleves" method="POST" style="margin-top: 10px;">
            <button type="submit" style="padding: 10px 20px; background: #4CAF50; color: white; border: none; border-radius: 5px; cursor: pointer;">
                🔧 Corriger automatiquement tous les rôles d'élèves
            </button>
            <p><small>Ceci changera tous les rôles 'eleve', 'Eleve', 'student' en 'élève'</small></p>
        </form>
    </div>
    """
    
    html += "</body></html>"
    return html

@app.route("/fix-roles-eleves", methods=["GET", "POST"])
def fix_roles_eleves():
    """Corriger automatiquement les rôles des élèves"""
    try:
        from models import User, db
        
        # Rôles à corriger
        roles_a_corriger = ['eleve', 'Eleve', 'student', 'Student', 'ÚlÞve']
        
        # Compter avant
        avant = {}
        for role in roles_a_corriger:
            avant[role] = User.query.filter_by(role=role).count()
        
        # Corriger
        for role in roles_a_corriger:
            eleves = User.query.filter_by(role=role).all()
            for eleve in eleves:
                eleve.role = 'eleve'
        
        db.session.commit()
        
        # Compter après
        apres = User.query.filter_by(role='élève').count()
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head><title>Correction rôles</title></head>
        <body style="font-family: Arial; padding: 20px;">
        <h1>✅ Correction terminée</h1>
        
        <h3>Avant :</h3>
        <ul>
        """
        
        for role, count in avant.items():
            if count > 0:
                html += f"<li>Rôle '{role}': {count} utilisateurs</li>"
        
        html += f"""
        </ul>
        
        <h3>Après :</h3>
        <p>Rôle 'élève': {apres} utilisateurs</p>
        
        <div style="margin-top: 30px;">
            <a href="/debug-eleves-urgence" style="padding: 10px 20px; background: #2196F3; color: white; text-decoration: none; border-radius: 5px;">
                🔍 Vérifier à nouveau
            </a>
            <a href="/admin/eleves" style="padding: 10px 20px; background: #4CAF50; color: white; text-decoration: none; border-radius: 5px; margin-left: 10px;">
                📋 Voir la page élèves
            </a>
        </div>
        </body>
        </html>
        """
        
        return html
        
    except Exception as e:
        import traceback
        return f"<h1>Erreur</h1><pre>{traceback.format_exc()}</pre>"


@app.route("/admin/cleanup-student-names")
@admin_required
def cleanup_student_names():
    """Nettoyer les noms bizarres des élèves"""
    try:
        from models import User, db
        
        result = "<h1>Nettoyage des noms d'élèves</h1>"
        
        # Trouver les élèves avec des caractères bizarres
        all_students = User.query.filter_by(role="élève").all()
        
        cleaned = []
        
        for student in all_students:
            original_name = student.nom_complet
            cleaned_name = original_name
            
            # Remplacer les caractères bizarres
            replacements = [
                ('╔lÞve', 'Élève'),
                ('╔', 'É'),
                ('Þ', 'è'),
                ('Þ', 'é'),
                ('7Þme', '7ème'),
                ('_', ' ')
            ]
            
            for old, new in replacements:
                cleaned_name = cleaned_name.replace(old, new)
            
            # Capitaliser proprement
            if cleaned_name != original_name:
                student.nom_complet = cleaned_name
                cleaned.append(f"'{original_name}' → '{cleaned_name}'")
        
        if cleaned:
            db.session.commit()
            result += "<h2>Noms corrigés :</h2>"
            result += "<ul>"
            for change in cleaned:
                result += f"<li>{change}</li>"
            result += "</ul>"
        else:
            result += "<p>Aucun nom à corriger</p>"
        
        # Afficher la liste finale
        result += "<h2>Liste finale des élèves :</h2>"
        result += "<table border='1' style='border-collapse: collapse;'>"
        result += "<tr><th>Nom</th><th>Email</th><th>Enseignant</th></tr>"
        
        for student in User.query.filter_by(role="élève").order_by(User.nom_complet).all():
            teacher = User.query.get(student.enseignant_referent_id) if student.enseignant_referent_id else None
            result += f"""
            <tr>
                <td>{student.nom_complet}</td>
                <td>{student.email}</td>
                <td>{teacher.nom_complet if teacher else 'Aucun'}</td>
            </tr>
            """
        
        result += "</table>"
        
        return result
        
    except Exception as e:
        import traceback
        return f"<h1>Erreur</h1><p>{str(e)}</p><pre>{traceback.format_exc()}</pre>", 500


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

def get_exercices_par_enseignant_for_template(enseignant, lang='fr'):
    result = {}

    eleves = enseignant.get_eleves_encadres()
    niveaux_ids = {e.niveau_id for e in eleves if e.niveau_id}

    if not niveaux_ids:
        return {}

    niveaux = Niveau.query.filter(Niveau.id.in_(niveaux_ids)).all()

    for niveau in niveaux:
        for matiere in niveau.matieres:
            if matiere.nom not in result:
                result[matiere.nom] = {}

            for unite in matiere.unites:
                for lecon in unite.lecons:
                    exercices = []
                    for ex in lecon.exercices:
                        exercices.append({
                            "id": ex.id,
                            "question": ex.question_fr if lang == "fr" else ex.question_en,
                            "explication": ex.explication_fr if lang == "fr" else ex.explication_en,
                            "temps": ex.temps,
                            "chemin_image": ex.chemin_image,
                        })

                    if exercices:
                        result[matiere.nom][
                            lecon.titre_fr if lang == "fr" else lecon.titre_en
                        ] = exercices

    return result



def get_exercices_par_lecon_pour_enseignant(self):
    """
    Retourne les exercices groupés par leçon pour tous les élèves affectés à cet enseignant.
    Structure:
    {
        eleve_id: {
            'nom': 'Nom Élève',
            'matieres': {
                matiere_id: {
                    'nom': 'Nom Matière',
                    'lecons': {
                        lecon_id: {
                            'titre': 'Titre Leçon',
                            'exercices': [
                                {'id': ..., 'question_fr': ..., 'question_en': ...},
                                ...
                            ]
                        }
                    }
                }
            }
        }
    }
    """
    if not self.est_enseignant():
        return {}

    result = {}
    eleves = self.get_eleves_encadres()
    for eleve in eleves:
        result[eleve.id] = {
            'nom': eleve.nom_complet,
            'matieres': {}
        }

        # Parcours des matières via le niveau de l'élève
        for matiere in eleve.niveau.matieres:
            result[eleve.id]['matieres'][matiere.id] = {
                'nom': matiere.nom,
                'lecons': {}
            }

            for unite in matiere.unites:
                for lecon in unite.lecons:
                    result[eleve.id]['matieres'][matiere.id]['lecons'][lecon.id] = {
                        'titre': lecon.titre_fr,
                        'exercices': [
                            {
                                'id': ex.id,
                                'question_fr': ex.question_fr,
                                'question_en': ex.question_en,
                                'temps': ex.temps,
                                'chemin_image': ex.chemin_image
                            }
                            for ex in lecon.exercices
                        ]
                    }
    return result


@app.route("/enseignant/exercices")
def enseignant_exercices():
    """
    Page enseignant des exercices.
    Version légère :
    - récupère les élèves rattachés à l'enseignant ;
    - récupère les niveaux de ces élèves ;
    - affiche Matière → Unité → Leçon ;
    - ne charge pas tous les exercices ;
    - transmet seulement le nombre d'exercices et le premier exercice de chaque leçon.
    """

    from sqlalchemy.orm import selectinload
    from sqlalchemy import func
    from models import User, Niveau, Matiere, Unite, Lecon, Exercice, db

    # ============================================================
    # AUTHENTIFICATION ENSEIGNANT
    # ============================================================

    if "user_id" not in session:
        return redirect(url_for("login_enseignant"))

    if session.get("role") != "enseignant":
        flash("Accès réservé aux enseignants", "error")
        return redirect(url_for("login_enseignant"))

    enseignant = db.session.get(User, session["user_id"])

    if not enseignant or not enseignant.est_enseignant():
        session.clear()
        flash("Session enseignant invalide. Veuillez vous reconnecter.", "error")
        return redirect(url_for("login_enseignant"))

    lang = session.get("lang", getattr(enseignant, "langue", None) or "fr")

    # ============================================================
    # ÉLÈVES DE CET ENSEIGNANT
    # ============================================================

    eleves = (
        User.query
        .filter(
            User.role == "eleve",
            User.enseignant_referent_id == enseignant.id
        )
        .order_by(User.nom_complet.asc())
        .all()
    )

    niveaux_ids = list({eleve.niveau_id for eleve in eleves if eleve.niveau_id})

    print("👨‍🏫 Enseignant :", enseignant.id, enseignant.email)
    print("👥 Élèves :", [(e.id, e.nom_complet, e.niveau_id) for e in eleves])
    print("🎓 Niveaux trouvés :", niveaux_ids)

    if not niveaux_ids:
        flash("Aucun niveau trouvé pour les élèves rattachés à cet enseignant.", "warning")
        return render_template(
            "enseignant_exercices.html",
            matieres=[],
            lang=lang,
            enseignant=enseignant
        )

    # ============================================================
    # COMPTER LES EXERCICES PAR LEÇON
    # ET RÉCUPÉRER LE PREMIER EXERCICE DE CHAQUE LEÇON
    # ============================================================

    exercices_infos = (
        db.session.query(
            Exercice.lecon_id.label("lecon_id"),
            func.count(Exercice.id).label("total"),
            func.min(Exercice.id).label("premier_exercice_id")
        )
        .join(Lecon, Lecon.id == Exercice.lecon_id)
        .join(Unite, Unite.id == Lecon.unite_id)
        .join(Matiere, Matiere.id == Unite.matiere_id)
        .filter(Matiere.niveau_id.in_(niveaux_ids))
        .group_by(Exercice.lecon_id)
        .all()
    )

    exercices_par_lecon = {
        row.lecon_id: {
            "total": int(row.total or 0),
            "premier_exercice_id": row.premier_exercice_id
        }
        for row in exercices_infos
    }

    print("📘 Leçons avec exercices :", len(exercices_par_lecon))
    print("📊 Total exercices accessibles :", sum(v["total"] for v in exercices_par_lecon.values()))

    # ============================================================
    # CHARGER LA STRUCTURE SANS CHARGER LES EXERCICES
    # Niveau → Matière → Unité → Leçon
    # ============================================================

    niveaux = (
        Niveau.query
        .options(
            selectinload(Niveau.matieres)
            .selectinload(Matiere.unites)
            .selectinload(Unite.lecons)
        )
        .filter(Niveau.id.in_(niveaux_ids))
        .order_by(Niveau.nom.asc())
        .all()
    )

    matieres_data = []

    for niveau in niveaux:
        niveau_nom = niveau.nom_en if lang == "en" and niveau.nom_en else niveau.nom

        eleves_niveau = [
            eleve.nom_complet or eleve.username or eleve.email
            for eleve in eleves
            if eleve.niveau_id == niveau.id
        ]

        for matiere in niveau.matieres:
            matiere_nom = matiere.nom_en if lang == "en" and matiere.nom_en else matiere.nom

            unites_list = []

            for unite in matiere.unites:
                unite_nom = unite.nom_en if lang == "en" and unite.nom_en else unite.nom

                lecons_list = []

                for lecon in unite.lecons:
                    info_exercices = exercices_par_lecon.get(lecon.id)

                    # On ignore les leçons qui n'ont aucun exercice
                    if not info_exercices or info_exercices["total"] == 0:
                        continue

                    titre = lecon.titre_en if lang == "en" and lecon.titre_en else lecon.titre_fr

                    lecons_list.append({
                        "id": lecon.id,
                        "titre": titre or f"Leçon {lecon.id}",
                        "total_exercices": info_exercices["total"],
                        "premier_exercice_id": info_exercices["premier_exercice_id"]
                    })

                # On ignore les unités sans leçon avec exercices
                if not lecons_list:
                    continue

                unites_list.append({
                    "id": unite.id,
                    "nom": unite_nom or f"Unité {unite.id}",
                    "lecons": lecons_list
                })

            # On ignore les matières sans unité/leçon avec exercices
            if not unites_list:
                continue

            matieres_data.append({
                "id": matiere.id,
                "nom": matiere_nom or f"Matière {matiere.id}",
                "niveau": niveau_nom or f"Niveau {niveau.id}",
                "eleves": eleves_niveau,
                "unites": unites_list
            })

    print("📚 Matières affichées :", len(matieres_data))

    return render_template(
        "enseignant_exercices.html",
        matieres=matieres_data,
        lang=lang,
        enseignant=enseignant
    )




@app.route("/enseignant/lecon/<int:lecon_id>/exercices-json")
def enseignant_lecon_exercices_json(lecon_id):
    """
    Charger les exercices d'une leçon à la demande.
    Pagination pour éviter de retourner trop d'exercices en une fois.
    """

    from models import User, Niveau, Matiere, Unite, Lecon, Exercice

    # ============================================================
    # AUTHENTIFICATION ENSEIGNANT
    # ============================================================

    if "user_id" not in session or session.get("role") != "enseignant":
        return jsonify({
            "success": False,
            "message": "Non autorisé"
        }), 401

    enseignant = User.query.get(session["user_id"])

    if not enseignant or not enseignant.est_enseignant():
        return jsonify({
            "success": False,
            "message": "Accès refusé"
        }), 403

    lang = session.get("lang", getattr(enseignant, "langue", None) or "fr")

    # ============================================================
    # SÉCURITÉ
    # Vérifier que la leçon appartient à une matière du niveau
    # d'au moins un élève rattaché à cet enseignant.
    # ============================================================

    lecon = (
        Lecon.query
        .join(Unite, Unite.id == Lecon.unite_id)
        .join(Matiere, Matiere.id == Unite.matiere_id)
        .join(Niveau, Niveau.id == Matiere.niveau_id)
        .filter(Lecon.id == lecon_id)
        .first()
    )

    if not lecon:
        return jsonify({
            "success": False,
            "message": "Leçon introuvable"
        }), 404

    eleves_niveau_count = (
        User.query
        .filter(
            User.role.in_(["eleve", "élève"]),
            User.enseignant_referent_id == enseignant.id,
            User.niveau_id == lecon.unite.matiere.niveau_id
        )
        .count()
    )

    if eleves_niveau_count == 0:
        return jsonify({
            "success": False,
            "message": "Vous n'avez pas accès aux exercices de cette leçon."
        }), 403

    # ============================================================
    # PAGINATION
    # ============================================================

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    if per_page not in [10, 20, 50]:
        per_page = 20

    pagination = (
        Exercice.query
        .filter(Exercice.lecon_id == lecon_id)
        .order_by(Exercice.id.asc())
        .paginate(
            page=page,
            per_page=per_page,
            error_out=False
        )
    )

    exercices_data = []

    for ex in pagination.items:
        question = ex.question_fr if lang == "fr" else ex.question_en
        reponse = ex.reponse_fr if lang == "fr" else ex.reponse_en
        explication = ex.explication_fr if lang == "fr" else ex.explication_en
        options = ex.options_fr if lang == "fr" else ex.options_en

        exercices_data.append({
            "id": ex.id,
            "question": question or "",
            "options": options or "",
            "reponse": reponse or "",
            "explication": explication or "",
            "image_context": ex.get_image_context(lang=lang) if hasattr(ex, "get_image_context") else None
        })

    return jsonify({
        "success": True,
        "exercices": exercices_data,
        "page": pagination.page,
        "pages": pagination.pages,
        "total": pagination.total,
        "has_next": pagination.has_next,
        "has_prev": pagination.has_prev,
        "next_page": pagination.next_num if pagination.has_next else None,
        "prev_page": pagination.prev_num if pagination.has_prev else None
    })


@app.route("/enseignant/exercice/<int:exercice_id>/visualisation")
def enseignant_exercice_visualisation(exercice_id):
    """
    Visualisation d'un exercice par l'enseignant.
    L'enseignant peut voir l'exercice seulement si l'exercice appartient
    au niveau d'au moins un de ses élèves rattachés.
    """

    from models import User, Exercice, Lecon, Unite, Matiere, Niveau
    from sqlalchemy.orm import joinedload

    # ============================================================
    # AUTHENTIFICATION ENSEIGNANT
    # ============================================================

    if "user_id" not in session:
        return redirect(url_for("login_enseignant"))

    if session.get("role") != "enseignant":
        flash("Accès réservé aux enseignants", "error")
        return redirect(url_for("login_enseignant"))

    enseignant = db.session.get(User, session["user_id"])

    if not enseignant or not enseignant.est_enseignant():
        session.clear()
        flash("Session enseignant invalide. Veuillez vous reconnecter.", "error")
        return redirect(url_for("login_enseignant"))

    lang = request.args.get("lang") or session.get("lang", getattr(enseignant, "langue", None) or "fr")

    if lang not in ["fr", "en"]:
        lang = "fr"

    session["lang"] = lang
    session.modified = True

    # ============================================================
    # RÉCUPÉRER L'EXERCICE AVEC SA LEÇON / UNITÉ / MATIÈRE / NIVEAU
    # ============================================================

    exercice = (
        Exercice.query
        .options(
            joinedload(Exercice.lecon)
            .joinedload(Lecon.unite)
            .joinedload(Unite.matiere)
            .joinedload(Matiere.niveau)
        )
        .filter(Exercice.id == exercice_id)
        .first()
    )

    if not exercice:
        flash("Exercice introuvable.", "error")
        return redirect(url_for("enseignant_exercices"))

    lecon = exercice.lecon

    if not lecon or not lecon.unite or not lecon.unite.matiere:
        flash("Structure de l'exercice incomplète.", "error")
        return redirect(url_for("enseignant_exercices"))

    matiere = lecon.unite.matiere
    niveau_id = matiere.niveau_id

    # ============================================================
    # SÉCURITÉ
    # Vérifier que l'enseignant a au moins un élève dans ce niveau.
    # ============================================================

    eleves_niveau_count = (
        User.query
        .filter(
            User.role.in_(["eleve", "élève"]),
            User.enseignant_referent_id == enseignant.id,
            User.niveau_id == niveau_id
        )
        .count()
    )

    if eleves_niveau_count == 0:
        flash("Vous n'avez pas accès à cet exercice.", "error")
        return redirect(url_for("enseignant_exercices"))

    # ============================================================
    # RÉCUPÉRER TOUS LES EXERCICES DE LA MÊME LEÇON
    # Pour permettre précédent / suivant / palette.
    # On charge seulement les exercices de cette leçon, pas tous.
    # ============================================================

    exercices = (
        Exercice.query
        .filter(Exercice.lecon_id == lecon.id)
        .order_by(Exercice.id.asc())
        .all()
    )

    total_exercices = len(exercices)

    if total_exercices == 0:
        flash("Aucun exercice trouvé pour cette leçon.", "warning")
        return redirect(url_for("enseignant_exercices"))

    # ============================================================
    # INDEX COURANT
    # ============================================================

    index = request.args.get("index", type=int)

    if index is None:
        index = 0
        for i, ex in enumerate(exercices):
            if ex.id == exercice.id:
                index = i
                break

    if index < 0:
        index = 0

    if index >= total_exercices:
        index = total_exercices - 1

    exercice = exercices[index]

    # ============================================================
    # TITRE DE LA LEÇON SELON LA LANGUE
    # Ton template utilise lecon.titre
    # On ajoute donc dynamiquement un attribut titre.
    # ============================================================

    titre_lecon = lecon.titre_en if lang == "en" and lecon.titre_en else lecon.titre_fr
    lecon.titre = titre_lecon or f"Leçon {lecon.id}"

    # ============================================================
    # IMAGE / CONTEXTE
    # Ton template utilise exercice.image_context.
    # On le prépare ici.
    # ============================================================

    if hasattr(exercice, "get_image_context"):
        exercice.image_context = exercice.get_image_context(lang=lang)
    else:
        exercice.image_context = None

    return render_template(
        "enseignant_exercice_visualisation.html",
        exercice=exercice,
        exercices=exercices,
        lecon=lecon,
        index=index,
        total_exercices=total_exercices,
        lang=lang,
        enseignant=enseignant
    )




@app.route("/admin/supprimer-eleve/<int:eleve_id>", methods=["POST"])
@admin_required
def supprimer_eleve(eleve_id):
    eleve = User.query.get_or_404(eleve_id)
    db.session.delete(eleve)
    db.session.commit()
    return redirect("/admin/eleves")


@app.route("/login-eleve", methods=["GET", "POST"])
def login_eleve():
    """Connexion des élèves - VERSION CORRIGÉE"""
    lang = session.get("lang", "fr")
    
    # Si déjà connecté en tant qu'élève
    if "user_id" in session and session.get("role") == "eleve":
        return redirect(url_for("dashboard_eleve"))
    
    if request.method == "POST":
        email = request.form.get("email")
        mot_de_passe = request.form.get("mot_de_passe")
        print(f"DEBUG login-eleve: Tentative de connexion avec email={email}")
        
        if not email or not mot_de_passe:
            flash(
                "Email et mot de passe requis" if lang == "fr" else "Email and password required",
                "error"
            )
            return render_template("login_eleve.html", lang=lang)

        # ✅ CORRECTION: Chercher avec les DEUX variantes de rôle
        from sqlalchemy import or_
        eleve = User.query.filter(
            User.email == email,
            or_(User.role == "eleve", User.role == "élève")  # ✅ Recherche les deux
        ).first()
        
        if not eleve:
            print(f"DEBUG login-eleve: Aucun élève trouvé avec email={email}")
            flash(
                "Email ou mot de passe incorrect" if lang == "fr" else "Incorrect email or password",
                "error"
            )
            return render_template("login_eleve.html", lang=lang)

        # Vérifier mot de passe
        if not eleve.verifier_mot_de_passe(mot_de_passe):
            print(f"DEBUG login-eleve: Mot de passe incorrect pour {email}")
            flash(
                "Email ou mot de passe incorrect" if lang == "fr" else "Incorrect email or password",
                "error"
            )
            return render_template("login_eleve.html", lang=lang)

        # ✅ CORRECTION PRINCIPALE : CONNECTER L'UTILISATEUR MÊME SI L'ESSAI A EXPIRÉ
        # Vérifier si l'élève a accès à la plateforme
        if not eleve.a_acces_plateforme():
            # ✅ IMPORTANT : Connecter l'utilisateur d'abord !
            session["user_id"] = eleve.id
            session["role"] = eleve.role
            session["nom_complet"] = eleve.nom_complet
            session["lang"] = eleve.langue if eleve.langue else "fr"
            
            # Mettre à jour les stats de connexion
            eleve.derniere_connexion = datetime.utcnow()
            eleve.nombre_connexions += 1
            db.session.commit()
            
            print(f"⚠️ Essai gratuit expiré pour {eleve.email}")
            
            # Vérifier spécifiquement si l'essai a expiré
            if hasattr(eleve, 'est_en_essai_gratuit') and hasattr(eleve, 'essai_est_expire'):
                if eleve.essai_est_expire():
                    flash(
                        "Votre essai gratuit a expiré. Veuillez souscrire à un abonnement." 
                        if lang == "fr" else "Your free trial has expired. Please subscribe.",
                        "warning"
                    )
                else:
                    flash(
                        "Votre compte n'est pas actif. Contactez l'administrateur." 
                        if lang == "fr" else "Your account is not active. Contact administrator.",
                        "error"
                    )
            
            # ✅ REDIRIGER VERS upgrade_options POUR CHOISIR UN ABONNEMENT
            return redirect(url_for("upgrade_options"))
        
        # ✅ Connexion réussie (essai actif ou déjà payé)
        session["user_id"] = eleve.id
        session["role"] = eleve.role
        session["nom_complet"] = eleve.nom_complet
        session["lang"] = eleve.langue if eleve.langue else "fr"
        
        # Mettre à jour les stats de connexion
        eleve.derniere_connexion = datetime.utcnow()
        eleve.nombre_connexions += 1
        db.session.commit()
        
        print(f"DEBUG login-eleve: Connexion réussie pour {eleve.nom_complet}")
        flash("Connexion réussie !" if lang == "fr" else "Login successful!", "success")

        return redirect(url_for("dashboard_eleve"))

    # GET -> afficher formulaire
    return render_template("login_eleve.html", lang=lang)

    
@app.route("/cleanup-bad-names")
def cleanup_bad_names():
    """Nettoyer les noms avec caractères bizarres"""
    try:
        from models import User, db
        
        # Trouver les élèves avec des caractères bizarres
        bad_students = User.query.filter_by(role="élève").all()
        
        results = []
        for student in bad_students:
            original = student.nom_complet
            cleaned = original
            
            # Remplacer les caractères problématiques
            if '╔' in cleaned or 'Þ' in cleaned:
                cleaned = cleaned.replace('╔', 'É').replace('Þ', 'è')
                
                # Correction spécifique pour "╔lÞve"
                if '╔lÞve' in cleaned:
                    cleaned = cleaned.replace('╔lÞve', 'Élève')
                
                # Mettre à jour si changé
                if cleaned != original:
                    student.nom_complet = cleaned
                    results.append(f"{original} → {cleaned}")
        
        if results:
            db.session.commit()
            html = "<h1>Noms nettoyés :</h1><ul>"
            for r in results:
                html += f"<li>{r}</li>"
            html += "</ul>"
        else:
            html = "<p>Aucun nom à nettoyer</p>"
        
        # Afficher la liste finale
        html += "<h2>Liste finale des élèves :</h2>"
        html += "<table border='1'><tr><th>ID</th><th>Nom</th><th>Email</th></tr>"
        
        for student in User.query.filter_by(role="élève").order_by(User.nom_complet).all():
            html += f"<tr><td>{student.id}</td><td>{student.nom_complet}</td><td>{student.email}</td></tr>"
        
        html += "</table>"
        
        return html
        
    except Exception as e:
        import traceback
        return f"<h1>Erreur</h1><pre>{traceback.format_exc()}</pre>"

@app.route("/fix-encoding-issue")
def fix_encoding_issue():
    """Corriger le problème d'encodage des noms"""
    try:
        from models import User, db
        import psycopg2
        from psycopg2 import sql
        
        results = []
        
        # Élèves à corriger
        eleves_a_corriger = [
            (8, "Élève test 7ème"),
            (9, "Élève_test_12")
        ]
        
        for eleve_id, nouveau_nom in eleves_a_corriger:
            eleve = User.query.get(eleve_id)
            if eleve:
                ancien_nom = eleve.nom_complet
                eleve.nom_complet = nouveau_nom
                results.append(f"{ancien_nom} → {nouveau_nom}")
        
        if results:
            db.session.commit()
            html = "<h1>Noms corrigés :</h1><ul>"
            for r in results:
                html += f"<li>{r}</li>"
            html += "</ul>"
        else:
            html = "<p>Aucun nom à corriger</p>"
        
        # Vérifier
        html += "<h2>Vérification :</h2>"
        html += "<table border='1'><tr><th>ID</th><th>Nom</th><th>Email</th></tr>"
        
        for eleve in User.query.filter_by(role="élève").order_by(User.nom_complet).all():
            html += f"<tr><td>{eleve.id}</td><td>{eleve.nom_complet}</td><td>{eleve.email}</td></tr>"
        
        html += "</table>"
        
        return html
        
    except Exception as e:
        import traceback
        return f"<h1>Erreur</h1><pre>{traceback.format_exc()}</pre>"

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
    """
    Gestion des exercices organisée par :
        niveau -> matière -> unité -> leçon -> exercices

    Optimisations :
    - filtres appliqués côté PostgreSQL ;
    - pagination sur les UNITÉS ;
    - seules les leçons/exercices des unités de la page sont chargés ;
    - pas de chargement des 12 000+ exercices en mémoire.
    """

    import math
    from sqlalchemy import or_

    # ============================================================
    # 1. PARAMÈTRES
    # ============================================================

    page = request.args.get("page", 1, type=int)
    niveau_id = request.args.get("niveau_id", type=int)
    matiere_id = request.args.get("matiere_id", type=int)
    q = (request.args.get("q") or "").strip()

    if page < 1:
        page = 1

    # Nombre d'UNITÉS par page.
    # 2 est volontairement prudent pour Render.
    per_page = 2

    session["current_exercises_page"] = page

    # ============================================================
    # 2. STATISTIQUES GLOBALES
    # ============================================================

    total_exercices = (
        db.session.query(db.func.count(Exercice.id)).scalar() or 0
    )
    total_lecons = (
        db.session.query(db.func.count(Lecon.id)).scalar() or 0
    )
    total_unites = (
        db.session.query(db.func.count(Unite.id)).scalar() or 0
    )
    total_matieres = (
        db.session.query(db.func.count(Matiere.id)).scalar() or 0
    )

    # ============================================================
    # 3. NIVEAUX ET MATIÈRES POUR LES FILTRES
    # ============================================================

    niveaux = (
        Niveau.query
        .order_by(Niveau.id.asc())
        .all()
    )

    toutes_matieres = (
        Matiere.query
        .order_by(Matiere.niveau_id.asc(), Matiere.nom.asc())
        .all()
    )

    matieres_par_niveau = {niveau.id: [] for niveau in niveaux}

    for matiere in toutes_matieres:
        matieres_par_niveau.setdefault(
            matiere.niveau_id,
            []
        ).append(matiere)

    # ============================================================
    # 4. REQUÊTE DES UNITÉS AYANT DES EXERCICES
    # ============================================================

    unites_query = (
        db.session.query(Unite, Matiere)
        .join(
            Matiere,
            Unite.matiere_id == Matiere.id
        )
        .join(
            Lecon,
            Lecon.unite_id == Unite.id
        )
        .join(
            Exercice,
            Exercice.lecon_id == Lecon.id
        )
    )

    # Filtre niveau
    if niveau_id:
        unites_query = unites_query.filter(
            Matiere.niveau_id == niveau_id
        )

    # Filtre matière
    if matiere_id:
        unites_query = unites_query.filter(
            Matiere.id == matiere_id
        )

    # Recherche
    if q:
        like_q = f"%{q}%"

        unites_query = unites_query.filter(
            or_(
                Exercice.question_fr.ilike(like_q),
                Exercice.question_en.ilike(like_q),
                Unite.nom.ilike(like_q),
                Unite.nom_en.ilike(like_q),
                Lecon.titre_fr.ilike(like_q),
                Lecon.titre_en.ilike(like_q),
            )
        )

    # Une unité ne doit apparaître qu'une seule fois.
    unites_query = unites_query.distinct()

    # ============================================================
    # 5. PAGINATION SUR LES UNITÉS
    # ============================================================

    total_unites_filtrees = unites_query.count()

    total_pages = max(
        1,
        math.ceil(total_unites_filtrees / per_page)
    )

    if page > total_pages:
        page = total_pages
        session["current_exercises_page"] = page

    offset = (page - 1) * per_page

    unites_page = (
        unites_query
        .order_by(
            Matiere.niveau_id.asc(),
            Matiere.id.asc(),
            Unite.id.asc()
        )
        .offset(offset)
        .limit(per_page)
        .all()
    )

    unite_ids = [
        unite.id
        for unite, matiere in unites_page
    ]

    # ============================================================
    # 6. CHARGER LES LEÇONS DES UNITÉS DE LA PAGE
    # ============================================================

    lecons_page = []

    if unite_ids:
        lecons_page = (
            Lecon.query
            .filter(
                Lecon.unite_id.in_(unite_ids)
            )
            .order_by(
                Lecon.unite_id.asc(),
                Lecon.id.asc()
            )
            .all()
        )

    lecon_ids = [
        lecon.id
        for lecon in lecons_page
    ]

    # ============================================================
    # 7. CHARGER LES EXERCICES DE CES LEÇONS
    # ============================================================

    exercices_page = []

    if lecon_ids:
        exercices_query = (
            Exercice.query
            .filter(
                Exercice.lecon_id.in_(lecon_ids)
            )
        )

        # Si une recherche est active, on n'affiche que les exercices
        # qui correspondent réellement au terme recherché.
        if q:
            like_q = f"%{q}%"
            exercices_query = exercices_query.filter(
                or_(
                    Exercice.question_fr.ilike(like_q),
                    Exercice.question_en.ilike(like_q),
                )
            )

        exercices_page = (
            exercices_query
            .order_by(
                Exercice.lecon_id.asc(),
                Exercice.id.asc()
            )
            .all()
        )

    exercices_par_lecon = {}

    for exercice in exercices_page:
        exercices_par_lecon.setdefault(
            exercice.lecon_id,
            []
        ).append(exercice)

    lecons_par_unite = {}

    for lecon in lecons_page:
        # En mode recherche, masquer les leçons qui n'ont aucun
        # exercice correspondant, sauf si le terme correspond au
        # titre de la leçon ou au nom de l'unité.
        if q and not exercices_par_lecon.get(lecon.id):
            titre = " ".join([
                lecon.titre_fr or "",
                lecon.titre_en or ""
            ]).lower()

            if q.lower() not in titre:
                continue

        lecons_par_unite.setdefault(
            lecon.unite_id,
            []
        ).append(lecon)

    # ============================================================
    # 8. COMPTES DES EXERCICES
    # ============================================================

    comptes_unites = {}

    if unite_ids:
        comptes_unites = dict(
            db.session.query(
                Unite.id,
                db.func.count(Exercice.id)
            )
            .join(
                Lecon,
                Lecon.unite_id == Unite.id
            )
            .join(
                Exercice,
                Exercice.lecon_id == Lecon.id
            )
            .filter(
                Unite.id.in_(unite_ids)
            )
            .group_by(Unite.id)
            .all()
        )

    matiere_ids_page = list({
        matiere.id
        for unite, matiere in unites_page
    })

    comptes_matieres = {}

    if matiere_ids_page:
        comptes_matieres = dict(
            db.session.query(
                Matiere.id,
                db.func.count(Exercice.id)
            )
            .join(
                Unite,
                Unite.matiere_id == Matiere.id
            )
            .join(
                Lecon,
                Lecon.unite_id == Unite.id
            )
            .join(
                Exercice,
                Exercice.lecon_id == Lecon.id
            )
            .filter(
                Matiere.id.in_(matiere_ids_page)
            )
            .group_by(Matiere.id)
            .all()
        )

    # ============================================================
    # 9. RECONSTRUIRE LA STRUCTURE DU TEMPLATE
    # ============================================================

    structure_matieres = {}

    for unite, matiere in unites_page:

        if matiere.id not in structure_matieres:
            structure_matieres[matiere.id] = {
                "id": matiere.id,
                "nom": matiere.nom,
                "nom_en": matiere.nom_en,
                "niveau_id": matiere.niveau_id,
                "niveau": matiere.niveau,
                "total_exercices": comptes_matieres.get(
                    matiere.id,
                    0
                ),
                "unites_avec_exercices": []
            }

        lecons_struct = []

        for lecon in lecons_par_unite.get(
            unite.id,
            []
        ):
            lecons_struct.append({
                "id": lecon.id,
                "titre_fr": lecon.titre_fr,
                "titre_en": lecon.titre_en,
                "exercices": exercices_par_lecon.get(
                    lecon.id,
                    []
                )
            })

        structure_matieres[matiere.id][
            "unites_avec_exercices"
        ].append({
            "id": unite.id,
            "nom": unite.nom,
            "nom_en": unite.nom_en,
            "total_exercices": comptes_unites.get(
                unite.id,
                0
            ),
            "lecons_avec_exercices": lecons_struct
        })

    matieres_avec_exercices = list(
        structure_matieres.values()
    )

    # ============================================================
    # 10. TOTAL D'EXERCICES CORRESPONDANT AUX FILTRES
    # ============================================================

    total_exercices_filtres_query = (
        db.session.query(
            db.func.count(Exercice.id)
        )
        .join(
            Lecon,
            Exercice.lecon_id == Lecon.id
        )
        .join(
            Unite,
            Lecon.unite_id == Unite.id
        )
        .join(
            Matiere,
            Unite.matiere_id == Matiere.id
        )
    )

    if niveau_id:
        total_exercices_filtres_query = (
            total_exercices_filtres_query.filter(
                Matiere.niveau_id == niveau_id
            )
        )

    if matiere_id:
        total_exercices_filtres_query = (
            total_exercices_filtres_query.filter(
                Matiere.id == matiere_id
            )
        )

    if q:
        like_q = f"%{q}%"
        total_exercices_filtres_query = (
            total_exercices_filtres_query.filter(
                or_(
                    Exercice.question_fr.ilike(like_q),
                    Exercice.question_en.ilike(like_q),
                )
            )
        )

    total_exercices_filtres = (
        total_exercices_filtres_query.scalar() or 0
    )

    # ============================================================
    # 11. PAGINATION
    # ============================================================

    has_previous = page > 1
    has_next = page < total_pages

    previous_page = (
        page - 1
        if has_previous
        else None
    )

    next_page = (
        page + 1
        if has_next
        else None
    )

    # ============================================================
    # 12. LOGS DE CONTRÔLE
    # ============================================================

    print("========== ADMIN GESTION EXERCICES ==========")
    print(f"🔎 request.args : {request.args.to_dict()}")
    print(f"🎓 Niveau : {niveau_id or 'tous'}")
    print(f"📚 Matière : {matiere_id or 'toutes'}")
    print(f"🔍 Recherche : {q or 'aucune'}")
    print(f"📦 Unités page : {len(unites_page)}")
    print(
        f"📦 Unités filtrées : "
        f"{total_unites_filtrees}"
    )
    print(
        f"📘 Leçons chargées : "
        f"{len(lecons_page)}"
    )
    print(
        f"🧩 Exercices chargés : "
        f"{len(exercices_page)}"
    )
    print(
        f"🧩 Exercices filtre : "
        f"{total_exercices_filtres}"
    )
    print(f"📄 Page : {page}/{total_pages}")
    print("==============================================")

    # ============================================================
    # 13. TEMPLATE
    # ============================================================

    return render_template(
        "liste_exercices.html",

        matieres_avec_exercices=matieres_avec_exercices,

        total_exercices=total_exercices,
        total_exercices_filtres=total_exercices_filtres,
        total_lecons=total_lecons,
        total_unites=total_unites,
        total_unites_filtrees=total_unites_filtrees,
        total_matieres=total_matieres,

        niveaux=niveaux,
        matieres_par_niveau=matieres_par_niveau,

        niveau_id_selectionne=niveau_id,
        matiere_id_selectionnee=matiere_id,
        q=q,

        page=page,
        per_page=per_page,
        total_pages=total_pages,
        has_previous=has_previous,
        has_next=has_next,
        previous_page=previous_page,
        next_page=next_page,

        lang=session.get("lang", "fr")
    )


@app.after_request
def after_request(response):
    """Fonction unifiée après requête"""
    
    # === 1. TIMING DES REQUÊTES ===
    # Logger les requêtes lentes (> 500ms)
    if hasattr(request, 'start_time'):
        duration = time.time() - request.start_time
        if duration > 0.5:
            logger.warning(f"⚠️ Requête lente: {request.path} - {duration:.2f}s")
    
    # === 2. HEADERS ANTI-CACHE (indispensable pour AJAX) ===
    # Empêche le navigateur de mettre en cache les pages
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    
    # === 3. LOGGING DÉVELOPPEMENT (optionnel) ===
    # Utile en développement, peut être commenté en production
    if app.debug:  # Seulement en mode debug
        print(f"📡 {request.method} {request.path} → {response.status_code}")
    
    return response


# ====================================================================
# 🚀 LANCEMENT DE L'APPLICATION
# ====================================================================

if __name__ == '__main__':
    # Créez le dossier de sessions s'il n'existe pas
    os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)
    
    print("🚀 Application Tutorat AI démarrée")
    print(f"📁 Dossier de sessions: {app.config['SESSION_FILE_DIR']}")
    print(f"🔗 Mode: {'Production' if 'postgresql' in DB_URL else 'Développement'}")
    
    app.run(debug=True, host='127.0.0.1', port=5000)
