# weekly_maintenance.py
"""
Maintenance hebdomadaire - À exécuter chaque lundi
"""

from app import app, db
from models import User, Commission
from sqlalchemy import func, or_
from datetime import datetime, timedelta

def maintenance_hebdomadaire():
    print("🛠️  MAINTENANCE HEBDOMADAIRE")
    print("=" * 60)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    
    with app.app_context():
        print("\n1️⃣ VÉRIFICATION SANTÉ BASE DE DONNÉES:")
        print("-" * 40)
        
        # 1. Problèmes de rôles
        print("🔍 Problèmes de rôles:")
        
        # Élèves avec accents
        eleves_problemes = User.query.filter(
            or_(
                User.role == 'élève',
                User.role == 'Élève',
                User.role == 'Elève'
            )
        ).count()
        
        # Enseignants avec mauvais rôles
        enseignants_problemes = User.query.filter(
            or_(
                User.role == 'teacher',
                User.role == 'Teacher',
                User.role == 'Enseignant'
            )
        ).count()
        
        print(f"   • Élèves avec accents      : {eleves_problemes}")
        print(f"   • Enseignants mauvais rôles: {enseignants_problemes}")
        
        if eleves_problemes + enseignants_problemes > 0:
            print("   ⚠️  Exécutez: python fix_all_routes.py")
        else:
            print("   ✅ Aucun problème de rôle")
        
        # 2. Utilisateurs sans mot de passe
        print("\n🔍 Utilisateurs sans hash mot de passe:")
        
        sans_hash = User.query.filter(
            User.mot_de_passe_hash.is_(None)
        ).count()
        
        print(f"   • Sans hash mot de passe: {sans_hash}")
        
        if sans_hash > 0:
            print("   ⚠️  Problème: ces utilisateurs ne peuvent pas se connecter")
            users = User.query.filter(User.mot_de_passe_hash.is_(None)).limit(5).all()
            for user in users:
                print(f"      - {user.email} ({user.role})")
        else:
            print("   ✅ Tous les utilisateurs peuvent se connecter")
        
        # 3. Élèves avec essai expiré
        print("\n🔍 Élèves avec essai expiré:")
        
        # Calcul approximatif (selon votre logique)
        eleves_essai = User.query.filter_by(
            role='eleve',
            statut_paiement='essai_gratuit'
        ).count()
        
        print(f"   • En essai gratuit: {eleves_essai}")
        
        # 4. Commissions en attente
        print("\n🔍 Commissions:")
        
        commissions_pending = Commission.query.filter_by(statut='pending').count()
        commissions_approved = Commission.query.filter_by(statut='approved').count()
        total_pending = db.session.query(func.sum(Commission.montant_commission)).filter(
            Commission.statut == 'pending'
        ).scalar() or 0
        
        print(f"   • En attente     : {commissions_pending} (${total_pending:.2f})")
        print(f"   • Approuvées     : {commissions_approved}")
        
        # 5. Activité récente
        print("\n📈 ACTIVITÉ RÉCENTE (7 derniers jours):")
        
        date_limite = datetime.now() - timedelta(days=7)
        
        nouveaux_utilisateurs = User.query.filter(
            User.date_inscription >= date_limite
        ).count()
        
        print(f"   • Nouveaux utilisateurs: {nouveaux_utilisateurs}")
        
        # 6. Recommandations
        print("\n🎯 RECOMMANDATIONS:")
        print("-" * 40)
        
        recommendations = []
        
        if eleves_problemes > 0:
            recommendations.append("Corriger les rôles élèves avec accents")
        
        if enseignants_problemes > 0:
            recommendations.append("Corriger les rôles enseignants")
        
        if sans_hash > 0:
            recommendations.append("Définir des mots de passe pour les utilisateurs sans hash")
        
        if commissions_pending > 0:
            recommendations.append(f"Traiter {commissions_pending} commission(s) en attente")
        
        if eleves_essai > 10:  # Seuil arbitraire
            recommendations.append(f"Suivre les {eleves_essai} élèves en essai gratuit")
        
        if recommendations:
            print("   Actions recommandées:")
            for i, rec in enumerate(recommendations, 1):
                print(f"   {i}. {rec}")
        else:
            print("   ✅ Aucune action nécessaire - tout va bien !")
        
        # 7. Sauvegarde des statistiques
        print("\n📊 STATISTIQUES À SAUVEGARDER:")
        print("-" * 40)
        
        stats = {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'total_eleves': User.query.filter_by(role='eleve').count(),
            'total_enseignants': User.query.filter_by(role='enseignant').count(),
            'eleves_essai': eleves_essai,
            'commissions_pending': commissions_pending,
            'commissions_pending_amount': float(total_pending),
            'problemes_roles': eleves_problemes + enseignants_problemes,
            'utilisateurs_sans_hash': sans_hash
        }
        
        print(f"   • Élèves totaux        : {stats['total_eleves']}")
        print(f"   • Enseignants totaux   : {stats['total_enseignants']}")
        print(f"   • Élèves en essai      : {stats['eleves_essai']}")
        print(f"   • Commissions en attente: ${stats['commissions_pending_amount']:.2f}")
        
        print("\n🎉 Maintenance terminée!")

if __name__ == "__main__":
    maintenance_hebdomadaire()