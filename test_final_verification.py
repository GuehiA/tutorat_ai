# test_final_verification.py
"""
Test de vérification après déploiement
"""

from app import app, db
from models import User
from sqlalchemy import or_

def test_apres_deploiement():
    print("🧪 VÉRIFICATION APRÈS DÉPLOIEMENT")
    print("=" * 60)
    
    with app.app_context():
        print("\n1️⃣ ÉTAT DE LA BASE:")
        print("-" * 40)
        
        # Compter les élèves avec les deux méthodes
        eleves_simple = User.query.filter_by(role='eleve').count()
        eleves_tous = User.query.filter(
            or_(User.role == 'eleve', User.role == 'élève')
        ).count()
        
        print(f"📊 Élèves trouvés:")
        print(f"   • Méthode simple (filter_by): {eleves_simple}")
        print(f"   • Méthode complète (or_)   : {eleves_tous}")
        
        if eleves_simple == eleves_tous:
            print("   ✅ PARFAIT ! Aucun élève avec accent")
        else:
            print(f"   ⚠️  {eleves_tous - eleves_simple} élève(s) avec accent")
            print("   Exécutez: python clean_duplicates.py")
        
        print("\n2️⃣ TEST CRÉATION RAPIDE:")
        print("-" * 40)
        
        from datetime import datetime
        from werkzeug.security import generate_password_hash
        
        test_email = f"verif_{datetime.now().strftime('%H%M%S')}@tutorat.com"
        
        try:
            # Créer
            eleve = User(
                username=f"verif{datetime.now().strftime('%H%M%S')}",
                nom_complet="Vérification Finale",
                email=test_email,
                role='eleve',
                statut='actif',
                statut_paiement='essai_gratuit',
                date_inscription=datetime.now()
            )
            eleve.mot_de_passe_hash = generate_password_hash("Verif123!")
            
            db.session.add(eleve)
            db.session.commit()
            
            print(f"✅ Élève créé: {test_email}")
            
            # Tester la visibilité
            visible = User.query.filter(
                or_(User.role == 'eleve', User.role == 'élève'),
                User.email == test_email
            ).first()
            
            print(f"   • Visible: {'✅ OUI' if visible else '❌ NON'}")
            
            # Nettoyer
            db.session.delete(eleve)
            db.session.commit()
            print(f"   • Nettoyé")
            
        except Exception as e:
            print(f"❌ Erreur: {e}")
        
        print("\n3️⃣ INSTRUCTIONS POUR TESTER:")
        print("-" * 40)
        print("🌐 Testez manuellement sur https://tutoratai.com:")
        print("   1. Connectez-vous en admin")
        print("   2. Allez à /admin/eleves - tous les élèves doivent apparaître")
        print("   3. Créez un nouvel élève via /admin/inscrire-eleve")
        print("   4. Vérifiez qu'il apparaît dans la liste")
        print("   5. Testez sa connexion via /login-eleve")
        
        print("\n🎉 Correction terminée !")

if __name__ == "__main__":
    test_apres_deploiement()