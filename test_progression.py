from app import app
from models import db, User, Exercise, StudentResponse

with app.app_context():
    print("Étudiants disponibles :")
    for u in User.query.all():
        print(f"- {u.username} ({u.nom_complet})")

    print("\nExercices disponibles :")
    for e in Exercise.query.all():
        print(f"- {e.theme} : {e.enonce}")

    # Insérer une réponse d'élève fictive
    eleve = User.query.filter_by(username="student_001").first()
    exercice = Exercise.query.filter_by(theme="équations").first()

    if eleve and exercice:
        reponse = StudentResponse(
            user_id=eleve.id,
            exercise_id=exercice.id,
            reponse_eleve="2x + 3 = 5 donc x = 1",
            analyse_ia="L'élève a oublié de soustraire correctement 3 des deux côtés."
        )
        db.session.add(reponse)
        db.session.commit()
        print("✅ Réponse enregistrée avec succès pour la progression.")

        # Vérifier l'insertion
        res = StudentResponse.query.filter_by(user_id=eleve.id).all()
        print(f"📊 Total de réponses enregistrées pour {eleve.username} : {len(res)}")
    else:
        print("❌ Élève ou exercice introuvable.")
