import json
from openai import OpenAI
import os

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def analyser_tentative_pedagogique(
    objectif_initial,
    derniere_question_ia,
    reponse_eleve,
    reponse_naima,
    matiere,
    niveau,
    diagnostic_bayesien=None,
    signaux_bayesiens=None,
    verification_calcul=None
):
    """
    Analyse pédagogiquement une tentative d'élève.
    Retourne une structure exploitable par l'admin.
    """

    diagnostic_bayesien = diagnostic_bayesien or {}
    signaux_bayesiens = signaux_bayesiens or {}
    verification_calcul = verification_calcul or {}

    prompt = f"""
Tu es un expert en pédagogie et en didactique.

Analyse la tentative suivante d'un élève.

Matière : {matiere}
Niveau : {niveau}

Objectif initial :
{objectif_initial}

Dernière question posée par l'IA :
{derniere_question_ia}

Réponse de l'élève :
{reponse_eleve}

Réponse donnée par Naima :
{reponse_naima}

Diagnostic bayésien :
{diagnostic_bayesien}

Signaux bayésiens :
{signaux_bayesiens}

Vérification mathématique locale :
{verification_calcul}

Tu dois répondre uniquement en JSON valide avec les champs suivants :

{{
  "notion_cible": "notion précise travaillée",
  "notions_maitrisees": ["..."],
  "notions_non_maitrisees": ["..."],
  "erreurs_probables": ["..."],
  "analyse_courte": "analyse pédagogique courte",
  "recommandation_enseignant": "ce que l'enseignant doit faire précisément",
  "exercice_remediation_suggere": "un court exercice de remédiation adapté",
  "niveau_intervention": "faible | moyen | urgent"
}}

Ne donne pas de texte hors JSON.
"""

    try:
        response = client.chat.completions.create(
            model=os.getenv("OPENAI_SIMPLE_MODEL", "gpt-4o-mini"),
            messages=[
                {
                    "role": "system",
                    "content": "Tu produis des analyses pédagogiques structurées en JSON strict."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.2,
            max_tokens=900
        )

        contenu = response.choices[0].message.content.strip()

        if contenu.startswith("```"):
            contenu = contenu.replace("```json", "").replace("```", "").strip()

        return json.loads(contenu)

    except Exception as e:
        print(f"⚠️ Erreur analyse pédagogique IA: {e}")

        return {
            "notion_cible": matiere,
            "notions_maitrisees": [],
            "notions_non_maitrisees": [],
            "erreurs_probables": [],
            "analyse_courte": "Analyse pédagogique non disponible.",
            "recommandation_enseignant": "Revoir la tentative manuellement.",
            "exercice_remediation_suggere": "",
            "niveau_intervention": "moyen"
        }