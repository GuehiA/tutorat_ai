# create_missing_tables.py
from app import app, db
from sqlalchemy import text

def create_missing_tables():
    """Crée les tables manquantes de la base de données"""
    with app.app_context():
        print("🔧 Création des tables manquantes...")
        
        # Liste des tables ESSENTIELLES à créer
        tables_to_create = [
            {
                'name': 'commissions',
                'sql': """
                    CREATE TABLE IF NOT EXISTS commissions (
                        id SERIAL PRIMARY KEY,
                        enseignant_id INTEGER NOT NULL REFERENCES users(id),
                        eleve_id INTEGER NOT NULL REFERENCES users(id),
                        type_abonnement VARCHAR(20) NOT NULL,
                        montant_total FLOAT NOT NULL,
                        montant_commission FLOAT NOT NULL,
                        taux_base FLOAT NOT NULL,
                        details_bonus JSON,
                        statut VARCHAR(20),
                        statut_eleve VARCHAR(20),
                        date_paiement_eleve TIMESTAMP NOT NULL,
                        date_calcul TIMESTAMP,
                        date_approbation TIMESTAMP,
                        date_versement_manuel TIMESTAMP,
                        reference_interac VARCHAR(100),
                        email_interac VARCHAR(255),
                        preuve_versement VARCHAR(255)
                    )
                """
            },
            {
                'name': 'versements_manuels',
                'sql': """
                    CREATE TABLE IF NOT EXISTS versements_manuels (
                        id SERIAL PRIMARY KEY,
                        enseignant_id INTEGER NOT NULL REFERENCES users(id),
                        montant_total FLOAT NOT NULL,
                        frais_transaction FLOAT DEFAULT 1.00,
                        montant_net FLOAT NOT NULL,
                        email_interac VARCHAR(255) NOT NULL,
                        methode_paiement VARCHAR(20) DEFAULT 'interac',
                        date_demande TIMESTAMP,
                        date_versement TIMESTAMP,
                        statut VARCHAR(20) DEFAULT 'demande',
                        reference_interac VARCHAR(100),
                        preuve_versement VARCHAR(255),
                        notes_admin TEXT
                    )
                """
            },
            {
                'name': 'info_versement_enseignant',
                'sql': """
                    CREATE TABLE IF NOT EXISTS info_versement_enseignant (
                        id SERIAL PRIMARY KEY,
                        enseignant_id INTEGER UNIQUE NOT NULL REFERENCES users(id),
                        methode_versement VARCHAR(50) DEFAULT 'interac',
                        email_interac VARCHAR(255),
                        nom_complet_interac VARCHAR(255),
                        email_paypal VARCHAR(255),
                        frequence_versement VARCHAR(20) DEFAULT 'mensuel',
                        seuil_minimum FLOAT DEFAULT 25.00,
                        date_mise_a_jour TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """
            }
        ]
        
        # Vérifier et créer chaque table
        for table in tables_to_create:
            try:
                # Vérifier si la table existe
                check = db.session.execute(
                    text(f"SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = '{table['name']}')")
                ).scalar()
                
                if not check:
                    print(f"➕ Création table: {table['name']}")
                    db.session.execute(text(table['sql']))
                    db.session.commit()
                    print(f"   ✅ Table {table['name']} créée")
                else:
                    print(f"✅ Table {table['name']} existe déjà")
                    
            except Exception as e:
                print(f"❌ Erreur table {table['name']}: {e}")
                db.session.rollback()
        
        # Créer aussi les autres tables du modèle si nécessaire
        other_tables = [
            'exercice_remediation',
            'remediation_suggestion',
            'parents',
            'parent_eleve',
            'niveaux',
            'matieres',
            'unites',
            'lecons',
            'exercices',
            'test_exercices',
            'tests_sommatifs',
            'student_responses',
            'test_responses'
        ]
        
        print("\n🔍 Vérification autres tables...")
        for table_name in other_tables:
            try:
                exists = db.session.execute(
                    text(f"SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = '{table_name}')")
                ).scalar()
                
                if exists:
                    print(f"   ✅ {table_name}")
                else:
                    print(f"   ❌ {table_name} - MANQUANTE")
            except:
                print(f"   ⚠️ {table_name} - Erreur vérification")
        
        print("\n🎉 Vérification terminée!")
        return True

if __name__ == "__main__":
    create_missing_tables()