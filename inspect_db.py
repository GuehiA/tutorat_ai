import sqlite3

conn = sqlite3.connect("tutorat.db")  # Mets ici le nom exact de ta base si différent
cursor = conn.cursor()

# Affiche le schéma de la table "user"
cursor.execute("PRAGMA table_info(user);")
for col in cursor.fetchall():
    print(col)

conn.close()
