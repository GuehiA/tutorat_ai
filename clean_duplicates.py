# clean_duplicates.py
"""
NETTOYAGE DES DOUBLONS D'EMAILS/USERNAMES
Exécuter: python clean_duplicates.py
"""

from app import app, db
from models import User
from sqlalchemy import func

def nettoyer_doublons():
    """Nettoie les doublons d'emails et usernames"""
    print("🧹 NETTOYAGE DES DOUBLONS")
    print("=" * 60)
    
    with app.app_context():
        # 1. DOUBLONS D'EMAILS
        print("\n1️⃣ DOUBLONS D'EMAILS:")
        print("-" * 40)
        
        duplicate_emails = db.session.query(
            User.email, func.count(User.id)
        ).group_by(User.email).having(func.count(User.id) > 1).all()
        
        if not duplicate_emails:
            print("✅ Aucun doublon d'email trouvé")
        else:
            print(f"⚠️  {len(duplicate_emails)} email(s) en double trouvé(s)")
            
            for email, count in duplicate_emails:
                print(f"\n📧 {email} ({count} occurrences):")
                
                # Récupérer tous les utilisateurs avec cet email
                users = User.query.filter_by(email=email).order_by(
                    User.date_inscription.desc()
                ).all()
                
                # Garder le plus récent, supprimer les autres
                keeper = users[0]
                to_delete = users[1:]
                
                print(f"   ✅ Gardé: {keeper.username} (ID {keeper.id}) créé le {keeper.date_inscription}")
                
                for user in to_delete:
                    print(f"   🗑️  Supprimé: {user.username} (ID {user.id}) - {user.role}")
                    db.session.delete(user)
            
            db.session.commit()
            print(f"\n✅ {sum([c-1 for e,c in duplicate_emails])} utilisateurs supprimés")
        
        # 2. DOUBLONS D'USERNAMES
        print("\n2️⃣ DOUBLONS D'USERNAMES:")
        print("-" * 40)
        
        duplicate_usernames = db.session.query(
            User.username, func.count(User.id)
        ).group_by(User.username).having(func.count(User.id) > 1).all()
        
        if not duplicate_usernames:
            print("✅ Aucun doublon de username trouvé")
        else:
            print(f"⚠️  {len(duplicate_usernames)} username(s) en double trouvé(s)")
            
            for username, count in duplicate_usernames:
                print(f"\n👤 {username} ({count} occurrences):")
                
                users = User.query.filter_by(username=username).order_by(
                    User.date_inscription.desc()
                ).all()
                
                # Garder le plus récent, supprimer les autres
                keeper = users[0]
                to_delete = users[1:]
                
                print(f"   ✅ Gardé: {keeper.email} (ID {keeper.id})")
                
                for user in to_delete:
                    # Changer le username pour le rendre unique
                    new_username = f"{user.username}_duplicate_{user.id}"
                    user.username = new_username
                    print(f"   🔄 Renommé: {user.email} → {new_username}")
            
            db.session.commit()
            print(f"\n✅ {len(duplicate_usernames)} username(s) corrigé(s)")
        
        # 3. VÉRIFICATION FINALE
        print("\n3️⃣ VÉRIFICATION FINALE:")
        print("-" * 40)
        
        total_emails = db.session.query(func.count(User.email)).scalar()
        unique_emails = db.session.query(func.count(func.distinct(User.email))).scalar()
        
        print(f"📧 Emails: {total_emails} total, {unique_emails} uniques")
        
        if total_emails == unique_emails:
            print("✅ Tous les emails sont maintenant uniques!")
        else:
            print("❌ Il reste des doublons d'emails")
        
        print("\n🎉 Nettoyage terminé!")

if __name__ == "__main__":
    nettoyer_doublons()