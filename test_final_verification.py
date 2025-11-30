# test_final_resolution.py
from app import app, db
from models import User, TestResponse, StudentResponse

with app.app_context():
    print("🧪 TEST FINAL - RÉSOLUTION DES CONFLITS")
    print("=" * 50)
    
    try:
        # 1. Test création user
        print("🎯 CRÉATION USER:")
        test_user = User(
            username="test_final",
            email="test@final.com", 
            nom_complet="Test Final",
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
        
        # 2. Test des nouveaux champs
        print("📊 TEST NOUVEAUX CHAMPS:")
        print(f"   ✅ Statut: {test_user.statut}")
        print(f"   ✅ Province: {test_user.province}")
        print(f"   ✅ Ville: {test_user.ville}")
        print(f"   ✅ Méthode est_actif(): {test_user.est_actif()}")
        
        # 3. Test TestResponse
        print("\n🎯 TEST TESTRESPONSE:")
        test_response = TestResponse(
            user_id=test_user.id,
            test_id=1,
            reponses_exercices={"q1": "A"},
            etoiles=4
        )
        db.session.add(test_response)
        db.session.commit()
        print("   ✅ TestResponse créé")
        print(f"   ✅ Relation TestResponse→User: {test_response.user.username}")  # Backref automatique
        
        # 4. Test StudentResponse  
        print("\n🎯 TEST STUDENTRESPONSE:")
        student_response = StudentResponse(
            user_id=test_user.id,
            exercice_id=1,
            reponse_eleve="Ma réponse",
            etoiles=3
        )
        db.session.add(student_response)
        db.session.commit()
        print("   ✅ StudentResponse créé")
        print(f"   ✅ Relation StudentResponse→User: {student_response.user.username}")  # Backref automatique
        
        # 5. Test relations User→autres
        print(f"\n🔗 RELATIONS USER:")
        print(f"   ✅ User→TestResponse: {len(test_user.tests_soumis)} test(s)")
        print(f"   ✅ User→StudentResponse: {len(test_user.reponses_exercices)} réponse(s)")
        
        # 6. Nettoyage
        db.session.delete(student_response)
        db.session.delete(test_response) 
        db.session.delete(test_user)
        db.session.commit()
        print("\n🧹 Nettoyage réussi")
        
        print("\n🎉 TOUS LES CONFLITS SONT RÉSOLUS !")
        print("   ✅ Migration des champs réussie")
        print("   ✅ Relations bidirectionnelles fonctionnelles")
        print("   ✅ Plus d'erreurs de backref")
        
    except Exception as e:
        print(f"\n❌ ERREUR: {e}")
        import traceback
        traceback.print_exc()
        db.session.rollback()