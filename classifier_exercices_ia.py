import os
import json
import time
from openai import OpenAI

from app import app
from models import db, Exercice


client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

MODEL = os.getenv("OPENAI_SIMPLE_MODEL", "gpt-4o-mini")


def nettoyer_json(contenu):
    if not contenu:
        return None

    contenu = contenu.strip()

    if contenu.startswith("```"):
        contenu = (
            contenu
            .replace("```json", "")
            .replace("```JSON", "")
            .replace("```", "")
            .strip()
        )

    try:
        return json.loads(contenu)

    except Exception as e:
        print("❌ JSON invalide :", e)
        print("Contenu reçu :", contenu[:500])
        return None


def contexte_exercice(exercice):
    lecon = exercice.lecon
    unite = lecon.unite if lecon else None
    matiere = unite.matiere if unite else None
    niveau = matiere.niveau if matiere else None

    return {
        "niveau": niveau.nom if niveau else "",
        "matiere": matiere.nom if matiere else "",
        "unite": unite.nom if unite else "",
        "lecon": lecon.titre_fr if lecon else "",
        "question_fr": exercice.question_fr or "",
        "question_en": exercice.question_en or "",
        "reponse_fr": exercice.reponse_fr or "",
        "reponse_en": exercice.reponse_en or "",
        "explication_fr": exercice.explication_fr or "",
        "explication_en": exercice.explication_en or "",
    }


def classifier_un_exercice(exercice, exercice_id=None):
    data = contexte_exercice(exercice)

    prompt = f"""
Tu es un expert en didactique, en évaluation scolaire et en conception d'exercices progressifs.

Tu dois classifier l'exercice suivant pour permettre une progression adaptative reliée à un réseau bayésien.

Contexte pédagogique :
Niveau : {data["niveau"]}
Matière : {data["matiere"]}
Unité : {data["unite"]}
Leçon : {data["lecon"]}

Énoncé français :
{data["question_fr"]}

Énoncé anglais :
{data["question_en"]}

Réponse attendue française :
{data["reponse_fr"]}

Réponse attendue anglaise :
{data["reponse_en"]}

Explication française :
{data["explication_fr"]}

Explication anglaise :
{data["explication_en"]}

Tu dois répondre uniquement en JSON valide avec cette structure exacte :

{{
  "notion_cible": "notion précise travaillée par l'exercice",
  "competence_cible": "compétence précise évaluée",
  "niveau_difficulte": "facile | moyen | difficile",
  "type_exercice": "rappel | application | consolidation | remediation | defi",
  "ordre_progression": 1,
  "prerequis": ["prérequis 1", "prérequis 2"],
  "justification": "courte justification pédagogique",
  "confiance": 0.0
}}

Règles :
- notion_cible doit être courte et précise.
- competence_cible doit décrire l'action attendue de l'élève.
- niveau_difficulte doit être seulement : facile, moyen ou difficile.
- type_exercice doit être seulement : rappel, application, consolidation, remediation ou defi.
- ordre_progression doit être un entier entre 1 et 10.
- confiance doit être un nombre entre 0 et 1.
- Si la réponse attendue ou l'explication est absente, classe quand même l'exercice à partir de l'énoncé et du contexte.
- Ne donne aucun texte hors JSON.
"""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "Tu retournes uniquement du JSON valide, sans texte autour."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.1,
            max_tokens=700
        )

        contenu = response.choices[0].message.content
        classification = nettoyer_json(contenu)

        return classification

    except Exception as e:
        print(f"❌ Erreur IA pour exercice {exercice_id} :", e)
        return None


def normaliser_classification(classification):
    if not classification:
        return None

    niveaux_valides = ["facile", "moyen", "difficile"]
    types_valides = ["rappel", "application", "consolidation", "remediation", "defi"]

    niveau = str(
        classification.get("niveau_difficulte", "moyen")
    ).lower().strip()

    type_exercice = str(
        classification.get("type_exercice", "application")
    ).lower().strip()

    if niveau not in niveaux_valides:
        niveau = "moyen"

    if type_exercice not in types_valides:
        type_exercice = "application"

    try:
        ordre = int(classification.get("ordre_progression", 1))
    except Exception:
        ordre = 1

    ordre = max(1, min(ordre, 10))

    try:
        confiance = float(classification.get("confiance", 0.0))
    except Exception:
        confiance = 0.0

    confiance = max(0.0, min(confiance, 1.0))

    prerequis = classification.get("prerequis", [])
    if not isinstance(prerequis, list):
        prerequis = []

    notion_cible = str(
        classification.get("notion_cible", "")
    ).strip()

    competence_cible = str(
        classification.get("competence_cible", "")
    ).strip()

    if not notion_cible:
        notion_cible = "notion non déterminée"

    if not competence_cible:
        competence_cible = "compétence non déterminée"

    return {
        "notion_cible": notion_cible,
        "competence_cible": competence_cible,
        "niveau_difficulte": niveau,
        "type_exercice": type_exercice,
        "ordre_progression": ordre,
        "prerequis": prerequis,
        "classification_ia": classification,
        "confiance_classification": confiance,
        "classification_validee": confiance >= 0.80
    }


def appliquer_classification(exercice, classification):
    exercice.notion_cible = classification["notion_cible"]
    exercice.competence_cible = classification["competence_cible"]
    exercice.niveau_difficulte = classification["niveau_difficulte"]
    exercice.type_exercice = classification["type_exercice"]
    exercice.ordre_progression = classification["ordre_progression"]
    exercice.prerequis = classification["prerequis"]
    exercice.classification_ia = classification["classification_ia"]
    exercice.confiance_classification = classification["confiance_classification"]
    exercice.classification_validee = classification["classification_validee"]


def recuperer_exercices_a_classifier(limite):
    return (
        Exercice.query
        .filter(
            db.or_(
                Exercice.classification_ia.is_(None),
                Exercice.notion_cible.is_(None),
                Exercice.niveau_difficulte.is_(None)
            )
        )
        .order_by(Exercice.id.asc())
        .limit(limite)
        .all()
    )


def classifier_exercices(limite=20, pause=1.0, pause_erreur=10):
    exercices = recuperer_exercices_a_classifier(limite)

    print(f"🔎 Exercices à classifier : {len(exercices)}")

    if not exercices:
        print("✅ Aucun exercice à classifier.")
        return

    total_ok = 0
    total_erreur = 0

    for exercice in exercices:
        exercice_id = exercice.id

        print("-" * 80)
        print(f"🧠 Classification exercice ID {exercice_id}")

        classification_brute = classifier_un_exercice(
            exercice,
            exercice_id=exercice_id
        )

        classification = normaliser_classification(classification_brute)

        if not classification:
            total_erreur += 1
            print(f"❌ Classification impossible pour exercice {exercice_id}")
            time.sleep(pause)
            continue

        appliquer_classification(exercice, classification)

        db.session.add(exercice)

        try:
            db.session.commit()
            total_ok += 1

            print(f"✅ Exercice {exercice_id} classifié")
            print(f"   Notion : {classification['notion_cible']}")
            print(f"   Difficulté : {classification['niveau_difficulte']}")
            print(f"   Type : {classification['type_exercice']}")
            print(f"   Confiance : {classification['confiance_classification']}")

        except Exception as e:
            try:
                db.session.rollback()
            except Exception:
                pass

            try:
                db.session.remove()
            except Exception:
                pass

            total_erreur += 1

            print(f"❌ Erreur sauvegarde exercice {exercice_id} :", e)
            print(f"⏸️ Pause de {pause_erreur} secondes avant de continuer...")

            time.sleep(pause_erreur)
            continue

        time.sleep(pause)

    print("=" * 80)
    print("✅ Classification terminée")
    print(f"Classifiés : {total_ok}")
    print(f"Erreurs : {total_erreur}")


if __name__ == "__main__":
    with app.app_context():
        limite = int(os.getenv("CLASSIFICATION_LIMITE", "20"))
        pause = float(os.getenv("CLASSIFICATION_PAUSE", "1.0"))
        pause_erreur = int(os.getenv("CLASSIFICATION_PAUSE_ERREUR", "10"))

        classifier_exercices(
            limite=limite,
            pause=pause,
            pause_erreur=pause_erreur
        )