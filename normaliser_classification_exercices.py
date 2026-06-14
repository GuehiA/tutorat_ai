from app import app
from models import db, Exercice


NORMALISATION_NOTIONS = {
    # --------------------------------------------------
    # Fractions
    # --------------------------------------------------
    "addition de fractions": "addition de fractions",
    "fractions et opérations": "opérations avec les fractions",
    "opérations avec des fractions": "opérations avec les fractions",
    "opérations avec les fractions": "opérations avec les fractions",
    "opérations sur les fractions": "opérations avec les fractions",
    "multiplication de fractions": "multiplication de fractions",
    "fractions simples": "fractions simples",

    # --------------------------------------------------
    # Conversions fractions, décimaux, pourcentages
    # --------------------------------------------------
    "conversion de fractions en pourcentages": "conversion fraction pourcentage",
    "conversion fraction pourcentage": "conversion fraction pourcentage",

    "conversion de fractions en décimaux": "conversion fraction décimal",
    "conversion fraction décimal": "conversion fraction décimal",

    "conversion décimal en pourcentage": "conversion décimal pourcentage",
    "conversion décimal pourcentage": "conversion décimal pourcentage",

    "conversion de pourcentage en fraction": "conversion pourcentage fraction",
    "conversion pourcentage fraction": "conversion pourcentage fraction",

    "conversion de pourcentages en décimaux": "conversion pourcentage décimal",
    "conversion pourcentage décimal": "conversion pourcentage décimal",

    "pourcentages": "pourcentages",
    "calcul de pourcentage": "calcul de pourcentage",

    # --------------------------------------------------
    # Ordre des opérations
    # --------------------------------------------------
    "ordre des opérations": "ordre des opérations",

    # --------------------------------------------------
    # Représentation et comparaison des nombres
    # --------------------------------------------------
    "représentation des nombres": "représentation des nombres",

    "comparaison de fractions et décimaux": "comparaison de nombres",
    "comparaison de valeurs": "comparaison de nombres",
    "comparaison de valeurs numériques": "comparaison de nombres",
    "ordre des nombres": "comparaison de nombres",

    # --------------------------------------------------
    # Inverses
    # --------------------------------------------------
    "inverse d'un pourcentage": "inverse et pourcentage",
    "inverse et pourcentage": "inverse et pourcentage",

    "inverse des fractions et nombres décimaux": "inverse de nombres",
    "inverse de nombres": "inverse de nombres",

    # --------------------------------------------------
    # Puissances, racines et notation scientifique
    # --------------------------------------------------
    "notation scientifique": "notation scientifique",

    "addition de notations scientifiques": "opérations en notation scientifique",
    "opérations en notation scientifique": "opérations en notation scientifique",

    "puissances": "puissances",

    "comparaison de puissances": "comparaison de puissances",
    "ordre des puissances": "comparaison de puissances",

    "racines carrées": "racines carrées",
    "racine carrée": "racines carrées",

    "racines carrées et puissances": "racines carrées et puissances",

    "racine carrée en notation scientifique": "racines carrées et notation scientifique",
    "racines carrées et notation scientifique": "racines carrées et notation scientifique",

    "estimation de racines carrées": "estimation de racines carrées",

    "diagonale d'un carré": "théorème de pythagore",
    "théorème de pythagore": "théorème de pythagore",

    # --------------------------------------------------
    # Taxes, rabais, prix, budget, finances
    # --------------------------------------------------
    "calcul du prix total avec taxe": "taxes et prix total",
    "calcul du prix total avec taxes": "taxes et prix total",
    "calcul du coût total avec taxes": "taxes et prix total",
    "calcul des coûts et taxes": "taxes et prix total",

    "calcul du prix total avec rabais et taxes": "taxes et rabais",
    "calcul du prix total après réduction et taxes": "taxes et rabais",
    "calcul du prix final avec taxes et réductions": "taxes et rabais",
    "calcul du coût final avec réduction et taxe": "taxes et rabais",
    "calcul des taxes et réductions": "taxes et rabais",
    "calcul de la taxe après réduction": "taxes et rabais",

    "calcul du prix initial avec taxes et réductions": "prix initial taxes et rabais",
    "calcul du prix initial avec rabais et taxe": "prix initial taxes et rabais",

    "calcul du prix avant taxe": "prix avant taxe",

    "calcul du prix après rabais": "rabais",
    "calcul du prix avant rabais": "prix avant rabais",
    "calcul de réduction": "rabais",
    "calcul du rabais": "rabais",
    "calcul de rabais": "rabais",

    "calcul de la taxe": "taxes",

    "calcul du coût total avec taxes et pourboires": "taxes et pourboires",
    "calcul du coût total avec taxes et frais": "taxes et frais",

    "calcul du solde après dépenses": "budget et dépenses",

    "calcul de commission": "commission",
    "pourcentage de commission": "commission",

    "calcul de pourboire": "pourboire",

    # --------------------------------------------------
    # Rapports et échelles
    # --------------------------------------------------
    "rapport": "rapport",
    "simplification de rapport": "rapport",
    "partage en fonction d'un rapport": "rapport",

    "rapport et échelle": "rapport et échelle",

    "échelle": "échelle",
    "échelle de carte": "échelle",
    "échelle et distance": "échelle",

        # --------------------------------------------------
    # Équations, inéquations, systèmes
    # --------------------------------------------------
    "résolution d'équations du premier degré": "équations du premier degré",
    "équations du premier degré": "équations du premier degré",
    "résolution d'équations linéaires": "équations du premier degré",
    "résolution d'équations": "équations",
    "résolution d'inéquations": "inéquations",
    "système d'équations": "systèmes d'équations",
    "système d'équations du premier degré": "systèmes d'équations",

    # --------------------------------------------------
    # Intérêts simples et composés
    # --------------------------------------------------
    "intérêt simple": "intérêt simple",
    "intérêts simples": "intérêt simple",
    "taux d'intérêt": "intérêt simple",

    "intérêt composé": "intérêt composé",
    "intérêts composés": "intérêt composé",

    # --------------------------------------------------
    # Budget, épargne, dépenses
    # --------------------------------------------------
    "budget personnel": "budget personnel",
    "budget mensuel": "budget personnel",
    "gestion du budget": "budget personnel",
    "gestion de budget": "budget personnel",
    "gestion budgétaire": "budget personnel",
    "équilibre budgétaire": "budget personnel",
    "dépenses fixes et variables": "budget personnel",
    "dépenses fixes et budget": "budget personnel",
    "priorisation des dépenses": "budget personnel",
    "calcul du solde budgétaire": "budget personnel",
    "calcul des dépenses et du solde": "budget personnel",
    "impact d'un achat sur le budget": "budget personnel",

    "calcul d'épargne": "épargne",
    "épargne dans un budget": "épargne",
    "calcul du temps d'épargne": "épargne",
    "objectifs financiers": "objectifs financiers",

    # --------------------------------------------------
    # Cartes de crédit, cartes de débit, paiement
    # --------------------------------------------------
    "compréhension du crédit": "crédit",
    "utilisation de la carte de crédit": "carte de crédit",
    "utilisation responsable de la carte de crédit": "carte de crédit",
    "utilité des cartes de crédit": "carte de crédit",
    "avantages et inconvénients des cartes de crédit": "carte de crédit",
    "risques financiers liés à l'utilisation de cartes": "carte de crédit",
    "dépenses excessives liées aux cartes de crédit": "carte de crédit",
    "frais de carte de crédit": "carte de crédit",
    "intérêts sur carte de crédit": "carte de crédit",
    "coûts associés à l'utilisation d'une carte de crédit": "carte de crédit",

    "utilisation de la carte de débit": "carte de débit",
    "frais de carte de débit": "carte de débit",

    "comparaison des cartes de paiement": "comparaison carte débit crédit",
    "différence entre carte de débit et carte de crédit": "comparaison carte débit crédit",
    "choix de paiement": "moyens de paiement",

    # --------------------------------------------------
    # Coût d’opportunité et partage
    # --------------------------------------------------
    "coût d'opportunité": "coût d'opportunité",
    "partage de biens": "partage et proportion",

    # --------------------------------------------------
    # Pourcentages additionnels
    # --------------------------------------------------
    "pourcentage d'augmentation": "pourcentage d'augmentation",

        # --------------------------------------------------
    # Intérêt simple - variantes
    # --------------------------------------------------
    "taux d'intérêt simple": "intérêt simple",
    "calcul de l'intérêt simple": "intérêt simple",
    "calcul du taux d'intérêt simple": "intérêt simple",
    "calcul de capital avec intérêt simple": "intérêt simple",
    "calcul du capital initial": "intérêt simple",

    # --------------------------------------------------
    # Intérêt composé - variantes
    # --------------------------------------------------
    "intérêt composé et simple": "intérêts simples et composés",

    # --------------------------------------------------
    # Taxes, prix initial, pourboires - variantes
    # --------------------------------------------------
    "calcul du prix initial avec réduction et taxe": "prix initial taxes et rabais",
    "calcul du montant avant taxe et pourboire": "prix initial taxes et pourboire",
    "calcul du montant avant taxes et pourboires": "prix initial taxes et pourboire",
    "calcul du prix avant taxes et pourboires": "prix initial taxes et pourboire",

    # --------------------------------------------------
    # Algèbre - expressions
    # --------------------------------------------------
    "calcul d'expressions algébriques": "expressions algébriques",
    "simplification d'expressions algébriques": "simplification d'expressions algébriques",
    "réduction d'expressions algébriques": "réduction d'expressions algébriques",
    "identification des termes semblables": "termes semblables",
    "termes semblables": "termes semblables",

    # --------------------------------------------------
    # Polynômes
    # --------------------------------------------------
    "degré d'un polynôme": "degré d'un polynôme",
    "polynômes de degré 2": "degré d'un polynôme",
    "polynômes de degré 3": "degré d'un polynôme",
    "coefficient d'un polynôme": "coefficient d'un polynôme",
    "coefficient de polynôme": "coefficient d'un polynôme",
    "identification des coefficients": "coefficient d'un polynôme",

    # --------------------------------------------------
    # Budget - notions restantes
    # --------------------------------------------------
    "budget et dépenses": "budget personnel",

    # --------------------------------------------------
    # Crédit - notions restantes
    # --------------------------------------------------
    "crédit": "carte de crédit",

    # --------------------------------------------------
    # Petites notions financières isolées
    # --------------------------------------------------
    "taxes et frais": "taxes et frais",
    "taxes et pourboires": "taxes et pourboires",

        # --------------------------------------------------
    # Développement, factorisation, produits remarquables
    # --------------------------------------------------
    "développement": "développement d'expressions algébriques",
    "développement d'expressions algébriques": "développement d'expressions algébriques",
    "développement et réduction d'expressions algébriques": "développement et réduction d'expressions algébriques",
    "développement et simplification d'expressions algébriques": "développement et simplification d'expressions algébriques",
    "développement de produits remarquables": "produits remarquables",
    "développement d'un binôme au carré": "produits remarquables",

    "factorisation": "factorisation d'expressions algébriques",
    "factorisation d'expressions algébriques": "factorisation d'expressions algébriques",
    "factorisation de polynômes": "factorisation d'expressions algébriques",
    "facteur commun": "facteur commun",
    "facteurs communs": "facteur commun",

    "développement et factorisation": "développement et factorisation",

    # --------------------------------------------------
    # Suites
    # --------------------------------------------------
    "suite arithmétique": "suites arithmétiques",
    "suites arithmétiques": "suites arithmétiques",
    "suite géométrique": "suites géométriques",
    "suites géométriques": "suites géométriques",
    "suites numériques": "suites numériques",
    "identification de suites": "suites numériques",
    "suites arithmétiques et géométriques": "suites arithmétiques et géométriques",
    "différence entre suites arithmétiques et géométriques": "suites arithmétiques et géométriques",

    # --------------------------------------------------
    # Fonctions et modèles
    # --------------------------------------------------
    "fonction linéaire": "fonctions linéaires",
    "fonction affine": "fonctions linéaires",
    "modèles linéaires": "fonctions linéaires",
    "régularité et relations linéaires": "fonctions linéaires",
    "formule de croissance linéaire": "fonctions linéaires",

    "fonction quadratique": "fonction quadratique",
    "fonction exponentielle": "fonction exponentielle",
    "diminution exponentielle": "fonction exponentielle",

    # --------------------------------------------------
    # Graphiques, droites, pente
    # --------------------------------------------------
    "représentation graphique des relations": "représentation graphique",
    "représentation graphique des relations linéaires": "représentation graphique",
    "représentation graphique des équations linéaires": "représentation graphique",
    "coefficient directeur": "pente et coefficient directeur",
    "coefficient directeur et équation de droite": "pente et coefficient directeur",
    "comparaison de pentes": "pente et coefficient directeur",

    # --------------------------------------------------
    # Données
    # --------------------------------------------------
    "types de données": "types de données",

        # --------------------------------------------------
    # Statistiques et données
    # --------------------------------------------------
    "organisation des données": "organisation des données",
    "collecte de données": "collecte de données",
    "collecte et organisation de données": "collecte de données",
    "collecte de données qualitatives": "collecte de données",
    "collecte de données quantitatives": "collecte de données",
    "classification des données": "types de données",
    "types de données": "types de données",
    "types de graphiques": "représentation des données",
    "tableau de fréquences": "représentation des données",
    "analyse de diagrammes en bâtons": "représentation des données",
    "analyse d'histogramme": "représentation des données",
    "analyse de données": "analyse de données",
    "analyse des données": "analyse de données",
    "analyse de la distribution": "distribution des données",
    "distribution des données": "distribution des données",
    "dispersion des données": "dispersion des données",
    "étendue des données": "dispersion des données",
    "valeur aberrante": "dispersion des données",
    "incomplétude des données": "qualité des données",
    "biais dans les questions": "biais et collecte de données",
    "prédiction de données": "prédiction de données",
    "moyenne arithmétique": "mesures de tendance centrale",
    "médiane": "mesures de tendance centrale",
    "mode": "mesures de tendance centrale",
    "mesures de tendance centrale": "mesures de tendance centrale",
    "comparaison des mesures de tendance centrale": "mesures de tendance centrale",
    "quartiles": "quartiles",
    "quartiles et intervalle interquartile": "quartiles",
    "interquartile et homogénéité des données": "quartiles",

    # --------------------------------------------------
    # Probabilités
    # --------------------------------------------------
    "probabilité": "probabilités",
    "probabilité d'événements": "probabilités",
    "probabilité des événements": "probabilités",
    "probabilité d'un événement": "probabilités",
    "probabilité d'événements simples": "probabilités",
    "probabilité avec des dés": "probabilités",
    "probabilité de choix d'un jour": "probabilités",
    "probabilité d'événements impossibles": "probabilités",
    "probabilité d'un événement certain": "probabilités",
    "probabilité d'absence": "probabilités",
    "probabilité complémentaire": "probabilité complémentaire",
    "probabilité d'événements complémentaires": "probabilité complémentaire",
    "probabilité expérimentale": "probabilité expérimentale",
    "probabilité expérimentale et théorique": "probabilité expérimentale",
    "probabilité et diagramme de venn": "probabilité et diagramme de venn",
    "probabilité d'événements dans un diagramme de venn": "probabilité et diagramme de venn",
    "probabilité et ensembles": "probabilité et ensembles",
    "probabilité et gestion des données": "probabilités",

    # --------------------------------------------------
    # Angles, triangles, polygones
    # --------------------------------------------------
    "types d'angles": "types d'angles",
    "classement des angles": "types d'angles",
    "angles obtus": "types d'angles",
    "angles droits": "types d'angles",
    "angles complémentaires": "angles particuliers",
    "angles supplémentaires": "angles particuliers",
    "angles complémentaires et supplémentaires": "angles particuliers",
    "angles adjacents": "angles particuliers",

    "angles dans un triangle": "angles dans les triangles",
    "angles d'un triangle": "angles dans les triangles",
    "mesure des angles dans un triangle": "angles dans les triangles",
    "somme des angles d'un triangle": "angles dans les triangles",
    "propriétés des angles dans un triangle": "angles dans les triangles",
    "propriétés des angles dans les triangles": "angles dans les triangles",

    "triangle rectangle": "triangles rectangles",
    "triangles rectangles": "triangles rectangles",
    "mesure des angles dans un triangle rectangle": "triangles rectangles",
    "angles dans un triangle rectangle": "triangles rectangles",
    "orthocentre d'un triangle rectangle": "droites remarquables du triangle",

    "types de triangles": "types de triangles",
    "propriétés des triangles": "propriétés des triangles",
    "mesure des angles dans un triangle isocèle": "triangles isocèles",
    "angles d'un triangle isocèle": "triangles isocèles",
    "propriétés des angles dans un triangle isocèle": "triangles isocèles",
    "mesure des angles dans un triangle équilatéral": "triangles équilatéraux",
    "propriétés des triangles équilatéraux": "triangles équilatéraux",

    "médianes dans un triangle": "droites remarquables du triangle",
    "médianes d'un triangle": "droites remarquables du triangle",
    "médiatrice d'un triangle": "droites remarquables du triangle",
    "bissectrice d'un angle": "droites remarquables du triangle",
    "propriétés des droites particulières dans un triangle": "droites remarquables du triangle",
    "cercle circonscrit et triangles": "droites remarquables du triangle",

    # --------------------------------------------------
    # Polygones et quadrilatères
    # --------------------------------------------------
    "polygones": "polygones",
    "polygones réguliers": "polygones",
    "propriétés des polygones": "polygones",
    "angles d'un polygone": "angles des polygones",
    "angles et polygones": "angles des polygones",

    "propriétés des quadrilatères": "quadrilatères",
    "propriétés des rectangles": "quadrilatères",
    "propriétés des parallélogrammes": "quadrilatères",
    "trapèze et parallélogramme": "quadrilatères",
    "propriétés des diagonales des quadrilatères": "quadrilatères",
    "mesure des angles dans un quadrilatère": "quadrilatères",
    "angles d'un rectangle": "quadrilatères",
    "propriétés des angles dans un rectangle": "quadrilatères",
    "propriétés des angles dans un parallélogramme": "quadrilatères",
    "propriétés des angles dans un trapèze": "quadrilatères",
    "propriétés des angles d'un carré": "quadrilatères",

    # --------------------------------------------------
    # Géométrie générale
    # --------------------------------------------------
    "propriétés des formes géométriques": "géométrie plane",
    "transformations géométriques": "transformations géométriques",

        # --------------------------------------------------
    # Conversions numériques - variantes
    # --------------------------------------------------
    "conversion de fractions": "conversions fractions décimaux pourcentages",
    "conversion de nombres": "conversions fractions décimaux pourcentages",
    "conversion de décimaux": "conversion décimal pourcentage",
    "conversion décimale en pourcentage": "conversion décimal pourcentage",
    "conversion décimale en fraction": "conversion décimal fraction",
    "conversion de fractions en décimaux et pourcentages": "conversions fractions décimaux pourcentages",
    "fractions et pourcentages": "conversions fractions pourcentages",
    "proportions et pourcentages": "proportions et pourcentages",

    # --------------------------------------------------
    # Arrondissement et estimation
    # --------------------------------------------------
    "arrondissement des décimaux": "arrondissement des nombres",
    "arrondissement de décimaux": "arrondissement des nombres",
    "arrondissement des nombres décimaux": "arrondissement des nombres",
    "estimation de sommes": "estimation",
    "estimation de différences": "estimation",
    "estimation de produits": "estimation",
    "estimation de quotients": "estimation",

    # --------------------------------------------------
    # Opérations de base
    # --------------------------------------------------
    "addition de nombres": "addition",
    "addition de nombres à deux chiffres": "addition",
    "addition de décimaux": "addition",
    "somme de nombres": "addition",
    "soustraction": "soustraction",
    "multiplication": "multiplication",
    "division": "division",
    "division de nombres naturels": "division",
    "division de nombres décimaux": "division",

    # --------------------------------------------------
    # Fractions - variantes
    # --------------------------------------------------
    "calcul de fractions": "opérations avec les fractions",
    "calcul de distances avec des fractions": "opérations avec les fractions",
    "résolution de problèmes de fractions": "opérations avec les fractions",
    "multiplication de fractions": "multiplication de fractions",

    # --------------------------------------------------
    # Racines carrées - variantes
    # --------------------------------------------------
    "carrés parfaits": "racines carrées",
    "racines carrées": "racines carrées",

    # --------------------------------------------------
    # Équations - variantes
    # --------------------------------------------------
    "résolution d'équations simples": "équations du premier degré",
    "résolution d'équations linéaires simples": "équations du premier degré",
    "équations linéaires": "équations du premier degré",
    "équations algébriques": "équations",
    "équations du périmètre d'un rectangle": "équations du premier degré",
    "résolution d'équations à deux étapes": "équations du premier degré",

    # --------------------------------------------------
    # Proportionnalité
    # --------------------------------------------------
    "raisonnement proportionnel": "proportionnalité",
    "proportionnalité": "proportionnalité",
    "proportions": "proportionnalité",
    "proportions et fractions": "proportionnalité",
    "règles de proportionnalité": "proportionnalité",
    "taux unitaire": "proportionnalité",

    # --------------------------------------------------
    # Suites - variantes
    # --------------------------------------------------
    "règles de suites": "suites numériques",
    "règles de suites arithmétiques": "suites arithmétiques",
    "suites algébriques": "suites numériques",
    "suites de fibonacci": "suites numériques",

        # --------------------------------------------------
    # Devises et taux de change
    # --------------------------------------------------
    "conversion de devises": "conversion de devises",
    "taux de change": "conversion de devises",

    # --------------------------------------------------
    # Intérêts - variantes
    # --------------------------------------------------
    "calcul des intérêts": "intérêt simple",
    "calcul d'intérêts": "intérêt simple",
    "calcul des intérêts simples": "intérêt simple",
    "calcul du taux d'intérêt": "intérêt simple",
    "comparaison des taux d'intérêt": "intérêt simple",
    "intérêts": "intérêt simple",
    "taux d'intérêt des emprunts": "intérêt simple",
    "estimation des intérêts": "intérêt simple",
    "calcul du dépôt initial avec intérêts": "intérêt simple",

    # --------------------------------------------------
    # Budget et économie
    # --------------------------------------------------
    "budgétisation": "budget personnel",
    "budget et épargne": "budget personnel",
    "budget et économies": "budget personnel",
    "économie et budget": "budget personnel",
    "économie et budgétisation": "budget personnel",
    "économie mensuelle": "budget personnel",
    "économie hebdomadaire": "budget personnel",
    "épargne vs emprunt": "budget personnel",
    "calcul du temps nécessaire pour atteindre un objectif financier": "objectifs financiers",

    # --------------------------------------------------
    # Racines carrées
    # --------------------------------------------------
    "racines carrées et carrés parfaits": "racines carrées",
    "racines carrées et volumes": "racines carrées",

    # --------------------------------------------------
    # Calcul mental, estimation, opérations
    # --------------------------------------------------
    "calcul mental et estimation": "estimation",
    "estimation et calcul de quantités": "estimation",
    "multiplication et estimation": "estimation",
    "calcul mental des prix": "calcul mental",

    "multiplication de nombres": "multiplication",
    "tables de multiplication": "multiplication",
    "multiplication et soustraction": "opérations de base",

    "double d'un nombre": "opérations de base",
    "somme de deux nombres": "addition",
    "somme des chiffres": "addition",
    "somme des entiers": "addition",

    # --------------------------------------------------
    # Nombres entiers, diviseurs, multiples
    # --------------------------------------------------
    "nombres premiers": "nombres entiers",
    "diviseurs d'un nombre": "nombres entiers",
    "multiples de 3": "multiples",
    "multiples de 10": "multiples",
    "identification des nombres pairs et impairs": "nombres pairs et impairs",

    # --------------------------------------------------
    # Géométrie et mesures
    # --------------------------------------------------
    "aire": "aire et périmètre",
    "calcul de l'aire": "aire et périmètre",
    "aire du triangle": "aire et périmètre",
    "aire d'un cercle": "aire et périmètre",
    "calcul de la surface d'un rectangle": "aire et périmètre",
    "périmètre et aire des rectangles": "aire et périmètre",
    "aire et périmètre des rectangles": "aire et périmètre",
    "calcul du périmètre d'un rectangle": "aire et périmètre",

    "volume et surface": "volume de solides",
    "volume et mesures": "volume de solides",
    "volume d'un cylindre": "volume de solides",
    "volume des cylindres": "volume de solides",
    "volume et surface des cylindres": "volume de solides",
    "volume et surface d'un cylindre creux": "volume de solides",
    "volume de solides composés": "volume de solides",
    "volume et aire totale des pavés droits": "volume de solides",
    "volume et dimensions géométriques": "volume de solides",
    "volume et aire d'un cône tronqué": "volume de solides",

    # --------------------------------------------------
    # Conversions d’unités
    # --------------------------------------------------
    "conversion d'unités": "conversions d'unités",
    "conversion d'unités de mesure": "conversions d'unités",
    "conversions d'unités de mesure": "conversions d'unités",
    "conversions d'unités de volume": "conversions d'unités",
    "unités de mesure": "conversions d'unités",
    "conversion de volumes": "conversions d'unités",

        # --------------------------------------------------
    # Solides 3D
    # --------------------------------------------------
    "identification des solides 3d": "solides 3d",
    "propriétés des solides 3d": "solides 3d",
    "cylindre": "solides 3d",
    "prismes triangulaires": "solides 3d",

    "volume des solides 3d": "volume de solides",
    "volume des prismes": "volume de solides",
    "volume du cylindre": "volume de solides",

    # --------------------------------------------------
    # Cercles, cylindres, cônes
    # --------------------------------------------------
    "circonférence et aire du cercle": "cercle : aire et circonférence",
    "circonférence et aire des cercles": "cercle : aire et circonférence",
    "circonférence du cercle": "cercle : aire et circonférence",
    "circonférence d'un cercle": "cercle : aire et circonférence",
    "circonférence et rayon d'un cercle": "cercle : aire et circonférence",
    "aire du cercle": "cercle : aire et circonférence",
    "aire des cercles": "cercle : aire et circonférence",
    "aire du disque": "cercle : aire et circonférence",
    "effet du rayon sur circonférence et aire": "cercle : aire et circonférence",
    "calcul du périmètre et de l'aire d'un cercle": "cercle : aire et circonférence",
    "calcul du rayon, circonférence et aire d'un cercle": "cercle : aire et circonférence",

    "surface d'un cylindre": "surface et volume du cylindre",
    "surface totale d'un cylindre": "surface et volume du cylindre",
    "surface latérale d'un cylindre": "surface et volume du cylindre",
    "aire des surfaces cylindriques": "surface et volume du cylindre",
    "calcul de la surface et du volume d'un cylindre": "surface et volume du cylindre",
    "rayon d'un cylindre": "surface et volume du cylindre",
    "calcul du rayon d'un cylindre": "surface et volume du cylindre",
    "développement de cylindre": "surface et volume du cylindre",

    "aire latérale d'un cône": "cône : aire et volume",
    "calcul de l'aire latérale d'un cône": "cône : aire et volume",
    "calcul de la génératrice et de l'aire latérale d'un cône": "cône : aire et volume",
    "rayon d'un cône": "cône : aire et volume",
    "développement d'un cône": "cône : aire et volume",

    # --------------------------------------------------
    # Probabilités - variantes
    # --------------------------------------------------
    "probabilités simples": "probabilités",
    "probabilités avec des dés": "probabilités",
    "probabilités avec une pièce": "probabilités",
    "probabilités avec remise": "probabilités avec ou sans remise",
    "probabilités sans remise": "probabilités avec ou sans remise",
    "probabilité conditionnelle": "probabilités conditionnelles",
    "probabilités conditionnelles": "probabilités conditionnelles",
    "probabilité de succès par hasard": "probabilités",

    # --------------------------------------------------
    # Données - variantes
    # --------------------------------------------------
    "collecte et organisation des données": "collecte de données",
    "types de données et statistiques descriptives": "types de données",

        # --------------------------------------------------
    # Fonctions affines, relations linéaires, équations de droites
    # --------------------------------------------------
    "fonction affine": "fonctions affines",
    "fonctions affines": "fonctions affines",
    "relations affines": "fonctions affines",
    "relations et fonctions affines": "fonctions affines",
    "fonctions affines proportionnelles": "fonctions affines",
    "variation d'une fonction affine": "fonctions affines",
    "vitesse moyenne et équation affine": "fonctions affines",

    "relation linéaire": "fonctions linéaires",
    "relations linéaires": "fonctions linéaires",
    "relations non linéaires": "relations non linéaires",

    "équation de droite": "équations de droites",
    "équation de la droite": "équations de droites",
    "équation d'une droite horizontale": "équations de droites",
    "équations de droites": "équations de droites",
    "graphique de relation linéaire": "représentation graphique",
    "analyse de graphiques": "représentation graphique",
    "lecture de graphiques": "représentation graphique",
    "interprétation de graphiques": "représentation graphique",

    # --------------------------------------------------
    # Visualisation et interprétation des données
    # --------------------------------------------------
    "visualisation des données": "représentation des données",
    "représentation graphique des données": "représentation des données",
    "interprétation de données": "interprétation de données",
    "interprétation de données graphiques": "interprétation de données",
    "interprétation de diagrammes": "interprétation de données",
    "interprétation de diagrammes circulaires": "interprétation de données",
    "interprétation des diagrammes circulaires": "interprétation de données",

    # --------------------------------------------------
    # Justification, raisonnement, métacognition
    # --------------------------------------------------
    "justification mathématique": "justification mathématique",
    "justification des solutions": "justification mathématique",
    "justification des méthodes de résolution": "justification mathématique",
    "justification des raisonnements": "justification mathématique",
    "justification des résultats en mathématiques": "justification mathématique",
    "justification d'une solution en pourcentage": "justification mathématique",
    "justification en géométrie": "justification mathématique",

    "raisonnement logique": "raisonnement logique",
    "raisonnement logique sur les nombres pairs": "raisonnement logique",

    "métacognition": "métacognition",
    "métacognition en algèbre": "métacognition",
    "réflexion métacognitive": "métacognition",
    "réflexion sur la stratégie": "métacognition",
    "réflexion sur les erreurs": "métacognition",
    "réflexion sur le processus de codage": "métacognition",

        # --------------------------------------------------
    # Pente, équation de droite
    # --------------------------------------------------
    "pente et équation de droite": "pente et équations de droites",
    "pente et équation de la droite": "pente et équations de droites",
    "pente et équations de droites": "pente et équations de droites",
    "pente des droites": "pente et équations de droites",

    # --------------------------------------------------
    # Aires de triangles et quadrilatères
    # --------------------------------------------------
    "aire d'un triangle": "aire des triangles",
    "aire d'un triangle et propriétés des triangles": "aire des triangles",
    "aire du triangle et propriétés des triangles": "aire des triangles",
    "aire et propriétés des triangles": "aire des triangles",
    "aire de triangle et trapèze": "aire et périmètre",
    "hauteur d'un triangle": "aire des triangles",

    "aire et propriétés des quadrilatères": "quadrilatères",
    "quadrilatères et aire": "quadrilatères",
    "quadrilatères et propriétés géométriques": "quadrilatères",
    "parallélogramme et rectangle": "quadrilatères",
    "trapèze": "quadrilatères",
    "propriétés des losanges": "quadrilatères",
    "propriétés des trapèzes isocèles": "quadrilatères",

    # --------------------------------------------------
    # Angles et droites parallèles
    # --------------------------------------------------
    "angles alternes-internes": "angles et droites parallèles",
    "angles alternes-internes et correspondants": "angles et droites parallèles",
    "angles correspondants et propriétés des quadrilatères": "angles et droites parallèles",
    "angles formés par des droites parallèles et une sécante": "angles et droites parallèles",
    "angles formés par une sécante et des parallèles": "angles et droites parallèles",

    # --------------------------------------------------
    # Cercles et propriétés
    # --------------------------------------------------
    "propriétés des cercles": "cercles",
    "triangles inscrits et propriétés des cercles": "cercles",
    "corde et arc dans un cercle": "cercles",
    "corde et rayon dans un cercle": "cercles",
    "propriétés des cordes dans un cercle": "cercles",
    "propriétés des diamètres dans un cercle": "cercles",
    "médiatrice et cercle": "cercles",

    # --------------------------------------------------
    # Diagonales et polygones
    # --------------------------------------------------
    "diagonales de quadrilatères": "quadrilatères",
    "diagonales d'un losange": "quadrilatères",
    "diagonales égales et propriétés des quadrilatères": "quadrilatères",
    "diagonales perpendiculaires": "quadrilatères",
    "diagonales et propriétés des figures": "quadrilatères",
    "diagonales des polygones réguliers": "polygones",
    "diagonales d'un polygone inscrit": "polygones",
    "diagonales d'un polygone régulier": "polygones",
    "somme des angles intérieurs des polygones": "polygones",
    "propriétés des polygones réguliers": "polygones",
    "polygones réguliers et cercles": "polygones",

        # --------------------------------------------------
    # Aire, périmètre, figures planes
    # --------------------------------------------------
    "périmètre et aire": "aire et périmètre",
    "périmètre et aire d'un rectangle": "aire et périmètre",
    "périmètre et aire des figures géométriques": "aire et périmètre",
    "périmètre et aire des figures composées": "aire et périmètre",
    "périmètre et aire d'un carré": "aire et périmètre",
    "périmètre et aire d'un triangle": "aire et périmètre",
    "périmètre et aire du trapèze": "aire et périmètre",
    "périmètre et aire du triangle équilatéral": "aire et périmètre",
    "aire et périmètre des figures planes": "aire et périmètre",
    "aire et périmètre des figures géométriques": "aire et périmètre",
    "aire et périmètre de figures géométriques": "aire et périmètre",
    "aire et périmètre de formes géométriques": "aire et périmètre",
    "aire et périmètre des carrés": "aire et périmètre",
    "aire et périmètre du rectangle": "aire et périmètre",
    "aire d'un rectangle": "aire et périmètre",
    "calcul de l'aire et du périmètre d'un rectangle": "aire et périmètre",
    "calcul du périmètre et de l'aire d'un rectangle": "aire et périmètre",
    "calcul de périmètre et aire d'un carré": "aire et périmètre",

    # --------------------------------------------------
    # Optimisation aire / périmètre
    # --------------------------------------------------
    "optimisation d'aire": "optimisation aire et périmètre",
    "optimisation de l'aire d'un rectangle": "optimisation aire et périmètre",
    "optimisation de l'aire d'une figure rectangulaire": "optimisation aire et périmètre",
    "optimisation de périmètre": "optimisation aire et périmètre",
    "optimisation de périmètres": "optimisation aire et périmètre",
    "optimisation de figures planes": "optimisation aire et périmètre",
    "optimisation de surfaces": "optimisation aire et périmètre",

    # --------------------------------------------------
    # Aire et volume des solides
    # --------------------------------------------------
    "aire des solides": "aire des solides",
    "aire des cônes": "aire des solides",
    "aire des sphères": "aire des solides",
    "aire de surface d'une sphère": "aire des solides",
    "aire totale des cylindres": "aire des solides",
    "volume des solides": "volume de solides",
    "volume des pyramides": "volume de solides",
    "volume des prismes et pyramides": "volume de solides",
    "volume de la sphère": "volume de solides",
    "volume des sphères": "volume de solides",
    "volume d'un cube": "volume de solides",

    # --------------------------------------------------
    # Changement d’échelle
    # --------------------------------------------------
    "changement d'échelle": "changement d'échelle",
    "changement d'échelle en géométrie": "changement d'échelle",
    "changement d'échelle en géométrie 3d": "changement d'échelle",
    "changement d'échelle et volume": "changement d'échelle",
    "changement d'échelle et aire": "changement d'échelle",
    "changement d'échelle et aire d'un triangle": "changement d'échelle",
    "changement d'échelle d'un cercle": "changement d'échelle",
    "changement d'échelle des volumes et surfaces": "changement d'échelle",
    "changement d'échelle dans les volumes et surfaces": "changement d'échelle",

    # --------------------------------------------------
    # Équations / isolation
    # --------------------------------------------------
    "isolation de variables": "isolation de variables",

        # --------------------------------------------------
    # Exposants et puissances
    # --------------------------------------------------
    "lois des exposants": "lois des exposants",
    "exposants négatifs": "lois des exposants",
    "calcul de puissances": "puissances",

    # --------------------------------------------------
    # Isolation de variables
    # --------------------------------------------------
    "isolation de variable": "isolation de variables",
    "isolation de variables": "isolation de variables",

    # --------------------------------------------------
    # Équations - variantes avancées
    # --------------------------------------------------
    "résolution d'équations rationnelles": "équations",
    "résolution d'équations avec fractions": "équations",
    "équations de coût": "équations",

    # --------------------------------------------------
    # Pourcentages, ratios, proportions
    # --------------------------------------------------
    "calcul de pourcentages": "calcul de pourcentage",
    "calcul de pourcentage à partir d'un rapport": "calcul de pourcentage",
    "calcul de pourcentage et application de ratios": "calcul de pourcentage",
    "estimation de pourcentage": "calcul de pourcentage",
    "estimation de pourcentages": "calcul de pourcentage",

    "pourcentage et fraction": "pourcentage",
    "pourcentage et fractions": "pourcentage",
    "pourcentage et masse": "pourcentage",
    "pourcentage et approximation": "pourcentage",
    "pourcentage et variations de prix": "pourcentage",
    "pourcentages et ratios": "pourcentage",
    "ratios et pourcentages": "pourcentage",
    "rapport et pourcentage": "pourcentage",
    "pourcentage et rapport": "pourcentage",

    "rapport et proportion": "proportionnalité",
    "rapport de proportions": "proportionnalité",
    "proportion directe": "proportionnalité",
    "proportion et pourcentage": "proportionnalité",

    # --------------------------------------------------
    # Moyennes et statistiques
    # --------------------------------------------------
    "moyenne et distributions de notes": "mesures de tendance centrale",
    "moyenne et interprétation des résultats": "mesures de tendance centrale",
    "calcul de moyenne": "mesures de tendance centrale",

    # --------------------------------------------------
    # Géométrie simple
    # --------------------------------------------------
    "périmètre du rectangle": "aire et périmètre",
    "périmètre du cercle": "cercle : aire et circonférence",
    "aire et circonférence d'un cercle": "cercle : aire et circonférence",
    "calcul du rayon et de l'aire d'un cercle": "cercle : aire et circonférence",

    "volume des cubes": "volume de solides",
    "division par zéro": "division",

        # --------------------------------------------------
    # Systèmes d'équations
    # --------------------------------------------------
    "systèmes d'équations linéaires": "systèmes d'équations",
    "systèmes d'équations linéaires à 3 variables": "systèmes d'équations",
    "méthodes de résolution de systèmes d'équations": "systèmes d'équations",
    "modélisation de systèmes d'équations": "systèmes d'équations",

    # --------------------------------------------------
    # Géométrie analytique : droites
    # --------------------------------------------------
    "équation d'une droite": "équations de droites",
    "équation d'une droite parallèle": "équations de droites",
    "équation d'une droite perpendiculaire": "équations de droites",
    "équation de la droite perpendiculaire": "équations de droites",
    "équation d'une droite verticale": "équations de droites",
    "droite verticale": "équations de droites",

    "appartenance d'un point à une droite": "équations de droites",
    "position relative de deux droites": "position relative de deux droites",
    "intersection de droites": "intersection de droites",
    "distance entre droites": "position relative de deux droites",

    # --------------------------------------------------
    # Segments, médianes, médiatrices
    # --------------------------------------------------
    "milieu et longueur d'un segment": "milieu et longueur d'un segment",
    "milieu et distance d'un segment": "milieu et longueur d'un segment",
    "milieu des segments": "milieu et longueur d'un segment",
    "longueur et milieu d'un segment": "milieu et longueur d'un segment",

    "médiane d'un triangle": "droites remarquables du triangle",
    "médiane dans un triangle": "droites remarquables du triangle",
    "propriétés des médianes dans un triangle": "droites remarquables du triangle",
    "longueur et équation de la médiane": "droites remarquables du triangle",

    "médiatrice d'un segment": "droites remarquables du triangle",
    "médiatrices de segments": "droites remarquables du triangle",

    # --------------------------------------------------
    # Cercles en géométrie analytique
    # --------------------------------------------------
    "équation du cercle": "équation du cercle",
    "équation de la tangente à un cercle": "cercle et tangente",
    "cercle et tangente": "cercle et tangente",
    "cercle circonscrit": "cercles",
    "cercle circonscrit et tangentes": "cercles",
    "intersection de cercles": "cercles",
    "géométrie analytique des cercles": "géométrie analytique",

    # --------------------------------------------------
    # Quadrilatères / triangles avancés
    # --------------------------------------------------
    "géométrie analytique des quadrilatères": "quadrilatères",
    "diagonales et propriétés des quadrilatères": "quadrilatères",
    "milieux et longueurs dans un quadrilatère": "quadrilatères",
    "longueur des diagonales": "quadrilatères",
    "longueur et intersection des diagonales": "quadrilatères",
    "intersection de diagonales": "quadrilatères",

    "propriétés des triangles inscrits dans un cercle": "propriétés des triangles",
    "triangles rectangles et cercles": "propriétés des triangles",
    "triangles inscrits": "propriétés des triangles",
    "triangles et cercles circonscrits": "propriétés des triangles",
    "propriétés des triangles et cercles": "propriétés des triangles",
    "propriétés des triangles scalènes": "propriétés des triangles",

        # --------------------------------------------------
    # Relations non linéaires et fonctions quadratiques
    # --------------------------------------------------
    "relations quadratiques": "fonction quadratique",
    "relation quadratique": "fonction quadratique",
    "relations du second degré": "fonction quadratique",
    "relation du second degré": "fonction quadratique",
    "identification de relations quadratiques": "fonction quadratique",
    "identification des relations quadratiques": "fonction quadratique",
    "identification des relations du second degré": "fonction quadratique",
    "caractéristiques de la parabole": "fonction quadratique",
    "caractéristiques d'une fonction quadratique": "fonction quadratique",
    "caractéristiques d'une fonction du second degré": "fonction quadratique",
    "modélisation d'une relation du second degré": "fonction quadratique",
    "modélisation de relations du second degré": "fonction quadratique",

    # --------------------------------------------------
    # Formes de la parabole
    # --------------------------------------------------
    "forme générale d'une parabole": "forme générale de la parabole",
    "forme factorisée d'une parabole": "forme factorisée de la parabole",
    "forme factorisée d'une relation du second degré": "forme factorisée de la parabole",
    "forme canonique de la parabole": "forme canonique de la parabole",
    "forme canonique d'une parabole": "forme canonique de la parabole",
    "forme canonique des fonctions quadratiques": "forme canonique de la parabole",
    "forme canonique des équations quadratiques": "forme canonique de la parabole",
    "parabole en forme canonique": "forme canonique de la parabole",
    "équation canonique de la parabole": "forme canonique de la parabole",
    "équation canonique d'une parabole": "forme canonique de la parabole",
    "forme canonique et forme générale": "forme canonique de la parabole",
    "transformation de la forme canonique en forme générale": "forme canonique de la parabole",

    # --------------------------------------------------
    # Équations du second degré
    # --------------------------------------------------
    "équation quadratique": "équations du second degré",
    "équation du second degré": "équations du second degré",
    "équations du second degré": "équations du second degré",
    "résolution d'équations du second degré": "équations du second degré",
    "racines d'une équation du second degré": "racines d'équations du second degré",
    "racines d'équations du second degré": "racines d'équations du second degré",
    "discriminant": "discriminant des équations du second degré",
    "discriminant d'une équation du second degré": "discriminant des équations du second degré",

    # --------------------------------------------------
    # Intersections de courbes
    # --------------------------------------------------
    "intersection de courbes": "intersection de courbes",
    "intersections de courbes": "intersection de courbes",
    "intersection de paraboles": "intersection de courbes",
    "intersection de figures géométriques": "intersection de courbes",

    # --------------------------------------------------
    # Trigonométrie
    # --------------------------------------------------
    "trigonométrie des triangles rectangles": "trigonométrie des triangles rectangles",
    "sinus dans un triangle rectangle": "trigonométrie des triangles rectangles",
    "sinus dans les triangles rectangles": "trigonométrie des triangles rectangles",
    "cosinus dans un triangle rectangle": "trigonométrie des triangles rectangles",
    "cosinus dans les triangles rectangles": "trigonométrie des triangles rectangles",
    "tangente dans un triangle rectangle": "trigonométrie des triangles rectangles",

        # --------------------------------------------------
    # Vecteurs - notions générales
    # --------------------------------------------------
    "projection de vecteurs": "projection de vecteurs",
    "projection d'un vecteur": "projection de vecteurs",
    "projection vectorielle": "projection de vecteurs",

    "opérations sur les vecteurs": "opérations sur les vecteurs",
    "addition de vecteurs": "opérations sur les vecteurs",
    "soustraction de vecteurs": "opérations sur les vecteurs",
    "addition et soustraction de vecteurs": "opérations sur les vecteurs",
    "addition de vecteurs et colinéarité": "opérations sur les vecteurs",
    "multiplication d'un vecteur par un scalaire": "opérations sur les vecteurs",
    "multiplication de vecteurs par un scalaire": "opérations sur les vecteurs",
    "distributivité des vecteurs": "opérations sur les vecteurs",
    "associativité des opérations vectorielles": "opérations sur les vecteurs",
    "associativité des opérations sur les vecteurs": "opérations sur les vecteurs",

    "calcul de vecteurs": "calcul de vecteurs",
    "calcul de vecteurs et colinéarité": "calcul de vecteurs",
    "calcul de vecteurs et plan": "calcul de vecteurs",
    "calcul de vecteurs et coplanarité": "calcul de vecteurs",

    "représentation des vecteurs": "représentation des vecteurs",
    "vecteurs en coordonnées": "représentation des vecteurs",
    "vecteurs en espace": "représentation des vecteurs",
    "vecteurs et plans": "vecteurs dans l'espace",
    "vecteurs et plan dans l'espace": "vecteurs dans l'espace",
    "vecteurs et coplanarité": "vecteurs dans l'espace",
    "composantes d'un vecteur en 3d": "vecteurs dans l'espace",

    # --------------------------------------------------
    # Vecteurs - composantes, norme, égalité
    # --------------------------------------------------
    "composantes des vecteurs": "composantes et norme des vecteurs",
    "composantes de vecteurs": "composantes et norme des vecteurs",
    "composantes et norme d'un vecteur": "composantes et norme des vecteurs",
    "composantes et norme des vecteurs": "composantes et norme des vecteurs",
    "composantes et direction des vecteurs": "composantes et norme des vecteurs",
    "direction et composantes d'un vecteur": "composantes et norme des vecteurs",

    "égalité de vecteurs": "égalité de vecteurs",
    "égalité des vecteurs": "égalité de vecteurs",
    "égalité et norme des vecteurs": "égalité de vecteurs",
    "égalité des vecteurs et norme": "égalité de vecteurs",

    # --------------------------------------------------
    # Vecteurs - colinéarité
    # --------------------------------------------------
    "colinéarité des vecteurs": "colinéarité des vecteurs",
    "vecteurs et colinéarité": "colinéarité des vecteurs",
    "colinéarité et norme des vecteurs": "colinéarité des vecteurs",
    "colinéarité et vecteur normal": "colinéarité des vecteurs",
    "colinéarité et vecteurs normaux": "colinéarité des vecteurs",

    "translation de vecteurs": "translation de vecteurs",
    "résolution d'équations vectorielles": "équations vectorielles",
    "produit scalaire et orthogonalité": "produit scalaire et orthogonalité",
}


def normaliser_texte(valeur):
    if not valeur:
        return None

    valeur = str(valeur).strip().lower()

    # Nettoyage léger des espaces
    valeur = " ".join(valeur.split())

    return NORMALISATION_NOTIONS.get(valeur, valeur)


def main():
    exercices = (
        Exercice.query
        .filter(Exercice.classification_ia.isnot(None))
        .all()
    )

    print(f"🔎 Exercices classifiés à normaliser : {len(exercices)}")

    total_modifies = 0

    for ex in exercices:
        ancienne_notion = ex.notion_cible
        nouvelle_notion = normaliser_texte(ancienne_notion)

        if nouvelle_notion and nouvelle_notion != ancienne_notion:
            print("-" * 80)
            print(f"Exercice {ex.id}")
            print(f"Ancienne notion : {ancienne_notion}")
            print(f"Nouvelle notion : {nouvelle_notion}")

            ex.notion_cible = nouvelle_notion

            if ex.classification_ia:
                ex.classification_ia["notion_cible_normalisee"] = nouvelle_notion

            db.session.add(ex)
            total_modifies += 1

    try:
        db.session.commit()
        print("=" * 80)
        print(f"✅ Normalisation terminée. Exercices modifiés : {total_modifies}")

    except Exception as e:
        db.session.rollback()
        print("=" * 80)
        print("❌ Erreur pendant la normalisation.")
        print(e)


if __name__ == "__main__":
    with app.app_context():
        main()