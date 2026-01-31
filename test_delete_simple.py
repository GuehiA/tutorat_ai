from app import app, db
from models import User

print("🧪 Test suppression élève...")

with app.app_context():
    # Trouver un élève
    eleve = User.query.filter_by(role='eleve').first()
    
    if eleve:
        print(f"✅ Élève trouvé: {eleve.email} (ID: {eleve.id})")
        print("🎯 Maintenant testez dans l'interface:")
        print("   1. Allez sur https://tutoratai.com")
        print("   2. Connectez-vous en admin")
        print("   3. Allez à /admin/eleves")
        print(f"   4. Supprimez l'élève ID {eleve.id}")
        print("   5. Vérifiez qu'il n'y a plus d'erreur")
        
        # Vérifier les commissions associées
        from models import Commission
        commissions = Commission.query.filter_by(eleve_id=eleve.id).count()
        print(f"📊 Commissions associées: {commissions}")
    else:
        print("❌ Aucun élève trouvé")
        print("💡 Créez d'abord un élève via l'interface admin")