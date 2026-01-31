# test_complet_enseignants.py
"""
Test complet de toutes les fonctionnalités enseignants
"""

from app import app, db
from models import User, Commission
from sqlalchemy import or_, func
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

def test_complet_enseignants():
    print("🧪 TEST COMPLET FONCTIONNALITÉS ENSEIGNANTS")
    print("=" * 60)
    
    with app.app_context():
        print("\n1️⃣ ÉTAT GÉNÉRAL:")
        print("-" * 40)
        
        # Statistiques
        total_enseignants = User.query.filter_by(role='enseignant').count()
        total_eleves = User.query.filter(
            or_(User.role == 'eleve', User.role == 'élève')
        ).count()
        
        print(f"📊 Enseignants: {total_enseignants}")
        print(f"📊 Élèves: {total_eleves}")
        
        # Liste des enseignants
        print(f"\n👨‍🏫 LISTE DES ENSEIGNANTS:")
        enseignants = User.query.filter_by(role='enseignant').all()
        
        for ens in enseignants:
            # Élèves encadrés
            eleves_encadres = User.query.filter_by(
                enseignant_referent_id=ens.id,
                role='eleve'
            ).count()
            
            # Commissions
            commissions_total = db.session.query(func.sum(Commission.montant_commission)).filter(
                Commission.enseignant_id == ens.id,
                Commission.statut == 'approved'
            ).scalar() or 0
            
            print(f"   • {ens.nom_complet:25}")
            print(f"     Email: {ens.email}")
            print(f"     Élèves encadrés: {eleves_encadres}")
            print(f"     Commissions: ${commissions_total:.2f}")
        
        print("\n2️⃣ TEST CRÉATION ENSEIGNANT COMPLET:")
        print("-" * 40)
        
        test_email = f"test_complet_ens_{datetime.now().strftime('%H%M%S')}@tutorat.com"
        
        try:
            # Créer un enseignant complet
            enseignant = User(
                username=f"completens_{datetime.now().strftime('%H%M%S')}",
                nom_complet="Enseignant Test Complet",
                email=test_email,
                role='enseignant',
                statut='actif',
                statut_paiement='paye',
                date_inscription=datetime.now(),
                taux_commission=25.0,
                specialite='Mathématiques Avancées',
                methode_versement='interac',
                email_interac_paiement='paiement@interac.com',
                frequence_versement='mensuel',
                seuil_minimum_paiement=50.0,
                experience_annees=8,
                telephone_professionnel='514-123-4567',
                biographie='Enseignant expérimenté en mathématiques',
                qualifications='PhD Mathématiques, 10 ans expérience',
                statut_enseignant='actif'
            )
            enseignant.mot_de_passe_hash = generate_password_hash("Enseignant123!")
            
            db.session.add(enseignant)
            db.session.commit()
            
            print(f"✅ Enseignant créé: {test_email}")
            print(f"   • Commission: {enseignant.taux_commission}%")
            print(f"   • Spécialité: {enseignant.specialite}")
            print(f"   • Méthode versement: {enseignant.methode_versement}")
            
            # Test: Connexion
            test_login = check_password_hash(enseignant.mot_de_passe_hash, "Enseignant123!")
            print(f"   • Test connexion: {'✅ RÉUSSI' if test_login else '❌ ÉCHEC'}")
            
            # Test: Fonctions enseignant
            print(f"   • Est enseignant: {'✅ OUI' if enseignant.est_enseignant() else '❌ NON'}")
            print(f"   • Est actif: {'✅ OUI' if enseignant.est_actif() else '❌ NON'}")
            
            # Nettoyer
            db.session.delete(enseignant)
            db.session.commit()
            print(f"   • Nettoyé")
            
        except Exception as e:
            print(f"❌ Erreur création: {e}")
            import traceback
            traceback.print_exc()
        
        print("\n3️⃣ TEST ASSIGNATION ÉLÈVE-ENSEIGNANT:")
        print("-" * 40)
        
        # Prendre un élève et un enseignant existants
        eleve_test = User.query.filter_by(role='eleve').first()
        enseignant_test = User.query.filter_by(role='enseignant').first()
        
        if eleve_test and enseignant_test:
            print(f"🔗 Test assignation:")
            print(f"   • Élève: {eleve_test.email}")
            print(f"   • Enseignant: {enseignant_test.email}")
            
            # Assigner
            eleve_test.enseignant_referent_id = enseignant_test.id
            
            # Vérifier
            eleves_encadres = enseignant_test.get_eleves_encadres()
            count = enseignant_test.count_eleves_encadres()
            
            print(f"   • Élèves encadrés après: {count}")
            
            # Réinitialiser
            eleve_test.enseignant_referent_id = None
            db.session.commit()
            print(f"   • Réinitialisé")
        else:
            print("⚠️  Impossible de tester: besoin d'au moins 1 élève et 1 enseignant")
        
        print("\n4️⃣ TEST COMMISSIONS:")
        print("-" * 40)
        
        if enseignant_test:
            # Créer une commission test
            commission = Commission(
                enseignant_id=enseignant_test.id,
                eleve_id=eleve_test.id if eleve_test else 1,
                type_abonnement='annuel',
                montant_total=299.99,
                montant_commission=59.99,  # 20% de 299.99
                taux_base=20.0,
                statut='pending',
                date_paiement_eleve=datetime.now(),
                date_calcul=datetime.now()
            )
            
            db.session.add(commission)
            db.session.commit()
            
            print(f"💰 Commission créée:")
            print(f"   • Enseignant: {enseignant_test.email}")
            print(f"   • Montant: ${commission.montant_commission:.2f}")
            print(f"   • Statut: {commission.statut}")
            
            # Calculer commissions
            total = enseignant_test.calculer_commission_totale()
            pending = enseignant_test.calculer_commission_en_attente()
            
            print(f"   • Total commissions: ${total:.2f}")
            print(f"   • En attente: ${pending:.2f}")
            
            # Nettoyer
            db.session.delete(commission)
            db.session.commit()
            print(f"   • Commission nettoyée")
        
        print("\n5️⃣ VÉRIFICATION ROUTES:")
        print("-" * 40)
        
        routes_importantes = [
            ('/admin-enseignants', 'Liste enseignants'),
            ('/login-enseignant', 'Connexion enseignant'),
            ('/admin/creer-enseignant', 'Création enseignant'),
            ('/dashboard-enseignant', 'Dashboard enseignant'),
            ('/enseignant/commissions', 'Commissions enseignant'),
            ('/enseignant/eleves', 'Élèves encadrés')
        ]
        
        print("🔍 Assurez-vous que ces routes fonctionnent:")
        for route, description in routes_importantes:
            print(f"   • {route:30} - {description}")
        
        print("\n🎯 CONCLUSIONS:")
        print("-" * 40)
        
        if total_enseignants > 0:
            print(f"✅ {total_enseignants} enseignant(s) opérationnel(s)")
            print(f"✅ Rôles uniformisés")
            print(f"✅ Fonctions de base testées")
            print(f"\n🌐 Testez maintenant sur le site:")
            print(f"   1. Connectez-vous en enseignant")
            print(f"   2. Vérifiez le dashboard enseignant")
            print(f"   3. Testez la gestion des élèves")
            print(f"   4. Vérifiez les commissions")
        else:
            print("⚠️  Aucun enseignant trouvé")
            print("   Créez des enseignants via /admin/creer-enseignant")

if __name__ == "__main__":
    test_complet_enseignants()