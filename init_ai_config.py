# init_ai_config.py
"""
Script d'initialisation de la configuration IA par matière.
Exécuter: python init_ai_config.py
"""

import os
import sys
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

# Ajouter le dossier courant au path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Importer l'application et les modèles
from app import app, db
from models import MatiereAIConfig, User, Niveau, Matiere, Unite, Lecon, Exercice


def init_matiere_ai_config():
    """Initialise la configuration IA par défaut pour les matières"""
    
    # Configuration par défaut pour toutes les matières
    configs_par_defaut = [
        # Mathématiques et cours spécifiques (Grades 11-12)
        {"matiere_nom": "Mathématiques", "modele_ia": "deepseek-v4-pro", "api_choice": "deepseek", "priorite": 10, 
         "description": "Maths général - DeepSeek Pro (recommandé pour calculs complexes)"},
        {"matiere_nom": "MCR3U", "modele_ia": "deepseek-v4-pro", "api_choice": "deepseek", "priorite": 10,
         "description": "Functions (Grade 11) - DeepSeek Pro"},
        {"matiere_nom": "MHF4U", "modele_ia": "deepseek-v4-pro", "api_choice": "deepseek", "priorite": 10,
         "description": "Advanced Functions (Grade 12) - DeepSeek Pro"},
        {"matiere_nom": "MCV4U", "modele_ia": "deepseek-v4-pro", "api_choice": "deepseek", "priorite": 10,
         "description": "Calculus and Vectors (Grade 12) - DeepSeek Pro"},
        {"matiere_nom": "MDM4U", "modele_ia": "deepseek-v4-flash", "api_choice": "deepseek", "priorite": 5,
         "description": "Data Management (Grade 12) - DeepSeek Flash"},
        
        # Sciences
        {"matiere_nom": "Sciences", "modele_ia": "deepseek-v4-flash", "api_choice": "deepseek", "priorite": 5,
         "description": "Sciences générales - DeepSeek Flash"},
        {"matiere_nom": "Physique", "modele_ia": "deepseek-v4-pro", "api_choice": "deepseek", "priorite": 10,
         "description": "Physique (équations, calculs) - DeepSeek Pro"},
        {"matiere_nom": "Chimie", "modele_ia": "deepseek-v4-pro", "api_choice": "deepseek", "priorite": 10,
         "description": "Chimie (équations, calculs) - DeepSeek Pro"},
        {"matiere_nom": "Biologie", "modele_ia": "deepseek-v4-flash", "api_choice": "deepseek", "priorite": 5,
         "description": "Biologie (concepts) - DeepSeek Flash"},
        {"matiere_nom": "SNC1D", "modele_ia": "deepseek-v4-flash", "api_choice": "deepseek", "priorite": 5,
         "description": "Science (Grade 9) - DeepSeek Flash"},
        {"matiere_nom": "SNC2D", "modele_ia": "deepseek-v4-flash", "api_choice": "deepseek", "priorite": 5,
         "description": "Science (Grade 10) - DeepSeek Flash"},
        
        # Langues (OpenAI meilleur pour la langue)
        {"matiere_nom": "Français", "modele_ia": "gpt-4o-mini", "api_choice": "openai", "priorite": 5,
         "description": "Français (grammaire, rédaction) - OpenAI mini"},
        {"matiere_nom": "English", "modele_ia": "gpt-4o-mini", "api_choice": "openai", "priorite": 5,
         "description": "English (grammar, writing) - OpenAI mini"},
        {"matiere_nom": "Anglais", "modele_ia": "gpt-4o-mini", "api_choice": "openai", "priorite": 5,
         "description": "Anglais - OpenAI mini"},
        {"matiere_nom": "FSF1D", "modele_ia": "gpt-4o-mini", "api_choice": "openai", "priorite": 5,
         "description": "French (Grade 9) - OpenAI mini"},
        {"matiere_nom": "FEF1D", "modele_ia": "gpt-4o-mini", "api_choice": "openai", "priorite": 5,
         "description": "French Immersion - OpenAI mini"},
        {"matiere_nom": "ENG1D", "modele_ia": "gpt-4o-mini", "api_choice": "openai", "priorite": 5,
         "description": "English (Grade 9) - OpenAI mini"},
        {"matiere_nom": "ENG2D", "modele_ia": "gpt-4o-mini", "api_choice": "openai", "priorite": 5,
         "description": "English (Grade 10) - OpenAI mini"},
        {"matiere_nom": "ENG3U", "modele_ia": "gpt-4o-mini", "api_choice": "openai", "priorite": 5,
         "description": "English (Grade 11) - OpenAI mini"},
        {"matiere_nom": "ENG4U", "modele_ia": "gpt-4o-mini", "api_choice": "openai", "priorite": 5,
         "description": "English (Grade 12) - OpenAI mini"},
        
        # Sciences humaines
        {"matiere_nom": "Histoire", "modele_ia": "gpt-4o-mini", "api_choice": "openai", "priorite": 3,
         "description": "Histoire - OpenAI mini"},
        {"matiere_nom": "Géographie", "modele_ia": "gpt-4o-mini", "api_choice": "openai", "priorite": 3,
         "description": "Géographie - OpenAI mini"},
        {"matiere_nom": "Économie", "modele_ia": "deepseek-v4-flash", "api_choice": "deepseek", "priorite": 3,
         "description": "Économie (calculs) - DeepSeek Flash"},
        {"matiere_nom": "Philosophie", "modele_ia": "gpt-4o-mini", "api_choice": "openai", "priorite": 3,
         "description": "Philosophie - OpenAI mini"},
        
        # Arts
        {"matiere_nom": "Arts", "modele_ia": "gpt-4o-mini", "api_choice": "openai", "priorite": 2,
         "description": "Arts plastiques - OpenAI mini"},
        {"matiere_nom": "Musique", "modele_ia": "gpt-4o-mini", "api_choice": "openai", "priorite": 2,
         "description": "Musique - OpenAI mini"},
        
        # Informatique
        {"matiere_nom": "Informatique", "modele_ia": "deepseek-v4-flash", "api_choice": "deepseek", "priorite": 5,
         "description": "Informatique (code, algorithmes) - DeepSeek Flash"},
        {"matiere_nom": "ICS2O", "modele_ia": "deepseek-v4-flash", "api_choice": "deepseek", "priorite": 5,
         "description": "Computer Science (Grade 10) - DeepSeek Flash"},
        {"matiere_nom": "ICS3U", "modele_ia": "deepseek-v4-flash", "api_choice": "deepseek", "priorite": 5,
         "description": "Computer Science (Grade 11) - DeepSeek Flash"},
        {"matiere_nom": "ICS4U", "modele_ia": "deepseek-v4-pro", "api_choice": "deepseek", "priorite": 10,
         "description": "Computer Science (Grade 12) - DeepSeek Pro"},
    ]
    
    compteur_ajouts = 0
    compteur_existants = 0
    
    print("=" * 60)
    print("🎯 INITIALISATION DE LA CONFIGURATION IA PAR MATIÈRE")
    print("=" * 60)
    
    for config in configs_par_defaut:
        exists = MatiereAIConfig.query.filter_by(matiere_nom=config["matiere_nom"]).first()
        if not exists:
            new_config = MatiereAIConfig(
                matiere_nom=config["matiere_nom"],
                modele_ia=config["modele_ia"],
                api_choice=config["api_choice"],
                priorite=config.get("priorite", 0),
                description=config.get("description", ""),
                actif=True
            )
            db.session.add(new_config)
            compteur_ajouts += 1
            print(f"✅ AJOUTÉ: {config['matiere_nom']} → {config['api_choice']}/{config['modele_ia']}")
        else:
            compteur_existants += 1
            print(f"⏭️ EXISTANT: {config['matiere_nom']}")
    
    db.session.commit()
    
    print("-" * 60)
    print(f"📊 Résumé: {compteur_ajouts} ajouté(s), {compteur_existants} existant(s)")
    print("=" * 60)
    
    return compteur_ajouts


def init_from_existing_matieres():
    """
    Optionnel: Ajoute automatiquement toutes les matières existantes dans la base
    avec une configuration par défaut (DeepSeek Flash)
    """
    matieres_existantes = Matiere.query.all()
    compteur = 0
    
    print("\n" + "=" * 60)
    print("📚 RECHERCHE DES MATIÈRES EXISTANTES DANS LA BASE")
    print("=" * 60)
    
    for matiere in matieres_existantes:
        exists = MatiereAIConfig.query.filter_by(matiere_nom=matiere.nom).first()
        if not exists:
            # Par défaut: DeepSeek Flash pour toutes les nouvelles matières
            new_config = MatiereAIConfig(
                matiere_nom=matiere.nom,
                modele_ia="deepseek-v4-flash",
                api_choice="deepseek",
                priorite=1,
                description=f"Configuration automatique pour {matiere.nom}",
                actif=True
            )
            db.session.add(new_config)
            compteur += 1
            print(f"✅ AJOUTÉ (auto): {matiere.nom}")
    
    if compteur > 0:
        db.session.commit()
        print(f"📊 {compteur} matière(s) existante(s) ajoutée(s) avec config par défaut")
    else:
        print("ℹ️ Aucune nouvelle matière existante à ajouter")
    
    return compteur


if __name__ == "__main__":
    print("\n")
    print("🌟 SCRIPT DE CONFIGURATION IA - TUTORAT AI")
    print("\n")
    
    with app.app_context():
        # S'assurer que la table existe
        db.create_all()
        print("✅ Base de données prête")
        
        # Initialiser les configurations
        ajouts = init_matiere_ai_config()
        
        # Optionnel: ajouter les matières existantes automatiquement
        print("\n")
        reponse = input("Voulez-vous aussi ajouter automatiquement les matières existantes? (o/N): ")
        if reponse.lower() == 'o':
            init_from_existing_matieres()
        
        print("\n" + "=" * 60)
        print("🎉 CONFIGURATION TERMINÉE!")
        print("=" * 60)
        
        # Afficher le résumé final
        total_configs = MatiereAIConfig.query.count()
        actifs = MatiereAIConfig.query.filter_by(actif=True).count()
        
        print(f"\n📊 État final:")
        print(f"   - Total configurations: {total_configs}")
        print(f"   - Configurations actives: {actifs}")
        print(f"   - Configurations inactives: {total_configs - actifs}")
        
        print("\n💡 Prochaines étapes:")
        print("   1. Lancer l'application: python app.py")
        print("   2. Aller dans /admin/ai-config pour gérer les configurations")
        print("   3. Tester la correction d'exercice")
        print()