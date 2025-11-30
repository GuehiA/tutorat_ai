# migration_correction.py
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from models import User
from datetime import datetime, timedelta

def migration_correction():
    with app.app_context():
        print("=== 🔧 CORRECTION MIGRATION ===")
        
        try:
            # Corriger les statuts "gratuit" en "essai_gratuit"
            print("🔄 Correction des statuts 'gratuit'...")
            
            eleves_gratuits = User.query.filter_by(statut_paiement="gratuit").all()
            for eleve in eleves_gratuits:
                eleve.statut_paiement = "essai_gratuit"
                if not eleve.date_fin_essai:
                    # SIMPLIFICATION : utiliser datetime.utcnow() qui fonctionne partout
                    eleve.date_fin_essai = datetime.utcnow() + timedelta(hours=48)
                if not eleve.statut_essai:
                    eleve.statut_essai = "actif"
                print(f"✅ Corrigé: {eleve.username} -> essai_gratuit")
            
            # Corriger les statuts None
            eleves_none = User.query.filter(User.statut_paiement.is_(None)).all()
            for eleve in eleves_none:
                eleve.statut_paiement = "non_paye"
                print(f"✅ Corrigé: {eleve.username} -> non_paye")
            
            db.session.commit()
            print("🎉 Correction terminée !")
            
            # Vérification finale
            print("\n=== 🔍 VÉRIFICATION FINALE ===")
            eleves = User.query.filter_by(role="élève").all()
            for eleve in eleves:
                print(f"👤 {eleve.username}:")
                print(f"   Statut paiement: {eleve.statut_paiement}")
                print(f"   Statut essai: {eleve.statut_essai}")
                print(f"   Date fin essai: {eleve.date_fin_essai}")
                print(f"   Essai actif: {eleve.est_en_essai_gratuit()}")
                print("---")
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Erreur lors de la correction: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    migration_correction()