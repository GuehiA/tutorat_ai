# test_simple_migration.py
from app import app, db
from datetime import datetime, timezone

with app.app_context():
    print("🔍 TEST SIMPLE - Vérification des nouveaux champs uniquement")
    print("=" * 50)
    
    # Juste vérifier que les champs existent
    from models import User
    
    # Vérifier la structure
    columns = [col.name for col in User.__table__.columns]
    nouveaux_champs = ['statut', 'statut_paiement', 'province', 'telephone', 'ville']
    
    for champ in nouveaux_champs:
        if champ in columns:
            print(f"✅ {champ} - PRÉSENT")
        else:
            print(f"❌ {champ} - ABSENT")
    
    # Test de base sans relations complexes
    try:
        user_count = User.query.count()
        print(f"✅ Base accessible - {user_count} utilisateurs trouvés")
    except Exception as e:
        print(f"❌ Erreur accès base: {e}")
    
    print("=" * 50)
    print("Si tout est ✅, la migration a réussi!")