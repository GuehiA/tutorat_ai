# add_final_columns.py
import os
import sys
from sqlalchemy import create_engine, text

def add_final_columns():
    """Ajoute les 3 dernières colonnes manquantes à la table users"""
    print("🔧 Ajout des colonnes finales manquantes...")
    
    # Récupérer DATABASE_URL
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        print("❌ DATABASE_URL non trouvé")
        return False
    
    engine = create_engine(db_url)
    
    # Les 3 colonnes finales à ajouter
    final_columns = [
        ('disponibilites', 'JSON', "DEFAULT '{}'::json"),
        ('note_moyenne', 'FLOAT', 'DEFAULT 0.0'),
        ('nombre_evaluations', 'INTEGER', 'DEFAULT 0'),
    ]
    
    try:
        with engine.connect() as conn:
            added_count = 0
            
            for col_name, col_type, col_default in final_columns:
                # Vérifier si la colonne existe déjà
                check_query = text(f"""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name='users' AND column_name='{col_name}'
                """)
                
                result = conn.execute(check_query).fetchone()
                
                if not result:
                    # Ajouter la colonne
                    alter_query = text(f"""
                        ALTER TABLE users 
                        ADD COLUMN {col_name} {col_type} {col_default}
                    """)
                    
                    print(f"➕ Ajout: {col_name} ({col_type})")
                    conn.execute(alter_query)
                    added_count += 1
                else:
                    print(f"✅ Existe déjà: {col_name}")
            
            conn.commit()
            
            print(f"\n📊 Résultat: {added_count} colonnes ajoutées sur 3")
            
            # Vérification complète
            print("\n🔍 Vérification de toutes les colonnes critiques...")
            critical_columns = [
                'enseignant_referent_id',
                'date_mise_a_jour',
                'methode_versement',
                'email_interac_paiement', 
                'nom_complet_interac',
                'frequence_versement',
                'taux_commission',
                'statut_enseignant',
                'disponibilites',
                'note_moyenne',
                'nombre_evaluations'
            ]
            
            all_present = True
            for col in critical_columns:
                result = conn.execute(text(f"""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name='users' AND column_name='{col}'
                """)).fetchone()
                
                if result:
                    print(f"  ✓ {col}")
                else:
                    print(f"  ✗ {col} - MANQUANTE")
                    all_present = False
            
            if all_present:
                print("\n🎉 TOUTES les colonnes sont présentes!")
            else:
                print("\n⚠️ Certaines colonnes manquent encore!")
            
            # Compte total
            total_query = text("""
                SELECT COUNT(*) 
                FROM information_schema.columns 
                WHERE table_name='users'
            """)
            total_columns = conn.execute(total_query).scalar()
            print(f"\n📈 Total colonnes dans la table users: {total_columns}")
            
            return all_present
            
    except Exception as e:
        print(f"❌ ERREUR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("=" * 50)
    print("MIGRATION FINALE - Colonnes manquantes")
    print("=" * 50)
    
    success = add_final_columns()
    
    if success:
        print("\n✅ Migration finale réussie!")
        print("Votre application devrait maintenant fonctionner.")
        sys.exit(0)
    else:
        print("\n❌ Migration échouée!")
        sys.exit(1)