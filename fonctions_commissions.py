# fonctions_commissions.py - AVEC LES MÊMES NOMS QUE DANS APP.PY
from datetime import datetime
from models import db, Commission, VersementManuel, User
from sqlalchemy import func

print("✅ Import des modèles de commission réussi")

# === EXACTEMENT LES MÊMES FONCTIONS QUE DANS VOTRE IMPORT ===

def creer_commission_apres_paiement(eleve_id, plan_type, montant):
    """Crée une commission après un paiement d'élève"""
    try:
        # Trouver l'élève
        eleve = User.query.get(eleve_id)
        if not eleve or eleve.role != 'eleve':
            print(f"❌ Élève {eleve_id} non trouvé ou n'est pas un élève")
            return None
        
        # Trouver l'enseignant référent
        enseignant_id = eleve.enseignant_referent_id
        if not enseignant_id:
            print(f"❌ Aucun enseignant référent pour l'élève {eleve_id}")
            return None
        
        # Vérifier l'enseignant
        enseignant = User.query.get(enseignant_id)
        if not enseignant or enseignant.role != 'enseignant':
            print(f"❌ Enseignant {enseignant_id} non trouvé ou n'est pas un enseignant")
            return None
        
        # Taux selon le plan
        taux_commission = {
            'basique': 5.0, 'standard': 7.5, 'premium': 10.0,
            'mensuel': 10.0, 'annuel': 15.0, 'gratuit': 0.0
        }.get(plan_type, 5.0)
        
        # Calcul
        montant_commission = montant * (taux_commission / 100)
        
        # Créer la commission
        commission = Commission(
            enseignant_id=enseignant_id,
            eleve_id=eleve_id,
            type_abonnement=plan_type,
            montant_total=montant,
            montant_commission=montant_commission,
            taux_base=taux_commission,
            statut='pending',
            statut_eleve='actif',
            date_paiement_eleve=datetime.utcnow(),
            date_calcul=datetime.utcnow(),
            details_bonus={
                'plan_type': plan_type,
                'taux_applique': taux_commission,
                'montant_original': montant
            }
        )
        
        db.session.add(commission)
        db.session.commit()
        
        print(f"✅ Commission créée: {taux_commission}% pour enseignant {enseignant_id}")
        return commission
        
    except Exception as e:
        print(f"❌ Erreur création commission: {e}")
        db.session.rollback()
        return None


def integrer_commission(eleve_id, plan_type, montant):
    """Alias pour creer_commission_apres_paiement"""
    return creer_commission_apres_paiement(eleve_id, plan_type, montant)


def calculer_commission_enseignant(enseignant_id, date_debut=None, date_fin=None):
    """Calcule les commissions pour un enseignant"""
    try:
        # Si pas de dates, prendre le mois en cours
        if not date_debut or not date_fin:
            date_debut = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            next_month = date_debut.replace(day=28) + datetime.timedelta(days=4)
            date_fin = next_month - datetime.timedelta(days=next_month.day)
        
        # Récupérer les commissions
        commissions = Commission.query.filter(
            Commission.enseignant_id == enseignant_id,
            Commission.date_calcul.between(date_debut, date_fin)
        ).all()
        
        # Calculs
        total_commission = sum(c.montant_commission for c in commissions)
        en_attente = sum(c.montant_commission for c in commissions if c.statut == 'pending')
        payees = sum(c.montant_commission for c in commissions if c.statut == 'paid')
        
        return {
            'total': total_commission,
            'en_attente': en_attente,
            'payees': payees,
            'nombre': len(commissions),
            'commissions': [c.to_dict() for c in commissions] if hasattr(Commission, 'to_dict') else commissions
        }
        
    except Exception as e:
        print(f"⚠️ Erreur calculer_commission_enseignant: {e}")
        return {
            'total': 0,
            'en_attente': 0,
            'payees': 0,
            'nombre': 0,
            'commissions': []
        }


def traiter_versement_manuel(versement_id, action, reference_interac=None, preuve_versement=None):
    """Traite une demande de versement manuel"""
    try:
        versement = VersementManuel.query.get(versement_id)
        if not versement:
            print(f"❌ Versement {versement_id} non trouvé")
            return False, "Versement non trouvé"
        
        if action == 'approuver':
            versement.statut = 'approved'
            versement.date_versement = datetime.utcnow()
            if reference_interac:
                versement.reference_interac = reference_interac
            if preuve_versement:
                versement.preuve_versement = preuve_versement
            
            db.session.commit()
            print(f"✅ Versement {versement_id} approuvé")
            return True, "Versement approuvé"
            
        elif action == 'rejeter':
            versement.statut = 'rejected'
            db.session.commit()
            print(f"✅ Versement {versement_id} rejeté")
            return True, "Versement rejeté"
            
        elif action == 'completer':
            versement.statut = 'complete'
            versement.date_versement = datetime.utcnow()
            if reference_interac:
                versement.reference_interac = reference_interac
            if preuve_versement:
                versement.preuve_versement = preuve_versement
            
            db.session.commit()
            print(f"✅ Versement {versement_id} complété")
            return True, "Versement complété"
            
        else:
            return False, "Action non reconnue"
            
    except Exception as e:
        print(f"❌ Erreur traitement versement: {e}")
        db.session.rollback()
        return False, str(e)


def demander_versement_manuel(enseignant_id, montant_total, email_interac, methode_paiement='interac'):
    """Demande un versement manuel pour un enseignant"""
    try:
        # Vérifier l'enseignant
        enseignant = User.query.get(enseignant_id)
        if not enseignant or enseignant.role != 'enseignant':
            print(f"❌ Enseignant {enseignant_id} non trouvé ou invalide")
            return None, "Enseignant non trouvé"
        
        # Vérifier le solde de commissions
        commissions_pending = Commission.query.filter_by(
            enseignant_id=enseignant_id,
            statut='pending'
        ).all()
        
        solde_pending = sum(c.montant_commission for c in commissions_pending)
        
        if montant_total > solde_pending:
            print(f"⚠️ Montant demandé ({montant_total}) > solde disponible ({solde_pending})")
            return None, "Solde insuffisant"
        
        # Calculer les frais
        frais_transaction = 1.00  # Frais fixes pour Interac
        montant_net = montant_total - frais_transaction
        
        # Créer le versement
        versement = VersementManuel(
            enseignant_id=enseignant_id,
            montant_total=montant_total,
            frais_transaction=frais_transaction,
            montant_net=montant_net,
            email_interac=email_interac,
            methode_paiement=methode_paiement,
            statut='demande',
            date_demande=datetime.utcnow()
        )
        
        db.session.add(versement)
        db.session.commit()
        
        print(f"✅ Demande de versement créée pour enseignant {enseignant_id}")
        return versement, "Demande créée avec succès"
        
    except Exception as e:
        print(f"❌ Erreur demande versement: {e}")
        db.session.rollback()
        return None, str(e)


def completer_versement_manuel(versement_id, reference_interac, preuve_versement=None):
    """Complète un versement manuel"""
    try:
        versement = VersementManuel.query.get(versement_id)
        if not versement:
            print(f"❌ Versement {versement_id} non trouvé")
            return False, "Versement non trouvé"
        
        # Mettre à jour
        versement.statut = 'complete'
        versement.date_versement = datetime.utcnow()
        versement.reference_interac = reference_interac
        
        if preuve_versement:
            versement.preuve_versement = preuve_versement
        
        # Marquer les commissions associées comme payées
        # On pourrait chercher les commissions correspondantes
        commissions = Commission.query.filter_by(
            enseignant_id=versement.enseignant_id,
            statut='pending'
        ).all()
        
        for commission in commissions:
            if commission.montant_commission <= versement.montant_total:
                commission.statut = 'paid'
                commission.date_versement_manuel = datetime.utcnow()
                versement.montant_total -= commission.montant_commission
        
        db.session.commit()
        
        print(f"✅ Versement {versement_id} complété")
        return True, "Versement complété avec succès"
        
    except Exception as e:
        print(f"❌ Erreur complétion versement: {e}")
        db.session.rollback()
        return False, str(e)


# === FONCTIONS UTILES SUPPLEMENTAIRES (si vous en avez besoin ailleurs) ===

def get_commissions_enseignant(enseignant_id, statut=None):
    """Récupère les commissions d'un enseignant"""
    query = Commission.query.filter_by(enseignant_id=enseignant_id)
    
    if statut:
        query = query.filter_by(statut=statut)
    
    return query.order_by(Commission.date_calcul.desc()).all()


def get_versements_enseignant(enseignant_id, statut=None):
    """Récupère les versements d'un enseignant"""
    query = VersementManuel.query.filter_by(enseignant_id=enseignant_id)
    
    if statut:
        query = query.filter_by(statut=statut)
    
    return query.order_by(VersementManuel.date_demande.desc()).all()


def get_solde_commission(enseignant_id):
    """Calcule le solde de commission d'un enseignant"""
    solde = db.session.query(func.sum(Commission.montant_commission)).filter(
        Commission.enseignant_id == enseignant_id,
        Commission.statut == 'pending'
    ).scalar()
    
    return solde or 0.0


print("✅ Module fonctions_commissions chargé avec les 5 fonctions requises")