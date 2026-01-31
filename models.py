# models.py - VERSION OPTIMISÉE
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import JSON

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    nom_complet = db.Column(db.String(128), nullable=False)
    email = db.Column(db.String(128), unique=True, nullable=False)

    niveau_id = db.Column(db.Integer, db.ForeignKey('niveaux.id'))
    niveau = db.relationship('Niveau', backref='eleves')

    enseignant_referent_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    parents = db.relationship(
        'Parent',
        secondary='parent_eleve',
        backref='eleves',
        lazy='dynamic'
    )

    role = db.Column(db.String(20), nullable=False)
    mot_de_passe_hash = db.Column(db.String(256), nullable=False)

    langue = db.Column(db.String(10), default="fr")

    # Paiement et statut
    statut = db.Column(db.String(20), default="actif")
    statut_paiement = db.Column(db.String(20), default="non_paye")
    statut_essai = db.Column(db.String(20), default='actif')
    inscrit_par_admin = db.Column(db.Boolean, default=False)

    # Facturation
    telephone = db.Column(db.String(20), nullable=True)
    adresse = db.Column(db.Text, nullable=True)
    ville = db.Column(db.String(100), nullable=True)
    province = db.Column(db.String(50), nullable=True)
    code_postal = db.Column(db.String(10), nullable=True)
    pays = db.Column(db.String(50), default="Canada")

    stripe_session_id = db.Column(db.String(255), nullable=True)
    stripe_payment_intent = db.Column(db.String(255), nullable=True)
    stripe_customer_id = db.Column(db.String(255), nullable=True)

    # Dates importantes
    date_naissance = db.Column(db.Date, nullable=True)
    date_inscription = db.Column(db.DateTime, default=datetime.utcnow)
    date_dernier_paiement = db.Column(db.DateTime, nullable=True)
    date_fin_abonnement = db.Column(db.DateTime, nullable=True)
    date_fin_essai = db.Column(db.DateTime, nullable=True)

    # Métadonnées
    email_verifie = db.Column(db.Boolean, default=False)
    telephone_verifie = db.Column(db.Boolean, default=False)
    accepte_cgu = db.Column(db.Boolean, default=False)
    date_acceptation_cgu = db.Column(db.DateTime, nullable=True)
    derniere_connexion = db.Column(db.DateTime, nullable=True)
    nombre_connexions = db.Column(db.Integer, default=0)
    timezone = db.Column(db.String(50), default="America/Toronto")
    preferences_notifications = db.Column(db.JSON, default=lambda: {
        'email_cours': True,
        'email_progres': True,
        'email_marketing': False
    })

    # Enseignant
    methode_versement = db.Column(db.String(50), default='interac')
    email_interac_paiement = db.Column(db.String(255))
    nom_complet_interac = db.Column(db.String(255))
    email_paypal = db.Column(db.String(255))
    frequence_versement = db.Column(db.String(20), default='mensuel')
    seuil_minimum_paiement = db.Column(db.Float, default=25.00)
    date_mise_a_jour = db.Column(db.DateTime, onupdate=datetime.utcnow)
    taux_commission = db.Column(db.Float, default=20.0)
    specialite = db.Column(db.String(100))
    biographie = db.Column(db.Text)
    qualifications = db.Column(db.Text)
    experience_annees = db.Column(db.Integer, default=0)
    telephone_professionnel = db.Column(db.String(20))
    site_web = db.Column(db.String(255))
    linkedin = db.Column(db.String(255))
    statut_enseignant = db.Column(db.String(20), default='actif')
    disponibilites = db.Column(db.JSON, default=lambda: {
        'lundi': [], 'mardi': [], 'mercredi': [], 'jeudi': [],
        'vendredi': [], 'samedi': [], 'dimanche': []
    })

    # Notes et évaluations
    note_moyenne = db.Column(db.Float, default=0.0)
    nombre_evaluations = db.Column(db.Integer, default=0)

    # -------------------- Gestion mot de passe --------------------
    @property
    def mot_de_passe(self):
        raise AttributeError("Accès interdit au mot de passe en clair.")

    @mot_de_passe.setter
    def mot_de_passe(self, mot):
        self.mot_de_passe_hash = generate_password_hash(mot)

    def verifier_mot_de_passe(self, mot_saisi):
        return check_password_hash(self.mot_de_passe_hash, mot_saisi)

    # -------------------- Statut utilisateur --------------------
    def est_enseignant(self):
        return self.role == 'enseignant'

    def est_eleve(self):
        return self.role == 'eleve'

    def est_admin(self):
        return self.role == 'admin'

    def est_actif(self):
        if self.role == 'admin':
            return True
        if self.statut_paiement == "paye":
            return True
        if self.est_en_essai_gratuit():
            return True
        return False

    def est_en_attente_paiement(self):
        return self.statut == "en_attente_paiement"

    def a_acces_plateforme(self):
        return self.est_actif()

    # -------------------- Essai gratuit --------------------
    def activer_essai_gratuit(self, duree_heures=48):
        self.statut = "actif"
        self.statut_paiement = "essai_gratuit"
        self.statut_essai = "actif"
        self.date_fin_essai = datetime.utcnow() + timedelta(hours=duree_heures)

    def est_en_essai_gratuit(self):
        if self.statut_paiement != "essai_gratuit":
            return False
        if not self.date_fin_essai:
            return False
        return datetime.utcnow() < self.date_fin_essai

    def essai_est_expire(self):
        if self.statut_paiement != "essai_gratuit":
            return False
        if not self.date_fin_essai:
            return True
        return datetime.utcnow() >= self.date_fin_essai

    def temps_restant_essai(self):
        if not self.est_en_essai_gratuit():
            return None
        return self.date_fin_essai - datetime.utcnow()

    # -------------------- Paiement --------------------
    def marquer_comme_paye(self, stripe_session_id=None, stripe_payment_intent=None):
        self.statut = "actif"
        self.statut_paiement = "paye"
        self.statut_essai = "payant"
        if stripe_session_id:
            self.stripe_session_id = stripe_session_id
        if stripe_payment_intent:
            self.stripe_payment_intent = stripe_payment_intent
        self.date_dernier_paiement = datetime.utcnow()
        self.date_fin_abonnement = datetime.utcnow() + timedelta(days=365)

    def renouveler_abonnement(self, duree_jours=365):
        self.date_dernier_paiement = datetime.utcnow()
        self.date_fin_abonnement = datetime.utcnow() + timedelta(days=duree_jours)
        self.statut_paiement = "paye"
        self.statut = "actif"
        self.statut_essai = "payant"

    def jours_restants_abonnement(self):
        if not self.date_fin_abonnement:
            return 0
        delta = self.date_fin_abonnement - datetime.utcnow()
        return max(delta.days, 0)

    # -------------------- Relations pédagogiques --------------------
    def get_enseignant_referent(self):
        if self.enseignant_referent_id:
            return User.query.get(self.enseignant_referent_id)
        return None

    def get_eleves_encadres(self):
        if self.est_enseignant():
            return User.query.filter_by(enseignant_referent_id=self.id, role='eleve').all()
        return []

    def count_eleves_encadres(self):
        if self.est_enseignant():
            return User.query.filter_by(enseignant_referent_id=self.id, role='eleve').count()
        return 0

    def ajouter_eleve(self, eleve):
        if self.est_enseignant() and eleve.est_eleve():
            eleve.enseignant_referent_id = self.id
            db.session.commit()

    # -------------------- Commissions --------------------
    def calculer_commission_totale(self):
        if not self.est_enseignant():
            return 0
        commissions = Commission.query.filter_by(enseignant_id=self.id, statut='approved').all()
        return sum(c.montant_commission for c in commissions)

    def calculer_commission_en_attente(self):
        if not self.est_enseignant():
            return 0
        commissions = Commission.query.filter_by(enseignant_id=self.id, statut='pending').all()
        return sum(c.montant_commission for c in commissions)

    def get_all_commissions(self):
        enseignant_comms = Commission.query.filter_by(enseignant_id=self.id).all()
        eleve_comms = Commission.query.filter_by(eleve_id=self.id).all()
        return enseignant_comms + eleve_comms

    # -------------------- Adresse --------------------
    def obtenir_adresse_complete(self):
        if not self.adresse:
            return None
        elements = [self.adresse, self.ville, self.province, self.code_postal, self.pays]
        return ", ".join(filter(None, elements))

    # -------------------- Représentation --------------------
    def __repr__(self):
        return f"<User {self.username} ({self.email}) - {self.role}>"

# --- Relations remédiations ---
User.remediations = db.relationship(
    "RemediationSuggestion",
    back_populates="user",
    lazy='dynamic',
    foreign_keys='RemediationSuggestion.user_id',
    cascade="all, delete-orphan"
)

# -------------------------------------------------------------------------------------------------
# Les autres classes restent identiques : ExerciceRemediation, RemediationSuggestion, Parent, ParentEleve,
# Niveau, Matiere, Unite, Lecon, Exercice, TestExercice, TestSommatif, StudentResponse,
# Commission, VersementManuel, InfoVersementEnseignant
# -------------------------------------------------------------------------------------------------

class ExerciceRemediation(db.Model):
    __tablename__ = "exercice_remediation"

    id = db.Column(db.Integer, primary_key=True)

    # 🔗 Relation vers la suggestion d' origine
    suggestion_id = db.Column(
        db.Integer,
        db.ForeignKey("remediation_suggestion.id", ondelete="CASCADE"),
        nullable=False
    )

    # 🧩 Contenu de la remédiation
    enonce = db.Column(db.Text, nullable=False)
    reponse = db.Column(db.Text, nullable=False)
    analyse_ia = db.Column(db.Text, nullable=True)

    # 🕓 Suivi
    date_creation = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    statut = db.Column(db.String(20), default="proposé")  # proposé, validé, rejeté

    # 🔁 Relation bidirectionnelle avec RemediationSuggestion
    suggestion = db.relationship("RemediationSuggestion", back_populates="exercices")


class RemediationSuggestion(db.Model):
    __tablename__ = "remediation_suggestion"

    id = db.Column(db.Integer, primary_key=True)

    # 🔗 Relation vers l'élève concerné
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)

    # ✅ Relation corrigée - cohérente avec User.remediations
    user = db.relationship("User", back_populates="remediations")

    # 🎓 Contexte pédagogique
    theme = db.Column(db.String(100), nullable=False)     # Ex : "Fraction", "Passé composé"
    lecon = db.Column(db.String(100), nullable=True)      # Titre de la leçon si applicable

    # 🧠 Message et remédiation
    message = db.Column(db.Text, nullable=True)           # Analyse des erreurs ou difficultés
    exercice_suggere = db.Column(db.Text, nullable=True)  # Ex : "Complète la phrase suivante..."

    # 🕓 Suivi et statut
    statut = db.Column(db.String(20), default="en_attente")  # "en_attente", "valide", "refuse"
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    vue_par_eleve = db.Column(db.Boolean, default=False)

    # 📥 Réponse de l'élève après remédiation
    reponse_eleve = db.Column(db.Text)
    date_soumission = db.Column(db.DateTime)

    # 🔗 Relation vers les exercices de remédiation associés
    exercices = db.relationship(
        "ExerciceRemediation",
        back_populates="suggestion",
        cascade="all, delete-orphan"
    )


class Enseignant(db.Model):
    __tablename__ = "enseignants"
    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(128))
    email = db.Column(db.String(128), unique=True)
    mot_de_passe_hash = db.Column(db.String(256))

    @property
    def mot_de_passe(self):
        raise AttributeError("Mot de passe inaccessible.")

    @mot_de_passe.setter
    def mot_de_passe(self, mot):
        self.mot_de_passe_hash = generate_password_hash(mot)

    def verifier_mot_de_passe(self, mot_saisi):
        return check_password_hash(self.mot_de_passe_hash, mot_saisi)


class Parent(db.Model):
    __tablename__ = "parents"
    id = db.Column(db.Integer, primary_key=True)
    nom_complet = db.Column(db.String(128))
    email = db.Column(db.String(128), unique=True)
    telephone = db.Column(db.String(20))
    telephone2 = db.Column(db.String(20))


class ParentEleve(db.Model):
    __tablename__ = "parent_eleve"
    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('parents.id'))
    eleve_id = db.Column(db.Integer, db.ForeignKey('users.id'))


### --- Structure pédagogique --- ###

class Niveau(db.Model):
    __tablename__ = "niveaux"
    id = db.Column(db.Integer, primary_key=True)

    nom = db.Column(db.String(50), nullable=False)      # nom en français
    nom_en = db.Column(db.String(50), nullable=True)     # nom en anglais (NOUVEAU)

    matieres = db.relationship("Matiere", backref="niveau", cascade="all, delete-orphan")


class Matiere(db.Model):
    __tablename__ = "matieres"
    id = db.Column(db.Integer, primary_key=True)

    nom = db.Column(db.String(100), nullable=False)      # nom en français
    nom_en = db.Column(db.String(100), nullable=True)     # nom en anglais (NOUVEAU)

    niveau_id = db.Column(db.Integer, db.ForeignKey('niveaux.id'))
    unites = db.relationship("Unite", backref="matiere", cascade="all, delete-orphan")


class Unite(db.Model):
    __tablename__ = "unites"
    id = db.Column(db.Integer, primary_key=True)

    nom = db.Column(db.String(100), nullable=False)      # nom en français
    nom_en = db.Column(db.String(100), nullable=True)     # nom en anglais (NOUVEAU)

    matiere_id = db.Column(db.Integer, db.ForeignKey('matieres.id'))
    lecons = db.relationship("Lecon", backref="unite", cascade="all, delete-orphan")


class Lecon(db.Model):
    __tablename__ = "lecons"
    id = db.Column(db.Integer, primary_key=True)
    titre_fr = db.Column(db.String(255), nullable=False)
    titre_en = db.Column(db.String(255), nullable=False)
    objectif_fr = db.Column(db.Text)
    objectif_en = db.Column(db.Text)
    unite_id = db.Column(db.Integer, db.ForeignKey('unites.id'))
    
    # ⚠️ CORRECTION : UNE SEULE relation exercices
    exercices = db.relationship("Exercice", 
                               backref="lecon", 
                               cascade="all, delete-orphan",
                               lazy=True)  # Gardez seulement cette ligne
    
    # Supprimez la ligne dupliquée :
    # exercices = db.relationship("Exercice", backref="lecon", cascade="all, delete-orphan")

### --- Exercices & Tests --- ###

class TestResponse(db.Model):
    __tablename__ = "test_responses"
    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete='CASCADE'), nullable=False)
    test_id = db.Column(db.Integer, db.ForeignKey("tests_sommatifs.id"), nullable=False)

    test = db.relationship("TestSommatif", backref="reponses")

    reponses_exercices = db.Column(db.JSON)
    analyse_ia = db.Column(db.Text)
    etoiles = db.Column(db.Integer)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


class Exercice(db.Model):
    __tablename__ = "exercices"
    id = db.Column(db.Integer, primary_key=True)

    lecon_id = db.Column(db.Integer, db.ForeignKey('lecons.id'))

    question_fr = db.Column(db.Text)
    question_en = db.Column(db.Text)

    options_fr = db.Column(db.Text)
    options_en = db.Column(db.Text)

    reponse_fr = db.Column(db.Text)
    reponse_en = db.Column(db.Text)

    explication_fr = db.Column(db.Text)
    explication_en = db.Column(db.Text)

    temps = db.Column(db.Integer)

    chemin_image = db.Column(db.String(255))  # Chemin du fichier image facultatif

    # ✅ NOUVEAUX CHAMPS pour l'optimisation IA
    image_description_fr = db.Column(db.Text)  # Description française de l'image
    image_description_en = db.Column(db.Text)  # Description anglaise de l'image
    image_keywords = db.Column(db.String(500))  # Mots-clés pour l'IA
    image_elements = db.Column(db.Text)  # Éléments visuels importants (JSON)

    # Relation avec les réponses des élèves
    reponses_eleves = db.relationship("StudentResponse", 
                                     backref="exercice",
                                     cascade="all, delete-orphan",
                                     lazy=True)
    
    @property
    def theme(self):
        try:
            return self.lecon.unite.matiere.nom
        except:
            return "Thème inconnu"

    @property
    def niveau(self):
        try:
            return self.lecon.unite.matiere.niveau.nom
        except:
            return "Niveau inconnu"

    def get_image_context(self, lang='fr'):
        """Retourne le contexte d'image optimisé pour l'IA"""
        if not self.chemin_image:
            return ""
        
        description = self.image_description_fr if lang == 'fr' else self.image_description_en
        if description:
            return f"\n📊 Description de l'image: {description}" if lang == 'fr' else f"\n📊 Image description: {description}"
        else:
            return f"\n📊 [Élément visuel lié à l'exercice]" if lang == 'fr' else f"\n📊 [Visual element related to the exercise]"


class TestExercice(db.Model):
    __tablename__ = "test_exercices"

    id = db.Column(db.Integer, primary_key=True)
    test_id = db.Column(db.Integer, db.ForeignKey("tests_sommatifs.id"), nullable=False)

    question_fr = db.Column(db.Text)
    reponse_fr = db.Column(db.Text)
    explication_fr = db.Column(db.Text)

    question_en = db.Column(db.Text)
    reponse_en = db.Column(db.Text)
    explication_en = db.Column(db.Text)

    chemin_image = db.Column(db.String(255))  # chemin image éventuelle

    test = db.relationship("TestSommatif", back_populates="exercices")


class TestSommatif(db.Model):
    __tablename__ = "tests_sommatifs"

    id = db.Column(db.Integer, primary_key=True)
    unite_id = db.Column(db.Integer, db.ForeignKey('unites.id'), nullable=False)
    unite = db.relationship("Unite", backref="tests")

    # Contenu optionnel
    question_fr = db.Column(db.Text)
    question_en = db.Column(db.Text)
    reponse_fr = db.Column(db.Text)
    reponse_en = db.Column(db.Text)
    explication_fr = db.Column(db.Text)
    explication_en = db.Column(db.Text)

    temps = db.Column(db.Integer)
    chemin_fichier = db.Column(db.String(255))     # PDF énoncé
    chemin_corrige = db.Column(db.String(255))     # PDF corrigé

    # ✅ Relation vers plusieurs exercices
    exercices = db.relationship(
        "TestExercice",
        back_populates="test",
        cascade="all, delete-orphan"
    )


class StudentResponse(db.Model):
    __tablename__ = "student_responses"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    exercice_id = db.Column(db.Integer, db.ForeignKey('exercices.id', ondelete='CASCADE'), nullable=True)
    test_exercice_id = db.Column(db.Integer, db.ForeignKey('test_exercices.id'), nullable=True)
    test_id = db.Column(db.Integer, db.ForeignKey('tests_sommatifs.id'), nullable=True)

    reponse_eleve = db.Column(db.Text)
    analyse_ia = db.Column(db.Text)
    etoiles = db.Column(db.Integer)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    # Relations utiles
    test_exercice = db.relationship("TestExercice")


### --- MODÈLES DE COMMISSIONS --- ###

class Commission(db.Model):
    __tablename__ = "commissions"
    
    id = db.Column(db.Integer, primary_key=True)
    enseignant_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    eleve_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    type_abonnement = db.Column(db.String(20), nullable=False)
    montant_total = db.Column(db.Float, nullable=False)
    montant_commission = db.Column(db.Float, nullable=False)
    taux_base = db.Column(db.Float, nullable=False)
    details_bonus = db.Column(JSON)
    statut = db.Column(db.String(20), default='pending')
    statut_eleve = db.Column(db.String(20), default='actif')
    date_paiement_eleve = db.Column(db.DateTime, nullable=False)
    date_calcul = db.Column(db.DateTime, default=datetime.utcnow)
    date_approbation = db.Column(db.DateTime)
    date_versement_manuel = db.Column(db.DateTime)
    reference_interac = db.Column(db.String(100))
    email_interac = db.Column(db.String(255))
    preuve_versement = db.Column(db.String(255))
    
    # Relations
    enseignant = db.relationship('User', 
                               foreign_keys=[enseignant_id],
                               backref='commissions_comme_enseignant')
    
    eleve = db.relationship('User', 
                          foreign_keys=[eleve_id],
                          backref='commissions_comme_eleve')
    
    def to_dict(self):
        return {
            'id': self.id,
            'enseignant_id': self.enseignant_id,
            'enseignant_nom': self.enseignant.nom_complet if self.enseignant else '',
            'eleve_id': self.eleve_id,
            'eleve_nom': self.eleve.nom_complet if self.eleve else '',
            'type_abonnement': self.type_abonnement,
            'montant_total': self.montant_total,
            'montant_commission': self.montant_commission,
            'taux_base': self.taux_base,
            'details_bonus': self.details_bonus,
            'statut': self.statut,
            'statut_eleve': self.statut_eleve,
            'date_paiement_eleve': self.date_paiement_eleve.isoformat() if self.date_paiement_eleve else None,
            'date_calcul': self.date_calcul.isoformat() if self.date_calcul else None,
            'date_versement_manuel': self.date_versement_manuel.isoformat() if self.date_versement_manuel else None,
            'reference_interac': self.reference_interac,
            'email_interac': self.email_interac
        }


class VersementManuel(db.Model):
    __tablename__ = "versements_manuels"
    
    id = db.Column(db.Integer, primary_key=True)
    enseignant_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    montant_total = db.Column(db.Float, nullable=False)
    frais_transaction = db.Column(db.Float, default=1.00)
    montant_net = db.Column(db.Float, nullable=False)
    email_interac = db.Column(db.String(255), nullable=False)
    date_demande = db.Column(db.DateTime, default=datetime.utcnow)
    date_versement = db.Column(db.DateTime)
    statut = db.Column(db.String(20), default='demande')
    methode_paiement = db.Column(db.String(20), default='interac')  # ← Valeur par défaut ici
    reference_interac = db.Column(db.String(100))
    preuve_versement = db.Column(db.String(255))
    notes_admin = db.Column(db.Text)
    
    enseignant = db.relationship('User', 
                               foreign_keys=[enseignant_id],
                               backref='versements_manuels')
    
    # Pas besoin de __init__ personnalisé, SQLAlchemy gère les valeurs par défaut
    
    def to_dict(self):
        return {
            'id': self.id,
            'enseignant_id': self.enseignant_id,
            'enseignant_nom': self.enseignant.nom_complet if self.enseignant else '',
            'montant_total': self.montant_total,
            'frais_transaction': self.frais_transaction,
            'montant_net': self.montant_net,
            'email_interac': self.email_interac,
            'methode_paiement': self.methode_paiement,
            'date_demande': self.date_demande.isoformat() if self.date_demande else None,
            'date_versement': self.date_versement.isoformat() if self.date_versement else None,
            'statut': self.statut,
            'reference_interac': self.reference_interac
        }


class InfoVersementEnseignant(db.Model):
    __tablename__ = "info_versement_enseignant"
    
    id = db.Column(db.Integer, primary_key=True)
    enseignant_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    methode_versement = db.Column(db.String(50), default='interac')
    email_interac = db.Column(db.String(255))
    nom_complet_interac = db.Column(db.String(255))
    email_paypal = db.Column(db.String(255))
    frequence_versement = db.Column(db.String(20), default='mensuel')
    seuil_minimum = db.Column(db.Float, default=25.00)
    date_mise_a_jour = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    enseignant = db.relationship('User', 
                               foreign_keys=[enseignant_id],
                               backref=db.backref('info_versement', uselist=False))
    
    def to_dict(self):
        return {
            'id': self.id,
            'enseignant_id': self.enseignant_id,
            'methode_versement': self.methode_versement,
            'email_interac': self.email_interac,
            'frequence_versement': self.frequence_versement,
            'seuil_minimum': self.seuil_minimum,
            'date_mise_a_jour': self.date_mise_a_jour.isoformat() if self.date_mise_a_jour else None
        }

# ⚠️ CORRECTION IMPORTANTE: Ajouter la relation remediations à la classe User
# Nous devons le faire après la définition de RemediationSuggestion
User.remediations = db.relationship(
    "RemediationSuggestion", 
    back_populates="user",
    lazy='dynamic',
    foreign_keys='RemediationSuggestion.user_id',
    cascade="all, delete-orphan"
)

print("✅ Tous les modèles définis avec succès")