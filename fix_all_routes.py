# fix_all_routes.py
"""
CORRECTION COMPLÈTE DES 3 ROUTES
"""

from app import app, db
from models import User
from sqlalchemy import or_

def verifier_et_corriger():
    """Vérifie et corrige tous les problèmes"""
    print("🔧 CORRECTION COMPLÈTE DES ROUTES")
    print("=" * 60)
    
    with app.app_context():
        # 1. CORRIGER TOUS LES RÔLES AVEC ACCENTS
        print("\n1️⃣ CORRECTION FINALE DES RÔLES:")
        print("-" * 40)
        
        # Liste complète des variations
        variations = ['élève', 'Élève', 'Elève', 'ELÈVE', 'student', 'Student']
        
        total_corriges = 0
        for variation in variations:
            users = User.query.filter_by(role=variation).all()
            if users:
                print(f"   {variation} → eleve : {len(users)}")
                for user in users:
                    user.role = 'eleve'
                    total_corriges += 1
        
        if total_corriges > 0:
            db.session.commit()
            print(f"\n✅ {total_corriges} utilisateur(s) corrigé(s)")
        else:
            print("\n✅ Tous les rôles sont déjà corrects")
        
        # 2. TESTER LES 3 ROUTES
        print("\n2️⃣ TEST DES 3 ROUTES:")
        print("-" * 40)
        
        # Test 1: /admin/eleves (liste)
        print("\n📊 TEST /admin/eleves:")
        
        # Version actuelle (PROBLÈMATIQUE)
        eleves_actuel = User.query.filter_by(role='eleve').count()
        print(f"   • Actuel (filter_by): {eleves_actuel} élève(s)")
        
        # Version corrigée (DEVRAIT être)
        eleves_corrige = User.query.filter(
            or_(User.role == 'eleve', User.role == 'élève')
        ).count()
        print(f"   • Corrigé (or_): {eleves_corrige} élève(s)")
        
        if eleves_actuel == eleves_corrige:
            print("   ✅ Tous les élèves sont visibles")
        else:
            print(f"   ❌ {eleves_corrige - eleves_actuel} élève(s) invisible(s)")
        
        # Test 2: /login-eleve
        print("\n🔐 TEST /login-eleve:")
        
        # Prendre un élève avec accent si existe
        eleve_accent = User.query.filter_by(role='élève').first()
        if eleve_accent:
            print(f"   • Élève avec accent trouvé: {eleve_accent.email}")
            print(f"   • Version actuelle (filter_by): NE LE TROUVERA PAS")
            print(f"   • Version corrigée (or_): LE TROUVERA")
        else:
            print("   ✅ Aucun élève avec accent (bon signe)")
        
        # Test 3: Création d'un élève
        print("\n➕ TEST CRÉATION ÉLÈVE:")
        
        from datetime import datetime
        from werkzeug.security import generate_password_hash
        
        test_email = f"test_final_{datetime.now().strftime('%H%M%S')}@tutorat.com"
        
        try:
            # Créer avec le BON rôle
            eleve_test = User(
                username=f"testfinal_{datetime.now().strftime('%H%M%S')}",
                nom_complet="Test Final",
                email=test_email,
                role='eleve',  # ← SANS accent
                statut='actif',
                statut_paiement='essai_gratuit',
                date_inscription=datetime.utcnow()
            )
            eleve_test.mot_de_passe_hash = generate_password_hash("Test123!")
            
            db.session.add(eleve_test)
            db.session.commit()
            
            # Tester la visibilité
            visible_liste = User.query.filter_by(role='eleve', email=test_email).first()
            visible_login = User.query.filter(
                User.email == test_email,
                or_(User.role == 'eleve', User.role == 'élève')
            ).first()
            
            print(f"   • Créé: {test_email}")
            print(f"   • Visible dans liste: {'✅' if visible_liste else '❌'}")
            print(f"   • Trouvable pour login: {'✅' if visible_login else '❌'}")
            
            # Nettoyer
            db.session.delete(eleve_test)
            db.session.commit()
            
        except Exception as e:
            print(f"   ❌ Erreur: {e}")
        
        # 3. VÉRIFICATION FINALE
        print("\n3️⃣ ÉTAT FINAL:")
        print("-" * 40)
        
        # Distribution des rôles
        roles = db.session.query(User.role, db.func.count(User.id)).group_by(User.role).all()
        
        print("📊 Distribution par rôle:")
        for role, count in roles:
            print(f"   • {repr(role):15} : {count:3} utilisateur(s)")
        
        # Élèves trouvés par chaque méthode
        eleves_simple = User.query.filter_by(role='eleve').count()
        eleves_tous = User.query.filter(
            or_(User.role == 'eleve', User.role == 'élève')
        ).count()
        
        print(f"\n🎯 ÉLÈVES:")
        print(f"   • Avec role='eleve' : {eleves_simple}")
        print(f"   • Tous les élèves   : {eleves_tous}")
        
        if eleves_simple == eleves_tous:
            print("   ✅ PARFAIT ! Tous les élèves sont corrects et visibles")
        else:
            print(f"   ⚠️  Attention: {eleves_tous - eleves_simple} élève(s) avec accent restant(s)")
        
        print("\n🔧 ACTIONS À FAIRE DANS VOTRE CODE:")
        print("   1. /admin/inscrire-eleve: ✓ DÉJÀ CORRIGÉ (role='eleve')")
        print("   2. /admin/eleves: Remplacer filter_by par filter(or_(...))")
        print("   3. /login-eleve: Remplacer filter_by par filter(or_(...))")
        
        print("\n🎉 Analyse terminée!")

if __name__ == "__main__":
    verifier_et_corriger()