import os
import re
from pathlib import Path
import sqlite3

def analyser_fichiers_inutiles(racine_app='.'):
    """
    Analyse l'application pour trouver les fichiers inutiles
    """
    print("🔍 Analyse des fichiers inutiles en cours...\n")
    
    # Dossier racine de l'application
    app_root = Path(racine_app)
    
    # Fichiers essentiels Flask
    fichiers_essentiels = {
        'app.py', 'run.py', 'wsgi.py', 'application.py',
        'requirements.txt', 'Pipfile', 'Pipfile.lock',
        'config.py', 'config.json', '.env', '.flaskenv',
        'static/', 'templates/', 'migrations/'
    }
    
    # Extensions de fichiers à analyser
    extensions_python = {'.py'}
    extensions_templates = {'.html', '.jinja', '.jinja2'}
    extensions_static = {'.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico'}
    extensions_docs = {'.md', '.txt', '.rst'}
    extensions_config = {'.json', '.yaml', '.yml', '.ini', '.cfg'}
    
    # Fichiers système à ignorer
    fichiers_ignores = {
        '__pycache__/', '.git/', '.vscode/', '.idea/', 'venv/', 'env/',
        '.gitignore', '.dockerignore', '.env.example', 'README.md'
    }
    
    # Collecte de tous les fichiers
    tous_fichiers = []
    for root, dirs, files in os.walk(app_root):
        for file in files:
            chemin_complet = Path(root) / file
            chemin_relatif = chemin_complet.relative_to(app_root)
            tous_fichiers.append(str(chemin_relatif))
    
    # Analyse des imports Python
    imports_trouves = analyser_imports_python(app_root)
    
    # Analyse des références dans les templates
    references_templates = analyser_references_templates(app_root)
    
    # Analyse des références statiques
    references_static = analyser_references_statiques(app_root)
    
    # Analyse de la base de données (si SQLite)
    references_db = analyser_references_db(app_root)
    
    # Identification des fichiers inutiles
    fichiers_inutiles = identifier_fichiers_inutiles(
        tous_fichiers, imports_trouves, references_templates, 
        references_static, references_db, fichiers_ignores
    )
    
    # Génération du rapport
    generer_rapport(fichiers_inutiles, len(tous_fichiers))
    
    return fichiers_inutiles

def analyser_imports_python(app_root):
    """
    Analyse tous les fichiers Python pour trouver les imports
    """
    imports = set()
    app_root = Path(app_root)
    
    for fichier_py in app_root.rglob("*.py"):
        try:
            with open(fichier_py, 'r', encoding='utf-8') as f:
                contenu = f.read()
                
            # Recherche des imports
            motifs_import = [
                r'from\s+([\w\.]+)\s+import',
                r'import\s+([\w\.]+)',
                r'@app\.route\([^)]+\)\s*def\s+(\w+)',
                r'class\s+(\w+)',
                r'def\s+(\w+)',
            ]
            
            for motif in motifs_import:
                matches = re.findall(motif, contenu)
                for match in matches:
                    if isinstance(match, tuple):
                        match = match[0]
                    imports.add(match.strip())
                    
        except Exception as e:
            print(f"⚠️ Erreur lecture {fichier_py}: {e}")
    
    return imports

def analyser_references_templates(app_root):
    """
    Analyse les références dans les templates
    """
    references = set()
    app_root = Path(app_root)
    
    for template_file in app_root.rglob("*.html"):
        try:
            with open(template_file, 'r', encoding='utf-8') as f:
                contenu = f.read()
                
            # Recherche des includes et extends
            motifs_template = [
                r'{%\s*include\s+[\'"]([^\'"]+)[\'"]',
                r'{%\s*extends\s+[\'"]([^\'"]+)[\'"]',
                r'url_for\([^)]*[\'"]([^\'"]+)[\'"]',
                r'href=[\'"]([^\'"]+\.html)[\'"]',
                r'src=[\'"]([^\'"]+)[\'"]',
            ]
            
            for motif in motifs_template:
                matches = re.findall(motif, contenu)
                for match in matches:
                    references.add(match.strip())
                    
        except Exception as e:
            print(f"⚠️ Erreur lecture template {template_file}: {e}")
    
    return references

def analyser_references_statiques(app_root):
    """
    Analyse les références aux fichiers statiques
    """
    references = set()
    app_root = Path(app_root)
    
    # Analyse des fichiers HTML
    for html_file in app_root.rglob("*.html"):
        try:
            with open(html_file, 'r', encoding='utf-8') as f:
                contenu = f.read()
                
            # Recherche des ressources statiques
            motifs_static = [
                r'src=[\'"]([^\'"]*\.[css|js|png|jpg|jpeg|gif|svg|ico]+)[\'"]',
                r'href=[\'"]([^\'"]*\.[css]+)[\'"]',
                r'url\([\'"]?([^\'")]+)[\'"]?\)',
                r'url_for\([^)]*static[^)]*[\'"]([^\'"]+)[\'"]',
            ]
            
            for motif in motifs_static:
                matches = re.findall(motif, contenu)
                for match in matches:
                    references.add(match.strip())
                    
        except Exception as e:
            print(f"⚠️ Erreur lecture HTML {html_file}: {e}")
    
    # Analyse des fichiers CSS
    for css_file in app_root.rglob("*.css"):
        try:
            with open(css_file, 'r', encoding='utf-8') as f:
                contenu = f.read()
                
            # Recherche des URLs dans CSS
            motifs_css = [
                r'url\([\'"]?([^\'")]+)[\'"]?\)',
                r'@import\s+[\'"]([^\'"]+)[\'"]',
            ]
            
            for motif in motifs_css:
                matches = re.findall(motif, contenu)
                for match in matches:
                    references.add(match.strip())
                    
        except Exception as e:
            print(f"⚠️ Erreur lecture CSS {css_file}: {e}")
    
    return references

def analyser_references_db(app_root):
    """
    Analyse les références dans la base de données (SQLite)
    """
    references = set()
    app_root = Path(app_root)
    
    # Recherche des fichiers de base de données
    for db_file in app_root.rglob("*.db"):
        try:
            conn = sqlite3.connect(db_file)
            cursor = conn.cursor()
            
            # Récupère les noms des tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()
            
            for table in tables:
                references.add(f"db_table:{table[0]}")
                
            conn.close()
            
        except Exception as e:
            print(f"⚠️ Erreur lecture DB {db_file}: {e}")
    
    return references

def identifier_fichiers_inutiles(tous_fichiers, imports, templates_ref, static_ref, db_ref, ignores):
    """
    Identifie les fichiers potentiellement inutiles
    """
    fichiers_utilises = set()
    fichiers_inutiles = []
    
    # Ajouter les références trouvées
    for ref in templates_ref:
        fichiers_utilises.add(ref)
    
    for ref in static_ref:
        fichiers_utilises.add(ref)
    
    # Analyser chaque fichier
    for fichier in tous_fichiers:
        # Ignorer les fichiers système
        if any(fichier.startswith(ignore) for ignore in ignores):
            continue
            
        # Vérifier si le fichier est référencé
        nom_fichier = Path(fichier).name
        nom_sans_ext = Path(fichier).stem
        
        est_utilise = (
            nom_fichier in fichiers_utilises or
            nom_sans_ext in imports or
            any(ref in fichier for ref in fichiers_utilises) or
            any(nom_sans_ext in imp for imp in imports)
        )
        
        if not est_utilise:
            # Vérifications supplémentaires
            if not est_fichier_essentiel(fichier):
                fichiers_inutiles.append(fichier)
    
    return fichiers_inutiles

def est_fichier_essentiel(fichier):
    """
    Détermine si un fichier est essentiel au fonctionnement
    """
    essentials = {
        'app.py', 'run.py', 'config.py', 'requirements.txt',
        '__init__.py', 'models.py', 'routes.py', 'forms.py',
        'create_tables.py', 'seed.py'
    }
    
    chemin = Path(fichier)
    return (
        chemin.name in essentials or
        chemin.name.startswith('.') or
        chemin.suffix in {'.py', '.html', '.css', '.js'} and chemin.parent.name in {'templates', 'static'}
    )

def generer_rapport(fichiers_inutiles, total_fichiers):
    """
    Génère un rapport détaillé des fichiers inutiles
    """
    print("=" * 60)
    print("📊 RAPPORT D'ANALYSE DES FICHIERS INUTILES")
    print("=" * 60)
    print(f"Total fichiers analysés: {total_fichiers}")
    print(f"Fichiers potentiellement inutiles: {len(fichiers_inutiles)}")
    print("-" * 60)
    
    if fichiers_inutiles:
        print("🗑️ FICHIERS POTENTIELLEMENT INUTILES:")
        print("-" * 60)
        
        # Grouper par type
        par_type = {}
        for fichier in fichiers_inutiles:
            ext = Path(fichier).suffix.lower()
            if ext not in par_type:
                par_type[ext] = []
            par_type[ext].append(fichier)
        
        for ext_type, fichiers in sorted(par_type.items()):
            print(f"\n📁 {ext_type or 'SANS EXTENSION'} ({len(fichiers)} fichiers):")
            for fichier in sorted(fichiers):
                print(f"   ❌ {fichier}")
        
        print("\n" + "=" * 60)
        print("💡 RECOMMANDATIONS:")
        print("1. Sauvegardez votre application avant suppression")
        print("2. Testez après chaque suppression")
        print("3. Vérifiez les dépendances manuelles")
        print("4. Les fichiers de configuration peuvent être essentiels")
        
        # Générer un script de nettoyage
        generer_script_nettoyage(fichiers_inutiles)
    else:
        print("🎉 Aucun fichier inutile trouvé !")
        print("Votre application semble bien organisée.")

def generer_script_nettoyage(fichiers_inutiles):
    """
    Génère un script Python pour nettoyer les fichiers inutiles
    """
    script_content = """#!/usr/bin/env python3
# Script de nettoyage automatique - À utiliser avec précaution !
import os
import shutil

def nettoyer_fichiers():
    fichiers_a_supprimer = {}
    
    print("🧹 Nettoyage des fichiers inutiles...")
    
    for fichier in fichiers_a_supprimer:
        try:
            if os.path.exists(fichier):
                if os.path.isfile(fichier):
                    os.remove(fichier)
                    print(f"✅ Supprimé: {fichier}")
                elif os.path.isdir(fichier):
                    shutil.rmtree(fichier)
                    print(f"✅ Dossier supprimé: {fichier}")
            else:
                print(f"⚠️ Fichier non trouvé: {fichier}")
        except Exception as e:
            print(f"❌ Erreur avec {fichier}: {e}")
    
    print("\\n🎉 Nettoyage terminé !")

if __name__ == "__main__":
    print("Ce script va supprimer les fichiers listés.")
    confirmation = input("Confirmez-vous la suppression ? (oui/NON): ")
    if confirmation.lower() == 'oui':
        nettoyer_fichiers()
    else:
        print("❌ Nettoyage annulé.")
""".format(fichiers_inutiles)
    
    with open("nettoyage_automatique.py", "w", encoding="utf-8") as f:
        f.write(script_content)
    
    print(f"\n📄 Script de nettoyage généré: 'nettoyage_automatique.py'")

# Version interactive
def analyser_interactif():
    """
    Version interactive de l'analyse
    """
    print("🔍 Analyseur de fichiers inutiles - Flask App")
    print("=" * 50)
    
    racine = input("Entrez le chemin de votre application Flask [./]: ").strip()
    if not racine:
        racine = "."
    
    if not os.path.exists(racine):
        print("❌ Le chemin spécifié n'existe pas.")
        return
    
    print(f"\nAnalyse de: {os.path.abspath(racine)}")
    
    try:
        fichiers_inutiles = analyser_fichiers_inutiles(racine)
        
        if fichiers_inutiles:
            print(f"\n🎯 {len(fichiers_inutiles)} fichiers potentiellement inutiles identifiés.")
            
            # Option de nettoyage immédiat
            nettoyer = input("\nVoulez-vous créer un script de nettoyage ? (o/n): ").lower()
            if nettoyer == 'o':
                generer_script_nettoyage(fichiers_inutiles)
        else:
            print("\n🎉 Aucun fichier inutile trouvé !")
            
    except Exception as e:
        print(f"❌ Erreur lors de l'analyse: {e}")

if __name__ == "__main__":
    analyser_interactif()