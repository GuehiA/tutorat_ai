# services/diagnostic_history_service.py

from models import db, DiagnosticBayesien


def construire_recommandation_diagnostic(niveau_risque, verification_calcul=None):
    """
    Construit une recommandation pédagogique lisible pour l'admin.
    """

    verification_calcul = verification_calcul or {}

    if verification_calcul.get("calcul_verifie") and verification_calcul.get("est_correct") is False:
        return (
            "Erreur mathématique détectée. Recommander une correction guidée, "
            "une reprise de l'étape de calcul et un exercice similaire plus simple."
        )

    if niveau_risque == "élevé":
        return (
            "Risque élevé. Recommander une explication très guidée, "
            "une seule question à la fois, des indices progressifs et un exercice de remédiation."
        )

    if niveau_risque == "moyen":
        return (
            "Risque moyen. Recommander une consolidation, une justification du raisonnement "
            "et un exercice comparable pour vérifier la compréhension."
        )

    if niveau_risque == "faible":
        return (
            "Risque faible. Recommander une question plus exigeante, "
            "une généralisation de la méthode ou un exercice d'approfondissement."
        )

    return (
        "Diagnostic insuffisant. Recommander de recueillir plus de réponses "
        "avant de conclure sur le niveau de difficulté."
    )


def enregistrer_diagnostic_bayesien(
    user_id,
    diagnostic,
    signaux=None,
    matiere=None,
    exercice_id=None,
    lecon_id=None,
    verification_calcul=None,
    source="naima",
    analyse_pedagogique=None,
    meta_processus_naima=None
):
    """
    Enregistre un diagnostic bayésien dans la table diagnostics_bayesiens.

    Cette version enregistre aussi :
    - le diagnostic bayésien ;
    - les signaux pédagogiques ;
    - la vérification mathématique éventuelle ;
    - l'analyse pédagogique intelligente ;
    - la preuve que Naima est connectée au processus pédagogique.
    """

    diagnostic = diagnostic or {}
    signaux = signaux or {}
    verification_calcul = verification_calcul or {}
    analyse_pedagogique = analyse_pedagogique or {}
    meta_processus_naima = meta_processus_naima or {}

    niveau_risque = diagnostic.get("niveau_risque")

    recommandation = construire_recommandation_diagnostic(
        niveau_risque=niveau_risque,
        verification_calcul=verification_calcul
    )

    diagnostic_complet = {
        "diagnostic": diagnostic,
        "signaux": signaux,
        "verification_calcul": verification_calcul,
        "analyse_pedagogique": analyse_pedagogique,

        # Preuve technique et pédagogique que Naima est connectée au processus
        "processus_naima": meta_processus_naima
    }

    ligne = DiagnosticBayesien(
        user_id=user_id,
        exercice_id=exercice_id,
        lecon_id=lecon_id,
        matiere=matiere,

        # Diagnostic bayésien
        probabilite_difficulte=diagnostic.get("probabilite_difficulte"),
        pourcentage_difficulte=diagnostic.get("pourcentage_difficulte"),
        niveau_risque=niveau_risque,

        # Signaux bayésiens
        maitrise_cours=signaux.get("maitrise_cours"),
        erreurs=signaux.get("erreurs"),
        temps_reponse=signaux.get("temps_reponse"),

        # Vérification mathématique
        verification_calcul=verification_calcul if verification_calcul else None,

        # Recommandation simple
        recommandation=recommandation,

        # Analyse pédagogique intelligente
        notion_cible=analyse_pedagogique.get("notion_cible"),
        notions_maitrisees=analyse_pedagogique.get("notions_maitrisees"),
        notions_non_maitrisees=analyse_pedagogique.get("notions_non_maitrisees"),
        erreurs_probables=analyse_pedagogique.get("erreurs_probables"),
        recommandation_enseignant=analyse_pedagogique.get("recommandation_enseignant"),
        exercice_remediation_suggere=analyse_pedagogique.get("exercice_remediation_suggere"),
        niveau_intervention=analyse_pedagogique.get("niveau_intervention"),
        analyse_pedagogique_ia=analyse_pedagogique if analyse_pedagogique else None,

        # Données complètes pour consultation admin
        diagnostic_complet=diagnostic_complet,

        source=source
    )

    db.session.add(ligne)
    db.session.commit()

    print("✅ Diagnostic bayésien enregistré avec processus Naima.")
    print("🔎 Processus Naima sauvegardé :", meta_processus_naima)

    return ligne