# debug_eleve_invisible.py - VERSION CORRIGÉE
"""
DEBUG: Pourquoi l'élève créé n'apparaît pas dans la liste et ne peut pas se connecter
"""

from app import app, db
from models import User
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime

def debug_eleve_invisible():
    """Trouve pourquoi les élèves ne sont pas visibles"""
    print("🔍 DEBUG: ÉLÈVE INVISIBLE ET CONNEXION IMPOSSIBLE")
    print("=" * 60)
    
    with app.app_context():
        print("\n1️⃣ ANALYSE DE TOUS LES UTILISATEURS:")
        print("-" * 40)
        
        # Compter par rôle EXACT
        from sqlalchemy import func
        roles_counts = db.session.query(User.role, func.count(User.id)).group_by(User.role).all()
        
        print("📊 Distribution par rôle:")
        for role, count in roles_counts:
            print(f"   • {repr(role):15} : {count:3} utilisateurs")
        
        # Chercher les incohérences
        print(f"\n🔍 Recherche élève avec rôle différent de 'eleve':")
        variations = ['eleve', 'élève', 'Élève', 'Elève', 'student', 'Student']
        
        for variation in variations:
            users = User.query.filter_by(role=variation).all()
            if users:
                print(f"\n📋 Rôle '{variation}' : {len(users)} utilisateur(s)")
                for user in users[:3]:  # Montrer les 3 premiers
                    print(f"   → {user.email:35} - {user.nom_complet}")
        
        print("\n2️⃣ VÉRIFICATION DE LA LISTE /admin/eleves:")
        print("-" * 40)
        
        # Ce que votre route admin/eleves fait probablement
        eleves_query = User.query.filter_by(role='eleve').order_by(User.date_inscription.desc())
        eleves_count = eleves_query.count()
        eleves_list = eleves_query.all()
        
        print(f"📊 Requête actuelle: User.query.filter_by(role='eleve')")
        print(f"   • Résultat: {eleves_count} élève(s)")
        
        if eleves_count > 0:
            print(f"\n📋 Élèves trouvés (premiers 5):")
            for i, eleve in enumerate(eleves_list[:5], 1):
                ens_ref = eleve.enseignant_referent_id
                ens = User.query.get(ens_ref) if ens_ref else None
                ens_name = ens.nom_complet if ens else "Aucun"
                print(f"   {i}. {eleve.email:35} - Enseignant: {ens_name}")
        
        # Vérifier s'il y a des élèves avec enseignant_referent_id NULL vs NOT NULL
        print(f"\n3️⃣ ANALYSE ENSEIGNANT_RÉFÉRENT:")
        print("-" * 40)
        
        # Élèves AVEC enseignant référent
        eleves_avec_ens = User.query.filter(
            User.role == 'eleve',
            User.enseignant_referent_id.isnot(None)
        ).count()
        
        # Élèves SANS enseignant référent
        eleves_sans_ens = User.query.filter(
            User.role == 'eleve',
            User.enseignant_referent_id.is_(None)
        ).count()
        
        print(f"   • Avec enseignant référent : {eleves_avec_ens} élève(s)")
        print(f"   • Sans enseignant référent : {eleves_sans_ens} élève(s)")
        
        # Montrer les enseignants et leurs élèves
        print(f"\n4️⃣ ENSEIGNANTS ET LEURS ÉLÈVES:")
        print("-" * 40)
        
        enseignants = User.query.filter_by(role='enseignant').all()
        
        for ens in enseignants:
            eleves_encadres = User.query.filter_by(
                role='eleve',
                enseignant_referent_id=ens.id
            ).all()
            
            print(f"\n👨‍🏫 {ens.nom_complet} ({ens.email}):")
            print(f"   ID: {ens.id}, Élèves encadrés: {len(eleves_encadres)}")
            
            if eleves_encadres:
                for eleve in eleves_encadres:
                    print(f"      👨‍🎓 {eleve.email} - {eleve.nom_complet}")
            else:
                print(f"      Aucun élève encadré")
        
        print("\n5️⃣ TEST DE CONNEXION POUR LES ÉLÈVES:")
        print("-" * 40)
        
        # Prendre 2 élèves au hasard et tester leur connexion
        eleves_test = User.query.filter_by(role='eleve').limit(2).all()
        
        for eleve in eleves_test:
            print(f"\n🔐 Test connexion pour: {eleve.email}")
            print(f"   • ID: {eleve.id}")
            print(f"   • Username: {eleve.username}")
            print(f"   • Rôle: {eleve.role}")
            print(f"   • Mot de passe hash présent: {'OUI' if eleve.mot_de_passe_hash else 'NON'}")
            print(f"   • Statut: {eleve.statut}")
            print(f"   • Statut paiement: {eleve.statut_paiement}")
            
            # Tester un mot de passe
            if eleve.mot_de_passe_hash:
                # Tester avec un mauvais mot de passe
                test_wrong = check_password_hash(eleve.mot_de_passe_hash, "MauvaisMotDePasse")
                print(f"   • Test mdp incorrect: {'ÉCHEC (normal)' if not test_wrong else 'SUCCÈS (anormal!)'}")
                
                # Tester avec un mot de passe potentiel
                test_passwords = [
                    "Test123!", "Password123!", "Motdepasse123!", 
                    eleve.username + "123!", eleve.email.split('@')[0] + "123!",
                    "123456", "password", "admin123"
                ]
                
                found = False
                for pwd in test_passwords:
                    if check_password_hash(eleve.mot_de_passe_hash, pwd):
                        print(f"   • 🔓 Mot de passe trouvé: '{pwd}'")
                        found = True
                        break
                
                if not found:
                    print(f"   • 🔒 Mot de passe non trouvé dans les tests")
        
        print("\n6️⃣ CRÉATION D'UN TEST DIRECT:")
        print("-" * 40)
        
        # Créer un élève de test
        test_email = f"debug_test_{datetime.now().strftime('%H%M%S')}@tutorat.com"
        
        try:
            # Vérifier
            if User.query.filter_by(email=test_email).first():
                print("❌ Email existe déjà")
            else:
                # Créer comme le fait l'admin
                nouvel_eleve = User(
                    username=f"debugtest_{datetime.now().strftime('%H%M%S')}",
                    nom_complet="Debug Test Élève",
                    email=test_email,
                    role='eleve',
                    statut='actif',
                    statut_paiement='essai_gratuit',
                    date_inscription=datetime.utcnow(),
                    email_verifie=True
                )
                nouvel_eleve.mot_de_passe_hash = generate_password_hash("DebugTest123!")
                
                db.session.add(nouvel_eleve)
                db.session.commit()
                
                print(f"✅ Élève test créé: {test_email}")
                print(f"   • ID: {nouvel_eleve.id}")
                print(f"   • Rôle: {nouvel_eleve.role}")
                print(f"   • Visible dans liste? {nouvel_eleve.role == 'eleve'}")
                
                # Vérifier immédiatement dans la liste
                visible = User.query.filter_by(role='eleve', email=test_email).first()
                print(f"   • Trouvé par requête: {'OUI' if visible else 'NON'}")
                
                # Nettoyer
                db.session.delete(nouvel_eleve)
                db.session.commit()
                print(f"   • (Supprimé pour nettoyage)")
                
        except Exception as e:
            print(f"❌ Erreur création: {e}")
            import traceback
            traceback.print_exc()
        
        print("\n7️⃣ DERNIERS ÉLÈVES CRÉÉS (pour debug):")
        print("-" * 40)
        
        derniers_eleves = User.query.filter_by(role='eleve').order_by(User.date_inscription.desc()).limit(5).all()
        
        if derniers_eleves:
            for i, eleve in enumerate(derniers_eleves, 1):
                print(f"\n{i}. {eleve.email}")
                print(f"   • ID: {eleve.id}")
                print(f"   • Nom: {eleve.nom_complet}")
                print(f"   • Date création: {eleve.date_inscription}")
                print(f"   • Enseignant réf ID: {eleve.enseignant_referent_id}")
                print(f"   • Statut: {eleve.statut}")
                print(f"   • Statut paiement: {eleve.statut_paiement}")
        else:
            print("Aucun élève trouvé!")

if __name__ == "__main__":
    debug_eleve_invisible()