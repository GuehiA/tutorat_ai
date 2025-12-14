from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, TextAreaField, DateField, BooleanField, SubmitField, HiddenField  
from wtforms.validators import DataRequired, Email, Length, Optional, EqualTo, ValidationError
from datetime import datetime
from models import User, Parent  # Ajoutez ces imports si nécessaires

# =====================
# FORMULAIRE INSCRIPTION NORMALE (Élève seul)
# =====================

class InscriptionEleveForm(FlaskForm):
    """Formulaire d'inscription standard pour les élèves (sans admin)"""
    
    username = StringField('Nom d\'utilisateur', validators=[
        DataRequired(message="Le nom d'utilisateur est obligatoire"), 
        Length(min=3, max=64, message="Le nom d'utilisateur doit contenir entre 3 et 64 caractères")
    ])
    
    email = StringField('Email', validators=[
        DataRequired(message="L'email est obligatoire"), 
        Email(message="Veuillez entrer un email valide")
    ])
    
    nom_complet = StringField('Nom complet', validators=[
        DataRequired(message="Le nom complet est obligatoire"), 
        Length(min=2, max=128, message="Le nom complet doit contenir entre 2 et 128 caractères")
    ])
    
    mot_de_passe = PasswordField('Mot de passe', validators=[
        DataRequired(message="Le mot de passe est obligatoire"), 
        Length(min=6, message="Le mot de passe doit contenir au moins 6 caractères")
    ])
    
    confirmer_mot_de_passe = PasswordField('Confirmer le mot de passe', validators=[
        DataRequired(message="Veuillez confirmer votre mot de passe"),
        EqualTo('mot_de_passe', message="Les mots de passe doivent correspondre")
    ])
    
    telephone = StringField('Téléphone', validators=[
        Optional(), 
        Length(max=20, message="Le numéro de téléphone ne peut pas dépasser 20 caractères")
    ])
    
    # CHAMP NIVEAU
    niveau = SelectField('Niveau', coerce=int, validators=[
        DataRequired(message="Veuillez sélectionner un niveau")
    ])
    
    # CHAMP PLAN TYPE (AJOUTÉ) - très important!
    plan_type = HiddenField('Type de plan', default='annual', validators=[
        DataRequired(message="Le type de plan est requis")
    ])
    
    accepte_cgu = BooleanField('J\'accepte les conditions d\'utilisation', validators=[
        DataRequired(message="Vous devez accepter les conditions d'utilisation")
    ])
    
    submit = SubmitField('S\'inscrire')

    # Validations personnalisées
    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('Ce nom d\'utilisateur est déjà utilisé. Veuillez en choisir un autre.')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('Cet email est déjà utilisé. Veuillez en choisir un autre.')

    def validate_plan_type(self, plan_type):
        # Validation pour s'assurer que le type de plan est valide
        valid_plans = ['weekly', 'monthly', 'annual']
        if plan_type.data not in valid_plans:
            raise ValidationError('Type de plan invalide. Veuillez sélectionner un forfait valide.')

# =====================
# FORMULAIRE ADMIN (Avec parent)
# =====================

class InscriptionEleveAdminForm(FlaskForm):
    # =====================
    # INFORMATIONS ÉLÈVE
    # =====================
    
    # Champs de base
    username = StringField('Nom d\'utilisateur', validators=[
        DataRequired(message="Le nom d'utilisateur est obligatoire"), 
        Length(min=3, max=64, message="Le nom d'utilisateur doit contenir entre 3 et 64 caractères")
    ])
    
    email = StringField('Email de l\'élève', validators=[
        DataRequired(message="L'email est obligatoire"), 
        Email(message="Veuillez entrer un email valide")
    ])
    
    nom_complet = StringField('Nom complet de l\'élève', validators=[
        DataRequired(message="Le nom complet est obligatoire"), 
        Length(min=2, max=128, message="Le nom complet doit contenir entre 2 et 128 caractères")
    ])
    
    mot_de_passe = PasswordField('Mot de passe', validators=[
        DataRequired(message="Le mot de passe est obligatoire"), 
        Length(min=6, message="Le mot de passe doit contenir au moins 6 caractères")
    ])
    
    # Informations personnelles
    telephone = StringField('Téléphone de l\'élève', validators=[
        Optional(), 
        Length(max=20, message="Le numéro de téléphone ne peut pas dépasser 20 caractères")
    ])
    
    date_naissance = DateField('Date de naissance', validators=[Optional()])
    
    # Adresse
    adresse = TextAreaField('Adresse', validators=[Optional()])
    ville = StringField('Ville', validators=[
        Optional(), 
        Length(max=100, message="Le nom de ville ne peut pas dépasser 100 caractères")
    ])
    
    province = SelectField('Province', choices=[
        ('', 'Sélectionnez une province'),
        ('QC', 'Québec'),
        ('ON', 'Ontario'),
        ('BC', 'Colombie-Britannique'),
        ('AB', 'Alberta'),
        ('MB', 'Manitoba'),
        ('SK', 'Saskatchewan'),
        ('NS', 'Nouvelle-Écosse'),
        ('NB', 'Nouveau-Brunswick'),
        ('PE', 'Île-du-Prince-Édouard'),
        ('NL', 'Terre-Neuve-et-Labrador'),
        ('YT', 'Yukon'),
        ('NT', 'Territoires du Nord-Ouest'),
        ('NU', 'Nunavut')
    ], validators=[Optional()])
    
    code_postal = StringField('Code postal', validators=[
        Optional(), 
        Length(max=10, message="Le code postal ne peut pas dépasser 10 caractères")
    ])
    
    # =====================
    # INFORMATIONS PARENT
    # =====================
    
    parent_email = StringField('Email du parent', validators=[
        DataRequired(message="L'email du parent est obligatoire"), 
        Email(message="Veuillez entrer un email valide pour le parent")
    ])
    
    responsable_nom = StringField('Nom du responsable', validators=[
        DataRequired(message="Le nom du responsable est obligatoire"), 
        Length(min=2, max=128, message="Le nom du responsable doit contenir entre 2 et 128 caractères")
    ])
    
    responsable_telephone = StringField('Téléphone du responsable', validators=[
        DataRequired(message="Le téléphone du responsable est obligatoire"), 
        Length(max=20, message="Le numéro de téléphone ne peut pas dépasser 20 caractères")
    ])
    
    # =====================
    # INFORMATIONS PÉDAGOGIQUES
    # =====================
    
    niveau_id = SelectField('Niveau', coerce=int, validators=[
        DataRequired(message="Veuillez sélectionner un niveau")
    ])
    
    enseignant_id = SelectField('Enseignant', coerce=int, validators=[Optional()])
    
    # =====================
    # PARAMÈTRES ADMINISTRATIFS
    # =====================
    
    statut = SelectField('Statut du compte', choices=[
        ('actif', 'Actif'),
        ('en_attente_paiement', 'En attente de paiement'),
        ('inactif', 'Inactif'),
        ('suspendu', 'Suspendu')
    ], default='actif', validators=[DataRequired()])
    
    statut_paiement = SelectField('Statut de paiement', choices=[
        ('non_paye', 'Non payé'),
        ('paye', 'Payé - Inscrit par admin'),
        ('en_attente', 'En attente'),
        ('rembourse', 'Remboursé')
    ], default='non_paye', validators=[DataRequired()])
    
    # =====================
    # VÉRIFICATIONS
    # =====================
    
    email_verifie = BooleanField('Email vérifié', default=False)
    telephone_verifie = BooleanField('Téléphone vérifié', default=False)
    accepte_cgu = BooleanField('Accepte les CGU', default=True)
    
    # =====================
    # SOUMISSION
    # =====================
    
    submit = SubmitField('Inscrire l\'élève')

    # Validations personnalisées
    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('Ce nom d\'utilisateur est déjà utilisé. Veuillez en choisir un autre.')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('Cet email est déjà utilisé. Veuillez en choisir un autre.')

    def validate_parent_email(self, parent_email):
        # Vérification optionnelle pour éviter les doublons de parent
        pass