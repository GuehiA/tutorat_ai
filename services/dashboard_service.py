# services/dashboard_service.py
from sqlalchemy import func, case, and_
from sqlalchemy.orm import joinedload
from models import db, User, Niveau, Matiere, Unite, Lecon, Exercice, TestSommatif, Commission, VersementManuel
from .cache_service import timed_cache
import logging
import time

logger = logging.getLogger(__name__)

class DashboardService:
    """Service optimisé pour le dashboard admin"""
    
    def __init__(self, lang='fr'):
        self.lang = lang
        self.start_time = time.time()
    
    def log_time(self, operation):
        """Logger le temps d'exécution"""
        elapsed = time.time() - self.start_time
        logger.info(f"⏱️ {operation}: {elapsed:.3f}s")
    
    @timed_cache(timeout=300)  # Cache 5 minutes
    def get_all_stats(self):
        """Récupère TOUTES les statistiques en UNE SEULE REQUÊTE"""
        logger.info("🚀 Chargement de toutes les statistiques...")
        self.start_time = time.time()
        
        try:
            # 1. Statistiques principales en UNE SEULE requête
            main_stats = db.session.query(
                func.count(case((User.role == 'enseignant', 1), else_=None)).label('enseignants'),
                func.count(case((User.role == 'eleve', 1), else_=None)).label('eleves'),
                func.count(Lecon.id).label('lecons'),
                func.count(Exercice.id).label('exercices'),
                func.count(TestSommatif.id).label('tests')
            ).select_from(User).outerjoin(Lecon).outerjoin(Exercice).outerjoin(TestSommatif).first()
            
            self.log_time("Statistiques principales")
            
            # 2. Niveaux avec toutes leurs relations (optimisé)
            niveaux = Niveau.query.options(
                db.selectinload(Niveau.matieres)
                .selectinload(Matiere.unites)
                .selectinload(Unite.lecons)
                .selectinload(Lecon.exercices),
                db.selectinload(Niveau.matieres)
                .selectinload(Matiere.unites)
                .selectinload(Unite.tests)
            ).order_by(Niveau.id).all()
            
            self.log_time("Chargement niveaux")
            
            # 3. Répartition élèves par niveau
            eleves_par_niveau = db.session.query(
                Niveau.nom,
                func.count(User.id)
            ).outerjoin(User, and_(
                Niveau.id == User.niveau_id,
                User.role == 'eleve'
            )).group_by(Niveau.id).all()
            
            self.log_time("Répartition élèves")
            
            # 4. Statistiques de monétisation (une seule requête)
            monetization = db.session.query(
                func.coalesce(func.sum(Commission.montant_commission), 0).label('total_commissions'),
                func.coalesce(func.sum(
                    case((Commission.statut.in_(['pending', 'paiement_manuel']), Commission.montant_commission), else_=0)
                ), 0).label('pending_payments'),
                func.count(VersementManuel.id).label('payments_count'),
                func.count(db.distinct(
                    case((Commission.montant_commission > 0, Commission.enseignant_id))
                )).label('active_teachers')
            ).select_from(Commission).outerjoin(VersementManuel).first()
            
            self.log_time("Statistiques monétisation")
            
            # 5. Paiements récents
            recent_payments = db.session.query(
                VersementManuel.id,
                User.nom_complet.label('enseignant_nom'),
                User.email,
                VersementManuel.email_interac,
                VersementManuel.montant_total,
                VersementManuel.montant_net,
                VersementManuel.statut,
                VersementManuel.date_demande,
                VersementManuel.reference_interac
            ).join(User, VersementManuel.enseignant_id == User.id)\
             .filter(User.role == 'enseignant')\
             .order_by(VersementManuel.date_demande.desc())\
             .limit(10)\
             .all()
            
            self.log_time("Paiements récents")
            
            # 6. Commissions enseignants
            teacher_commissions = self.get_teacher_commissions()
            
            self.log_time("Commissions enseignants")
            
            result = {
                'stats': {
                    'enseignants_count': main_stats.enseignants or 0,
                    'eleves_count': main_stats.eleves or 0,
                    'lecons_count': main_stats.lecons or 0,
                    'exercices_count': main_stats.exercices or 0,
                    'total_tests': main_stats.tests or 0
                },
                'niveaux': [self._format_niveau(n) for n in niveaux],
                'eleves_par_niveau': [[n[0], n[1]] for n in eleves_par_niveau],
                'monetization_stats': {
                    'total_commissions': float(monetization.total_commissions),
                    'pending_payments': float(monetization.pending_payments),
                    'payments_count': monetization.payments_count,
                    'active_teachers': monetization.active_teachers
                },
                'recent_payments': [self._format_payment(p) for p in recent_payments],
                'teacher_commissions': teacher_commissions
            }
            
            logger.info(f"✅ Dashboard chargé en {time.time() - self.start_time:.2f}s")
            return result
            
        except Exception as e:
            logger.error(f"❌ Erreur dans get_all_stats: {e}")
            import traceback
            logger.error(traceback.format_exc())
            # Retourner des données par défaut en cas d'erreur
            return self._get_default_stats()
    
    def get_teacher_commissions(self):
        """Récupère les commissions par enseignant"""
        try:
            # Requête pour les commissions
            teachers = db.session.query(
                User.id,
                User.nom_complet,
                User.email,
                func.coalesce(func.sum(Commission.montant_commission), 0).label('total_commissions'),
                func.coalesce(func.sum(
                    case((Commission.statut.in_(['pending', 'paiement_manuel']), Commission.montant_commission), else_=0)
                ), 0).label('pending'),
                func.coalesce(func.sum(
                    case((Commission.statut.in_(['approved', 'paid', 'complete']), Commission.montant_commission), else_=0)
                ), 0).label('paid')
            ).outerjoin(Commission, User.id == Commission.enseignant_id)\
             .filter(User.role == 'enseignant')\
             .group_by(User.id, User.nom_complet, User.email)\
             .order_by(db.desc('total_commissions'))\
             .limit(20)\
             .all()
            
            result = []
            for t in teachers:
                # Compter les élèves séparément
                students_count = db.session.query(func.count(User.id))\
                    .filter_by(enseignant_referent_id=t.id, role="eleve")\
                    .scalar() or 0
                
                # Dernier paiement
                last_payment = db.session.query(VersementManuel.date_versement)\
                    .filter_by(enseignant_id=t.id, statut='complete')\
                    .order_by(VersementManuel.date_versement.desc())\
                    .first()
                
                result.append({
                    'id': t.id,
                    'nom_complet': t.nom_complet or 'N/A',
                    'email': t.email or '',
                    'total_commissions': float(t.total_commissions),
                    'pending': float(t.pending),
                    'paid': float(t.paid),
                    'students_count': students_count,
                    'last_payment': last_payment[0].strftime('%Y-%m-%d') if last_payment else ('Never' if self.lang == 'en' else 'Jamais')
                })
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Erreur get_teacher_commissions: {e}")
            return []
    
    def _format_niveau(self, niveau):
        """Formate un niveau pour le JSON"""
        return {
            'id': niveau.id,
            'nom': niveau.nom_en if self.lang == 'en' and niveau.nom_en else niveau.nom,
            'matieres': [self._format_matiere(m) for m in niveau.matieres] if niveau.matieres else []
        }
    
    def _format_matiere(self, matiere):
        """Formate une matière pour le JSON"""
        return {
            'id': matiere.id,
            'nom': matiere.nom_en if self.lang == 'en' and matiere.nom_en else matiere.nom,
            'unites': [self._format_unite(u) for u in matiere.unites] if matiere.unites else []
        }
    
    def _format_unite(self, unite):
        """Formate une unité pour le JSON"""
        return {
            'id': unite.id,
            'nom': unite.nom_en if self.lang == 'en' and unite.nom_en else unite.nom,
            'lecons': [{'id': l.id, 'titre': l.titre_en if self.lang == 'en' and l.titre_en else l.titre_fr} 
                      for l in unite.lecons] if unite.lecons else [],
            'tests': [{'id': t.id, 'nom': f"Test #{t.id}"} for t in unite.tests] if unite.tests else []
        }
    
    def _format_payment(self, p):
        """Formate un paiement pour le JSON"""
        return {
            'id': p.id,
            'enseignant_nom': p.enseignant_nom,
            'email': p.email_interac or p.email or '',
            'montant_total': float(p.montant_total or 0),
            'montant_net': float(p.montant_net) if p.montant_net else float(p.montant_total or 0),
            'statut': p.statut or 'demande',
            'date_demande': p.date_demande.isoformat() if p.date_demande else None,
            'date': p.date_demande.strftime('%Y-%m-%d') if p.date_demande else 'N/A',
            'email_interac': p.email_interac or '',
            'reference_interac': p.reference_interac or ''
        }
    
    def _get_default_stats(self):
        """Retourne des statistiques par défaut en cas d'erreur"""
        return {
            'stats': {
                'enseignants_count': 0,
                'eleves_count': 0,
                'lecons_count': 0,
                'exercices_count': 0,
                'total_tests': 0
            },
            'niveaux': [],
            'eleves_par_niveau': [],
            'monetization_stats': {
                'total_commissions': 0,
                'pending_payments': 0,
                'payments_count': 0,
                'active_teachers': 0
            },
            'recent_payments': [],
            'teacher_commissions': []
        }
