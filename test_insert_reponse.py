from app import app
from models import db, User, Exercise, StudentResponse

with app.app_context():
    # Nettoyage pour éviter les doublons
    print("🔁 Suppression des anciennes réponses...")
    StudentResponse.query.delete()
    db.session.commit()

    eleve = User.query.filter_by(username="student_001").first()
    exercice = Exercise.query.filter_by(theme="équations").first()

    if not eleve:
        print("❌ Élève 'student_001' introuvable.")
    elif not exercice:
        print("❌ Aucun exercice avec le thème 'équations'.")
    else:
        reponse = StudentResponse(
            user_id=eleve.id,
            exercise_id=exercice.id,
            reponse_eleve="2x + 3 = 5 donc x = 1",
            analyse_ia="L'élève a bien résolu mais a oublié d'écrire les étapes. 2 étoiles.",
            etoiles=2
        )
        db.session.add(reponse)
        db.session.commit()

        total = StudentResponse.query.filter_by(user_id=eleve.id).count()
        print(f"✅ Réponse ajoutée. Total de réponses pour {eleve.username} : {total}")
