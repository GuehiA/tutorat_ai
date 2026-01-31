# check_enseignants_roles.py
"""
Vérification des problèmes de rôles pour les enseignants
"""

from app import app, db
from models import User
from sqlalchemy import or_, func

def verifier_problemes_enseignants():
    """Vérifie tous les problèmes potentiels avec les rôles enseignants"""
    print("🔍 DIAGNOSTIC ENSEIGNANTS - PROBLÈMES DE RÔLES")
    print("=" * 60)
    
    with app.app_context():
        print("\n1️⃣ ÉTAT ACTUEL DES RÔLES ENSEIGNANTS:")
        print("-" * 40)
        
        # Voir tous les rôles distincts
        roles_distincts = db.session.query(User.role).distinct().all()
        roles_list = [r[0] for r in roles_distincts]
        
        print("🎭 Rôles distincts dans la base:")
        for role in sorted(roles_list):
            count = User.query.filter_by(role=role).count()
            print(f"   • {repr(role):20} : {count:3} utilisateur(s)")
        
        # Vérifier spécifiquement les enseignants
        print("\n2️⃣ ENSEIGNANTS - VARIATIONS POSSIBLES:")
        print("-" * 40)
        
        variations_enseignants = [
            'enseignant', 'Enseignant', 'ENSEIGNANT', 'teacher', 'Teacher', 'TEACHER',
            'prof', 'Prof', 'PROF', 'professeur', 'Professeur', 'PROFESSEUR'
        ]
        
        for variation in variations_enseignants:
            count = User.query.filter_by(role=variation).count()
            if count > 0:
                print(f"   • {repr(variation):20} : {count:3} utilisateur(s)")
                
                # Montrer les emails
                users = User.query.filter_by(role=variation).limit(3).all()
                for user in users:
                    print(f"      - {user.email}")
        
        print("\n3️⃣ COMPARAISON DES MÉTHODES DE RECHERCHE:")
        print("-" * 40)
        
        # Méthode 1: Exacte (ce que fait probablement votre code)
        enseignants_exact = User.query.filter_by(role='enseignant').count()
        print(f"   • Recherche 'enseignant' exact : {enseignants_exact}")
        
        # Méthode 2: Toutes variantes
        enseignants_tous = User.query.filter(
            or_(
                User.role == 'enseignant',
                User.role == 'Enseignant',
                User.role == 'teacher',
                User.role == 'Teacher'
            )
        ).count()
        print(f"   • Toutes variantes              : {enseignants_tous}")
        
        if enseignants_exact == enseignants_tous:
            print("   ✅ Aucun problème détecté")
        else:
            print(f"   ⚠️  Problème: {enseignants_tous - enseignants_exact} enseignant(s) invisible(s)")
            
            # Montrer les invisibles
            invisibles = User.query.filter(
                or_(
                    User.role == 'Enseignant',
                    User.role == 'teacher',
                    User.role == 'Teacher'
                )
            ).all()
            
            print(f"\n🔍 Enseignants invisibles:")
            for user in invisibles:
                print(f"   • {user.email:35} - rôle: {repr(user.role)}")
        
        print("\n4️⃣ VÉRIFICATION DES ROUTES ENSEIGNANTS:")
        print("-" * 40)
        
        # Routes qui pourraient être affectées
        routes_enseignants = [
            '/admin-enseignants',
            '/login-enseignant',
            '/admin/creer-enseignant',
            '/dashboard-enseignant'
        ]
        
        print("🔎 Vérifiez ces routes dans votre code:")
        for route in routes_enseignants:
            print(f"   • {route}")
        
        print("\n5️⃣ CORRECTIONS À APPLIQUER:")
        print("-" * 40)
        
        if enseignants_exact != enseignants_tous:
            print("⚠️  Corrections nécessaires:")
            print("   1. Normaliser tous les rôles à 'enseignant' (sans majuscule)")
            print("   2. Modifier les routes pour chercher avec or_()")
            print("   3. S'assurer que la création utilise toujours 'enseignant'")
        else:
            print("✅ Aucune correction nécessaire (rôles déjà uniformisés)")
        
        # 6. CRÉATION D'UN TEST
        print("\n6️⃣ TEST CRÉATION ENSEIGNANT:")
        print("-" * 40)
        
        from datetime import datetime
        from werkzeug.security import generate_password_hash
        
        test_email = f"test_ens_{datetime.now().strftime('%H%M%S')}@tutorat.com"
        
        try:
            # Créer avec le bon rôle
            enseignant = User(
                username=f"testens_{datetime.now().strftime('%H%M%S')}",
                nom_complet="Test Enseignant",
                email=test_email,
                role='enseignant',  # ← SANS majuscule
                statut='actif',
                statut_paiement='paye',
                date_inscription=datetime.now(),
                taux_commission=20.0,
                specialite='Mathématiques',
                methode_versement='interac'
            )
            enseignant.mot_de_passe_hash = generate_password_hash("Test123!")
            
            db.session.add(enseignant)
            db.session.commit()
            
            print(f"✅ Enseignant créé: {test_email}")
            
            # Tester la visibilité
            visible_exact = User.query.filter_by(role='enseignant', email=test_email).first()
            visible_variantes = User.query.filter(
                or_(
                    User.role == 'enseignant',
                    User.role == 'Enseignant',
                    User.role == 'teacher'
                ),
                User.email == test_email
            ).first()
            
            print(f"   • Visible (exact)     : {'✅' if visible_exact else '❌'}")
            print(f"   • Visible (variantes) : {'✅' if visible_variantes else '❌'}")
            
            # Nettoyer
            db.session.delete(enseignant)
            db.session.commit()
            print(f"   • Nettoyé")
            
        except Exception as e:
            print(f"❌ Erreur: {e}")
        
        print("\n🎯 RÉCAPITULATIF:")
        print("-" * 40)
        
        if enseignants_exact == enseignants_tous:
            print("✅ Aucun problème détecté avec les enseignants")
        else:
            print(f"⚠️  {enseignants_tous - enseignants_exact} enseignant(s) avec rôle incorrect")
            print("   Exécutez le script de correction")

if __name__ == "__main__":
    verifier_problemes_enseignants()