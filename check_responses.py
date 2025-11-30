from app import app
from models import db, User, StudentResponse

with app.app_context():
    eleve = User.query.filter_by(username="student_001").first()

    if eleve:
        reps = StudentResponse.query.filter_by(user_id=eleve.id).all()
        print(f"Réponses trouvées : {len(reps)}")
        for r in reps:
            print(f"- Exercice ID: {r.exercise_id}, Étoiles: {r.etoiles}")
    else:
        print("Élève non trouvé.")
