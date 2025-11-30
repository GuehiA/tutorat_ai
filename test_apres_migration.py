# test_apres_migration.py
from app import app, db
from models import User

with app.app_context():
    print("🧪 TEST APRÈS MIGRATION")
    print("=" * 40)
    
    try:
        # 1. Vérification structure
        user_columns = [col.name for col in User.__table__.columns]
        nouveaux_champs = ['statut', 'statut_paiement', 'province', 'telephone', 'ville', 'stripe_customer_id']
        
        print("📋 NOUVEAUX CHAMPS VÉRIFIÉS:")
        for champ in nouveaux_champs:
            status = "✅ PRÉSENT" if champ in user_columns else "❌ ABSENT"
            print(f"   {status} - {champ}")
        
        # 2. Test création user
        print("\n🎯 TEST CRÉATION USER:")
        test_user = User(
            username="test_migration",
            email="test@migration.com",
            nom_complet="Test Migration",
            role="élève", 
            mot_de_passe="test123",
            statut="actif",
            province="QC"
        )
        
        db.session.add(test_user)
        db.session.commit()
        print("   ✅ Création user réussie")
        
        # 3. Test lecture
        user_db = User.query.filter_by(username="test_migration").first()
        print(f"   ✅ Lecture user: {user_db.username} (statut: {user_db.statut})")
        
        # 4. Nettoyage
        db.session.delete(user_db)
        db.session.commit()
        print("   ✅ Nettoyage réussi")
        
        print("\n🎉 MIGRATION ET TEST RÉUSSIS!")
        
    except Exception as e:
        print(f"\n❌ ERREUR: {e}")
        db.session.rollback()