import os
import json
from PIL import Image, ImageDraw, ImageFont

def create_webmanifest():
    """Crée le fichier webmanifest"""
    manifest = {
        "name": "VirtuEduc - Virtual Education",
        "short_name": "VirtuEduc",
        "description": "Plateforme de tutorat IA pour l'éducation virtuelle",
        "icons": [
            {
                "src": "android-chrome-192x192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any maskable"
            },
            {
                "src": "android-chrome-512x512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable"
            }
        ],
        "theme_color": "#1a4fb3",
        "background_color": "#ffffff",
        "display": "standalone",
        "scope": "/",
        "start_url": "/",
        "orientation": "portrait-primary",
        "categories": ["education", "productivity"]
    }
    
    with open('static/favicon/site.webmanifest', 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

def create_favicon_high_contrast():
    """VERSION RECOMMANDÉE - Blanc sur bleu foncé - MEILLEURE VISIBILITÉ"""
    os.makedirs('static/favicon', exist_ok=True)
    sizes = [16, 32, 180, 192, 512]
    
    print("🎨 Création des nouveaux favicons - CONTRASTE ÉLEVÉ...")
    print("📝 Lettres 'VE' bien visibles cette fois !")
    
    for size in sizes:
        # Fond bleu FONCÉ pour meilleur contraste
        img = Image.new('RGB', (size, size), color='#1a4fb3')
        draw = ImageDraw.Draw(img)
        
        if size >= 16:  # Même pour les petites tailles
            try:
                # TEXTE TRÈS GROS pour une meilleure visibilité
                if size >= 180:
                    font_size = size // 2.2
                    text = "VE"
                elif size >= 64:
                    font_size = size // 2.5
                    text = "VE"
                elif size >= 32:
                    font_size = size // 1.8
                    text = "VE"
                else:  # 16px
                    font_size = size // 1.3
                    text = "V"  # Juste "V" pour 16px
                
                # Essayer une police grasse
                try:
                    font = ImageFont.truetype("arialbd.ttf", int(font_size))
                except:
                    try:
                        font = ImageFont.truetype("arial.ttf", int(font_size))
                    except:
                        font = ImageFont.load_default()
                
                # Calcul position centrée
                bbox = draw.textbbox((0, 0), text, font=font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
                x = (size - text_width) / 2
                y = (size - text_height) / 2
                
                # TEXTE BLANC PUR - CONTRASTE MAXIMUM
                draw.text((x, y), text, fill='#FFFFFF', font=font)
                
            except Exception as e:
                print(f"⚠️  Erreur pour {size}x{size}: {e}")
        
        # Sauvegarder avec les noms standards
        if size == 16:
            img.save('static/favicon/favicon-16x16.png')
            print(f"✅ {size}x{size}px - V (très visible)")
        elif size == 32:
            img.save('static/favicon/favicon-32x32.png')
            print(f"✅ {size}x{size}px - VE (bien visible)")
        elif size == 180:
            img.save('static/favicon/apple-touch-icon.png')
            print(f"✅ {size}x{32}px - VE (excellente visibilité)")
        elif size == 192:
            img.save('static/favicon/android-chrome-192x192.png')
            print(f"✅ {size}x{size}px - VE (parfait)")
        elif size == 512:
            img.save('static/favicon/android-chrome-512x512.png')
            print(f"✅ {size}x{size}px - VE (très grande)")
    
    # Créer les fichiers supplémentaires
    create_webmanifest()
    
    # Créer favicon.ico (16x16)
    try:
        img_16 = Image.open('static/favicon/favicon-16x16.png')
        img_16.save('static/favicon/favicon.ico')
        print("✅ favicon.ico créé")
    except Exception as e:
        print(f"⚠️  Erreur favicon.ico: {e}")
    
    print("\n🎉 NOUVEAUX FAVICONS CRÉÉS AVEC SUCCÈS!")
    print("👁️  Les lettres 'VE' sont maintenant BIEN VISIBLES!")
    print("📁 Dossier: static/favicon/")
    print("\n🔄 Pour voir les changements:")
    print("   1. Rechargez votre page dans le navigateur")
    print("   2. Videz le cache si nécessaire (Ctrl+F5)")

if __name__ == "__main__":
    print("="*60)
    print("🎨 GÉNÉRATEUR DE FAVICONS VIRTUEDUC - VERSION AMÉLIORÉE")
    print("="*60)
    print("🔧 Cette version garantit une MEILLEURE VISIBILITÉ")
    print("   - Fond bleu foncé (#1a4fb3)")
    print("   - Texte blanc pur et très gros")
    print("   - Contraste maximum pour les onglets")
    print("="*60)
    
    # Vérifier si le dossier existe déjà
    if os.path.exists('static/favicon'):
        print("\n⚠️  ATTENTION: Des favicons existent déjà!")
        choix = input("Voulez-vous les écraser? (oui/non): ").strip().lower()
        if choix != 'oui':
            print("❌ Opération annulée")
            exit()
    
    create_favicon_high_contrast()
    
    print("\n" + "="*60)
    print("✅ INSTALLATION TERMINÉE")
    print("="*60)
    print("📋 Fichiers créés:")
    print("   • favicon-16x16.png    (V bien visible)")
    print("   • favicon-32x32.png    (VE bien visible)") 
    print("   • apple-touch-icon.png (VE excellente visibilité)")
    print("   • android-chrome-*.png (VE parfait)")
    print("   • favicon.ico")
    print("   • site.webmanifest")
    print("\n🎯 Les favicons s'afficheront dans:")
    print("   - Onglets du navigateur")
    print("   - Signets/favoris")
    print("   - Écran d'accueil mobile")
    print("   - Barre de tâches")