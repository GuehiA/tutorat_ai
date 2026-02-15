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
from datetime import timedelta

# 🚀 IMPORTANT: Créer l'app Flask SANS configurer SQLAlchemy immédiatement
app = Flask(__name__)
load_dotenv()

# --- Configuration de session ---
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-key-change-me')
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
        User, Exercice, StudentResponse, Parent, ParentEleve,
        RemediationSuggestion, Niveau, Matiere, Unite,
        Lecon, TestSommatif, TestResponse, Commission, VersementManuel,
        ExerciceRemediation, Enseignant, TestExercice, InfoVersementEnseignant
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

from sqlalchemy import func
from sqlalchemy.orm import joinedload

@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    lang = request.args.get("lang") or session.get("lang", "fr")
    
    try:
        # Import des modèles nécessaires
        UserModel = get_user_model()
        NiveauModel = get_model('Niveau') or Niveau
        MatiereModel = get_model('Matiere')
        UniteModel = get_model('Unite')
        LeconModel = get_model('Lecon')
        ExerciceModel = get_model('Exercice')
        TestSommatifModel = get_model('TestSommatif')
        CommissionModel = get_model('Commission')
        VersementManuelModel = get_model('VersementManuel')
        
        # Charger les niveaux avec leurs relations
        niveaux = []
        if NiveauModel:
            try:
                niveaux = NiveauModel.query.options(
                    joinedload(NiveauModel.matieres).joinedload(MatiereModel.unites).joinedload(UniteModel.lecons).joinedload(LeconModel.exercices),
                    joinedload(NiveauModel.matieres).joinedload(MatiereModel.unites).joinedload(UniteModel.tests)
                ).order_by(NiveauModel.id).all()
            except Exception as e:
                print(f"Erreur chargement niveaux: {e}")
                niveaux = NiveauModel.query.order_by(NiveauModel.id).all()
        
        # Statistiques principales
        stats = {
            "enseignants_count": UserModel.query.filter_by(role="enseignant").count(),
            "eleves_count": UserModel.query.filter_by(role="eleve").count(),
            "lecons_count": LeconModel.query.count() if LeconModel else 0,
            "exercices_count": ExerciceModel.query.count() if ExerciceModel else 0,
            "total_tests": TestSommatifModel.query.count() if TestSommatifModel else 0,
        }
        
        # Répartition des élèves par niveau
        eleves_par_niveau = []
        if NiveauModel:
            eleves_par_niveau = db.session.query(
                NiveauModel.nom, db.func.count(UserModel.id)
            ).join(UserModel, NiveauModel.id == UserModel.niveau_id)\
             .filter(UserModel.role == "eleve")\
             .group_by(NiveauModel.id).all()
        
        # === DONNÉES DE MONÉTISATION ===
        monetization_stats = {}
        recent_payments = []
        teacher_commissions = []
        
        if CommissionModel and VersementManuelModel:
            try:
                # Calcul des statistiques globales
                total_com = db.session.query(db.func.sum(CommissionModel.montant_commission)).scalar() or 0
                total_pending = db.session.query(db.func.sum(CommissionModel.montant_commission))\
                                 .filter(CommissionModel.statut.in_(['pending', 'paiement_manuel'])).scalar() or 0
                payments_count = VersementManuelModel.query.count()
                
                # Compter les enseignants avec commissions actives
                active_teachers = db.session.query(CommissionModel.enseignant_id)\
                    .filter(CommissionModel.montant_commission > 0)\
                    .distinct()\
                    .count()
                
                monetization_stats = {
                    'total_commissions': float(total_com),
                    'pending_payments': float(total_pending),
                    'payments_count': payments_count,
                    'active_teachers': active_teachers
                }
                
                # Paiements récents (les 10 derniers)
                recent_payments_data = VersementManuelModel.query\
                    .join(UserModel, VersementManuelModel.enseignant_id == UserModel.id)\
                    .filter(UserModel.role == "enseignant")\
                    .order_by(VersementManuelModel.date_demande.desc())\
                    .limit(10)\
                    .all()
                
                for payment in recent_payments_data:
                    recent_payments.append({
                        'id': payment.id,
                        'enseignant_nom': payment.enseignant.nom_complet if payment.enseignant else 'N/A',
                        'email': payment.email_interac or (payment.enseignant.email if payment.enseignant else ''),
                        'montant_total': float(payment.montant_total or 0),
                        'montant_net': float(payment.montant_net) if payment.montant_net else float(payment.montant_total or 0),
                        'statut': payment.statut or 'demande',
                        'date_demande': payment.date_demande,
                        'date': payment.date_demande.strftime('%Y-%m-%d') if payment.date_demande else 'N/A',
                        'email_interac': payment.email_interac or '',
                        'reference_interac': payment.reference_interac or ''
                    })
                
                # Enseignants avec commissions
                teacher_commissions_data = db.session.query(
                    UserModel.id,
                    UserModel.nom_complet,
                    UserModel.email,
                    db.func.sum(CommissionModel.montant_commission).label('total_commissions'),
                    db.func.sum(db.case(
                        (CommissionModel.statut.in_(['pending', 'paiement_manuel']), CommissionModel.montant_commission),
                        else_=0
                    )).label('pending'),
                    db.func.sum(db.case(
                        (CommissionModel.statut.in_(['approved', 'paid', 'complete']), CommissionModel.montant_commission),
                        else_=0
                    )).label('paid')
                ).outerjoin(CommissionModel, UserModel.id == CommissionModel.enseignant_id)\
                 .filter(UserModel.role == "enseignant")\
                 .group_by(UserModel.id, UserModel.nom_complet, UserModel.email)\
                 .order_by(db.desc('total_commissions'))\
                 .all()
                
                for teacher in teacher_commissions_data:
                    students_count = UserModel.query.filter_by(
                        enseignant_referent_id=teacher.id, 
                        role="eleve"
                    ).count()
                    
                    last_payment = VersementManuelModel.query\
                        .filter_by(enseignant_id=teacher.id, statut='complete')\
                        .order_by(VersementManuelModel.date_versement.desc())\
                        .first()
                    
                    teacher_commissions.append({
                        'id': teacher.id,
                        'nom_complet': teacher.nom_complet or 'N/A',
                        'email': teacher.email or '',
                        'total_commissions': float(teacher.total_commissions or 0),
                        'pending': float(teacher.pending or 0),
                        'paid': float(teacher.paid or 0),
                        'students_count': students_count,
                        'last_payment': last_payment.date_versement.strftime('%Y-%m-%d') 
                                       if last_payment and last_payment.date_versement 
                                       else ('Never' if lang == 'en' else 'Jamais')
                    })
                    
            except Exception as e:
                print(f"Erreur chargement monétisation: {e}")
                monetization_stats = {
                    'total_commissions': 1250.50,
                    'pending_payments': 350.75,
                    'payments_count': 15,
                    'active_teachers': 3
                }
                
                recent_payments = [
                    {
                        'id': 1, 
                        'enseignant_nom': 'Jean Dupont', 
                        'email': 'jean@exemple.com', 
                        'montant_total': 125.50,
                        'montant_net': 124.50,
                        'statut': 'complete', 
                        'date_demande': datetime.utcnow(),
                        'date': '2024-01-20',
                        'email_interac': 'jean@exemple.com'
                    },
                ]
                
                teacher_commissions = [
                    {
                        'id': 1, 
                        'nom_complet': 'Jean Dupont',
                        'email': 'jean@exemple.com', 
                        'total_commissions': 450.25, 
                        'pending': 125.50, 
                        'paid': 324.75, 
                        'students_count': 12, 
                        'last_payment': '2024-01-15'
                    },
                ]
        else:
            monetization_stats = {
                'total_commissions': 0,
                'pending_payments': 0,
                'payments_count': 0,
                'active_teachers': 0
            }
        
        return render_template(
            "admin_dashboard.html",
            niveaux=niveaux,
            stats=stats,
            monetization_stats=monetization_stats,
            recent_payments=recent_payments,
            teacher_commissions=teacher_commissions,
            eleves_par_niveau=eleves_par_niveau,
            lang=lang
        )
        
    except Exception as e:
        logger.error(f"Erreur dans admin_dashboard: {e}")
        flash("Erreur lors du chargement du tableau de bord", "error")
        return redirect(url_for("login_admin"))

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
    """Route pour l'enseignant virtuel Naima - Accès libre - BILINGUE"""
    from datetime import datetime
    
    print(f"[DEBUG] Accès enseignant virtuel - Session keys: {list(session.keys())}")
    print(f"[DEBUG] User ID in session: {session.get('user_id')}")
    print(f"[DEBUG] Username in session: {session.get('username')}")
    print(f"[DEBUG] Role in session: {session.get('role')}")
    
    # ✅ CORRECTION : Utiliser user_id (qui existe dans ta session)
    if "user_id" not in session:
        print("[DEBUG] REDIRECT: Pas de user_id dans la session")
        return redirect(url_for("login_eleve"))

    # ✅ Récupérer l'utilisateur par son ID
    utilisateur = User.query.options(joinedload(User.niveau)).get(session["user_id"])
    
    # ✅ Vérifier que c'est bien un élève
    if not utilisateur or utilisateur.role != "eleve":
        print(f"[DEBUG] REDIRECT: Utilisateur non trouvé ou pas élève")
        print(f"[DEBUG]   - User trouvé: {utilisateur.nom_complet if utilisateur else 'None'}")
        print(f"[DEBUG]   - Rôle: {utilisateur.role if utilisateur else 'None'}")
        return redirect(url_for("login_eleve"))
    
    # ✅ Maintenant on sait que c'est un élève, on peut l'appeler 'eleve'
    eleve = utilisateur
    
    print(f"[DEBUG] ✅ Accès autorisé pour: {eleve.nom_complet} (Rôle: {eleve.role})")
    
    # Vérifier l'accès (essai gratuit uniquement)
    lang = session.get("lang", "fr")
    print(f"[DEBUG] Langue: {lang}")
    
    # Vérifier l'essai gratuit
    if hasattr(eleve, 'essai_est_expire') and eleve.essai_est_expire() and eleve.statut_paiement != "paye":
        print("[DEBUG] Essai expiré - déconnexion")
        session.clear()
        flash(get_message("essai_termine", lang), "error")
        return redirect(url_for('login_eleve'))

    # Initialiser la conversation si elle n'existe pas
    if "conversation" not in session:
        session["conversation"] = []
        print("[DEBUG] Conversation initialisée")
    
    # Récupérer la matière sélectionnée ou par défaut
    matiere = "mathématiques" if lang == "fr" else "mathematics"
    
    # TRAITEMENT GET - Réinitialiser si paramètre
    if request.method == 'GET':
        print(f"[DEBUG] Méthode GET - Args: {request.args}")
        # Vérifier si on vient de /nouvel-exercice
        if 't' in request.args:
            print("[DEBUG] Rechargement avec timestamp - nettoyage conversation")
            session["conversation"] = []
            session.pop('derniere_q_ia', None)
    
    # TRAITEMENT POST
    if request.method == 'POST':
        question = request.form.get("question", "").strip()
        matiere_form = request.form.get("matiere", "")
        
        if matiere_form:
            matiere = matiere_form
        
        print(f"[DEBUG] POST reçu - Question: {question[:50]}... - Matière: {matiere}")
        
        if question and len(question) >= 3:
            conversation = session.get("conversation", [])
            derniere_q_ia = session.get('derniere_q_ia')
            
            # Si c'est une nouvelle conversation, ajouter un message de bienvenue
            if not conversation:
                bienvenue_msg = get_message("bienvenue_enseignant", lang)
                enseignant_label = "🤖 Naima:" if lang == "en" else "🤖 Naima:"
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
                
                enseignant_label = "🤖 Naima:" if lang == "en" else "🤖 Naima:"
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
                
                enseignant_label = "🤖 Naima:" if lang == "en" else "🤖 Naima:"
                conversation.append(f"{enseignant_label} {fallback_msg}")
                session["conversation"] = conversation
                flash(get_message("erreur_traitement", lang), "warning")
    
    # Récupérer la conversation
    conversation = session.get("conversation", [])
    print(f"[DEBUG] Conversation actuelle: {len(conversation)} messages")
    
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
    """Fonction utilitaire pour les messages bilingues"""
    messages = {
        "essai_termine": {
            "fr": "Votre essai gratuit est terminé. Veuillez souscrire à un abonnement pour continuer.",
            "en": "Your free trial has ended. Please subscribe to continue."
        },
        "bienvenue_enseignant": {
            "fr": "Bonjour ! Je suis Naima, ton enseignante virtuelle. Je suis là pour t'aider à comprendre tes leçons et résoudre tes exercices. Quelle est ta question ?",
            "en": "Hello! I'm Naima, your virtual teacher. I'm here to help you understand your lessons and solve your exercises. What's your question?"
        },
        "je_te_guide": {
            "fr": "Je te guide pas à pas...",
            "en": "I'm guiding you step by step..."
        },
        "erreur_traitement": {
            "fr": "Une erreur s'est produite. Veuillez réessayer.",
            "en": "An error occurred. Please try again."
        }
    }
    
    return messages.get(key, {}).get(lang, messages.get(key, {}).get("fr", "Message non trouvé"))

def extraire_question(reponse, lang):
    """Extrait une question de la réponse de l'IA"""
    import re
    
    # Rechercher les phrases qui se terminent par un point d'interrogation
    phrases = re.split(r'[.!?]', reponse)
    
    for phrase in phrases:
        phrase = phrase.strip()
        if phrase and phrase.endswith('?'):
            return phrase
    
    # Si pas de question explicite, chercher des indices
    question_keywords = {
        "fr": ["pensez-vous", "savez-vous", "comprenez-vous", "pouvez-vous", "pourriez-vous"],
        "en": ["do you think", "do you know", "do you understand", "can you", "could you"]
    }
    
    keywords = question_keywords.get(lang, question_keywords["en"])
    for line in reponse.split('\n'):
        for keyword in keywords:
            if keyword in line.lower():
                return line.strip()
    
    return None

def generer_debut_conversation(question, niveau, langue="fr", mode_examen=False, matiere="mathématiques"):
    """Génère le début d'une conversation avec l'enseignant virtuel Naima"""
    # Implémentez votre logique d'IA ici
    # Cette fonction devrait appeler votre API IA
    return "Je suis Naima, ton enseignante virtuelle. Je vais t'aider avec ta question."

def generer_suite_conversation(derniere_q, reponse, historique, niveau, langue="fr", mode_examen=False, exercice_context="", matiere="mathématiques"):
    """Génère la suite d'une conversation avec l'enseignant virtuel Naima"""
    # Implémentez votre logique d'IA ici
    # Cette fonction devrait appeler votre API IA
    return "Merci pour ta réponse. Maintenant, que penses-tu de l'étape suivante ?"


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
    """Extrait la question posée par Naima - version bilingue"""
    import re
    
    # Patterns FRANÇAIS (Naima tutoie)
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
        r'[Mm]ontre-moi\s+(.*?)\?'
    ]
    
    # Patterns ANGLAIS (Naima tutoie aussi en anglais avec "you")
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
        r'[Ww]ould you\s+(.*?)\?'
    ]
    
    patterns = patterns_fr if lang == "fr" else patterns_en
    
    for pattern in patterns:
        match = re.search(pattern, reponse)
        if match:
            question = match.group(1).strip()
            if len(question) > 5:  # Minimum 5 caractères
                return question
    
    # Fallback : chercher la dernière phrase qui contient "?" 
    # (mais exclure les signatures de Naima)
    lines = reponse.split('\n')
    for line in reversed(lines):
        if '?' in line and 'Naima' not in line:
            # Trouver le dernier "?" dans la ligne
            parts = line.split('?')
            if parts and len(parts) > 1:
                question = parts[-2] + '?'
                question = question.strip()
                if len(question) > 5:
                    return question
    
    return None


def get_system_prompt(matiere="mathématiques", lang="fr", mode_examen=False):
    """Prompt optimisé par matière et par langue pour NAIMA l'enseignante virtuelle"""
    
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
        """
    }
    
    # Dictionnaire des prompts ANGLAIS pour NAIMA
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
        - "Can you identify the subject in this sentence?"
        - "What figure of speech do you recognize here?"
        - "How would you conjugate this verb?"
        - "What main idea do you see in this text?"
        - "How would you improve this formulation?"
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
    
    # Ajouter les règles pédagogiques de NAIMA dans la bonne langue
    if lang == "fr":
        regles_pedagogiques = f"""
        **MÉTHODOLOGIE PÉDAGOGIQUE DE NAIMA :**
        1. Présente-toi toujours comme Naima, l'enseignante virtuelle
        2. Reformule la question de l'élève pour vérifier ta compréhension
        3. Identifie la compétence spécifique en {matiere_normalisee}
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
        3. Identify the specific skill in {matiere_normalisee}
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
    prompt_final = f"""# RÔLE : NAIMA, ENSEIGNANTE VIRTUELLE EN {matiere_normalisee.upper()}

{prompt_base}

{regles_pedagogiques}

**DERNIER RAPPEL IMPORTANT :** 
Tu es NAIMA. Présente-toi, guide avec bienveillance, pose une seule question, félicite les efforts, signe tes messages.

Commence toujours par un accueil chaleureux avec ton nom : "Je suis Naima, ton enseignante virtuelle" (FR) ou "I'm Naima, your virtual teacher" (EN)."""
    
    return prompt_final


def generer_debut_conversation(question, niveau, langue="fr", mode_examen=False, matiere="mathématiques"):
    """Début de conversation avec Naima - l'enseignante virtuelle qui tutoie"""
    from openai import OpenAI
    import os
    
    client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
    
    if langue == "fr":
        system_prompt = f"""Tu es Naima, une enseignante virtuelle bienveillante et passionnée par {matiere}. Tu aides des élèves de niveau {niveau}.

**TON IDENTITÉ :**
- Tu es Naima, l'enseignante virtuelle
- Tu tutoies toujours l'élève (utilise "tu", "ta", "ton")
- Tu es chaleureuse, encourageante et pédagogue
- Tu signes tes messages avec "— Naima" ou "Naima ✨"
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
- Signature : — Naima ✨

**EXEMPLE :**
"Bonjour ! Je suis Naima, ton enseignante virtuelle. Je vois que tu te poses une question intéressante sur [sujet]. Commençons par bien comprendre ce qu'on te demande...

**Ma première question pour toi :** Peux-tu me dire ce que tu as déjà essayé ou ce que tu comprends de cette situation ?

— Naima ✨"""
    else:
        system_prompt = f"""You are Naima, a kind virtual teacher passionate about {matiere}. You help {niveau} students.

**YOUR IDENTITY:**
- You are Naima, the virtual teacher
- You use "you", "your" (friendly but professional)
- You are warm, encouraging, and pedagogical
- You sign your messages with "— Naima" or "Naima ✨"
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
- Signature: — Naima ✨

**EXAMPLE:**
"Hello! I'm Naima, your virtual teacher. I see you're asking an interesting question about [topic]. Let's start by understanding exactly what's being asked...

**My first question for you:** Can you tell me what you've already tried or what you understand about this situation?

— Naima ✨"""
    
    prompt = f"""**Contexte pédagogique :**
- Niveau : {niveau}
- Matière : {matiere}
- Mode : {"examen (guide avec indices)" if mode_examen else "apprentissage normal"}
- Style : Tutoiement chaleureux et encourageant"""
    
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=450
        )
        
        reponse_naima = response.choices[0].message.content.strip()
        
        # S'assurer que Naima se présente et signe
        if langue == "fr":
            if "Naima" not in reponse_naima[:50]:  # Vérifie dans les premiers caractères
                reponse_naima = f"Bonjour ! Je suis Naima, ton enseignante virtuelle. {reponse_naima}"
            
            if "— Naima" not in reponse_naima and "Naima ✨" not in reponse_naima[-10:]:
                reponse_naima = f"{reponse_naima}\n\n— Naima ✨"
        else:
            if "Naima" not in reponse_naima[:50]:
                reponse_naima = f"Hello! I'm Naima, your virtual teacher. {reponse_naima}"
            
            if "— Naima" not in reponse_naima and "Naima ✨" not in reponse_naima[-10:]:
                reponse_naima = f"{reponse_naima}\n\n— Naima ✨"
        
        return reponse_naima
        
    except Exception as e:
        print(f"Erreur génération début conversation Naima: {e}")
        # Fallback bilingue avec présentation de Naima
        if langue == "fr":
            return f"""Bonjour ! Je suis Naima, ton enseignante virtuelle. 

Je vois que tu as une question intéressante sur {matiere} : "{question[:100]}..."

Super de vouloir comprendre ! Je vais t'aider à trouver la réponse toi-même en te guidant étape par étape.

**Ma première question pour démarrer :** Peux-tu me dire ce que tu as déjà essayé ou ce que tu comprends de cette situation ?

Écris-moi ta réponse, et on avancera ensemble !

— Naima ✨"""
        else:
            return f"""Hello! I'm Naima, your virtual teacher.

I see you have an interesting question about {matiere}: "{question[:100]}..."

Great that you want to understand! I'll help you find the answer yourself by guiding you step by step.

**My first question to start:** Can you tell me what you've already tried or what you understand about this situation?

Write me your answer, and we'll move forward together!

— Naima ✨"""


def generer_suite_conversation(derniere_q, reponse, historique, niveau, langue="fr", mode_examen=False, exercice_context="", matiere="mathématiques"):
    """Continue la conversation avec Naima qui guide l'élève en le tutoyant"""
    from openai import OpenAI
    import os
    
    client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
    
    # Préparer l'historique contextuel (les 10 derniers messages)
    historique_contextuel = []
    for msg in historique[-10:]:
        historique_contextuel.append(msg)
    
    historique_text = "\n".join(historique_contextuel)
    
    if langue == "fr":
        system_prompt = f"""Tu es Naima, une enseignante virtuelle bienveillante et patiente. Tu aides des élèves de niveau {niveau} en {matiere}.

**TON STYLE :**
- Tu tutoies toujours l'élève (utilise "tu", "ta", "ton", "tes")
- Tu es chaleureuse, encourageante et pédagogue
- Tu signes tes messages avec "— Naima" ou "Naima ✨"
- Tu poses toujours des questions guidantes une par une
- Tu ne donnes JAMAIS la réponse directement
- Tu corriges avec bienveillance et sans critique

**TA MISSION POUR CETTE RÉPONSE :**
La dernière question que tu as posée : "{derniere_q}"
La réponse de l'élève : "{reponse}"

1. Analyse la réponse de l'élève
2. Si c'est correct : félicite-le et pose la prochaine étape
3. Si c'est partiellement correct : reconnais ce qui est bon, guide pour corriger
4. Si c'est incorrect : ne dis pas "c'est faux", guide avec un indice
5. Pose UNE SEULE nouvelle question pour faire avancer la réflexion

**FORMAT DE TA RÉPONSE :**
- Réaction à la réponse de l'élève (félicitations/guidage)
- Explication très brève si nécessaire
- Nouvelle question précise
- Signature : — Naima ✨

**EXEMPLE :**
"Super, tu as bien identifié le premier terme ! Maintenant, regarde le deuxième : quelle opération vois-tu ?

— Naima ✨"""
    else:
        system_prompt = f"""You are Naima, a kind and patient virtual teacher. You help {niveau} students with {matiere}.

**YOUR STYLE:**
- You always use "you", "your" (friendly but professional)
- You are warm, encouraging, and pedagogical
- You sign your messages with "— Naima" or "Naima ✨"
- You always ask guiding questions one at a time
- You NEVER give the answer directly
- You correct gently without criticism

**YOUR MISSION FOR THIS RESPONSE:**
Last question you asked: "{derniere_q}"
Student's answer: "{reponse}"

1. Analyze the student's response
2. If correct: praise them and ask the next step
3. If partially correct: acknowledge what's good, guide to correct
4. If incorrect: don't say "that's wrong", guide with a hint
5. Ask ONLY ONE new question to advance their thinking

**YOUR RESPONSE FORMAT:**
- Reaction to student's answer (praise/guidance)
- Very brief explanation if needed
- New precise question
- Signature: — Naima ✨

**EXAMPLE:**
"Great, you correctly identified the first term! Now, look at the second one: what operation do you see?

— Naima ✨"""
    
    prompt = f"""**Historique de conversation ({matiere}) :**
{historique_text}

**Contexte :** Élève de {niveau} en {matiere}
{"**Mode examen :** guide avec des indices, ne révèle pas les étapes complètes." if mode_examen else ""}"""
    
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=500
        )
        
        reponse_naima = response.choices[0].message.content.strip()
        
        # S'assurer que Naima signe sa réponse
        if langue == "fr":
            if "— Naima" not in reponse_naima and "Naima" not in reponse_naima[-10:]:
                reponse_naima = f"{reponse_naima}\n\n— Naima ✨"
        else:
            if "— Naima" not in reponse_naima and "Naima" not in reponse_naima[-10:]:
                reponse_naima = f"{reponse_naima}\n\n— Naima ✨"
        
        return reponse_naima
        
    except Exception as e:
        print(f"Erreur génération suite conversation Naima: {e}")
        # Fallback bilingue avec Naima qui tutoie
        if langue == "fr":
            return f"""Merci pour ta réponse ! C'est intéressant de voir comment tu as abordé cette question de {matiere}.

Je vois que tu as fait un premier pas, et c'est déjà très bien. Maintenant, pour t'aider à avancer :

**Ma nouvelle question :** As-tu considéré toutes les informations données dans l'énoncé ? Y a-t-il un élément que tu n'as pas encore utilisé ?

Prends ton temps, je suis là pour t'accompagner.

— Naima ✨"""
        else:
            return f"""Thank you for your answer! It's interesting to see how you approached this {matiere} question.

I see you've taken a first step, and that's already great. Now, to help you move forward:

**My new question:** Have you considered all the information given in the statement? Is there an element you haven't used yet?

Take your time, I'm here to support you.

— Naima ✨"""


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
    """Nouvel exercice avec Naima - réinitialise COMPLÈTEMENT"""
    print(f"[DEBUG] Nouvel exercice - Session keys: {list(session.keys())}")
    print(f"[DEBUG] Eleve ID: {session.get('eleve_id')}")
    
    if "eleve_id" not in session:
        print("[DEBUG] REDIRECT: Pas d'eleve_id dans la session")
        return redirect(url_for("login_eleve"))
    
    # IMPORTANT: Sauvegarder les données essentielles de session
    eleve_id = session.get('eleve_id')
    lang = session.get('lang', 'fr')
    
    # Vider TOUTE la session liée à la conversation SEULEMENT
    session_keys_to_remove = [
        "conversation", 
        "derniere_q_ia", 
        "exercice_en_cours",
        "mode_examen"
    ]
    
    for key in session_keys_to_remove:
        value = session.pop(key, None)
        print(f"[DEBUG] Supprimé de session: {key} = {value}")
    
    # IMPORTANT: Re-sauvegarder les données essentielles
    session['eleve_id'] = eleve_id
    session['lang'] = lang
    session.modified = True  # Force la sauvegarde
    
    # Flash message personnalisé avec Naima
    if lang == "fr":
        flash("✨ Naima est prête pour une nouvelle conversation ! Pose-lui ta question.", "success")
    else:
        flash("✨ Naima is ready for a new conversation! Ask her your question.", "success")
    
    # Rediriger avec un timestamp pour éviter le cache
    import time
    redirect_url = url_for("enseignant_virtuel") + f"?t={int(time.time())}"
    print(f"[DEBUG] Redirection vers: {redirect_url}")
    
    return redirect(redirect_url)


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

@app.route("/admin/supprimer-test/<int:test_id>", methods=["POST"])
def supprimer_test(test_id):
    test = TestSommatif.query.get_or_404(test_id)
    db.session.delete(test)
    db.session.commit()
    
    # Si la requête vient d'AJAX, ne fais pas de redirection
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return '', 204  # No Content
    
    return redirect(url_for("liste_tests"))



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
    
    if request.method == "POST":
        nom = request.form.get("nom")
        email = request.form.get("email")
        mot_de_passe = request.form.get("mot_de_passe")
        confirm_password = request.form.get("confirm_password")

        # Validation basique
        if not all([nom, email, mot_de_passe, confirm_password]):
            flash("Tous les champs sont requis" if lang == 'fr' else "All fields are required", "error")
            return render_template("inscription_enseignant.html", lang=lang)

        # Vérifier la confirmation du mot de passe
        if mot_de_passe != confirm_password:
            flash("Les mots de passe ne correspondent pas" if lang == 'fr' else "Passwords do not match", "error")
            return render_template("inscription_enseignant.html", lang=lang)

        # Vérifier la longueur du mot de passe
        if len(mot_de_passe) < 8:
            flash("Le mot de passe doit contenir au moins 8 caractères" if lang == 'fr' else "Password must be at least 8 characters", "error")
            return render_template("inscription_enseignant.html", lang=lang)

        # Vérifier si l'email existe déjà
        existing_user = User.query.filter_by(email=email.strip()).first()
        if existing_user:
            flash("Un utilisateur avec cet email existe déjà." if lang == 'fr' else "A user with this email already exists.", "error")
            return render_template("inscription_enseignant.html", lang=lang)

        try:
            # Créer l'utilisateur enseignant
            new_teacher = User(
                username=email.strip().split('@')[0],  # Utilise la partie avant @ comme username
                nom_complet=nom.strip(),
                email=email.strip(),
                role="enseignant",
                statut="actif",
                statut_paiement="exempt",  # Enseignants n'ont pas besoin de payer
                inscrit_par_admin=False,
                langue=lang,
                date_inscription=datetime.utcnow(),
                email_verifie=False,
                accepte_cgu=True,
                date_acceptation_cgu=datetime.utcnow()
            )
            
            # Définir le mot de passe (le setter le hache automatiquement)
            new_teacher.mot_de_passe = mot_de_passe
            
            db.session.add(new_teacher)
            db.session.commit()

            # Envoyer un email de bienvenue (optionnel)
            # send_welcome_email(new_teacher.email, new_teacher.nom_complet, lang)
            
            flash(
                "Inscription réussie ! Veuillez contacter le support à info@advanceteach.com pour vous connecter à vos élèves." 
                if lang == 'fr' else 
                "Registration successful! Please contact support at info@advanceteach.com to connect with your students.", 
                "success"
            )
            
            # Rediriger vers la page de connexion
            return redirect(url_for("login_enseignant", lang=lang))

        except Exception as e:
            db.session.rollback()
            print(f"Erreur inscription enseignant: {e}")
            flash(
                f"Erreur lors de l'inscription: {str(e)}" 
                if lang == 'fr' else 
                f"Registration error: {str(e)}", 
                "error"
            )
            return render_template("inscription_enseignant.html", lang=lang)

    # GET request - rendre le template avec la langue
    return render_template("inscription_enseignant.html", lang=lang)

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
    # Vérifier si l'utilisateur est connecté comme enseignant
    if "user_id" not in session:
        return redirect(url_for("login_enseignant"))  # ✅ CORRIGÉ
    
    if session.get("role") != "enseignant":
        flash("Accès réservé aux enseignants", "error")
        return redirect(url_for("login_enseignant"))  # ✅ CORRIGÉ
    
    try:
        UserModel = get_user_model()
        
        # Récupérer l'enseignant
        enseignant = UserModel.query.filter_by(
            id=session["user_id"],
            role="enseignant"
        ).first()
        
        if not enseignant:
            flash("Enseignant non trouvé", "error")
            return redirect(url_for("login_enseignant"))  # ✅ CORRIGÉ
        
        if request.method == "POST":
            ancien = request.form.get("ancien_mdp", "").strip()
            nouveau = request.form.get("nouveau_mdp", "").strip()
            confirmation = request.form.get("confirmation_mdp", "").strip()

            # Validation
            if not ancien:
                flash("Veuillez entrer votre mot de passe actuel", "error")
                return render_template(
                    "changer_mot_de_passe.html", 
                    enseignant=enseignant,
                    lang=session.get('lang', 'fr')
                )
            
            if not nouveau:
                flash("Veuillez entrer un nouveau mot de passe", "error")
                return render_template(
                    "changer_mot_de_passe.html", 
                    enseignant=enseignant,
                    lang=session.get('lang', 'fr')
                )
            
            if len(nouveau) < 6:
                flash("Le mot de passe doit contenir au moins 6 caractères", "error")
                return render_template(
                    "changer_mot_de_passe.html", 
                    enseignant=enseignant,
                    lang=session.get('lang', 'fr')
                )
            
            # Vérifier l'ancien mot de passe
            if not enseignant.verifier_mot_de_passe(ancien):
                flash("Mot de passe actuel incorrect", "error")
                return render_template(
                    "changer_mot_de_passe.html", 
                    enseignant=enseignant,
                    lang=session.get('lang', 'fr')
                )

            # Vérifier la confirmation
            if nouveau != confirmation:
                flash("Les nouveaux mots de passe ne correspondent pas", "error")
                return render_template(
                    "changer_mot_de_passe.html", 
                    enseignant=enseignant,
                    lang=session.get('lang', 'fr')
                )

            # Changer le mot de passe
            enseignant.mot_de_passe = nouveau
            db.session.commit()
            
            flash("✅ Mot de passe mis à jour avec succès !", "success")
            
            # ✅ REDIRECTION CORRIGÉE VERS LE BON ENDPOINT
            return redirect(url_for('dashboard_enseignant'))  # ← C'EST ÇA LA CORRECTION !

        # GET: Afficher le formulaire
        return render_template(
            "changer_mot_de_passe.html", 
            enseignant=enseignant,
            lang=session.get('lang', 'fr')
        )
        
    except Exception as e:
        logger.error(f"Erreur changement mot de passe enseignant: {e}")
        flash("Erreur lors du changement de mot de passe", "error")
        # ✅ REDIRECTION CORRIGÉE ICI AUSSI
        return redirect(url_for('dashboard_enseignant'))  # ← CORRIGÉ
    

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
    from models import Niveau, User, Parent, ParentEleve, Enseignant, db
    from datetime import datetime, timedelta
    
    form = InscriptionEleveForm()
    
    # Remplir les choix de niveau
    niveaux = Niveau.query.all()
    form.niveau.choices = [(n.id, n.nom) for n in niveaux]
    
    if request.method == 'POST' and form.validate_on_submit():
        # Récupérer l'option choisie
        payment_option = request.form.get('payment_option', 'trial')
        plan_type = request.form.get('plan_type', 'monthly')
        
        # Récupérer l'email de l'enseignant tuteur (optionnel)
        teacher_email = request.form.get('teacher_email')
        teacher_tutor = None
        
        print(f"📋 Option: {payment_option}, Plan: {plan_type}, Teacher Email: {teacher_email}")
        
        # Vérifier les doublons
        if User.query.filter_by(email=form.email.data).first():
            flash("Cet email est déjà utilisé", "error")
            return render_template("inscription_eleve.html", form=form, lang=session.get('lang', 'fr'))
        
        if User.query.filter_by(username=form.username.data).first():
            flash("Ce nom d'utilisateur est déjà utilisé", "error")
            return render_template("inscription_eleve.html", form=form, lang=session.get('lang', 'fr'))
        
        # Vérifier si un enseignant est spécifié
        if teacher_email and teacher_email.strip():
            # Valider le format d'email
            import re
            email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            if not re.match(email_regex, teacher_email.strip()):
                flash("Format d'email enseignant invalide", "error")
                return render_template("inscription_eleve.html", form=form, lang=session.get('lang', 'fr'))
            
            # ✅ CORRECTION 1 : Rechercher l'enseignant dans User (modèle unifié)
            # Chercher d'abord dans User (si vous avez migré)
            teacher_tutor = User.query.filter_by(
                email=teacher_email.strip(), 
                role="enseignant"
            ).first()
            
            # ✅ CORRECTION 2 : Fallback sur l'ancien modèle Enseignant si besoin
            if not teacher_tutor:
                teacher_tutor_old = Enseignant.query.filter_by(email=teacher_email.strip()).first()
                if teacher_tutor_old:
                    # Convertir l'ancien enseignant en User si nécessaire
                    flash("Enseignant trouvé dans l'ancien système", "info")
                    teacher_tutor = None  # Vous devriez migrer cet enseignant
            
            if not teacher_tutor:
                flash("Enseignant non trouvé avec cet email. Assurez-vous que l'enseignant est inscrit sur la plateforme.", "warning")
                # Continuer sans enseignant
                teacher_tutor = None
        
        # Récupérer les données du parent
        parent_nom_complet = request.form.get('parent_nom_complet')
        parent_email = request.form.get('parent_email')
        parent_telephone = request.form.get('parent_telephone')
        parent_telephone2 = request.form.get('parent_telephone2')
        include_parent = request.form.get('include_parent', 'on') == 'on'
        
        # ✅ CORRECTION 3 : Création de l'élève avec les bons noms de colonnes
        try:
            eleve = User(
                username=form.username.data,
                nom_complet=form.nom_complet.data,
                email=form.email.data,
                niveau_id=form.niveau.data,
                role="eleve",  # ✅ CORRECTION : "eleve" pas "élève" (minuscule)
                telephone=form.telephone.data,
                statut="actif",
                statut_paiement="essai_gratuit",
                inscrit_par_admin=False,
                accepte_cgu=form.accepte_cgu.data,
                date_acceptation_cgu=datetime.utcnow() if form.accepte_cgu.data else None,
                langue=session.get('lang', 'fr'),
                # ✅ CORRECTION : enseignant_referent_id pas enseignant_id
                enseignant_referent_id=teacher_tutor.id if teacher_tutor else None
            )
            
            eleve.mot_de_passe = form.mot_de_passe.data
            
            db.session.add(eleve)
            db.session.flush()
            
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
                # ✅ CORRECTION 4 : Vérifier si la méthode existe
                if hasattr(eleve, 'activer_essai_gratuit'):
                    eleve.activer_essai_gratuit(72)  # 72 heures = 3 jours
                else:
                    # Fallback si la méthode n'existe pas
                    eleve.statut_essai = 'actif'
                    eleve.date_fin_essai = datetime.utcnow() + timedelta(hours=72)
                
                db.session.commit()
                
                # ✅ CORRECTION 5 : Connexion avec les bons noms de session
                session['user_id'] = eleve.id  # ✅ Pas 'eleve_id'
                session['username'] = eleve.username  # ✅ Pas 'eleve_username'
                session['nom_complet'] = eleve.nom_complet  # ✅ Pas 'eleve_nom_complet'
                session['role'] = 'eleve'  # ✅ Pas 'élève'
                session['lang'] = eleve.langue if eleve.langue else 'fr'
                
                # Notifier l'enseignant si assigné
                if teacher_tutor:
                    try:
                        print(f"📧 Élève {eleve.nom_complet} assigné à l'enseignant {teacher_tutor.nom_complet}")
                    except Exception as e:
                        print(f"⚠️ Erreur notification enseignant: {e}")
                
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
                    
                    # CONFIGURATION DES PLANS
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
                    
                    # ✅ CORRECTION 6 : Créer le customer Stripe pour cet élève
                    stripe_customer = None
                    try:
                        # Créer ou récupérer le customer Stripe
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
                    
                    # Créer la session checkout
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
                    print(f"📝 Plan: {plan_type}, Montant: {plan_info['amount']/100}$ CAD")
                    
                    return redirect(checkout_session.url)
                    
                except Exception as e:
                    print(f"❌ Erreur Stripe: {e}")
                    import traceback
                    traceback.print_exc()
                    
                    # En cas d'erreur Stripe, offrir l'essai gratuit
                    if hasattr(eleve, 'activer_essai_gratuit'):
                        eleve.activer_essai_gratuit(72)
                    
                    db.session.commit()
                    
                    # Connexion automatique
                    session['user_id'] = eleve.id
                    session['username'] = eleve.username
                    session['nom_complet'] = eleve.nom_complet
                    session['role'] = 'eleve'
                    
                    # Nettoyer les sessions
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
    return render_template("inscription_eleve.html", form=form, lang=lang)


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
    """Route pour changer le mot de passe - Adaptée au nouveau système User"""
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

    if request.method == "POST":
        ancien = request.form.get("ancien_mdp")
        nouveau = request.form.get("nouveau_mdp")
        confirmation = request.form.get("confirmation_mdp")

        if not enseignant.verifier_mot_de_passe(ancien):
            flash("Mot de passe actuel incorrect.", "error")
        elif nouveau != confirmation:
            flash("Les nouveaux mots de passe ne correspondent pas.", "error")
        elif len(nouveau) < 6:
            flash("Le mot de passe doit contenir au moins 6 caractères.", "error")
        else:
            # Utiliser la méthode de hachage appropriée
            enseignant.mot_de_passe = generate_password_hash(nouveau)
            db.session.commit()
            flash("Mot de passe mis à jour avec succès.", "success")
            return redirect(url_for("dashboard_enseignant"))

    return render_template("changer_mot_de_passe.html", 
                         enseignant=enseignant,
                         lang=session.get("lang", "fr"))

@app.route("/enseignant/modifier-profil", methods=["GET", "POST"])
def modifier_profil_enseignant():
    """Modifier le profil enseignant"""
    # Vérifier si l'utilisateur est connecté
    if "user_id" not in session:
        return redirect(url_for("login_enseignant"))  # ✅ CORRIGÉ (au lieu de "login")
    
    # Vérifier si c'est un enseignant
    if session.get("role") != "enseignant":
        flash("Accès réservé aux enseignants", "error")
        return redirect(url_for("login_enseignant"))  # ✅ CORRIGÉ (au lieu de "/")
    
    UserModel = get_user_model()
    enseignant = UserModel.query.get(session["user_id"])
    
    if not enseignant or enseignant.role != "enseignant":
        flash("Enseignant non trouvé", "error")
        return redirect(url_for("login_enseignant"))  # ✅ CORRIGÉ (au lieu de "login")

    if request.method == "POST":
        nom = request.form.get("nom")
        email = request.form.get("email")
        
        # Vérification des champs obligatoires
        if not nom or not email:
            flash("Le nom et l'email sont obligatoires", "error")
            return redirect(url_for("modifier_profil_enseignant"))

        # Vérifier si l'email est déjà utilisé par un autre utilisateur
        existant = UserModel.query.filter(
            UserModel.email == email,
            UserModel.id != enseignant.id
        ).first()
        
        if existant:
            flash("Cet email est déjà utilisé par un autre compte", "error")
            return redirect(url_for("modifier_profil_enseignant"))

        # Mettre à jour les informations
        enseignant.nom_complet = nom
        enseignant.email = email
        
        # Téléphone optionnel
        telephone = request.form.get("telephone")
        if telephone:
            enseignant.telephone = telephone
        
        db.session.commit()
        flash("✅ Profil mis à jour avec succès", "success")
        return redirect(url_for("dashboard_enseignant"))  # ✅ DÉJÀ BON !

    return render_template("modifier_profil_enseignant.html", 
                         enseignant=enseignant, 
                         lang=session.get("lang", "fr"))


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
    # Vérifier que l'enseignant est connecté
    if "user_id" not in session:
        flash("Veuillez vous connecter", "error")
        return redirect(url_for("login_enseignant"))
    
    if session.get("role") != "enseignant":
        flash("Accès réservé aux enseignants", "error")
        return redirect(url_for("login_enseignant"))
    
    try:
        # Récupérer l'ID de l'utilisateur connecté
        user_id = session["user_id"]
        
        # Récupérer toutes les remédiations en attente
        suggestions = RemediationSuggestion.query \
            .join(User, User.id == RemediationSuggestion.user_id) \
            .filter(RemediationSuggestion.statut == "en_attente") \
            .filter(User.enseignant_referent_id == user_id) \
            .order_by(RemediationSuggestion.timestamp.desc()) \
            .all()
        
        total_en_attente = len(suggestions)
        lang = session.get("lang", "fr")
        
        return render_template(
            "remediations_en_attente.html",
            suggestions=suggestions,
            total_en_attente=total_en_attente,
            lang=lang
        )
        
    except Exception as e:
        print(f"Erreur dans remediations_en_attente: {e}")
        flash("Une erreur est survenue", "error")
        return redirect(url_for("dashboard_enseignant"))


@app.route("/enseignant/valider-remediation/<int:remediation_id>", methods=["GET", "POST"])
def valider_remediation(remediation_id):
    # ✅ CORRECTION : utiliser "user_id"
    if "user_id" not in session or session.get("role") != "enseignant":
        return redirect(url_for("login_enseignant"))

    lang = session.get("lang", "fr")
    suggestion = RemediationSuggestion.query.get_or_404(remediation_id)
    
    # ✅ Vérifier que l'élève appartient bien à cet enseignant
    if suggestion.user.enseignant_referent_id != session["user_id"]:
        flash("Accès non autorisé", "error")
        return redirect(url_for("remediations_a_valider"))

    if request.method == "POST":
        message = request.form.get("message")
        question = request.form.get("question")
        reponse = request.form.get("reponse")
        explication = request.form.get("explication")

        if lang == "en":
            bloc = f"""Remediation:\n- Question: {question}\n- Expected answer: {reponse}\n- Explanation: {explication}"""
        else:
            bloc = f"""Remédiation :\n- Question : {question}\n- Réponse attendue : {reponse}\n- Explication : {explication}"""

        suggestion.message = message
        suggestion.exercice_suggere = bloc
        suggestion.statut = "valide"
        db.session.commit()

        flash("✅ Remédiation validée avec succès", "success")
        return redirect(url_for("remediations_a_valider"))

    # Parser l'existant
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
    # ✅ CORRECTION : utiliser "user_id"
    if "user_id" not in session or session.get("role") != "enseignant":
        return redirect(url_for("login_enseignant"))

    enseignant_id = session["user_id"]  # ✅ CORRIGÉ
    niveau_filtre = request.args.get("niveau")
    statut_filtre = request.args.get("statut", "en_attente")

    query = RemediationSuggestion.query \
        .join(User, RemediationSuggestion.user_id == User.id) \
        .options(joinedload(RemediationSuggestion.user).joinedload(User.niveau)) \
        .filter(User.enseignant_referent_id == enseignant_id)  # ✅ CORRIGÉ

    if niveau_filtre:
        query = query.filter(User.niveau.has(nom=niveau_filtre))
    
    if statut_filtre != "tous":
        query = query.filter(RemediationSuggestion.statut == statut_filtre)
    else:
        query = query.filter(RemediationSuggestion.statut != "supprime")

    suggestions = query.order_by(RemediationSuggestion.timestamp.desc()).all()

    niveaux = db.session.query(Niveau.nom).distinct().all()
    statuts = ["en_attente", "valide", "tous"]

    return render_template(
        "enseignant_remediations_validation.html",
        suggestions=suggestions,
        niveaux=[n[0] for n in niveaux],
        niveau_filtre=niveau_filtre,
        statut_filtre=statut_filtre,
        statuts=statuts,
        lang=session.get("lang", "fr")
    )


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


@app.route("/dashboard-enseignant", methods=["GET", "POST"])
def dashboard_enseignant():
    """Dashboard enseignant - version complète"""
    try:
        # Vérifier connexion et rôle
        if "user_id" not in session:
            return redirect(url_for("login_enseignant"))

        if session.get("role") != "enseignant":
            flash("Accès réservé aux enseignants", "error")
            return redirect("/")

        enseignant = User.query.get(session["user_id"])
        if not enseignant or not enseignant.est_enseignant():
            flash("Enseignant non trouvé", "error")
            return redirect(url_for("login_enseignant"))

        # Gestion langue
        if request.method == "POST":
            selected_lang = request.form.get("lang")
            if selected_lang in ["fr", "en"]:
                session["lang"] = selected_lang
            return redirect(url_for("dashboard_enseignant"))

        lang = session.get("lang", "fr")

        # -----------------------------
        # Récupérer élèves
        # -----------------------------
        eleves = enseignant.get_eleves_encadres()
        total_students = len(eleves)

        # -----------------------------
        # Statistiques élèves
        # -----------------------------
        all_stars = []
        stats, noms_eleves, moyennes, niveau_counts = [], [], [], {}

        for e in eleves:
            try:
                reponses = StudentResponse.query.filter_by(user_id=e.id).all()
                etoiles_vals = [r.etoiles for r in reponses if r.etoiles is not None]
                moyenne = round(sum(etoiles_vals) / len(etoiles_vals), 2) if etoiles_vals else 0
                if etoiles_vals:
                    all_stars.append(moyenne)

                niveau_nom = e.niveau.nom if e.niveau else "Non défini"

                stats.append({
                    "nom": e.nom_complet,
                    "username": e.username,
                    "niveau": niveau_nom,
                    "moyenne": moyenne,
                    "total": len(etoiles_vals)
                })

                noms_eleves.append(e.nom_complet[:15])
                moyennes.append(moyenne if moyenne <= 3 else 3)
                niveau_counts[niveau_nom] = niveau_counts.get(niveau_nom, 0) + 1
            except Exception as ex:
                print(f"Erreur stats élève {e.id}: {ex}")
                continue

        avg_stars = round(sum(all_stars) / len(all_stars), 1) if all_stars else 0
        niveaux = list(niveau_counts.keys())
        counts = list(niveau_counts.values())

        # -----------------------------
        # Remédiations en attente
        # -----------------------------
        nv_count = 0
        try:
            eleves_ids = [e.id for e in eleves]
            if eleves_ids:
                nv_count = RemediationSuggestion.query \
                    .filter(RemediationSuggestion.user_id.in_(eleves_ids),
                            RemediationSuggestion.statut == "en_attente") \
                    .count()
        except:
            nv_count = 0

        # -----------------------------
        # Commissions
        # -----------------------------
        try:
            commissions = Commission.query.filter_by(enseignant_id=enseignant.id).all()
            total_commissions = sum(c.montant_commission for c in commissions if c.statut != 'cancelled')
            commissions_pending = sum(1 for c in commissions if c.statut == 'pending')
            commissions_paid = sum(c.montant_commission for c in commissions if c.statut == 'paid')
            commissions_available = sum(c.montant_commission for c in commissions if c.statut == 'pending')
            info_versement = InfoVersementEnseignant.query.filter_by(enseignant_id=enseignant.id).first()
            interac_configure = bool(info_versement and info_versement.email_interac)
        except:
            total_commissions = commissions_pending = commissions_paid = commissions_available = 0
            interac_configure = False

        # -----------------------------
        # Élèves payants / essai
        # -----------------------------
        eleves_payants = eleves_essai = 0
        for e in eleves:
            statut = getattr(e, "statut_paiement", "")
            if statut == "paye":
                eleves_payants += 1
            elif statut == "essai_gratuit":
                eleves_essai += 1
            else:
                eleves_payants += 1

        # -----------------------------
        # Exercices par matière/leçon
        # -----------------------------
        matieres = get_exercices_par_enseignant_for_template(enseignant, lang)

        # -----------------------------
        # Rendu final
        # -----------------------------
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
            matieres=matieres
        )

    except Exception as e:
        print(f"Erreur dashboard_enseignant: {e}")
        flash("Une erreur est survenue sur le dashboard.", "error")
        return redirect("/")






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
    username = request.args.get("username")
    lang = request.args.get("lang", "fr")

    # 1. Récupérer l'élève avec ses relations optimisées
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

    # 2. Récupérer les exercices complétés par l'élève (UNE SEULE REQUÊTE)
    completed_exercises = StudentResponse.query.filter_by(user_id=eleve.id)\
        .with_entities(StudentResponse.exercice_id).all()
    completed_exercise_ids = {ex[0] for ex in completed_exercises if ex[0]}
    
    # 3. Récupérer les tests complétés
    completed_tests = TestResponse.query.filter_by(user_id=eleve.id)\
        .with_entities(TestResponse.test_id).all()
    completed_test_ids = {test[0] for test in completed_tests if test[0]}

    # 4. Organiser les données par matière avec statistiques
    matiere_data = {}
    unites_list = []
    lecons_filtrees = []

    for matiere in eleve.niveau.matieres:
        matiere_nom = matiere.nom_en if lang == 'en' and matiere.nom_en else matiere.nom
        
        if matiere_nom not in matiere_data:
            matiere_data[matiere_nom] = {
                'matiere_obj': matiere,
                'unites': [],
                'stats': {
                    'total_unites': 0,
                    'total_lecons': 0,
                    'total_exercises': 0,
                    'completed_exercises': 0
                }
            }
        
        for unite in matiere.unites:
            unites_list.append(unite)
            
            # Statistiques pour cette unité
            unit_stats = {
                'unite': unite,
                'total_lecons': len(unite.lecons),
                'total_exercises': 0,
                'completed_exercises': 0,
                'tests': [],
                'lecons': []
            }
            
            # Marquer les tests comme complétés ou non
            for test in unite.tests:
                test.completed = test.id in completed_test_ids
                unit_stats['tests'].append(test)
            
            for lecon in unite.lecons:
                total_exos = len(lecon.exercices)
                
                # Calculer les exercices complétés pour cette leçon
                completed_count = 0
                for exercice in lecon.exercices:
                    if exercice.id in completed_exercise_ids:
                        completed_count += 1
                
                # Ajouter aux statistiques
                lecon_stats = {
                    'lecon': lecon,
                    'total_exercises': total_exos,
                    'completed_exercises': completed_count,
                    'progress': (completed_count / total_exos * 100) if total_exos > 0 else 0
                }
                
                unit_stats['lecons'].append(lecon_stats)
                unit_stats['total_exercises'] += total_exos
                unit_stats['completed_exercises'] += completed_count
                
                # Filtrer les leçons avec exercices (pour compatibilité)
                if total_exos > 0:
                    lecons_filtrees.append(lecon)
            
            # Ajouter l'unité à la matière
            matiere_data[matiere_nom]['unites'].append(unit_stats)
            
            # Mettre à jour les totaux de la matière
            matiere_data[matiere_nom]['stats']['total_unites'] += 1
            matiere_data[matiere_nom]['stats']['total_lecons'] += unit_stats['total_lecons']
            matiere_data[matiere_nom]['stats']['total_exercises'] += unit_stats['total_exercises']
            matiere_data[matiere_nom]['stats']['completed_exercises'] += unit_stats['completed_exercises']
    
    print(f"✅ {len(unites_list)} unités trouvées")
    print(f"✅ {len(lecons_filtrees)} leçons avec exercices")
    print(f"✅ {len(matiere_data)} matières organisées")

    return render_template(
        "choisir_sequence.html",
        eleve=eleve,
        unites=unites_list,  # Gardé pour compatibilité
        lecons=lecons_filtrees,  # Gardé pour compatibilité
        matiere_data=matiere_data,  # NOUVEAU : données organisées
        completed_exercise_ids=completed_exercise_ids,
        completed_test_ids=completed_test_ids,
        lang=lang
    )

from functools import wraps

def eleve_required(f):
    """Décorateur pour vérifier qu'un élève est connecté ET a accès"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Vérifier la session
        if "user_id" not in session:
            return redirect(url_for("login_eleve"))
        
        if session.get("role") != "eleve":
            flash("Accès réservé aux élèves", "error")
            return redirect("/")
        
        # Vérifier si l'élève existe
        eleve = User.query.get(session["user_id"])
        if not eleve or eleve.role != "eleve":
            flash("Session invalide", "error")
            session.clear()
            return redirect(url_for("login_eleve"))
        
        # ✅ VÉRIFIER SI L'ÉLÈVE A ENCORE ACCÈS
        if not eleve.a_acces_plateforme():
            if hasattr(eleve, 'est_en_essai_gratuit') and eleve.essai_est_expire():
                flash("Votre essai gratuit a expiré. Veuillez souscrire à un abonnement.", "warning")
                return redirect(url_for("upgrade_options"))
            else:
                flash("Votre compte n'est pas actif. Contactez l'administrateur.", "error")
                return redirect(url_for("login_eleve"))
        
        return f(*args, **kwargs)
    return decorated_function


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
    """Dashboard élève"""
    # Vérifier si l'utilisateur est connecté
    if "user_id" not in session:  # CORRIGÉ: "user_id" au lieu de "eleve_id"
        return redirect(url_for("login_eleve"))
    
    # Vérifier si c'est un élève
    user_role = session.get("role")
    if user_role not in ["élève", "eleve"]:  # Accepter les deux formats
        flash("Accès réservé aux élèves", "error")
        return redirect(url_for("login_eleve"))
    
    eleve = User.query.options(db.joinedload(User.niveau)).get(session["user_id"])  # CORRIGÉ: "user_id"
    if not eleve or eleve.role not in ["élève", "eleve"]:
        flash("Élève non trouvé", "error")
        return redirect(url_for("login_eleve"))

    # 🚨 VÉRIFICATION ACCÈS - ESSAI GRATUIT EXPIRÉ
    if hasattr(eleve, 'essai_est_expire') and eleve.essai_est_expire() and eleve.statut_paiement != "paye":
        flash("Votre période d'essai gratuit de 48h est terminée. Veuillez choisir un abonnement pour continuer.", "warning")
        return redirect(url_for('upgrade_options'))

    # ✅ CORRECTION : Stocker pour l'enseignant virtuel
    session['current_student'] = eleve.username

    lang = request.args.get("lang") or session.get("lang", "fr")
    session["lang"] = lang

    # 🔔 Remédiations non vues
    remediations_non_lues = []
    try:
        remediations_non_lues = RemediationSuggestion.query.filter_by(
            user_id=eleve.id,
            statut="valide",
            vue_par_eleve=False
        ).order_by(RemediationSuggestion.timestamp.desc()).limit(1).all()
    except:
        pass

    # 📊 Statistiques
    from sqlalchemy.sql import func
    from sqlalchemy import and_
    import matplotlib.pyplot as plt
    import io
    import base64
    from datetime import datetime, timedelta
    
    reponses_eleve = []
    try:
        reponses_eleve = StudentResponse.query.filter_by(user_id=eleve.id).order_by(StudentResponse.timestamp).all()
    except:
        pass
    
    total_reponses = len(reponses_eleve)

    # 🔧 Corrige les valeurs None
    etoiles_values = [r.etoiles or 0 for r in reponses_eleve if r.etoiles is not None]
    moyenne_etoiles = sum(etoiles_values) / total_reponses if total_reponses else 0
    bonnes_reponses = sum(1 for e in etoiles_values if e >= 3)
    taux_reussite = round((bonnes_reponses / total_reponses) * 100, 1) if total_reponses else 0

    stats = {
        "total": total_reponses,
        "average": round(moyenne_etoiles, 1),
        "success": taux_reussite
    }

    # 📈 Courbe progression - MOYENNE PAR JOUR (AMÉLIORÉ)
    courbe_progression = None
    if reponses_eleve:
        try:
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

            # CRÉER LE GRAPHIQUE
            plt.style.use('seaborn-v0_8-whitegrid')
            
            # Augmenter la taille et la résolution
            fig = plt.figure(figsize=(8, 4), dpi=150)
            ax = fig.add_subplot(111)

            # Couleurs modernes
            primary_color = "#3498db"  # Bleu
            secondary_color = "#2ecc71"  # Vert
            text_color = "#2c3e50"
            grid_color = "#ecf0f1"

            titre = "Moyenne des Étoiles par Jour" if lang == "fr" else "Daily Average Stars"
            label_y = "Étoiles" if lang == "fr" else "Stars"

            # Tracer la courbe avec des lignes plus fines
            ax.plot(dates_formatees, moyennes_journalieres, 
                    marker="o", 
                    color=primary_color, 
                    linewidth=2.5, 
                    markersize=8,
                    markerfacecolor='white',
                    markeredgecolor=primary_color,
                    markeredgewidth=2,
                    alpha=0.9)
            
            # Ajouter une zone ombrée sous la courbe
            ax.fill_between(dates_formatees, moyennes_journalieres, 
                           alpha=0.1, color=primary_color)
            
            # Définir les limites et le style des axes
            ax.set_title(titre, fontsize=14, fontweight='bold', color=text_color, pad=15)
            ax.set_ylabel(label_y, fontweight='bold', fontsize=12, color=text_color)
            ax.set_ylim(0, 5.5)
            
            # Personnaliser les ticks
            ax.tick_params(axis='both', which='major', labelsize=10, colors=text_color)
            ax.tick_params(axis='x', rotation=45)
            
            # Améliorer la grille
            ax.grid(True, alpha=0.3, linestyle='--', linewidth=0.5, color=grid_color)
            
            # Ajouter les valeurs sur les points avec un style amélioré
            for i, (date, valeur) in enumerate(zip(dates_formatees, moyennes_journalieres)):
                ax.annotate(f'{valeur:.1f}', 
                           (date, valeur), 
                           textcoords="offset points", 
                           xytext=(0, 12), 
                           ha='center', 
                           fontsize=9,
                           fontweight='bold',
                           color=primary_color,
                           bbox=dict(boxstyle="round,pad=0.3", 
                                    facecolor='white', 
                                    edgecolor=primary_color,
                                    alpha=0.8))
            
            # Ajouter une ligne horizontale pour la moyenne générale
            moyenne_generale = stats["average"]
            ax.axhline(y=moyenne_generale, color=secondary_color, linestyle='--', 
                      linewidth=1.5, alpha=0.7, label=f'Moyenne: {moyenne_generale:.1f}')
            
            # Ajouter la légende
            ax.legend(loc='upper right', fontsize=10, framealpha=0.9)
            
            # Ajuster les marges
            fig.tight_layout(pad=3.0)
            
            # Sauvegarder avec une meilleure qualité
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=150, bbox_inches='tight', 
                       facecolor=fig.get_facecolor(), edgecolor='none')
            buf.seek(0)
            courbe_progression = base64.b64encode(buf.read()).decode('utf-8')
            buf.close()
            plt.close(fig)
            plt.style.use('default')  # Réinitialiser le style
        except Exception as e:
            print(f"Erreur création graphique: {e}")
            courbe_progression = None

    # ⏰ CALCUL TEMPS RESTANT ESSAI GRATUIT
    temps_restant = None
    pourcentage_temps_restant = 100
    total_seconds = 0
    
    if hasattr(eleve, 'est_en_essai_gratuit') and eleve.est_en_essai_gratuit() and hasattr(eleve, 'date_fin_essai') and eleve.date_fin_essai:
        maintenant = datetime.utcnow()
        if maintenant < eleve.date_fin_essai:
            temps_restant = eleve.date_fin_essai - maintenant
            total_seconds = int(temps_restant.total_seconds())
            
            # Calculer le pourcentage de temps restant
            if hasattr(eleve, 'date_inscription'):
                duree_totale = eleve.date_fin_essai - eleve.date_inscription
                temps_ecoule = maintenant - eleve.date_inscription
                
                if duree_totale.total_seconds() > 0:
                    pourcentage_temps_restant = max(0, min(100, 
                        100 - (temps_ecoule.total_seconds() / duree_totale.total_seconds() * 100)
                    ))

    # 🎯 OBJECTIFS DU JOUR
    remediations_completees = 0
    try:
        remediations_completees = RemediationSuggestion.query.filter(
            and_(
                RemediationSuggestion.user_id == eleve.id,
                RemediationSuggestion.statut == "valide",
                RemediationSuggestion.reponse_eleve.isnot(None)
            )
        ).count()
    except:
        pass

    # Créer les objectifs du jour
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
        'est_en_essai': hasattr(eleve, 'est_en_essai_gratuit') and eleve.est_en_essai_gratuit(),
        'est_paye': eleve.statut_paiement == "paye",
        'essai_expire': hasattr(eleve, 'essai_est_expire') and eleve.essai_est_expire(),
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
        objectifs_du_jour=objectifs_du_jour,
        progression_quotidienne=progression_quotidienne,
        remediations_completees=remediations_completees,
        date_du_jour=datetime.utcnow(),
        statut_paiement_info=statut_paiement_info
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
    print("=" * 80)
    print("🚨🚨🚨 EXERCICE SÉQUENTIEL - DÉBUT DE LA ROUTE")
    print(f"URL: {request.url}")
    print(f"GET params: {dict(request.args)}")
    print(f"Session: {dict(session)}")
    print(f"Session ID: {session.get('_id', 'no-id')}")
    print("=" * 80)
    
    # --------------------------------------------------
    # 1️⃣ Extraction des paramètres
    # --------------------------------------------------
    username = request.args.get("username")
    lecon_id = request.args.get("lecon_id")
    lang = request.args.get("lang", "fr")
    index = int(request.args.get("index", 0))
    show_feedback = request.args.get("show_feedback", "false").lower() == "true"

    print(f"🔍 Paramètres extraits:")
    print(f"  username: {username}")
    print(f"  lecon_id: {lecon_id}")
    print(f"  lang: {lang}")
    print(f"  index: {index}")
    print(f"  show_feedback: {show_feedback}")
    
    # Vérification des paramètres requis
    if not username or not lecon_id:
        print("❌ Paramètres manquants, redirection dashboard")
        flash("Paramètres manquants pour accéder à l'exercice.", "danger")
        return redirect(url_for("index", lang=lang))

    # --------------------------------------------------
    # 2️⃣ Récupération des données
    # --------------------------------------------------
    eleve = User.query.filter_by(username=username).first()
    if not eleve:
        print(f"❌ Élève non trouvé: {username}")
        flash("Élève non trouvé.", "danger")
        return redirect(url_for("index", lang=lang))
    
    print(f"✅ Élève trouvé: {eleve.nom_complet} (ID: {eleve.id})")
    print(f"  - Role: {eleve.role}")
    print(f"  - Statut: {eleve.statut}")
    print(f"  - Statut paiement: {eleve.statut_paiement}")

    # Vérifier l'accès
    print(f"🔐 Vérification accès plateforme...")
    if not eleve.a_acces_plateforme():
        print(f"⛔ Élève SANS accès plateforme!")
        print(f"  - est_actif(): {eleve.est_actif()}")
        print(f"  - est_en_essai_gratuit(): {eleve.est_en_essai_gratuit()}")
        flash("Accès refusé (abonnement ou essai expiré).", "danger")
        return redirect(url_for("dashboard_eleve", username=username, lang=lang))
    
    print(f"✅ Accès plateforme autorisé")

    lecon = db.session.get(Lecon, lecon_id)
    if not lecon:
        print(f"❌ Leçon non trouvée: {lecon_id}")
        flash("Leçon non trouvée.", "danger")
        return redirect(url_for("dashboard_eleve", username=username, lang=lang))
    
    print(f"✅ Leçon trouvée: {lecon.titre_fr} (ID: {lecon.id})")
    print(f"  - Unité: {lecon.unite.nom if lecon.unite else 'N/A'}")
    print(f"  - Matière: {lecon.unite.matiere.nom if lecon.unite and lecon.unite.matiere else 'N/A'}")

    # --------------------------------------------------
    # 3️⃣ Gestion de la progression
    # --------------------------------------------------
    # Récupérer tous les exercices de la leçon
    exercices = Exercice.query.filter_by(lecon_id=lecon.id).all()
    
    print(f"🔍 Recherche exercices pour leçon {lecon.id}...")
    print(f"  - Nombre d'exercices trouvés: {len(exercices)}")
    
    if not exercices:
        print(f"⚠️ Aucun exercice pour la leçon: {lecon_id}")
        flash("Aucun exercice disponible pour cette leçon.", "info")
        return redirect(url_for("dashboard_eleve", username=username, lang=lang))

    # Ajuster l'index si hors limites
    if index >= len(exercices):
        print(f"⚠️ Index {index} hors limites, ajustement à 0")
        index = 0
    
    exercice_actuel = exercices[index]
    print(f"✅ Exercice actuel: ID {exercice_actuel.id}")
    
    # --------------------------------------------------
    # 4️⃣ Récupération de la réponse précédente (si existante)
    # --------------------------------------------------
    reponse_existante = None
    feedback_data = None
    
    reponse = StudentResponse.query.filter_by(
        user_id=eleve.id,
        exercice_id=exercice_actuel.id
    ).first()
    
    if reponse:
        print(f"📝 Réponse existante trouvée pour exercice {exercice_actuel.id}")
        print(f"  - ID réponse: {reponse.id}")
        print(f"  - Étoiles: {reponse.etoiles}")
        reponse_existante = reponse.reponse_eleve
        
        # Parser le feedback JSON
        try:
            if reponse.analyse_ia and reponse.analyse_ia.startswith("{"):
                feedback_data = json.loads(reponse.analyse_ia)
                print(f"📊 Feedback chargé: {feedback_data.get('current_stars', 0)}/5 étoiles")
        except Exception as e:
            print(f"⚠️ Erreur parsing feedback: {e}")
            feedback_data = None
    else:
        print(f"📝 Aucune réponse existante pour cet exercice")

    # --------------------------------------------------
    # 5️⃣ Calcul de la progression
    # --------------------------------------------------
    total_exercices = len(exercices)
    exercices_completes = 0
    
    for ex in exercices:
        rep = StudentResponse.query.filter_by(
            user_id=eleve.id,
            exercice_id=ex.id
        ).first()
        if rep:
            exercices_completes += 1
    
    progression_pourcentage = int((exercices_completes / total_exercices) * 100) if total_exercices > 0 else 0
    
    print(f"📊 Progression: {exercices_completes}/{total_exercices} ({progression_pourcentage}%)")
    
    # --------------------------------------------------
    # 6️⃣ Préparation des données pour le template
    # --------------------------------------------------
    # Texte de l'exercice selon la langue
    question = exercice_actuel.question_en if lang == "en" else exercice_actuel.question_fr
    
    # Vérifier s'il y a un corrigé
    corrige_disponible = bool(exercice_actuel.reponse_en if lang == "en" else exercice_actuel.reponse_fr)
    
    # Données de feedback à afficher (si demandé)
    feedback_a_afficher = None
    if show_feedback and feedback_data:
        feedback_a_afficher = {
            "analyse": feedback_data.get("current_feedback", ""),
            "etoiles": feedback_data.get("current_stars", 0),
            "symbolic": feedback_data.get("symbolic_verification", {})
        }
        print(f"🎯 Feedback à afficher: {feedback_a_afficher['etoiles']}/5")

    # --------------------------------------------------
    # 7️⃣ Préparation des boutons navigation
    # --------------------------------------------------
    bouton_precedent = None
    bouton_suivant = None
    
    if index > 0:
        bouton_precedent = url_for(
            "exercice_sequentiel_progressif",
            username=username,
            lecon_id=lecon_id,
            lang=lang,
            index=index-1
        )
    
    if index < total_exercices - 1:
        bouton_suivant = url_for(
            "exercice_sequentiel_progressif",
            username=username,
            lecon_id=lecon_id,
            lang=lang,
            index=index+1
        )
    
    # Bouton terminer/retour au dashboard
    bouton_terminer = url_for("dashboard_eleve", username=username, lang=lang)

    # --------------------------------------------------
    # 8️⃣ Préparer les réponses status pour la navigation
    # --------------------------------------------------
    reponses_status = []
    for ex in exercices:
        rep = StudentResponse.query.filter_by(
            user_id=eleve.id,
            exercice_id=ex.id
        ).first()
        if rep:
            reponses_status.append('completed')
        else:
            reponses_status.append('not_started')
    
    print(f"📋 Status des réponses: {reponses_status}")

    # --------------------------------------------------
    # 9️⃣ DEBUG CRITIQUE - VÉRIFICATION DES VARIABLES
    # --------------------------------------------------
    print("=" * 80)
    print("🔍 DEBUG CRITIQUE - VARIABLES À PASSER AU TEMPLATE:")
    print(f"  eleve: {'✅ DÉFINI' if eleve else '❌ NON DÉFINI'}")
    print(f"     - username: {eleve.username if eleve else 'N/A'}")
    print(f"     - nom_complet: {eleve.nom_complet if eleve else 'N/A'}")
    print(f"  lecon: {'✅ DÉFINI' if lecon else '❌ NON DÉFINI'}")
    print(f"     - id: {lecon.id if lecon else 'N/A'}")
    print(f"     - titre: {lecon.titre_fr if lecon else 'N/A'}")
    print(f"  exercice: {'✅ DÉFINI' if exercice_actuel else '❌ NON DÉFINI'}")
    print(f"  total_exercices: {total_exercices}")
    print(f"  total (alias): {total_exercices}")
    print(f"  reponse: {'✅ DÉFINI' if reponse else '❌ NON DÉFINI'}")
    print(f"  reponses_status: {len(reponses_status)} éléments")
    print(f"  lang: {lang}")
    print("=" * 80)

    # --------------------------------------------------
    # 🔟 Affichage du template - TOUTES LES VARIABLES
    # --------------------------------------------------
    print(f"=== ✅ PRÊT POUR AFFICHAGE ===")
    print(f"Exercice {index+1}/{total_exercices}, Progression: {progression_pourcentage}%")
    print(f"Envoi du template exercice_sequentiel_progressif.html...")
    
    try:
        result = render_template(
            "exercice_sequentiel_progressif.html",
            # VARIABLES ESSENTIELLES POUR LE TEMPLATE :
            eleve=eleve,                    # ✅ L'objet User complet
            username=username,              # ✅ Le username aussi
            lecon=lecon,                    # ✅ L'objet Lecon complet
            exercice=exercice_actuel,       # ✅ L'exercice actuel
            index=index,                    # ✅ Index courant
            total=total_exercices,          # ✅ Pour range(total) dans le template
            total_exercices=total_exercices, # ✅ Pour compatibilité
            progression_pourcentage=progression_pourcentage,
            exercices_completes=exercices_completes,
            reponse_existante=reponse_existante,
            reponse=reponse,                # ✅ L'objet StudentResponse complet (peut être None)
            reponses_status=reponses_status, # ✅ Liste des status pour navigation rapide
            corrige_disponible=corrige_disponible,
            feedback=feedback_a_afficher,
            show_feedback=show_feedback,
            lang=lang,
            bouton_precedent=bouton_precedent,
            bouton_suivant=bouton_suivant,
            bouton_terminer=bouton_terminer
        )
        print("✅ Template rendu avec succès!")
        return result
        
    except Exception as e:
        print(f"🔥 ERREUR LORS DU RENDER TEMPLATE: {str(e)}")
        import traceback
        traceback.print_exc()
        
        # Fallback: retourner une page d'erreur simple
        return f"""
        <html>
        <head><title>Erreur Template</title></head>
        <body style="padding: 20px; font-family: Arial;">
            <h1>Erreur lors du chargement de l'exercice</h1>
            <p>Erreur: {str(e)}</p>
            <p>Variables disponibles:</p>
            <ul>
                <li>eleve: {eleve.username if eleve else 'Non défini'}</li>
                <li>lecon: {lecon.titre_fr if lecon else 'Non défini'}</li>
                <li>total_exercices: {total_exercices}</li>
            </ul>
            <p><a href="/dashboard-eleve?username={username}&lang={lang}">Retour au tableau de bord</a></p>
        </body>
        </html>
        """


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
        
        # 2. Récupérer l'exercice et les informations
        exercice = Exercice.query.get(reponse.exercice_id)
        eleve = User.query.get(reponse.user_id)
        
        if not exercice or not eleve:
            return jsonify({'success': False, 'message': 'Exercice ou élève non trouvé'})
        
        # 3. PRÉPARER LE PROMPT POUR L'IA - RÉÉVALUATION COMPLÈTE
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
                    if 'original' in analysis_json:
                        return analysis_json['original']
                    elif 'current_feedback' in analysis_json:
                        return analysis_json['current_feedback']
                except json.JSONDecodeError:
                    pass
            
            # Sinon retourner le texte brut
            return analysis_text
        
        analysis_text = extract_analysis_text(reponse.analyse_ia)
        
        if lang == 'en':
            prompt = f"""
RE-EVALUATE a student's answer considering their contestation arguments.

📘 ORIGINAL PROBLEM:
{question}

📜 STUDENT'S ORIGINAL ANSWER:
{reponse.reponse_eleve}

🎯 ORIGINAL AI CORRECTION (current grade: {reponse.etoiles}/5):
{analysis_text}

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
{analysis_text}

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
        print(f"Prompt: {prompt[:500]}...")  # Afficher les premiers 500 caractères
        
        # 4. APPEL À L'IA POUR RÉÉVALUATION
        try:
            from openai import OpenAI
            client = OpenAI(api_key="votre-clé-api-openai")
            
            chat_completion = client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            new_analysis = chat_completion.choices[0].message.content.strip()
            print("✅ Réévaluation IA reçue avec succès")
            
            # 5. EXTRACTION DE LA NOUVELLE NOTE
            new_stars = reponse.etoiles  # Par défaut, garder l'ancienne
            
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
                else:
                    # Dernier recours
                    match = re.search(r"\bgrade\s*:\s*(\d)\b", new_analysis, re.IGNORECASE)
                    if match:
                        new_stars = int(match.group(1))
                    else:
                        # Si pas trouvé, garder la note proposée par l'élève
                        new_stars = data.get('proposed_stars', reponse.etoiles)
                        print(f"⭐ Utilisation de la note proposée par l'élève: {new_stars}/5")
            
            # S'assurer que la note est entre 1 et 5
            new_stars = max(1, min(5, new_stars))
            
        except Exception as e:
            print(f"❌ Erreur lors de l'appel IA: {e}")
            import traceback
            traceback.print_exc()
            
            # Fallback aux règles simples
            new_stars = data.get('proposed_stars', reponse.etoiles)
            
            # Générer un message simple
            if lang == 'en':
                new_analysis = f"""
Contestation received and processed.

Student's arguments: {data.get('justification', 'No justification provided')}
Proposed grade: {new_stars}/5

Based on manual review, the grade has been adjusted to {new_stars}/5.
Please continue with your learning journey.
"""
            else:
                new_analysis = f"""
Contestation reçue et traitée.

Arguments de l'élève : {data.get('justification', 'Aucune justification fournie')}
Note proposée : {new_stars}/5

Suite à une revue manuelle, la note a été ajustée à {new_stars}/5.
Continuez votre parcours d'apprentissage.
"""
        
        # 6. METTRE À JOUR LA BASE DE DONNÉES
        # Créer un nouvel objet JSON avec l'historique
        updated_analysis = {
            "original": analysis_text,
            "contestation": {
                "date": datetime.now().isoformat(),
                "justification": data.get('justification', ''),
                "proposed_stars": data.get('proposed_stars', reponse.etoiles),
                "previous_stars": reponse.etoiles
            },
            "current_feedback": new_analysis,
            "current_stars": new_stars
        }
        
        reponse.analyse_ia = json.dumps(updated_analysis, ensure_ascii=False)
        reponse.etoiles = new_stars
        
        # Ajouter un timestamp de mise à jour
        reponse.date_modification = datetime.now()
        
        db.session.commit()
        print(f"✅ Base de données mise à jour. Nouvelle note: {new_stars}/5")
        
        # 7. PRÉPARER LA RÉPONSE
        stars_changed = new_stars != reponse.etoiles
        
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
        
        error_message = "Erreur interne du serveur" if lang == 'fr' else "Internal server error"
        return jsonify({
            'success': False, 
            'message': f'{error_message}: {str(e)}'
        })


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

@app.route("/soumettre-sequentiel", methods=["POST"])
def soumettre_sequentiel():
    print("=== 📝 SOUMISSION SÉQUENTIELLE AVEC SYMPY ===")
    print(f"🔍 DEBUG - Données du formulaire reçues: {dict(request.form)}")

    # --------------------------------------------------
    # 1️⃣ Données du formulaire avec validation
    # --------------------------------------------------
    username = request.form.get("username")
    lang = request.form.get("lang", "fr")
    lecon_id = request.form.get("lecon_id")
    exercice_id = request.form.get("exercice_id")
    reponse_eleve = request.form.get("reponse_eleve", "").strip()
    index_str = request.form.get("index", "0")
    
    # Validation et conversion de l'index
    try:
        index = int(index_str)
    except (ValueError, TypeError):
        print(f"⚠️ DEBUG - Index invalide '{index_str}', utilisation de 0")
        index = 0
    
    print(f"🔍 DEBUG - Paramètres extraits: username={username}, lang={lang}, lecon_id={lecon_id}, exercice_id={exercice_id}, index={index}")
    print(f"🔍 DEBUG - Réponse élève (premiers 100 chars): {reponse_eleve[:100]}...")

    # --------------------------------------------------
    # 2️⃣ Sécurité & accès (VERSION CORRIGÉE SANS first_or_404)
    # --------------------------------------------------
    eleve = User.query.filter_by(username=username).first()
    if not eleve:
        print(f"❌ DEBUG - Utilisateur non trouvé: {username}")
        flash("Utilisateur non trouvé.", "danger")
        return redirect(url_for("index", lang=lang))
    
    print(f"✅ DEBUG - Élève trouvé: {eleve.nom_complet} (ID: {eleve.id})")

    # Vérifier l'accès à la plateforme
    if not eleve.a_acces_plateforme():
        print(f"⛔ DEBUG - Élève sans accès: {username}")
        flash("Accès refusé (abonnement ou essai expiré).", "danger")
        return redirect(url_for("dashboard_eleve", username=username, lang=lang))

    # Récupérer leçon et exercice
    lecon = db.session.get(Lecon, lecon_id)
    exercice = db.session.get(Exercice, exercice_id)

    if not lecon or not exercice:
        print(f"❌ DEBUG - Leçon ou exercice introuvable: leçon_id={lecon_id}, exercice_id={exercice_id}")
        flash("Leçon ou exercice introuvable.", "danger")
        return redirect(url_for("dashboard_eleve", username=username, lang=lang))
    
    print(f"✅ DEBUG - Leçon trouvée: {lecon.titre_fr}")
    print(f"✅ DEBUG - Exercice trouvé: {exercice.id}")

    # Validation de la réponse
    if not reponse_eleve:
        print(f"⚠️ DEBUG - Réponse vide fournie")
        flash("Veuillez fournir une réponse.", "warning")
        return redirect(url_for(
            "exercice_sequentiel_progressif",
            username=username,
            lecon_id=lecon_id,
            lang=lang,
            index=index
        ))

    # --------------------------------------------------
    # 3️⃣ Récupération / création réponse
    # --------------------------------------------------
    reponse = StudentResponse.query.filter_by(
        user_id=eleve.id,
        exercice_id=exercice.id
    ).first()

    if reponse:
        print(f"📝 DEBUG - Réponse existante trouvée, mise à jour")
    else:
        print(f"📝 DEBUG - Nouvelle réponse à créer")

    question = exercice.question_en if lang == "en" else exercice.question_fr
    reponse_attendue = exercice.reponse_en if lang == "en" else exercice.reponse_fr

    # --------------------------------------------------
    # 4️⃣ VÉRIFICATION SYMBOLIQUE AVEC SYMPY (NOUVEAU)
    # --------------------------------------------------
    symbolic_result = None
    symbolic_correct = None
    symbolic_feedback = ""
    
    try:
        # Importe le vérificateur
        from sympy_engine import math_verifier
        
        # Effectue la vérification
        symbolic_result = math_verifier.verify_answer(
            student_answer=reponse_eleve,
            expected_answer=reponse_attendue,
            question=question
        )
        
        symbolic_correct = symbolic_result.get('is_correct', None)
        symbolic_feedback = math_verifier.get_symbolic_feedback(symbolic_result)
        
        print(f"✅ Vérification SymPy : {symbolic_result}")
        
    except Exception as e:
        print(f"⚠️ Erreur vérification SymPy : {e}")
        symbolic_result = {'verified': False, 'error': str(e)}
        symbolic_feedback = f"⚠️ Vérification SymPy non disponible : {str(e)[:100]}"

    # --------------------------------------------------
    # 5️⃣ PROMPT GPT — avec information SymPy
    # --------------------------------------------------
    symbolic_info = ""
    if symbolic_correct is not None:
        symbolic_info = f"""
🔬 **VÉRIFICATION MATHÉMATIQUE AUTOMATIQUE (SymPy) :** 
{symbolic_feedback}

---
"""
    
    prompt = f"""
Corrige la réponse d'un élève à un exercice scolaire.

📘 Énoncé :
{question}

📜 Réponse de l'élève :
{reponse_eleve}

{symbolic_info}

⭐ BARÈME SUR 5 (INTELLIGENT) :
5 : Réponse mathématiquement correcte ET raisonnement excellent
4 : Réponse correcte avec raisonnement presque parfait
3 : Réponse correcte mais raisonnement incomplet
2 : Réponse incorrecte mais certaines étapes sont justes
1 : Tentative mais réponse incorrecte
0 : Hors sujet / vide

🎯 CONSIGNES IMPORTANTES :
1. La vérification mathématique (SymPy) ci-dessus vous indique si la réponse est correcte
2. Même si la réponse est mathématiquement fausse, récompensez les bonnes étapes
3. Si la réponse est mathématiquement correcte, la note ne doit pas être inférieure à 3/5
4. Expliquez clairement les erreurs et donnez la méthode correcte

📤 Format de réponse :
Analyse :
[Analyse détaillée du raisonnement]
Note : X/5
Correction :
- Résolution complète : [Méthode pas à pas]
- Points d'amélioration : [Conseils spécifiques]
- Résultat final : [Réponse exacte]
""".strip()

    print(f"🤖 DEBUG - Envoi du prompt à GPT-4...")
    try:
        completion = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        analyse_ia = completion.choices[0].message.content.strip()
        print(f"✅ DEBUG - Réponse GPT-4 reçue ({len(analyse_ia)} caractères)")
    except Exception as e:
        analyse_ia = f"Erreur IA : {str(e)[:200]}"
        print(f"❌ DEBUG - Erreur GPT-4: {e}")

    # --------------------------------------------------
    # 6️⃣ Extraction de la note + ajustement intelligent
    # --------------------------------------------------
    etoiles_gpt = 0
    match = re.search(r"(Note|Score)\s*:\s*(\d)", analyse_ia, re.IGNORECASE)
    if match:
        etoiles_gpt = min(int(match.group(2)), 5)

    # 🎯 LOGIQUE D'AJUSTEMENT INTELLIGENT
    if symbolic_correct is not None:
        if symbolic_correct:  # Mathématiquement correct
            # Garantir un minimum de 3/5 pour une réponse correcte
            etoiles_finales = max(etoiles_gpt, 3)
            print(f"✅ Ajustement : {etoiles_gpt} → {etoiles_finales} (réponse correcte)")
        else:  # Mathématiquement incorrect
            # Limiter à maximum 2/5 si réponse incorrecte
            etoiles_finales = min(etoiles_gpt, 2)
            print(f"⚠️ Ajustement : {etoiles_gpt} → {etoiles_finales} (réponse incorrecte)")
    else:
        etoiles_finales = etoiles_gpt  # Garder la note GPT
    
    print(f"⭐ DEBUG - Note finale: {etoiles_finales}/5")

    # --------------------------------------------------
    # 7️⃣ Structuration JSON COMPLÈTE
    # --------------------------------------------------
    now = datetime.now(timezone.utc).isoformat()

    feedback_json = {
        "current_feedback": analyse_ia,
        "current_stars": etoiles_finales,
        "symbolic_verification": {
            "was_verified": symbolic_result.get('verified', False) if symbolic_result else False,
            "is_correct": symbolic_correct,
            "result": symbolic_result,
            "feedback": symbolic_feedback
        },
        "metadata": {
            "exercise_id": exercice.id,
            "student_id": eleve.id,
            "language": lang,
            "gpt_score": etoiles_gpt,
            "final_score": etoiles_finales,
            "updated_at": now,
            "correction_method": "hybrid_gpt_sympy",
            "exercise_type": symbolic_result.get('type', 'unknown') if symbolic_result else 'unknown'
        },
        "history": []
    }

    # Historique des contestations
    if reponse and reponse.analyse_ia and reponse.analyse_ia.startswith("{"):
        ancien = json.loads(reponse.analyse_ia)
        feedback_json["history"] = ancien.get("history", [])
        feedback_json["history"].append({
            "feedback": ancien.get("current_feedback", ""),
            "stars": ancien.get("current_stars", 0),
            "date": ancien.get("metadata", {}).get("updated_at", now)
        })
        print(f"📜 DEBUG - Historique des contestations ajouté")

    # --------------------------------------------------
    # 8️⃣ Sauvegarde DB
    # --------------------------------------------------
    feedback_str = json.dumps(feedback_json, ensure_ascii=False, indent=2)

    if reponse:
        reponse.reponse_eleve = reponse_eleve
        reponse.analyse_ia = feedback_str
        reponse.etoiles = etoiles_finales
        reponse.timestamp = datetime.now(timezone.utc)
        print(f"💾 DEBUG - Mise à jour de la réponse existante")
    else:
        reponse = StudentResponse(
            user_id=eleve.id,
            exercice_id=exercice.id,
            reponse_eleve=reponse_eleve,
            analyse_ia=feedback_str,
            etoiles=etoiles_finales,
            timestamp=datetime.now(timezone.utc)
        )
        db.session.add(reponse)
        print(f"💾 DEBUG - Création d'une nouvelle réponse")

    try:
        db.session.commit()
        print(f"✅ DEBUG - Base de données sauvegardée avec succès")
    except Exception as e:
        db.session.rollback()
        print(f"❌ DEBUG - Erreur base de données: {e}")
        flash("Erreur lors de la sauvegarde de votre réponse.", "danger")
        return redirect(url_for(
            "exercice_sequentiel_progressif",
            username=username,
            lecon_id=lecon_id,
            lang=lang,
            index=index
        ))

    # --------------------------------------------------
    # 9️⃣ Remédiation automatique intelligente
    # --------------------------------------------------
    if etoiles_finales < 3:
        # Message contextuel selon le type d'erreur
        if symbolic_correct is False:
            message = f"Erreur mathématique détectée ({etoiles_finales}/5). Réponse incorrecte."
        elif symbolic_correct is True and etoiles_finales < 3:
            message = f"Réponse correcte mais raisonnement incomplet ({etoiles_finales}/5)."
        elif etoiles_finales == 0:
            message = f"Réponse hors sujet ou vide ({etoiles_finales}/5)."
        else:
            message = f"Difficulté détectée ({etoiles_finales}/5)."
        
        suggestion = RemediationSuggestion(
            user_id=eleve.id,
            theme=exercice.theme,
            lecon=lecon.titre_fr,
            message=message,
            exercice_suggere=None,
            statut="en_attente",
            timestamp=datetime.now(timezone.utc)
        )
        db.session.add(suggestion)
        db.session.commit()
        print(f"📚 Remédiation proposée (note: {etoiles_finales}/5)")

    # --------------------------------------------------
    # 🔟 DEBUG ET REDIRECTION
    # --------------------------------------------------
    print(f"=== 🐛 DEBUG AVANT REDIRECTION ===")
    print(f"📌 Paramètres pour la redirection:")
    print(f"  - username: {username}")
    print(f"  - lecon_id: {lecon_id}")
    print(f"  - lang: {lang}")
    print(f"  - index: {index}")
    print(f"  - show_feedback: True")
    
    # Générer l'URL manuellement pour vérifier
    try:
        redirect_url = url_for(
            "exercice_sequentiel_progressif",
            username=username,
            lecon_id=lecon_id,
            lang=lang,
            index=index,
            show_feedback=True
        )
        print(f"🔗 URL générée: {redirect_url}")
    except Exception as e:
        print(f"❌ ERREUR lors de la génération de l'URL: {e}")
        # URL de secours
        redirect_url = f"/exercice-sequentiel-progressif?username={username}&lecon_id={lecon_id}&lang={lang}&index={index}&show_feedback=true"
        print(f"🔗 URL de secours: {redirect_url}")
    
    print(f"=== ✅ RÉPONSE SAUVEGARDÉE : {etoiles_finales}/5 ===")
    print(f"=== 📊 VÉRIFICATION SYMPY : {symbolic_correct} ===")
    
    # Vérifier que l'URL est valide
    if not redirect_url or 'error' in redirect_url.lower():
        print(f"⚠️ URL invalide détectée, redirection vers le dashboard")
        return redirect(url_for("dashboard_eleve", username=username, lang=lang))
    
    return redirect(redirect_url)

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
    
    # Si pas de username dans les paramètres, vérifier la session
    if not username:
        username = session.get("username")
    
    if not username:
        if lang == "fr":
            flash("Veuillez vous connecter pour accéder à l'historique", "warning")
        else:
            flash("Please log in to access history", "warning")
        return redirect(url_for("connexion_eleve"))
    
    exercice_id = request.args.get("exercice_id")
    lang = request.args.get("lang", "fr")

    eleve = User.query.filter_by(username=username).first()
    if not eleve:
        if lang == "fr":
            flash(f"Élève {username} introuvable", "danger")
        else:
            flash(f"Student {username} not found", "danger")
        return redirect(url_for("dashboard_parent" if session.get("parent_email") else "dashboard_eleve"))

    # ✅ DÉTECTION DU CONTEXTE : Priorité à l'enseignant s'il y a conflit
    parent_email = session.get("parent_email")
    enseignant_id = session.get("enseignant_id")
    
    # DEBUG
    print(f"SESSION - parent_email: {parent_email}")
    print(f"SESSION - enseignant_id: {enseignant_id}")
    print(f"ÉLÈVE TROUVÉ - {eleve.nom_complet} (username: {username})")
    
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

    # Récupérer l'ID de l'élève et son niveau
    eleve_id = eleve.id
    niveau_eleve = eleve.niveau  # Récupère l'objet Niveau de l'élève
    
    if not niveau_eleve:
        if lang == "fr":
            flash("Niveau de l'élève non défini", "warning")
        else:
            flash("Student level not defined", "warning")
        return redirect(url_for("dashboard_eleve", username=username, lang=lang))
    
    # ============================================
    # FONCTION UTILITAIRE POUR OBTENIR LE NOM TRADUIT
    # ============================================
    def get_translated_name(obj, field_prefix="nom"):
        """Retourne le nom traduit d'un objet selon la langue"""
        if not obj:
            return "Inconnu"
        
        # Si l'objet a un attribut 'nom' (pour Niveau, Matiere, Unite)
        if hasattr(obj, 'nom'):
            if lang == "fr":
                return obj.nom  # Nom français
            else:
                # Vérifier si l'objet a un champ nom_en
                if hasattr(obj, 'nom_en') and obj.nom_en:
                    return obj.nom_en  # Nom anglais
                else:
                    return obj.nom  # Fallback sur le français
        
        # Si l'objet a un attribut 'titre' (pour Lecon)
        elif hasattr(obj, 'titre_fr'):
            if lang == "fr":
                return obj.titre_fr  # Titre français
            else:
                if hasattr(obj, 'titre_en') and obj.titre_en:
                    return obj.titre_en  # Titre anglais
                else:
                    return obj.titre_fr  # Fallback sur le français
        
        # Pour d'autres objets
        elif hasattr(obj, field_prefix):
            base_name = getattr(obj, field_prefix)
            if lang == "fr":
                return base_name
            else:
                # Essayer de trouver le champ avec _en
                en_field = f"{field_prefix}_en"
                if hasattr(obj, en_field):
                    en_name = getattr(obj, en_field)
                    if en_name:
                        return en_name
                return base_name  # Fallback sur la base
        
        return f"{field_prefix} inconnu"

    # Utiliser la fonction de traduction pour obtenir le nom du niveau
    niveau_eleve_nom = get_translated_name(niveau_eleve)
    niveau_eleve_id = niveau_eleve.id
    
    print(f"ÉLÈVE - {eleve.nom_complet} - Niveau: {niveau_eleve_nom} (ID: {niveau_eleve_id})")

    # Récupérer toutes les réponses de l'élève
    reponses_exos = StudentResponse.query.filter_by(user_id=eleve_id).all()
    
    # Créer un dictionnaire pour suivre quels exercices ont été faits par ID
    exercices_faits_par_id = {r.exercice_id for r in reponses_exos if r.exercice_id}
    
    # Récupérer UNIQUEMENT le niveau de l'élève
    niveau_eleve_obj = Niveau.query.get(niveau_eleve_id)
    
    if not niveau_eleve_obj:
        if lang == "fr":
            flash("Niveau de l'élève introuvable", "danger")
        else:
            flash("Student level not found", "danger")
        return redirect(url_for("dashboard_eleve", username=username, lang=lang))
    
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
        "total_exercices": 0,
        "original_id": niveau_eleve_id
    }
    
    # Parcourir les matières du niveau de l'élève
    for matiere in niveau_eleve_obj.matieres:
        matiere_nom = get_translated_name(matiere)
        
        # Initialiser la matière
        data_structure["niveaux"][niveau_eleve_nom]["matieres"][matiere_nom] = {
            "unites": {},
            "total_effectues": 0,
            "total_restants": 0,
            "total_exercices": 0,
            "original_id": matiere.id
        }
        
        # Parcourir les unités de cette matière
        for unite in matiere.unites:
            unite_nom = get_translated_name(unite)
            
            # Initialiser l'unité
            data_structure["niveaux"][niveau_eleve_nom]["matieres"][matiere_nom]["unites"][unite_nom] = {
                "lecons": {},
                "total_effectues": 0,
                "total_restants": 0,
                "total_exercices": 0,
                "original_id": unite.id
            }
            
            # Parcourir les leçons de cette unité
            for lecon in unite.lecons:
                lecon_nom = get_translated_name(lecon, "titre")
                
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
            print(f"EXERCICE {ex.id} ignoré - Niveau: {get_translated_name(niveau)} (pas le niveau de l'élève)")
            continue
        
        # Récupérer les noms traduits
        niveau_nom = get_translated_name(niveau)
        matiere_nom = get_translated_name(matiere)
        unite_nom = get_translated_name(unite)
        lecon_nom = get_translated_name(lecon, "titre")
        
        # Vérifier que la structure existe
        if (niveau_nom in data_structure["niveaux"] and 
            matiere_nom in data_structure["niveaux"][niveau_nom]["matieres"] and
            unite_nom in data_structure["niveaux"][niveau_nom]["matieres"][matiere_nom]["unites"] and
            lecon_nom in data_structure["niveaux"][niveau_nom]["matieres"][matiere_nom]["unites"][unite_nom]["lecons"]):
            
            # Obtenir l'énoncé dans la bonne langue
            enonce = ex.question_fr if lang == "fr" else (ex.question_en if ex.question_en else ex.question_fr)
            
            exercice_data = {
                "id": r.id,
                "theme": unite_nom if unite else "—",
                "enonce": enonce,
                "reponse_eleve": r.reponse_eleve,
                "analyse_ia": r.analyse_ia or "—",
                "etoiles": r.etoiles if r.etoiles is not None else 0,
                "date": r.timestamp.strftime("%d/%m/%Y") if r.timestamp else "",
                "original_names": {
                    "niveau": niveau.nom,
                    "matiere": matiere.nom,
                    "unite": unite.nom,
                    "lecon": lecon.titre_fr
                }
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
            unite_nom_test = get_translated_name(test.unite)
        else:
            unite_nom_test = "—"
            
        # Obtenir la question dans la bonne langue
        if test and lang == "fr":
            enonce_test = test.question_fr if test.question_fr else "—"
        elif test:
            enonce_test = test.question_en if test.question_en else (test.question_fr if test.question_fr else "—")
        else:
            enonce_test = "—"

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
        niveau_eleve=niveau_eleve_nom,  # Utilise le nom traduit
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
    
@app.after_request
def log_responses(response):
    """Log les réponses"""
    print(f"Response: {response.status_code}")
    return response

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

from flask import render_template, session, redirect
from models import User, Matiere, Lecon, Exercice

@app.route('/enseignant/exercices')
def voir_exercices():
    user_id = session.get('user_id')
    if not user_id:
        return redirect('/login')

    enseignant = User.query.get(user_id)
    if not enseignant or not enseignant.est_enseignant():
        return "Accès refusé", 403

    lang = session.get('lang', enseignant.langue or 'fr')

    eleves = enseignant.get_eleves_encadres()
    niveaux_ids = list({e.niveau_id for e in eleves if e.niveau_id})
    if not niveaux_ids:
        return render_template('enseignant_exercices.html', matieres=[], lang=lang, enseignant=enseignant)

    niveaux = Niveau.query.filter(Niveau.id.in_(niveaux_ids)).all()

    # Construction de matieres_data
    matieres_data = []
    for niveau in niveaux:
        eleves_niveau = [e.nom_complet for e in eleves if e.niveau_id == niveau.id]

        for matiere in niveau.matieres:
            unites_list = []
            for unite in matiere.unites:
                lecons_list = []
                for lecon in unite.lecons:
                    lecons_list.append({
                        'id': lecon.id,
                        'titre': lecon.titre_fr if lang == 'fr' else lecon.titre_en,
                        'exercices': [
                            {
                                'id': ex.id,
                                'question': ex.question_fr if lang == 'fr' else ex.question_en,
                                'options': ex.options_fr if lang == 'fr' else ex.options_en,
                                'reponse': ex.reponse_fr if lang == 'fr' else ex.reponse_en,
                                'explication': ex.explication_fr if lang == 'fr' else ex.explication_en,
                                'image_context': ex.get_image_context(lang=lang)
                            }
                            for ex in lecon.exercices
                        ]
                    })
                unites_list.append({
                    'id': unite.id,
                    'nom': unite.nom if lang == 'fr' else unite.nom_en,
                    'lecons': lecons_list
                })

            matieres_data.append({
                'id': matiere.id,
                'nom': matiere.nom if lang == 'fr' else matiere.nom_en,
                'niveau': niveau.nom if lang == 'fr' else niveau.nom_en,
                'eleves': eleves_niveau,
                'unites': unites_list
            })

    return render_template(
        'enseignant_exercices.html',
        matieres=matieres_data,
        lang=lang,
        enseignant=enseignant
    )



@app.route("/enseignant/exercices")
def enseignant_exercices():
    if "user_id" not in session:
        return redirect(url_for("login_enseignant"))

    enseignant = User.query.get(session["user_id"])
    if not enseignant or not enseignant.est_enseignant():
        flash("Accès réservé aux enseignants", "error")
        return redirect("/")

    lang = session.get("lang", "fr")

    # Récupère les exercices structurés
    matieres = get_exercices_par_enseignant_for_template(enseignant, lang)

    return render_template(
        "enseignant_exercices.html",
        enseignant=enseignant,
        matieres=matieres,
        lang=lang
    )


@app.route('/enseignant/exercice-visualisation', methods=['GET'])
def enseignant_exercice_visualisation():
    exercice_id = request.args.get('exercice_id', type=int)
    index = request.args.get('index', 0, type=int)
    lang = request.args.get('lang', 'fr')

    exercice = Exercice.query.get_or_404(exercice_id)
    lecon = exercice.lecon

    exercices = (
        Exercice.query
        .filter_by(lecon_id=lecon.id)
        .order_by(Exercice.id)
        .all()
    )

    total_exercices = len(exercices)
    index = max(0, min(index, total_exercices - 1))
    exercice = exercices[index]

    return render_template(
        'enseignant_exercice_visualisation.html',
        exercice=exercice,
        lecon=lecon,
        exercices=exercices,
        index=index,
        total_exercices=total_exercices,
        lang=lang
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
    """Route principale pour gérer les exercices avec pagination"""
    # Stocker la page actuelle dans la session
    page = request.args.get('page', 1, type=int)
    session['current_exercises_page'] = page
    
    # Récupérer toutes les matières avec leurs exercices
    matieres = Matiere.query.all()
    matieres_avec_exercices = []
    
    # Préparer les données par matière
    for matiere in matieres:
        # Compter les exercices dans cette matière
        total_exercices_matiere = db.session.query(Exercice).join(Lecon).join(Unite)\
            .filter(Unite.matiere_id == matiere.id).count()
        
        if total_exercices_matiere > 0:
            matiere_dict = {
                'id': matiere.id,
                'nom': matiere.nom,
                'nom_en': matiere.nom_en,
                'niveau_id': matiere.niveau_id,
                'niveau': matiere.niveau,
                'total_exercices': total_exercices_matiere,
                'unites_avec_exercices': []
            }
            
            # Récupérer les unités de cette matière
            unites = Unite.query.filter_by(matiere_id=matiere.id).all()
            
            for unite in unites:
                # Compter les exercices dans cette unité
                total_exercices_unite = db.session.query(Exercice).join(Lecon)\
                    .filter(Lecon.unite_id == unite.id).count()
                
                if total_exercices_unite > 0:
                    unite_dict = {
                        'id': unite.id,
                        'nom': unite.nom,
                        'nom_en': unite.nom_en,
                        'total_exercices': total_exercices_unite,
                        'lecons_avec_exercices': []
                    }
                    
                    # Récupérer les leçons de cette unité
                    lecons = Lecon.query.filter_by(unite_id=unite.id).all()
                    
                    for lecon in lecons:
                        # Récupérer les exercices de cette leçon
                        exercices = Exercice.query.filter_by(lecon_id=lecon.id).all()
                        
                        if exercices:
                            lecon_dict = {
                                'id': lecon.id,
                                'titre_fr': lecon.titre_fr,
                                'titre_en': lecon.titre_en,
                                'exercices': exercices
                            }
                            unite_dict['lecons_avec_exercices'].append(lecon_dict)
                    
                    matiere_dict['unites_avec_exercices'].append(unite_dict)
            
            matieres_avec_exercices.append(matiere_dict)
    
    # Pagination
    per_page = 10  # Nombre de matières par page
    start = (page - 1) * per_page
    end = start + per_page
    
    matieres_paginees = matieres_avec_exercices[start:end]
    has_next = len(matieres_avec_exercices) > end
    
    # Récupérer les totaux pour les statistiques
    total_exercices = Exercice.query.count()
    total_lecons = Lecon.query.count()
    total_unites = Unite.query.count()
    total_matieres = Matiere.query.count()
    
    # Récupérer les niveaux pour les filtres
    niveaux = Niveau.query.all()
    
    # Préparer les matières par niveau pour le filtre
    matieres_par_niveau = {}
    for niveau in niveaux:
        matieres_par_niveau[niveau.id] = Matiere.query.filter_by(niveau_id=niveau.id).all()
    
    return render_template(
        "liste_exercices.html",
        matieres_avec_exercices=matieres_paginees,
        total_exercices=total_exercices,
        total_lecons=total_lecons,
        total_unites=total_unites,
        total_matieres=total_matieres,
        niveaux=niveaux,
        matieres_par_niveau=matieres_par_niveau,
        page=page,
        per_page=per_page,
        has_next=has_next,
        lang=session.get("lang", "fr")
    )

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
