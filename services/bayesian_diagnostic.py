# services/bayesian_diagnostic.py

def diagnostiquer_difficulte(maitrise_cours, erreurs, temps_reponse):
    """
    Version simple et contrôlée du diagnostic bayésien.
    Elle évite les problèmes d'ordre des CPD au début.
    """

    probabilite = 0.10

    if maitrise_cours == "faible":
        probabilite += 0.40
    elif maitrise_cours == "moyenne":
        probabilite += 0.20
    elif maitrise_cours == "bonne":
        probabilite += 0.05

    if erreurs == "beaucoup":
        probabilite += 0.30
    elif erreurs == "peu":
        probabilite += 0.05

    if temps_reponse == "lent":
        probabilite += 0.15
    elif temps_reponse == "rapide":
        probabilite += 0.03

    probabilite = min(probabilite, 0.95)

    return {
        "probabilite_difficulte": round(probabilite, 3),
        "pourcentage_difficulte": round(probabilite * 100, 1),
        "niveau_risque": interpreter_risque(probabilite)
    }


def interpreter_risque(probabilite):
    if probabilite >= 0.70:
        return "élevé"
    elif probabilite >= 0.40:
        return "moyen"
    return "faible"