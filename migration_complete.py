# migration_complete.py
import os
import sys
from sqlalchemy import create_engine, text

def add_all_missing_columns():
    """Ajoute toutes les colonnes manquantes à la table users"""
    print("🔧 Migration complète des colonnes users...")
    
    # Récupérer DATABASE_URL
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        print("❌ DATABASE_URL non trouvé dans les variables d'environnement")
        return False
    
    engine = create_engine(db_url)
    
    # Toutes les colonnes à ajouter (nom, type, valeur par défaut)
    columns = [
        # --- Colonnes déjà ajoutées ---
        # ('enseignant_referent_id', 'INTEGER', ''),
        # ('date_mise_a_jour', 'TIMESTAMP', ''),
        
        # --- Colonnes manquantes (celles de l'erreur) ---
        ('methode_versement', 'VARCHAR(50)', "DEFAULT 'interac'"),
        ('email_interac_paiement', 'VARCHAR(255)', ''),
        ('nom_complet_interac', 'VARCHAR(255)', ''),
        ('email_paypal', 'VARCHAR(255)', ''),
        ('frequence_versement', 'VARCHAR(20)', "DEFAULT 'mensuel'"),
        ('seuil_minimum_paiement', 'FLOAT', 'DEFAULT 25.00'),
        ('taux_commission', 'FLOAT', 'DEFAULT 20.0'),
        ('specialite', 'VARCHAR(100)', ''),
        ('biographie', 'TEXT', ''),
        ('qualifications', 'TEXT', ''),
        ('experience_annees', 'INTEGER', 'DEFAULT 0'),
        ('telephone_professionnel', 'VARCHAR(20)', ''),
        ('site_web', 'VARCHAR(255)', ''),
        ('linkedin', 'VARCHAR(255)', ''),
        ('statut_enseignant', 'VARCHAR(20)', "DEFAULT 'actif'"),
    ]
    
    try:
        with engine.connect() as conn:
            added_count = 0
            existing_count = 0
            
            for col_name, col_type, col_default in columns:
                # Vérifier si la colonne existe déjà
                check_query = text(f"""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name='users' AND column_name='{col_name}'
                """)
                
                result = conn.execute(check_query).fetchone()
                
                if not result:
                    # Construire la commande SQL
                    default_clause = f' {col_default}' if col_default else ''
                    alter_query = text(f"""
                        ALTER TABLE users 
                        ADD COLUMN {col_name} {col_type}{default_clause}
                    """)
                    
                    print(f"➕ Ajout: {col_name} ({col_type})")
                    conn.execute(alter_query)
                    added_count += 1
                else:
                    print(f"✅ Existe déjà: {col_name}")
                    existing_count += 1
            
            conn.commit()
            
            print(f"\n📊 Résultat:")
            print(f"   • Colonnes ajoutées: {added_count}")
            print(f"   • Colonnes existantes: {existing_count}")
            print(f"   • Total: {added_count + existing_count} colonnes traitées")
            
            # Vérification finale
            total_query = text("""
                SELECT COUNT(*) 
                FROM information_schema.columns 
                WHERE table_name='users'
            """)
            total_columns = conn.execute(total_query).scalar()
            print(f"\n📈 Total colonnes dans la table users: {total_columns}")
            
            return True
            
    except Exception as e:
        print(f"❌ ERREUR lors de la migration: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = add_all_missing_columns()
    if success:
        print("\n🎉 Migration terminée avec succès!")
        sys.exit(0)
    else:
        print("\n💥 Migration échouée!")
        sys.exit(1)