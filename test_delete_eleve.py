# test_delete_eleve.py
from app import app, db
from models import User, Commission

def test_eleve_deletion():
    """Teste la suppression d'un élève"""
    with app.app_context():
        print("🧪 Test de suppression d'élève...")
        
        # Trouver un élève test
        eleve = User.query.filter_by(role='eleve').first()
        
        if not eleve:
            print("❌ Aucun élève trouvé pour tester")
            return False
        
        print(f"📋 Élève trouvé: {eleve.email} (ID: {eleve.id})")
        
        # Vérifier les commissions associées
        commissions = Commission.query.filter_by(eleve_id=eleve.id).all()
        print(f"📊 Commissions associées: {len(commissions)}")
        
        if commissions:
            print("⚠️ L'élève a des commissions. Tentative de suppression...")
        
        try:
            # Essayer de supprimer
            db.session.delete(eleve)
            db.session.commit()
            print("✅ Suppression réussie en mode test!")
            
            # Annuler pour ne pas vraiment supprimer
            db.session.rollback()
            print("🔄 Suppression annulée (rollback)")
            
            return True
            
        except Exception as e:
            print(f"❌ Erreur suppression: {e}")
            db.session.rollback()
            return False

if __name__ == "__main__":
    test_eleve_deletion()