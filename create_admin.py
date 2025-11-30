from app import app, db
from models import User

# Demande les infos à l'utilisateur
username = input("Nom d'utilisateur (username) : ")
nom_complet = input("Nom complet : ")
email = input("Adresse email : ")
mot_de_passe = input("Mot de passe : ")

with app.app_context():
    # Vérifie si l'email existe déjà
    if User.query.filter_by(email=email).first():
        print("⚠️ Cet email existe déjà dans la base.")
    else:
        admin = User(
            username=username,
            nom_complet=nom_complet,
            email=email,
            role="admin"
        )
        admin.mot_de_passe = mot_de_passe  # le setter hash le mot de passe
        db.session.add(admin)
        db.session.commit()
        print(f"✅ Compte administrateur '{username}' créé avec succès !")
