# create_test_users.py
"""
CRÉATION D'UTILISATEURS DE TEST
Exécuter: python create_test_users.py
"""

from app import app, db
from models import User
from werkzeug.security import generate_password_hash
from datetime import datetime, date

def creer_utilisateurs_test():
    """Crée des utilisateurs de test propres"""
    print("🧪 CRÉATION UTILISATEURS DE TEST")
    print("=" * 60)
    
    with app.app_context():
        # Liste des utilisateurs de test à créer
        test_users = [
            # Format: (username, nom_complet, email, role, date_naissance, specialite, taux)
            
            # 1. ÉLÈVES
            ('eleve_test1', 'Élève Test 1', 'eleve1@test.tutorat.com', 'eleve', '2010-05-15', None, None),
            ('eleve_test2', 'Élève Test 2', 'eleve2@test.tutorat.com', 'eleve', '2011-03-22', None, None),
            ('eleve_test3', 'Élève Test 3', 'eleve3@test.tutorat.com', 'eleve', '2010-11-08', None, None),
            
            # 2. ENSEIGNANTS
            ('ens_test1', 'Enseignant Test 1', 'enseignant1@test.tutorat.com', 'enseignant', None, 'Mathématiques', 25.0),
            ('ens_test2', 'Enseignant Test 2', 'enseignant2@test.tutorat.com', 'enseignant', None, 'Français', 20.0),
            
            # 3. ÉLÈVE AKUDE (si vous voulez)
            ('akude_test', 'Élève Akude Test', 'akude@test.tutorat.com', 'eleve', '2010-06-10', None, None),
        ]
        
        created = 0
        skipped = 0
        
        print(f"📋 {len(test_users)} utilisateurs de test à créer...")
        print("-" * 40)
        
        for username, nom_complet, email, role, date_naissance_str, specialite, taux in test_users:
            # Vérifier si existe déjà
            if User.query.filter_by(email=email).first():
                print(f"⏭️  SKIP: {email} existe déjà")
                skipped += 1
                continue
            
            try:
                # Créer l'utilisateur
                user = User(
                    username=username,
                    nom_complet=nom_complet,
                    email=email,
                    role=role,
                    statut='actif',
                    statut_paiement='essai_gratuit' if role == 'eleve' else 'paye',
                    date_inscription=datetime.utcnow(),
                    email_verifie=True
                )
                
                # Date de naissance pour élèves
                if role == 'eleve' and date_naissance_str:
                    year, month, day = map(int, date_naissance_str.split('-'))
                    user.date_naissance = date(year, month, day)
                
                # Propriétés enseignants
                if role == 'enseignant':
                    user.taux_commission = taux
                    user.specialite = specialite
                    user.methode_versement = 'interac'
                    user.frequence_versement = 'mensuel'
                    user.seuil_minimum_paiement = 25.0
                    user.statut_enseignant = 'actif'
                
                # Mot de passe (identique pour tous les tests)
                user.mot_de_passe_hash = generate_password_hash("Test123!")
                
                db.session.add(user)
                created += 1
                print(f"✅ CRÉÉ: {email} ({role})")
                
            except Exception as e:
                print(f"❌ ERREUR {email}: {e}")
        
        db.session.commit()
        
        # RÉSULTAT
        print("\n" + "=" * 60)
        print("📊 RÉSULTAT:")
        print(f"   • Créés: {created}")
        print(f"   • Skippés: {skipped}")
        
        # Identifiants de test
        if created > 0:
            print("\n🔐 IDENTIFIANTS DE TEST:")
            print("   Email / Test123! pour tous")
            print("\n   📧 Emails créés:")
            for username, nom_complet, email, role, *args in test_users:
                print(f"      • {email}")
        
        print("\n🎉 Création terminée!")

if __name__ == "__main__":
    creer_utilisateurs_test()