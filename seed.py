from models import db, User, Exercise, Parent, ParentEleve, , Niveau, Matiere
from app import app
from datetime import datetime

def seed_data():
    """Ajoute des données de test SEULEMENT si elles n'existent pas déjà"""
    with app.app_context():
        try:
            print("🌱 Vérification des données de seed...")
            
            # 1. VÉRIFIER si l'admin existe déjà - NE PAS LE RECRÉER
            admin = User.query.filter_by(email="ambroiseguehi@gmail.com").first()
            if admin:
                print(f"✅ Admin existe déjà: {admin.email}")
            else:
                print("ℹ️ Admin non trouvé - utiliser la connexion normale")
            
            # 2. Créer des données de test UNIQUEMENT SI nécessaire
            # Exemple: Vérifier si des élèves existent
            if User.query.filter_by(role="élève").count() == 0:
                print("📝 Création de données de test pour les élèves...")
                
                # Créer un élève de test
                eleve = User(
                    username="test_eleve",
                    nom_complet="Élève Test",
                    email="eleve.test@example.com",
                    role="élève",
                    statut="actif",
                    statut_paiement="essai_gratuit",
                    date_inscription=datetime.utcnow(),
                    date_fin_essai=datetime.utcnow() + datetime.timedelta(days=2)
                )
                eleve.mot_de_passe = "test123"
                db.session.add(eleve)
                
                print("✅ Élève de test créé")
                
                # Autres données de test si besoin...
                # exercices, niveaux, matières, etc.
                
                db.session.commit()
                print("✅ Données de test ajoutées")
            else:
                print("✅ Des élèves existent déjà - pas de données de test ajoutées")
            
        except Exception as e:
            print(f"❌ Erreur dans seed: {e}")
            db.session.rollback()

if __name__ == "__main__":
    # Ce script peut être exécuté manuellement si besoin
    seed_data()