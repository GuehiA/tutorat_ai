# restore_eleves_enseignants.py
from app import app, db
from models import User
from werkzeug.security import generate_password_hash
from datetime import datetime

def restore_eleves_enseignants_seulement():
    """Recrée SEULEMENT les élèves et enseignants manquants (pas les admins)"""
    with app.app_context():
        print("🔧 Restauration élèves et enseignants seulement...")
        
        # ========== LISTE DE VOS ÉLÈVES ==========
        # ⚠️ AJOUTEZ TOUS VOS ÉLÈVES ICI
        
        eleves_data = [
            # FORMAT: (username, nom_complet, email, password, date_naissance_YYYY_MM_DD)
            
            # ESSENTIELS
            ('chrys', 'Chrys Mamadou', 'chrys.mamadou@gmail.com', 'ChrysTemp123!', '2010-05-15'),
            
            # AJOUTEZ TOUS VOS AUTRES ÉLÈVES :
            # ('marie123', 'Marie Dubois', 'marie.dubois@email.com', 'MarieTemp123!', '2011-03-22'),
            # ('pierre456', 'Pierre Martin', 'pierre.martin@email.com', 'PierreTemp123!', '2010-11-08'),
            # ('sophie789', 'Sophie Tremblay', 'sophie.t@email.com', 'SophieTemp123!', '2011-07-14'),
            # ('lucas012', 'Lucas Gagnon', 'lucas.g@email.com', 'LucasTemp123!', '2010-09-30'),
            # ('emma345', 'Emma Bouchard', 'emma.b@email.com', 'EmmaTemp123!', '2011-01-25'),
            
            # ÉLÈVES AKUDE (si c'est un groupe/école spécifique)
            # ('akude1', 'Prénom Akude1', 'akude1@email.com', 'AkudeTemp123!', '2010-06-10'),
            # ('akude2', 'Prénom Akude2', 'akude2@email.com', 'AkudeTemp123!', '2011-02-18'),
            # AJOUTEZ TOUS LES ÉLÈVES AKUDE...
        ]
        
        # ========== LISTE DE VOS ENSEIGNANTS ==========
        # ⚠️ AJOUTEZ TOUS VOS ENSEIGNANTS ICI
        
        enseignants_data = [
            # FORMAT: (username, nom_complet, email, password, specialite, taux_commission)
            
            # ESSENTIELS
            ('prof_math', 'Jean Mathieu', 'jean.mathieu@tutorat.com', 'MathTemp123!', 'Mathématiques', 25.0),
            ('prof_fr', 'Marie Français', 'marie.francais@tutorat.com', 'FrenchTemp123!', 'Français', 20.0),
            
            # AJOUTEZ TOUS VOS AUTRES ENSEIGNANTS :
            # ('prof_science', 'Paul Science', 'paul.science@tutorat.com', 'ScienceTemp123!', 'Sciences', 22.0),
            # ('prof_anglais', 'Alice English', 'alice.english@tutorat.com', 'EnglishTemp123!', 'Anglais', 20.0),
        ]
        
        # ========== EXÉCUTION ==========
        
        created_eleves = 0
        created_enseignants = 0
        
        print(f"📋 {len(eleves_data)} élèves et {len(enseignants_data)} enseignants à restaurer...")
        print("=" * 60)
        
        # 1. RESTAURER LES ÉLÈVES
        print("\n👨‍🎓 RESTAURATION DES ÉLÈVES:")
        for username, nom_complet, email, password, date_naissance_str in eleves_data:
            if User.query.filter_by(email=email).first():
                print(f"  ✅ EXISTE: {email}")
                continue
            
            try:
                # Convertir date_naissance
                date_naissance = datetime.strptime(date_naissance_str, '%Y-%m-%d').date() if date_naissance_str else None
                
                eleve = User(
                    username=username,
                    nom_complet=nom_complet,
                    email=email,
                    role='eleve',
                    statut='actif',
                    statut_paiement='essai_gratuit',
                    date_inscription=datetime.utcnow(),
                    email_verifie=True,
                    date_naissance=date_naissance
                )
                eleve.mot_de_passe_hash = generate_password_hash(password)
                db.session.add(eleve)
                created_eleves += 1
                print(f"  ➕ CRÉÉ: {email}")
                
            except Exception as e:
                print(f"  ❌ ERREUR {email}: {e}")
        
        # 2. RESTAURER LES ENSEIGNANTS
        print("\n👨‍🏫 RESTAURATION DES ENSEIGNANTS:")
        for username, nom_complet, email, password, specialite, taux_commission in enseignants_data:
            if User.query.filter_by(email=email).first():
                print(f"  ✅ EXISTE: {email}")
                continue
            
            try:
                enseignant = User(
                    username=username,
                    nom_complet=nom_complet,
                    email=email,
                    role='enseignant',
                    statut='actif',
                    statut_paiement='paye',
                    date_inscription=datetime.utcnow(),
                    email_verifie=True,
                    taux_commission=taux_commission,
                    specialite=specialite,
                    methode_versement='interac',
                    frequence_versement='mensuel',
                    seuil_minimum_paiement=25.0,
                    statut_enseignant='actif'
                )
                enseignant.mot_de_passe_hash = generate_password_hash(password)
                db.session.add(enseignant)
                created_enseignants += 1
                print(f"  ➕ CRÉÉ: {email} ({specialite})")
                
            except Exception as e:
                print(f"  ❌ ERREUR {email}: {e}")
        
        # Sauvegarder
        db.session.commit()
        
        # RÉSULTAT
        print("\n" + "=" * 60)
        print("📊 RÉSULTAT:")
        print(f"   • Élèves créés: {created_eleves}")
        print(f"   • Enseignants créés: {created_enseignants}")
        print(f"   • Total nouveaux: {created_eleves + created_enseignants}")
        
        # Statistiques finales
        total_eleves = User.query.filter_by(role='eleve').count()
        total_enseignants = User.query.filter_by(role='enseignant').count()
        print(f"   • Total élèves dans DB: {total_eleves}")
        print(f"   • Total enseignants dans DB: {total_enseignants}")
        
        # Identifiants
        if created_eleves + created_enseignants > 0:
            print("\n🔐 IDENTIFIANTS TEMPORAIRES (à changer!):")
            
            if created_eleves > 0:
                print("\n  ÉLÈVES:")
                for username, nom_complet, email, password, date_naissance_str in eleves_data:
                    print(f"    {email} / {password}")
            
            if created_enseignants > 0:
                print("\n  ENSEIGNANTS:")
                for username, nom_complet, email, password, specialite, taux_commission in enseignants_data:
                    print(f"    {email} / {password} ({specialite})")
        
        print("\n⚠️ CHANGEZ TOUS LES MOTS DE PASSE IMMÉDIATEMENT!")
        print("🎉 Restauration élèves/enseignants terminée!")
        
        return True

if __name__ == "__main__":
    restore_eleves_enseignants_seulement()