from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    nom_complet = db.Column(db.String(128), nullable=False)
    email = db.Column(db.String(128), unique=True, nullable=False)

    # 🔗 Relations pédagogiques
    niveau_id = db.Column(db.Integer, db.ForeignKey('niveaux.id'))
    niveau = db.relationship('Niveau', backref='eleves')

    enseignant_id = db.Column(db.Integer, db.ForeignKey('enseignants.id'))
    enseignant = db.relationship("Enseignant", backref="eleves")

    role = db.Column(db.String(20), nullable=False)
    mot_de_passe_hash = db.Column(db.String(256), nullable=False)

    # 🔁 Relation vers les remédiations
    remediations = db.relationship(
        "RemediationSuggestion",
        back_populates="user",
        cascade="all, delete-orphan"
    )

    # 🌍 Préférence de langue
    langue = db.Column(db.String(10), default="fr")

    # 👨‍👩‍👧 Relation avec les parents
    parents = db.relationship("Parent", secondary="parent_eleve", backref="enfants")

    # 🆕 CHAMPS POUR LE SYSTÈME DE PAIEMENT ET INSCRIPTION
    statut = db.Column(db.String(20), default="actif")
    statut_paiement = db.Column(db.String(20), default="non_paye")
    inscrit_par_admin = db.Column(db.Boolean, default=False)
    
    # 🆕 INFORMATIONS DE FACTURATION CANADIENNES
    telephone = db.Column(db.String(20), nullable=True)
    adresse = db.Column(db.Text, nullable=True)
    ville = db.Column(db.String(100), nullable=True)
    province = db.Column(db.String(50), nullable=True)
    code_postal = db.Column(db.String(10), nullable=True)
    pays = db.Column(db.String(50), default="Canada")
    
    # 🆕 INFORMATIONS STRIPE
    stripe_session_id = db.Column(db.String(255), nullable=True)
    stripe_payment_intent = db.Column(db.String(255), nullable=True)
    stripe_customer_id = db.Column(db.String(255), nullable=True)
    
    # 🆕 DATES IMPORTANTES
    date_naissance = db.Column(db.Date, nullable=True)
    date_inscription = db.Column(db.DateTime, default=datetime.utcnow)
    date_dernier_paiement = db.Column(db.DateTime, nullable=True)
    date_fin_abonnement = db.Column(db.DateTime, nullable=True)
    
    # 🆕 NOUVEAUX CHAMPS POUR L'ESSAI GRATUIT
    date_fin_essai = db.Column(db.DateTime, nullable=True)
    statut_essai = db.Column(db.String(20), default='actif')
    
    # 🆕 MÉTADONNÉES SUPPLEMENTAIRES
    email_verifie = db.Column(db.Boolean, default=False)
    telephone_verifie = db.Column(db.Boolean, default=False)
    accepte_cgu = db.Column(db.Boolean, default=False)
    date_acceptation_cgu = db.Column(db.DateTime, nullable=True)
    
    # 🆕 RELATIONS AVEC LES RÉPONSES ET TESTS
    tests_soumis = db.relationship("TestResponse", backref="user", cascade="all, delete-orphan")
    reponses_exercices = db.relationship("StudentResponse", backref="user", cascade="all, delete-orphan")
    
    # 🆕 CHAMPS POUR LE SUIVI ET ANALYTIQUES
    derniere_connexion = db.Column(db.DateTime, nullable=True)
    nombre_connexions = db.Column(db.Integer, default=0)
    timezone = db.Column(db.String(50), default="America/Toronto")
    preferences_notifications = db.Column(db.JSON, default=lambda: {
        'email_cours': True,
        'email_progres': True,
        'email_marketing': False
    })

    # 🛡️ Gestion du mot de passe
    @property
    def mot_de_passe(self):
        raise AttributeError("Accès interdit au mot de passe en clair.")

    @mot_de_passe.setter
    def mot_de_passe(self, mot):
        self.mot_de_passe_hash = generate_password_hash(mot)

    def verifier_mot_de_passe(self, mot_saisi):
        return check_password_hash(self.mot_de_passe_hash, mot_saisi)
    
    # 🆕 MÉTHODES POUR LA GESTION DES PAIEMENTS ET ESSAI
    def marquer_comme_paye(self, stripe_session_id=None, stripe_payment_intent=None):
        """Marquer l'utilisateur comme payé"""
        self.statut = "actif"
        self.statut_paiement = "paye"
        self.statut_essai = "payant"
        if stripe_session_id:
            self.stripe_session_id = stripe_session_id
        if stripe_payment_intent:
            self.stripe_payment_intent = stripe_payment_intent
        self.date_dernier_paiement = datetime.utcnow()
        self.date_fin_abonnement = datetime.utcnow() + timedelta(days=365)
    
    def activer_essai_gratuit(self, duree_heures=48):
        """Activer l'essai gratuit"""
        self.statut = "actif"
        self.statut_paiement = "essai_gratuit"
        self.statut_essai = "actif"
        self.date_fin_essai = datetime.utcnow() + timedelta(hours=duree_heures)
    
    def est_en_essai_gratuit(self):
        """Vérifier si l'utilisateur est en essai gratuit"""
        if self.statut_paiement != "essai_gratuit":
            return False
        
        if not self.date_fin_essai:
            return False
            
        return datetime.utcnow() < self.date_fin_essai
    
    def essai_est_expire(self):
        """Vérifier si l'essai gratuit est expiré"""
        if self.statut_paiement != "essai_gratuit":
            return False
            
        if not self.date_fin_essai:
            return True
            
        return datetime.utcnow() >= self.date_fin_essai
    
    def temps_restant_essai(self):
        """Obtenir le temps restant de l'essai"""
        if not self.est_en_essai_gratuit():
            return None
            
        temps_restant = self.date_fin_essai - datetime.utcnow()
        return temps_restant
    
    def est_actif(self):
        """Vérifier si l'utilisateur est actif (payé ou en essai valide)"""
        if self.role == "admin":
            return True
            
        if self.statut_paiement == "paye":
            return True
            
        if self.est_en_essai_gratuit():
            return True
            
        return False
    
    def est_en_attente_paiement(self):
        """Vérifier si l'utilisateur est en attente de paiement"""
        return self.statut == "en_attente_paiement"
    
    def a_acces_plateforme(self):
        """Vérifier si l'utilisateur a accès à la plateforme"""
        return self.est_actif()
    
    def obtenir_adresse_complete(self):
        """Obtenir l'adresse complète formatée"""
        if not self.adresse:
            return None
        elements = [self.adresse]
        if self.ville:
            elements.append(self.ville)
        if self.province:
            elements.append(self.province)
        if self.code_postal:
            elements.append(self.code_postal)
        if self.pays:
            elements.append(self.pays)
        return ", ".join(filter(None, elements))
    
    def ajouter_parent(self, parent):
        """Ajouter un parent à l'élève"""
        if parent not in self.parents:
            self.parents.append(parent)
    
    def to_dict(self):
        """Convertir l'utilisateur en dictionnaire pour l'API"""
        return {
            'id': self.id,
            'username': self.username,
            'nom_complet': self.nom_complet,
            'email': self.email,
            'role': self.role,
            'statut': self.statut,
            'statut_paiement': self.statut_paiement,
            'niveau': self.niveau.nom if self.niveau else None,
            'date_inscription': self.date_inscription.isoformat() if self.date_inscription else None,
            'est_actif': self.est_actif(),
            'est_en_essai': self.est_en_essai_gratuit()
        }
    
    def jours_restants_abonnement(self):
        """Calculer le nombre de jours restants dans l'abonnement"""
        if not self.date_fin_abonnement:
            return 0
        aujourdhui = datetime.utcnow()
        if self.date_fin_abonnement < aujourdhui:
            return 0
        return (self.date_fin_abonnement - aujourdhui).days
    
    def renouveler_abonnement(self, duree_jours=365):
        """Renouveler l'abonnement pour une durée donnée"""
        self.date_dernier_paiement = datetime.utcnow()
        self.date_fin_abonnement = datetime.utcnow() + timedelta(days=duree_jours)
        self.statut_paiement = "paye"
        self.statut = "actif"
        self.statut_essai = "payant"
    
    def __repr__(self):
        return f"<User {self.username} ({self.email}) - {self.role}>"


class ExerciceRemediation(db.Model):
    __tablename__ = "exercice_remediation"

    id = db.Column(db.Integer, primary_key=True)

    # 🔗 Relation vers la suggestion d’origine
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
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    statut = db.Column(db.String(20), default="proposé")  # proposé, validé, rejeté

    # 🔁 Relation bidirectionnelle avec RemediationSuggestion
    suggestion = db.relationship("RemediationSuggestion", back_populates="exercices")


class RemediationSuggestion(db.Model):
    __tablename__ = "remediation_suggestion"

    id = db.Column(db.Integer, primary_key=True)

    # 🔗 Relation vers l'élève concerné
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)

    # ✅ Relation corrigée — cohérente avec User.remediations
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

    # 📥 Réponse de l’élève après remédiation
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
    exercices = db.relationship("Exercice", backref="lecon", cascade="all, delete-orphan")
    # ✅ Supprimé : les tests ne sont plus liés à la leçon
# tests = db.relationship("TestSommatif", backref="lecon", cascade="all, delete-orphan")


### --- Exercices & Tests --- ###

# Dans TestResponse - MODIFIEZ COMME ÇA
class TestResponse(db.Model):
    __tablename__ = "test_responses"
    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete='CASCADE'), nullable=False)
    test_id = db.Column(db.Integer, db.ForeignKey("tests_sommatifs.id"), nullable=False)

    # 🟡 PROBLÈME : La relation user est commentée mais utilisée dans User.tests_soumis
    # ✅ CORRECTION : Supprimez complètement cette ligne ou décommentez proprement
    # user = db.relationship("User", foreign_keys=[user_id], overlaps="tests_soumis,user")
    
    # ✅ GARDEZ cette ligne
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
    exercice_id = db.Column(db.Integer, db.ForeignKey('exercices.id'), nullable=True)
    test_exercice_id = db.Column(db.Integer, db.ForeignKey('test_exercices.id'), nullable=True)
    test_id = db.Column(db.Integer, db.ForeignKey('tests_sommatifs.id'), nullable=True)

    reponse_eleve = db.Column(db.Text)
    analyse_ia = db.Column(db.Text)
    etoiles = db.Column(db.Integer)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    # Relations utiles
    test_exercice = db.relationship("TestExercice")
    
    # 🟡 PROBLÈME : Cette ligne est commentée mais doit être supprimée
    # user = db.relationship("User")