# fix_accent_roles.py
"""
CORRECTION DES ACCENTS DANS LES RÔLES
Exécuter: python fix_accent_roles.py
"""

from app import app, db
from models import User

def corriger_accents_roles():
    """Corrige tous les rôles avec accents"""
    print("🔧 CORRECTION DES ACCENTS DANS LES RÔLES")
    print("=" * 60)
    
    with app.app_context():
        # Liste des variations avec accent à corriger
        variations_accents = ['élève', 'Élève', 'Elève', 'ELÈVE']
        
        total_corriges = 0
        
        print("\n🔍 RECHERCHE RÔLES AVEC ACCENTS:")
        print("-" * 40)
        
        for variation in variations_accents:
            users = User.query.filter_by(role=variation).all()
            
            if users:
                print(f"\n📋 {variation} → eleve : {len(users)} utilisateur(s)")
                
                for user in users:
                    ancien_role = user.role
                    user.role = 'eleve'
                    total_corriges += 1
                    print(f"   🔄 {user.email:35} : {ancien_role} → eleve")
        
        if total_corriges > 0:
            db.session.commit()
            print(f"\n✅ {total_corriges} utilisateur(s) corrigé(s)")
        else:
            print("\n✅ Aucune correction nécessaire")
        
        # VÉRIFICATION FINALE
        print("\n📊 VÉRIFICATION APRÈS CORRECTION:")
        print("-" * 40)
        
        roles_counts = {}
        roles = ['admin', 'enseignant', 'eleve', 'élève', 'Élève']  # Vérifier tous
        
        for role in roles:
            count = User.query.filter_by(role=role).count()
            if count > 0:
                roles_counts[role] = count
        
        print("Distribution des rôles:")
        for role, count in sorted(roles_counts.items()):
            print(f"   • {role:15} : {count:3} utilisateur(s)")
        
        # Statistiques importantes
        eleves_count = User.query.filter_by(role='eleve').count()
        variations_count = sum([User.query.filter_by(role=v).count() for v in variations_accents])
        
        print(f"\n🎯 ÉLÈVES:")
        print(f"   • Avec role='eleve' : {eleves_count}")
        print(f"   • Avec accents      : {variations_count}")
        
        if variations_count == 0 and eleves_count > 0:
            print("\n🎉 CORRECTION RÉUSSIE ! Tous les élèves ont maintenant role='eleve' (sans accent)")
        elif variations_count > 0:
            print(f"\n⚠️  ATTENTION: {variations_count} utilisateur(s) ont encore des accents")
            print("   Exécutez ce script à nouveau.")
        
        # Afficher la liste complète des élèves
        print("\n📋 LISTE COMPLÈTE DES ÉLÈVES (role='eleve'):")
        print("-" * 40)
        
        eleves = User.query.filter_by(role='eleve').order_by(User.date_inscription.desc()).all()
        
        if eleves:
            for eleve in eleves:
                date_str = eleve.date_inscription.strftime('%Y-%m-%d %H:%M') if eleve.date_inscription else 'N/A'
                print(f"   • [{date_str}] {eleve.email:35} - {eleve.nom_complet}")
        else:
            print("   Aucun élève trouvé avec role='eleve'")
        
        print("\n🎉 Correction terminée!")

def verifier_interface_admin():
    """Vérifie ce que voit l'interface admin"""
    print("\n🔍 VÉRIFICATION INTERFACE ADMIN:")
    print("=" * 60)
    
    with app.app_context():
        # Simuler ce que fait admin/eleves
        from sqlalchemy import or_
        
        # 1. Ce que fait actuellement votre code (sans accent)
        eleves_sans_accent = User.query.filter_by(role='eleve').all()
        
        # 2. Ce que les utilisateurs ont réellement (peut-être avec accent)
        eleves_tous = User.query.filter(
            or_(
                User.role == 'eleve',
                User.role == 'élève',
                User.role == 'Élève',
                User.role == 'Elève'
            )
        ).all()
        
        print(f"📊 Interface admin (recherche 'eleve'): {len(eleves_sans_accent)} élève(s)")
        print(f"📊 Réellement dans la base            : {len(eleves_tous)} élève(s)")
        
        if len(eleves_tous) > len(eleves_sans_accent):
            print(f"\n⚠️  PROBLÈME: {len(eleves_tous) - len(eleves_sans_accent)} élève(s) invisible(s) dans l'interface admin")
            
            # Montrer les invisibles
            emails_sans = {e.email for e in eleves_sans_accent}
            emails_tous = {e.email for e in eleves_tous}
            invisibles = emails_tous - emails_sans
            
            print(f"\n👻 ÉLÈVES INVISIBLES DANS L'INTERFACE ADMIN:")
            for email in invisibles:
                user = User.query.filter_by(email=email).first()
                print(f"   • {email:35} - rôle actuel: '{user.role}'")
        
        # Vérifier le problème de "email existe déjà"
        print("\n🔎 PROBLÈME 'EMAIL EXISTE DÉJÀ':")
        print("-" * 40)
        
        # Chercher Chrys Mamadou
        chrys = User.query.filter_by(email='chrys.mamadou@gmail.com').first()
        if chrys:
            print(f"📧 chrys.mamadou@gmail.com:")
            print(f"   • Existe avec ID: {chrys.id}")
            print(f"   • Rôle: '{chrys.role}'")
            print(f"   • Date création: {chrys.date_inscription}")
            
            # Essayer de créer un nouveau avec le même email
            print(f"\n🧪 Test création avec même email:")
            try:
                if User.query.filter_by(email='chrys.mamadou@gmail.com').first():
                    print("   ❌ Échec: Email existe déjà (normal)")
                else:
                    print("   ✅ Succès: Email disponible (anormal)")
            except Exception as e:
                print(f"   ⚠️  Erreur: {e}")

if __name__ == "__main__":
    corriger_accents_roles()
    verifier_interface_admin()