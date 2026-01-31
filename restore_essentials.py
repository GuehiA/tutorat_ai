# restore_essentials.py - Version MINIMUM
from app import app, db
from models import User
from werkzeug.security import generate_password_hash
from datetime import datetime

def restore_essentials_only():
    """Restaure SEULEMENT les comptes ESSENTIELS"""
    with app.app_context():
        print("🔧 Restauration des comptes ESSENTIELS seulement...")
        
        # ========== LISTE DES COMPTES ESSENTIELS ==========
        # ⚠️ MODIFIEZ CETTE LISTE AVEC VOS VRAIS COMPTES ESSENTIELS
        
        essential_users = [
            # FORMAT: (username, nom_complet, email, password, role, [specialite si enseignant])
            
            # 1. ADMIN (devrait déjà exister, mais au cas où)
            ('admin', 'Admin Principal', 'admin@tutorat.com', 'AdminSecure123!', 'admin', None),
            
            # 2. ENSEIGNANTS ESSENTIELS
            ('prof_principal', 'Enseignant Principal', 'enseignant.principal@tutorat.com', 'ProfSecure123!', 'enseignant', 'Mathématiques'),
            
            # 3. ÉLÈVES ESSENTIELS - ceux que vous utilisez POUR TESTER
            ('chrys', 'Chrys Mamadou', 'chrys.mamadou@gmail.com', 'ChrysSecure123!', 'eleve', None),
            
            # AJOUTEZ D'AUTRES ÉLÈVES que vous utilisez RÉGULIÈREMENT pour tester :
            # ('test_eleve', 'Élève Test', 'test.eleve@tutorat.com', 'TestSecure123!', 'eleve', None),
            # ('demo_eleve', 'Élève Démo', 'demo@tutorat.com', 'DemoSecure123!', 'eleve', None),
        ]
        # ========== FIN DE LA LISTE ==========
        
        created = 0
        existing = 0
        
        print(f"📋 {len(essential_users)} comptes essentiels à vérifier...")
        print("=" * 60)
        
        for username, nom, email, pwd, role, specialite in essential_users:
            # Vérifier existence
            if User.query.filter_by(email=email).first():
                print(f"✅ EXISTE DÉJÀ: {email} ({role})")
                existing += 1
                continue
            
            # Créer le compte
            try:
                user = User(
                    username=username,
                    nom_complet=nom,
                    email=email,
                    role=role,
                    statut='actif',
                    statut_paiement='paye' if role in ['admin', 'enseignant'] else 'essai_gratuit',
                    date_inscription=datetime.utcnow(),
                    email_verifie=True
                )
                
                # Configuration par rôle
                if role == 'enseignant':
                    user.taux_commission = 20.0
                    user.specialite = specialite or 'Général'
                    user.methode_versement = 'interac'
                    user.frequence_versement = 'mensuel'
                
                user.mot_de_passe_hash = generate_password_hash(pwd)
                db.session.add(user)
                created += 1
                print(f"➕ CRÉÉ: {email} ({role})")
                
            except Exception as e:
                print(f"❌ ERREUR {email}: {e}")
        
        db.session.commit()
        
        # Résumé
        print("\n" + "=" * 60)
        print("📊 RÉSULTAT:")
        print(f"   • Comptes existants: {existing}")
        print(f"   • Nouveaux créés: {created}")
        print(f"   • Total essentiels: {existing + created}")
        
        # Identifiants
        if created > 0:
            print("\n🔐 IDENTIFIANTS CRÉÉS (à changer!):")
            for username, nom, email, pwd, role, specialite in essential_users:
                print(f"   {role.upper():10} : {email:30} / {pwd}")
        
        print("\n🎉 Essentiels restaurés! Maintenant:")
        print("   1. Testez la connexion avec ces comptes")
        print("   2. Changez les mots de passe")
        print("   3. Ajoutez les autres utilisateurs via l'interface admin")
        
        return True

if __name__ == "__main__":
    restore_essentials_only()