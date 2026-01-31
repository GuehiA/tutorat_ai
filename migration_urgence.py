# migration_urgence.py
import os
import sys
from datetime import datetime

# Ajoutez le chemin de votre app
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def run_migration():
    """Migration d'urgence pour ajouter enseignant_referent_id"""
    try:
        # Importez après avoir configuré le path
        from app import db, app
        from sqlalchemy import text
        
        with app.app_context():
            print("🔧 Début de la migration d'urgence...")
            
            # 1. Vérifiez si la colonne existe déjà
            check_query = text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='users' AND column_name='enseignant_referent_id'
            """)
            
            result = db.session.execute(check_query).fetchone()
            
            if result:
                print("✅ La colonne enseignant_referent_id existe déjà")
            else:
                # 2. Ajoutez la colonne
                print("➕ Ajout de la colonne enseignant_referent_id...")
                
                alter_query = text("""
                    ALTER TABLE users 
                    ADD COLUMN enseignant_referent_id INTEGER 
                    REFERENCES users(id)
                """)
                
                db.session.execute(alter_query)
                db.session.commit()
                print("✅ Colonne ajoutée avec succès!")
            
            # 3. Vérifiez aussi date_mise_a_jour
            check_date = text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='users' AND column_name='date_mise_a_jour'
            """)
            
            result_date = db.session.execute(check_date).fetchone()
            
            if not result_date:
                print("➕ Ajout de date_mise_a_jour...")
                alter_date = text("""
                    ALTER TABLE users 
                    ADD COLUMN date_mise_a_jour TIMESTAMP
                """)
                db.session.execute(alter_date)
                db.session.commit()
                print("✅ date_mise_a_jour ajoutée!")
            
            print("🎉 Migration complète!")
            
    except Exception as e:
        print(f"❌ ERREUR: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)