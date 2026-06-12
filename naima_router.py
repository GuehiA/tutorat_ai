# naima_router.py - Routage intelligent OpenAI / DeepSeek pour Naima
import os
import re
import json
from openai import OpenAI
from typing import Dict, Any, Optional

# ============================================================
# CONFIGURATION DES DEUX CLIENTS
# ============================================================

# Client OpenAI (existant)
openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# Client DeepSeek (API compatible OpenAI)
deepseek_client = OpenAI(
    api_key=os.getenv('DEEPSEEK_API_KEY'),  # À ajouter dans .env
    base_url="https://api.deepseek.com"
)

# ============================================================
# DÉTECTION DE LA MATIÈRE ET DIFFICULTÉ
# ============================================================

def detecter_matiere(question: str, lang: str = "fr") -> str:
    """Détecte automatiquement la matière de la question"""
    question_lower = question.lower()
    
    # Mots-clés par matière
    patterns = {
        "maths": ["équation", "calcul", "fraction", "x=", "y=", "nombre", "addition", "soustraction", 
                  "multiplication", "division", "géométrie", "triangle", "angle", "pourcentage"],
        "francais": ["grammaire", "conjugaison", "verbe", "phrase", "texte", "poème", "adjectif", 
                     "nom", "sujet", "complément", "ponctuation"],
        "histoire": ["date", "guerre", "roi", "révolution", "siècle", "bataille", "empire", 
                     "civilisation", "préhistoire", "antiquité"],
        "sciences": ["atome", "cellule", "force", "énergie", "vitesse", "masse", "volume", 
                     "réaction", "chimique", "physique", "biologie"]
    }
    
    scores = {matiere: sum(1 for kw in mots if kw in question_lower) 
              for matiere, mots in patterns.items()}
    
    # Retourner la matière avec le score le plus élevé
    best_matiere = max(scores, key=scores.get)
    if scores[best_matiere] == 0:
        return "maths"  # Par défaut maths
    
    return best_matiere


def detecter_difficulte(question: str, niveau_eleve: str) -> str:
    """Détecte si la question est complexe (besoin DeepSeek) ou simple (OpenAI)"""
    question_lower = question.lower()
    
    # Mots-clés de questions complexes
    complex_keywords = [
        "résoudre", "démontrer", "prouve", "montre que", "calcule la limite",
        "équation", "système", "dérivée", "intégrale", "théorème",
        "démontre", "démonstration", "justifie", "déduis"
    ]
    
    # Compter les mots-clés complexes
    complex_score = sum(1 for kw in complex_keywords if kw in question_lower)
    
    # Longueur de la question (les questions longues sont souvent complexes)
    if len(question) > 150:
        complex_score += 1
    
    # Retourner "hard" pour DeepSeek, "easy" pour OpenAI
    if complex_score >= 2:
        return "hard"
    elif "=" in question and any(op in question for op in ["x", "y", "z"]):
        return "hard"
    else:
        return "easy"


# ============================================================
# ROUTEUR PRINCIPAL
# ============================================================

def choisir_modele(matiere: str, difficulte: str, type_requete: str = "chat") -> tuple:
    """
    Retourne (client, model_name, raison)
    
    - matiere: "maths", "francais", "histoire", "sciences"
    - difficulte: "easy" ou "hard"
    - type_requete: "chat", "correction", "exercice"
    """
    
    # Règle 1: Maths complexes → DeepSeek Pro
    if matiere == "maths" and difficulte == "hard":
        return deepseek_client, "deepseek-v4-pro", "Maths complexe → DeepSeek Pro"
    
    # Règle 2: Maths simples mais correction d'exercice → DeepSeek Flash
    if matiere == "maths" and type_requete == "correction":
        return deepseek_client, "deepseek-v4-flash", "Correction maths → DeepSeek Flash"
    
    # Règle 3: Correction d'exercice générale → DeepSeek Flash
    if type_requete == "correction":
        return deepseek_client, "deepseek-v4-flash", "Correction générale → DeepSeek Flash"
    
    # Règle 4: Génération d'exercice → SEULEMENT pour maths, sinon OpenAI
    if type_requete == "exercice":
        if matiere == "maths":
            return deepseek_client, "deepseek-v4-flash", "Génération exercice maths → DeepSeek Flash"
        else:
            # Pour français, histoire, etc. → OpenAI
            return openai_client, "gpt-4o-mini", f"Génération exercice {matiere} → OpenAI"
    
    # Règle 5: Tout le reste → OpenAI (meilleur pour dialogue Socratique)
    return openai_client, "gpt-4o-mini", "Dialogue Socratique → OpenAI"


def appel_ia(messages: list, type_requete: str = "chat", matiere: str = None, 
            niveau: str = "6ème", langue: str = "fr", **kwargs) -> str:
    """
    Appel intelligent vers OpenAI ou DeepSeek
    """
    
    if not matiere and messages:
        user_question = next((m["content"] for m in messages if m["role"] == "user"), "")
        matiere = detecter_matiere(user_question, langue)
    
    user_question = next((m["content"] for m in messages if m["role"] == "user"), "")
    difficulte = detecter_difficulte(user_question, niveau)
    
    client, model_name, raison = choisir_modele(matiere, difficulte, type_requete)
    
    print(f"🔀 ROUTAGE: {raison}")
    print(f"   → Modèle: {model_name}")
    print(f"   → Matière: {matiere}, Difficulté: {difficulte}")
    
    # Afficher le message utilisateur pour déboguer
    print(f"📝 Message utilisateur (premiers 200 caractères): {user_question[:200]}...")
    
    params = {
        "model": model_name,
        "messages": messages,
        "temperature": kwargs.get("temperature", 0.7),
        "max_tokens": kwargs.get("max_tokens", 800),
        "timeout": 30.0  # ← AJOUTER LE TIMEOUT
    }
    
    if "deepseek" in model_name:
        params["extra_body"] = {"thinking": {"type": "enabled"}}
    
    try:
        print(f"🔄 Envoi de la requête à {model_name}...")
        response = client.chat.completions.create(**params)
        result = response.choices[0].message.content.strip()
        print(f"✅ Réponse reçue ({len(result)} caractères)")
        print(f"📤 Début de la réponse: {result[:100]}...")
        return result
    except Exception as e:
        print(f"❌ Erreur avec {model_name}: {e}")
        print(f"🔄 Fallback sur OpenAI...")
        try:
            fallback = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=0.7,
                max_tokens=800,
                timeout=30.0
            )
            result = fallback.choices[0].message.content.strip()
            print(f"✅ Fallback réussi ({len(result)} caractères)")
            return result
        except Exception as e2:
            print(f"❌ Fallback aussi en erreur: {e2}")
            return ""  # Retourne vide pour déclencher le fallback manuel


# ============================================================
# FONCTIONS DE REMPLACEMENT POUR app.py
# ============================================================

def naima_generer_debut_conversation(question: str, niveau: str, langue: str = "fr", 
                                      mode_examen: bool = False, matiere: str = None) -> str:
    """Version améliorée avec routage DeepSeek/OpenAI"""
    
    # Détecter la matière si non fournie
    if not matiere:
        matiere = detecter_matiere(question, langue)
    
    # Construire le prompt système
    if langue == "fr":
        system_prompt = f"""Tu es Naima, une enseignante virtuelle bienveillante et passionnée par {matiere}. Tu aides des élèves de niveau {niveau}.

**TON IDENTITÉ :**
- Tu es Naima, l'enseignante virtuelle
- Tu tutoies toujours l'élève (utilise "tu", "ta", "ton")
- Tu es chaleureuse, encourageante et pédagogue
- Tu signes tes messages avec "— Naima ✨"
- Tu poses des questions guidantes une par une
- Tu ne donnes JAMAIS la réponse directement

**TA MISSION :**
Un élève de {niveau} te pose cette question en {matiere} : "{question}"

1. Accueille-le chaleureusement en te présentant comme Naima
2. Reformule sa question pour montrer que tu as compris
3. Donne une orientation générale adaptée à {matiere}
4. Pose la PREMIÈRE QUESTION qui le guide vers la première étape
5. Termine par ton nom pour créer un lien personnel

**FORMAT DE TA RÉPONSE :**
- Salutation avec présentation de Naima
- Reformulation de la question
- Orientation pédagogique
- Première question précise
- Signature : — Naima ✨"""
    else:
        system_prompt = f"""You are Naima, a virtual teacher passionate about {matiere}. You help {niveau} students.

**YOUR IDENTITY:**
- You are Naima, the virtual teacher
- You use warm, friendly language
- You are warm, encouraging, and pedagogical
- You sign your messages with "— Naima ✨"
- You ask guiding questions one at a time
- You NEVER give the answer directly

**YOUR MISSION:**
A {niveau} student asks you this {matiere} question: "{question}"

1. Welcome them warmly, introducing yourself as Naima
2. Rephrase their question to show understanding
3. Give general guidance adapted to {matiere}
4. Ask the FIRST QUESTION that guides them to the first step
5. End with your name to create personal connection

**YOUR RESPONSE FORMAT:**
- Greeting with Naima introduction
- Question rephrasing
- Pedagogical orientation
- First precise question
- Signature: — Naima ✨"""
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Contexte: niveau {niveau}, matière {matiere}, mode examen: {mode_examen}"}
    ]
    
    # Appel intelligent
    return appel_ia(messages, type_requete="chat", matiere=matiere, 
                    niveau=niveau, langue=langue)


def naima_generer_suite_conversation(derniere_q: str, reponse: str, historique: list,
                                      niveau: str, langue: str = "fr", mode_examen: bool = False,
                                      exercice_context: str = "", matiere: str = "mathématiques") -> str:
    """Version améliorée avec routage DeepSeek/OpenAI"""
    
    # Préparer l'historique
    historique_contextuel = "\n".join(historique[-10:])
    
    if langue == "fr":
        system_prompt = f"""Tu es Naima, une enseignante virtuelle bienveillante et patiente. Tu aides des élèves de niveau {niveau} en {matiere}.

**TON STYLE :**
- Tu tutoies toujours l'élève (utilise "tu", "ta", "ton", "tes")
- Tu es chaleureuse, encourageante et pédagogue
- Tu signes tes messages avec "— Naima ✨"
- Tu poses toujours des questions guidantes une par une
- Tu ne donnes JAMAIS la réponse directement
- Tu corriges avec bienveillance et sans critique

**TA MISSION POUR CETTE RÉPONSE :**
La dernière question que tu as posée : "{derniere_q}"
La réponse de l'élève : "{reponse}"

1. Analyse la réponse de l'élève
2. Si c'est correct : félicite-le et pose la prochaine étape
3. Si c'est partiellement correct : reconnais ce qui est bon, guide pour corriger
4. Si c'est incorrect : ne dis pas "c'est faux", guide avec un indice
5. Pose UNE SEULE nouvelle question pour faire avancer la réflexion

**FORMAT DE TA RÉPONSE :**
- Réaction à la réponse de l'élève (félicitations/guidage)
- Explication très brève si nécessaire
- Nouvelle question précise (sauf si exercice terminé)
- Signature : — Naima ✨"""
    else:
        system_prompt = f"""You are Naima, a kind and patient virtual teacher. You help {niveau} students with {matiere}.

**YOUR STYLE:**
- You use "you", "your" (friendly but professional)
- You are warm, encouraging, and pedagogical
- You sign your messages with "— Naima ✨"
- You ask guiding questions one at a time
- You NEVER give the answer directly
- You correct gently without criticism

**YOUR MISSION FOR THIS RESPONSE:**
Last question you asked: "{derniere_q}"
Student's answer: "{reponse}"

1. Analyze the student's response
2. If correct: praise them and ask the next step
3. If partially correct: acknowledge what's good, guide to correct
4. If incorrect: don't say "that's wrong", guide with a hint
5. Ask ONLY ONE new question to advance their thinking

**YOUR RESPONSE FORMAT:**
- Reaction to student's answer (praise/guidance)
- Very brief explanation if needed
- New precise question
- Signature: — Naima ✨"""
    
    prompt_utilisateur = f"""**Historique de conversation ({matiere}) :**
{historique_contextuel}

**Contexte :** Élève de {niveau} en {matiere}
{"**Mode examen :** guide avec des indices, ne révèle pas les étapes complètes." if mode_examen else ""}

Dernière question IA: {derniere_q}
Réponse élève: {reponse}
"""
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt_utilisateur}
    ]
    
    # Appel intelligent
    return appel_ia(messages, type_requete="chat", matiere=matiere, 
                    niveau=niveau, langue=langue)


def naima_corriger_exercice(question: str, reponse_eleve: str, correction_attendue: str = None,
                            langue: str = "fr", niveau: str = "6ème") -> Dict[str, Any]:
    """
    Correction d'exercice avec DeepSeek (spécialisé) ou OpenAI
    
    Retourne: {
        "correct": bool,
        "etoiles": int (0-5),
        "analyse": str,
        "feedback": str
    }
    """
    
    if langue == "fr":
        prompt = f"""Corrige la réponse d'un élève à cet exercice.

📘 Énoncé : {question}
📜 Réponse de l'élève : {reponse_eleve}
{f"✅ Réponse attendue : {correction_attendue}" if correction_attendue else ""}

⭐ BARÈME (5 points) :
- 5 : Réponse correcte, raisonnement excellent
- 4 : Réponse correcte, petit oubli
- 3 : Réponse correcte mais raisonnement incomplet
- 2 : Réponse incorrecte mais début de raisonnement
- 1 : Tentative mais erreur majeure
- 0 : Hors sujet ou vide

📤 Format de réponse STRICT (JSON uniquement) :
{{
    "correct": true/false,
    "etoiles": X,
    "analyse": "Analyse détaillée du raisonnement de l'élève",
    "feedback": "Message constructif pour l'élève"
}}"""
    else:
        prompt = f"""Correct the student's answer to this exercise.

📘 Problem: {question}
📜 Student's answer: {reponse_eleve}
{f"✅ Expected answer: {correction_attendue}" if correction_attendue else ""}

⭐ SCORING (5 points):
- 5: Correct answer, excellent reasoning
- 4: Correct answer, minor omission
- 3: Correct but incomplete reasoning
- 2: Incorrect but shows reasoning
- 1: Attempt but major error
- 0: Off-topic or empty

📤 Response format STRICT (JSON only):
{{
    "correct": true/false,
    "etoiles": X,
    "analyse": "Detailed analysis of student's reasoning",
    "feedback": "Constructive message for the student"
}}"""
    
    messages = [{"role": "user", "content": prompt}]
    
    # Pour la correction, on privilégie DeepSeek (plus rigoureux)
    try:
        response_text = appel_ia(messages, type_requete="correction", 
                                 matiere="maths", niveau=niveau, langue=langue,
                                 temperature=0.3, max_tokens=500)
        
        # Extraire le JSON
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        else:
            # Fallback
            return {
                "correct": False,
                "etoiles": 0,
                "analyse": "Erreur d'analyse",
                "feedback": "Je n'ai pas pu analyser ta réponse."
            }
    except Exception as e:
        print(f"❌ Erreur correction: {e}")
        return {
            "correct": False,
            "etoiles": 0,
            "analyse": str(e),
            "feedback": "Erreur technique. Réessaie."
        }


def naima_generer_exercice(matiere: str, niveau: str, difficulte: str = "moyen",
                           type_exercice: str = "exercice", mots_cles: str = "",
                           langue: str = "fr") -> Dict[str, Any]:
    """
    Génération d'exercice avec DeepSeek (maths) ou OpenAI (autres matières)
    """
    
    # Mapping des niveaux (accepte les deux formats)
    niveaux_map = {
        "1": {"fr": "CP (6-7 ans)", "en": "Grade 1 (6-7 years)"},
        "2": {"fr": "CE1 (7-8 ans)", "en": "Grade 2 (7-8 years)"},
        "3": {"fr": "CE2 (8-9 ans)", "en": "Grade 3 (8-9 years)"},
        "4": {"fr": "CM1 (9-10 ans)", "en": "Grade 4 (9-10 years)"},
        "5": {"fr": "CM2 (10-11 ans)", "en": "Grade 5 (10-11 years)"},
        "6": {"fr": "6ème (11-12 ans)", "en": "Grade 6 (11-12 years)"},
        "7": {"fr": "5ème (12-13 ans)", "en": "Grade 7 (12-13 years)"},
        "8": {"fr": "4ème (13-14 ans)", "en": "Grade 8 (13-14 years)"},
        "9": {"fr": "3ème (14-15 ans)", "en": "Grade 9 (14-15 years)"},
        "10": {"fr": "Seconde (15-16 ans)", "en": "Grade 10 (15-16 years)"},
        "11": {"fr": "Première (16-17 ans)", "en": "Grade 11 (16-17 years)"},
        "12": {"fr": "Terminale (17-18 ans)", "en": "Grade 12 (17-18 years)"},
        "13": {"fr": "Université (18+ ans)", "en": "College/University (18+ years)"},
        "college": {"fr": "Université (18+ ans)", "en": "College/University (18+ years)"},
        "university": {"fr": "Université (18+ ans)", "en": "College/University (18+ years)"},
        "cp": {"fr": "CP (6-7 ans)", "en": "Grade 1 (6-7 years)"},
        "ce1": {"fr": "CE1 (7-8 ans)", "en": "Grade 2 (7-8 years)"},
        "ce2": {"fr": "CE2 (8-9 ans)", "en": "Grade 3 (8-9 years)"},
        "cm1": {"fr": "CM1 (9-10 ans)", "en": "Grade 4 (9-10 years)"},
        "cm2": {"fr": "CM2 (10-11 ans)", "en": "Grade 5 (10-11 years)"},
        "6ème": {"fr": "6ème (11-12 ans)", "en": "Grade 6 (11-12 years)"},
        "5ème": {"fr": "5ème (12-13 ans)", "en": "Grade 7 (12-13 years)"},
        "4ème": {"fr": "4ème (13-14 ans)", "en": "Grade 8 (13-14 years)"},
        "3ème": {"fr": "3ème (14-15 ans)", "en": "Grade 9 (14-15 years)"},
        "seconde": {"fr": "Seconde (15-16 ans)", "en": "Grade 10 (15-16 years)"},
        "première": {"fr": "Première (16-17 ans)", "en": "Grade 11 (16-17 years)"},
        "terminale": {"fr": "Terminale (17-18 ans)", "en": "Grade 12 (17-18 years)"}
    }
    
    niveau_clean = niveau.lower().strip().replace("ème", "ème").replace("è", "e")
    
    if niveau_clean in niveaux_map:
        niveau_formatted = niveaux_map[niveau_clean][langue]
    else:
        niveau_formatted = f"Grade {niveau}" if langue == "en" else f"Niveau {niveau}"
    
    print(f"📚 Niveau: {niveau} → {niveau_formatted}")
    
    # Construction du prompt selon la matière
    if matiere == "français" or matiere == "french":
        prompt = f"""En tant que Naima, génère un EXERCICE COMPLET de {matiere} pour un élève de {niveau_formatted} (difficulté: {difficulte}).

{f"Thème spécifique: {mots_cles}" if mots_cles else "Thème: conjugaison et grammaire"}

⚠️ RÈGLES PÉDAGOGIQUES STRICTES:
- Ne donne JAMAIS la réponse dans l'énoncé
- Ne mets PAS d'exemple avec la réponse (ex: "Réponse : ...")
- L'élève doit trouver par lui-même
- L'énoncé ne contient que la consigne et les phrases à compléter
- Pas de "Réponse :" dans l'exercice

Exemple CORRECT d'énoncé:
"Conjugue les verbes entre parenthèses au présent de l'indicatif.

1. Les élèves (travailler) ___ très dur.
2. Je (être) ___ content de te voir."

Exemple INCORRECT (à éviter):
"Les élèves (travailler) ___ très dur. (Réponse : travaillent)"

Réponds avec ce format JSON STRICT:
{{
    "message_accueil": "Message d'introduction chaleureux (sans donner de réponse)",
    "enonce": "Consigne claire + liste des phrases à compléter (SANS RÉPONSES)",
    "premiere_question": "Première question pour guider l'élève (ouverte, sans donner la réponse)",
    "indices": ["Indice 1", "Indice 2", "Indice 3"],
    "correction": {{
        "reponse_finale": "Les réponses complètes (cachées jusqu'à la fin)",
        "explication": "Explication des règles"
    }}
}}"""
    else:
        prompt = f"""En tant que Naima, génère un EXERCICE COMPLET de {matiere} pour un élève de niveau {niveau_formatted} (difficulté: {difficulte}).

{f"Thème spécifique: {mots_cles}" if mots_cles else ""}

⚠️ RÈGLES PÉDAGOGIQUES:
- Ne donne JAMAIS la réponse dans l'énoncé
- L'élève doit trouver par lui-même

Réponds avec ce format JSON STRICT:
{{
    "message_accueil": "Message d'introduction chaleureux",
    "enonce": "Énoncé détaillé de l'exercice (SANS RÉPONSES)",
    "premiere_question": "Première question pour guider l'élève",
    "indices": ["indice 1", "indice 2", "indice 3"],
    "correction": {{
        "reponse_finale": "La réponse correcte",
        "explication": "Explication détaillée"
    }}
}}"""
    
    messages = [{"role": "user", "content": prompt}]
    
    response_text = appel_ia(messages, type_requete="exercice", 
                             matiere=matiere, niveau=niveau, langue=langue,
                             temperature=0.8, max_tokens=1200)
    
    json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
    if json_match:
        try:
            exercice = json.loads(json_match.group())
            
            # Vérifier que l'énoncé n'est pas trop court
            if len(exercice.get("enonce", "")) < 100 and matiere == "français":
                print("⚠️ Énoncé trop court, tentative de régénération...")
                raise Exception("Énoncé trop court")
                
            return exercice
        except json.JSONDecodeError:
            pass
    
    # Fallback simple (sans réponses dans l'énoncé)
    if matiere == "français" or matiere == "french":
        if langue == "fr":
            return {
                "message_accueil": "📖 Voici un exercice de conjugaison !",
                "enonce": """**Exercice : Conjugue les verbes au présent**

Consigne : Complète les phrases avec le bon verbe conjugué.

1. Les élèves (travailler) ___ très dur.
2. Je (être) ___ content de te voir.
3. Tu (finir) ___ tes devoirs.
4. Nous (aller) ___ à la plage.
5. Elles (prendre) ___ le bus.""",
                "premiere_question": "Complète la première phrase. Quelle est la conjugaison de 'travailler' ?",
                "indices": ["Les élèves = ils", "Terminaison du présent pour -er = -ent"],
                "correction": {
                    "reponse_finale": "1. travaillent, 2. suis, 3. finis, 4. allons, 5. prennent",
                    "explication": "Au présent : -e, -es, -e, -ons, -ez, -ent pour les verbes en -er."
                }
            }
    
    return {
        "message_accueil": "Voici un exercice !" if langue == "fr" else "Here's an exercise!",
        "enonce": f"Exercice de {matiere} à compléter.",
        "premiere_question": "Quelle est ta réponse ?",
        "indices": ["Relis bien l'énoncé", "Applique la règle"],
        "correction": {"reponse_finale": "À déterminer", "explication": "Réfléchis étape par étape."}
    }