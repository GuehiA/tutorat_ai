# diagnostic_bug.py
"""
DIAGNOSTIC COMPLET DU BUG DE CRÉATION ÉLÈVE/ENSEIGNANT
Exécuter: python diagnostic_bug.py
"""

from app import app, db
from models import User
from werkzeug.security import generate_password_hash
from datetime import datetime, date
from sqlalchemy import func, inspect
import traceback

def diagnostic_complet():
    """Diagnostic complet du système"""
    print("🔍 DIAGNOSTIC COMPLET - BUG CRÉATION UTILISATEUR")
    print("=" * 60)
    
    with app.app_context():
        # 1. VÉRIFICATION BASIQUE
        print("\n1️⃣ VÉRIFICATION BASIQUE")
        print("-" * 40)
        
        # Compter tous les utilisateurs
        total = User.query.count()
        print(f"📊 Total utilisateurs: {total}")
        
        # Par rôle
        roles = ['admin', 'enseignant', 'eleve']
        for role in roles:
            count = User.query.filter_by(role=role).count()
            print(f"   • {role:12} : {count:3} utilisateurs")
        
        # 2. VÉRIFIER LES DOUBLONS
        print("\n2️⃣ VÉRIFICATION DOUBLONS")
        print("-" * 40)
        
        # Doublons email
        duplicate_emails = db.session.query(
            User.email, func.count(User.id)
        ).group_by(User.email).having(func.count(User.id) > 1).all()
        
        if duplicate_emails:
            print("❌ EMAILS EN DOUBLE:")
            for email, count in duplicate_emails:
                print(f"   → {email} ({count} fois)")
                # Afficher les utilisateurs concernés
                users = User.query.filter_by(email=email).all()
                for u in users:
                    print(f"     - ID {u.id}: {u.username} ({u.role}) créé le {u.date_inscription}")
        else:
            print("✅ Aucun email en double")
        
        # Doublons username
        duplicate_usernames = db.session.query(
            User.username, func.count(User.id)
        ).group_by(User.username).having(func.count(User.id) > 1).all()
        
        if duplicate_usernames:
            print("\n❌ USERNAMES EN DOUBLE:")
            for username, count in duplicate_usernames:
                print(f"   → {username} ({count} fois)")
        else:
            print("✅ Aucun username en double")
        
        # 3. TEST DE CRÉATION D'UN ÉLÈVE
        print("\n3️⃣ TEST CRÉATION ÉLÈVE")
        print("-" * 40)
        
        test_email = f"test_diagnostic_{datetime.now().strftime('%H%M%S')}@tutorat.com"
        test_username = f"testdiag_{datetime.now().strftime('%H%M%S')}"
        
        print(f"Tentative de création: {test_email}")
        
        try:
            # Vérifier si existe déjà
            if User.query.filter_by(email=test_email).first():
                print("❌ ÉCHEC: Email existe déjà (ce ne devrait pas arriver)")
            elif User.query.filter_by(username=test_username).first():
                print("❌ ÉCHEC: Username existe déjà")
            else:
                # Créer l'élève
                eleve = User(
                    username=test_username,
                    nom_complet="Élève Test Diagnostic",
                    email=test_email,
                    role='eleve',
                    statut='actif',
                    statut_paiement='essai_gratuit',
                    date_inscription=datetime.utcnow(),
                    date_naissance=date(2010, 5, 15),
                    email_verifie=True
                )
                eleve.mot_de_passe_hash = generate_password_hash("Test123!")
                
                db.session.add(eleve)
                db.session.commit()
                
                # Vérifier que c'est bien sauvegardé
                saved = User.query.filter_by(email=test_email).first()
                if saved:
                    print(f"✅ SUCCÈS: Élève créé avec ID {saved.id}")
                    print(f"   • Email: {saved.email}")
                    print(f"   • Rôle: {saved.role}")
                    print(f"   • Username: {saved.username}")
                    
                    # Supprimer pour nettoyer
                    db.session.delete(saved)
                    db.session.commit()
                    print("   • (Supprimé pour nettoyage)")
                else:
                    print("❌ ÉCHEC: Élève non trouvé après création")
                    
        except Exception as e:
            print(f"❌ ERREUR lors de la création: {e}")
            print("StackTrace:", traceback.format_exc())
        
        # 4. TEST DE CRÉATION D'UN ENSEIGNANT
        print("\n4️⃣ TEST CRÉATION ENSEIGNANT")
        print("-" * 40)
        
        test_email_ens = f"ens_test_{datetime.now().strftime('%H%M%S')}@tutorat.com"
        test_username_ens = f"enstdiag_{datetime.now().strftime('%H%M%S')}"
        
        print(f"Tentative de création: {test_email_ens}")
        
        try:
            if User.query.filter_by(email=test_email_ens).first():
                print("❌ ÉCHEC: Email existe déjà")
            else:
                enseignant = User(
                    username=test_username_ens,
                    nom_complet="Enseignant Test",
                    email=test_email_ens,
                    role='enseignant',
                    statut='actif',
                    statut_paiement='paye',
                    date_inscription=datetime.utcnow(),
                    taux_commission=20.0,
                    specialite='Test',
                    methode_versement='interac'
                )
                enseignant.mot_de_passe_hash = generate_password_hash("Test123!")
                
                db.session.add(enseignant)
                db.session.commit()
                
                saved_ens = User.query.filter_by(email=test_email_ens).first()
                if saved_ens:
                    print(f"✅ SUCCÈS: Enseignant créé avec ID {saved_ens.id}")
                    
                    # Supprimer pour nettoyer
                    db.session.delete(saved_ens)
                    db.session.commit()
                    print("   • (Supprimé pour nettoyage)")
                else:
                    print("❌ ÉCHEC: Enseignant non trouvé après création")
                    
        except Exception as e:
            print(f"❌ ERREUR: {e}")
            print("StackTrace:", traceback.format_exc())
        
        # 5. ANALYSE DES ERREURS COURANTES
        print("\n5️⃣ ANALYSE ERREURS POTENTIELLES")
        print("-" * 40)
        
        # Vérifier les champs NULL dans colonnes NOT NULL
        print("Vérification contraintes NOT NULL:")
        
        # Liste des colonnes qui ne devraient pas être NULL
        not_null_columns = ['username', 'nom_complet', 'email', 'role', 'mot_de_passe_hash']
        
        for column in not_null_columns:
            # Compter les NULL
            null_count = User.query.filter(getattr(User, column) == None).count()
            if null_count > 0:
                print(f"   ⚠️  {column}: {null_count} valeurs NULL")
            else:
                print(f"   ✅ {column}: Aucun NULL")
        
        # 6. LOGS DES DERNIERS UTILISATEURS CRÉÉS
        print("\n6️⃣ DERNIERS UTILISATEURS CRÉÉS")
        print("-" * 40)
        
        derniers = User.query.order_by(User.date_inscription.desc()).limit(5).all()
        
        if derniers:
            for u in derniers:
                date_str = u.date_inscription.strftime('%Y-%m-%d %H:%M') if u.date_inscription else 'N/A'
                print(f"   • [{date_str}] {u.email:35} ({u.role:10}) - {u.nom_complet}")
        else:
            print("   Aucun utilisateur trouvé")
        
        # 7. RÉCAPITULATIF
        print("\n" + "=" * 60)
        print("🎯 RÉCAPITULATIF ET ACTIONS REQUISES")
        print("=" * 60)
        
        eleves_count = User.query.filter_by(role='eleve').count()
        enseignants_count = User.query.filter_by(role='enseignant').count()
        admins_count = User.query.filter_by(role='admin').count()
        
        print(f"📊 État actuel:")
        print(f"   • Admins: {admins_count}")
        print(f"   • Enseignants: {enseignants_count}")
        print(f"   • Élèves: {eleves_count}")
        
        if duplicate_emails:
            print(f"\n🚨 ACTION REQUISE: {len(duplicate_emails)} email(s) en double")
            print("   Ces doublons empêchent la création de nouveaux utilisateurs.")
            print("   Solution: Exécutez le script de nettoyage des doublons.")
        
        if eleves_count == 0:
            print(f"\n⚠️  ATTENTION: Aucun élève dans la base!")
            print("   Mais l'admin dit 'email existe déjà' - probablement doublon caché.")
        
        print("\n🔧 Scripts disponibles:")
        print("   1. clean_duplicates.py - Nettoyer les doublons")
        print("   2. create_test_users.py - Créer des utilisateurs de test")
        print("   3. fix_all_roles.py - Corriger tous les rôles")
        
        print("\n🎉 Diagnostic terminé!")

if __name__ == "__main__":
    diagnostic_complet()