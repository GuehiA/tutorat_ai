# test_avec_votre_correction.py
from app import app, db
from models import User, TestResponse

with app.app_context():
    print("🧪 TEST AVEC VOTRE CORRECTION")
    print("=" * 45)
    
    try:
        # 1. Vérification que les modèles se chargent sans erreur
        print("✅ Modèles chargés sans erreur")
        
        # 2. Vérification structure User
        user_columns = [col.name for col in User.__table__.columns]
        print(f"📊 User: {len(user_columns)} colonnes")
        
        # 3. Test création user
        print("\n🎯 TEST CRÉATION USER:")
        test_user = User(
            username="test_correction",
            email="test@correction.com",
            nom_complet="Test Correction",
            role="élève",
            mot_de_passe="test123",
            statut="actif", 
            statut_paiement="non_paye",
            province="QC",
            ville="Montréal"
        )
        
        db.session.add(test_user)
        db.session.commit()
        print("   ✅ User créé avec succès")
        
        # 4. Test des nouveaux champs
        print(f"   ✅ Statut: {test_user.statut}")
        print(f"   ✅ Province: {test_user.province}")
        print(f"   ✅ Méthode est_actif(): {test_user.est_actif()}")
        
        # 5. Test relation User → TestResponse
        print(f"   ✅ Relation tests_soumis: {len(test_user.tests_soumis)} tests")
        
        # 6. Test création TestResponse
        print("\n🎯 TEST TESTRESPONSE:")
        test_response = TestResponse(
            user_id=test_user.id,
            test_id=1,  # Suppose qu'un test existe
            reponses_exercices={"q1": "réponse A"},
            etoiles=3
        )
        
        db.session.add(test_response)
        db.session.commit()
        print("   ✅ TestResponse créé avec succès")
        
        # 7. Test relation TestResponse → User
        print(f"   ✅ Accès user depuis TestResponse: {test_response.user.username}")
        
        # 8. Nettoyage
        db.session.delete(test_response)
        db.session.delete(test_user)
        db.session.commit()
        print("\n🧹 Nettoyage réussi")
        
        print("\n🎉 TOUTES LES FONCTIONNALITÉS FONCTIONNENT!")
        print("   ✅ Migration des champs")
        print("   ✅ Relations User-TestResponse") 
        print("   ✅ Méthodes personnalisées")
        
    except Exception as e:
        print(f"\n❌ ERREUR: {e}")
        import traceback
        traceback.print_exc()
        db.session.rollback()