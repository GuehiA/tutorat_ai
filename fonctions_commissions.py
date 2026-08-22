# fonctions_commissions.py

from datetime import datetime, timedelta

from sqlalchemy import func

from models import (
    db,
    Commission,
    VersementManuel,
    User
)


print("✅ Import des modèles de commission réussi")


# ================================================================
# OUTILS INTERNES
# ================================================================

def _normaliser_plan_commission(plan_type):
    """
    Normalise les différents anciens et nouveaux noms de forfaits.
    """

    if not plan_type:
        return "unknown"

    valeur = str(plan_type).strip().lower()

    aliases = {
        # Nouveaux noms Stripe
        "monthly": "monthly",
        "quarterly": "quarterly",
        "annual": "annual",

        # Anciens noms français
        "mensuel": "monthly",
        "trimestriel": "quarterly",
        "annuel": "annual",

        # Anciens forfaits
        "basique": "basique",
        "standard": "standard",
        "premium": "premium",
        "gratuit": "gratuit",

        # Autres appellations historiques éventuelles
        "subscription": "subscription"
    }

    return aliases.get(
        valeur,
        valeur
    )


def _taux_commission_pour_plan(plan_type):
    """
    Retourne le taux de commission applicable.

    Les abonnements Stripe actuels :
        monthly
        quarterly
        annual

    utilisent le taux historique de 20 % de TutoratAI.
    """

    plan = _normaliser_plan_commission(
        plan_type
    )

    taux = {
        # Abonnements Stripe actuels
        "monthly": 20.0,
        "quarterly": 20.0,
        "annual": 20.0,

        # Compatibilité historique
        "subscription": 20.0,

        # Anciens forfaits
        "basique": 5.0,
        "standard": 7.5,
        "premium": 10.0,
        "gratuit": 0.0
    }

    return taux.get(
        plan,
        20.0
    )


def _chercher_commission_stripe_existante(
    eleve_id,
    stripe_reference
):
    """
    Cherche une commission déjà créée pour une référence Stripe.

    La référence Stripe est conservée dans details_bonus afin
    d'éviter une migration de la base de données.

    Cela permet notamment d'éviter qu'un même paiement crée
    plusieurs commissions lorsque Stripe renvoie plusieurs fois
    un webhook.
    """

    if not stripe_reference:
        return None

    try:
        commissions = (
            Commission.query
            .filter_by(
                eleve_id=eleve_id
            )
            .all()
        )

        for commission in commissions:
            details = (
                commission.details_bonus
                if isinstance(
                    commission.details_bonus,
                    dict
                )
                else {}
            )

            reference_existante = (
                details.get(
                    "stripe_reference"
                )
            )

            if (
                reference_existante
                and reference_existante
                == stripe_reference
            ):
                return commission

        return None

    except Exception as e:
        print(
            "⚠️ Erreur vérification "
            f"commission Stripe existante : {e}"
        )

        return None


# ================================================================
# CRÉATION DES COMMISSIONS
# ================================================================

def creer_commission_apres_paiement(
    eleve_id,
    plan_type,
    montant,
    stripe_reference=None,
    source="stripe"
):
    """
    Crée une commission après un paiement réussi d'élève.

    Protection anti-doublon :
    lorsqu'une stripe_reference est fournie, une même transaction
    Stripe ne peut pas générer plusieurs commissions.

    stripe_reference devrait idéalement être l'identifiant unique
    de la facture Stripe : invoice.id.
    """

    try:
        # ========================================================
        # 1. IDENTIFIER L'ÉLÈVE
        # ========================================================

        eleve = db.session.get(
            User,
            eleve_id
        )

        if not eleve:
            print(
                f"❌ Élève {eleve_id} non trouvé"
            )
            return None

        if eleve.role not in {
            "eleve",
            "élève"
        }:
            print(
                f"❌ Utilisateur {eleve_id} "
                f"n'est pas un élève"
            )
            return None

        # ========================================================
        # 2. IDENTIFIER L'ENSEIGNANT RÉFÉRENT
        # ========================================================

        enseignant_id = getattr(
            eleve,
            "enseignant_referent_id",
            None
        )

        if not enseignant_id:
            print(
                "ℹ️ Aucune commission créée : "
                f"l'élève {eleve_id} n'a pas "
                "d'enseignant référent."
            )
            return None

        enseignant = db.session.get(
            User,
            enseignant_id
        )

        if not enseignant:
            print(
                f"❌ Enseignant {enseignant_id} "
                "non trouvé"
            )
            return None

        if enseignant.role != "enseignant":
            print(
                f"❌ Utilisateur {enseignant_id} "
                "n'est pas un enseignant"
            )
            return None

        # ========================================================
        # 3. NORMALISER LE PLAN
        # ========================================================

        plan_normalise = (
            _normaliser_plan_commission(
                plan_type
            )
        )

        # ========================================================
        # 4. VÉRIFIER LE MONTANT
        # ========================================================

        try:
            montant = float(
                montant
            )

        except (
            TypeError,
            ValueError
        ):
            print(
                "❌ Montant de paiement "
                f"invalide : {montant}"
            )
            return None

        if montant <= 0:
            print(
                "❌ Impossible de créer une "
                "commission pour un paiement "
                f"de {montant}$"
            )
            return None

        # ========================================================
        # 5. PROTECTION ANTI-DOUBLON STRIPE
        # ========================================================

        if stripe_reference:
            commission_existante = (
                _chercher_commission_stripe_existante(
                    eleve_id=eleve_id,
                    stripe_reference=stripe_reference
                )
            )

            if commission_existante:
                print(
                    "ℹ️ Commission Stripe déjà "
                    "existante."
                )

                print(
                    f"   Référence : "
                    f"{stripe_reference}"
                )

                print(
                    f"   Commission ID : "
                    f"{commission_existante.id}"
                )

                print(
                    "   Aucun doublon créé."
                )

                return commission_existante

        # ========================================================
        # 6. CALCULER LE TAUX
        # ========================================================

        taux_commission = (
            _taux_commission_pour_plan(
                plan_normalise
            )
        )

        montant_commission = round(
            montant
            * (
                taux_commission
                / 100.0
            ),
            2
        )

        # ========================================================
        # 7. CRÉER LA COMMISSION
        # ========================================================

        maintenant = datetime.utcnow()

        commission = Commission(
            enseignant_id=enseignant_id,

            eleve_id=eleve_id,

            type_abonnement=plan_normalise,

            montant_total=montant,

            montant_commission=(
                montant_commission
            ),

            taux_base=taux_commission,

            statut="pending",

            statut_eleve="actif",

            date_paiement_eleve=maintenant,

            date_calcul=maintenant,

            details_bonus={
                "plan_type":
                    plan_normalise,

                "taux_applique":
                    taux_commission,

                "montant_original":
                    montant,

                "stripe_reference":
                    stripe_reference,

                "source":
                    source,

                "created_at":
                    maintenant.isoformat()
            }
        )

        db.session.add(
            commission
        )

        db.session.commit()

        print(
            "💰 Commission créée avec succès"
        )

        print(
            f"   Commission ID : "
            f"{commission.id}"
        )

        print(
            f"   Élève : "
            f"{eleve_id}"
        )

        print(
            f"   Enseignant : "
            f"{enseignant_id}"
        )

        print(
            f"   Plan : "
            f"{plan_normalise}"
        )

        print(
            f"   Paiement : "
            f"{montant:.2f}$"
        )

        print(
            f"   Taux : "
            f"{taux_commission:.2f}%"
        )

        print(
            f"   Commission : "
            f"{montant_commission:.2f}$"
        )

        if stripe_reference:
            print(
                f"   Référence Stripe : "
                f"{stripe_reference}"
            )

        return commission

    except Exception as e:
        print(
            "❌ Erreur création "
            f"commission : {e}"
        )

        db.session.rollback()

        return None


# ================================================================
# ALIAS UTILISÉ PAR APP.PY
# ================================================================

def integrer_commission(
    eleve_id,
    plan_type,
    montant,
    stripe_reference=None,
    source="stripe"
):
    """
    Alias vers creer_commission_apres_paiement().

    Conservé afin de ne pas casser les appels existants dans
    app.py ou d'autres parties de l'application.
    """

    return creer_commission_apres_paiement(
        eleve_id=eleve_id,
        plan_type=plan_type,
        montant=montant,
        stripe_reference=stripe_reference,
        source=source
    )


# ================================================================
# CALCUL DES COMMISSIONS D'UN ENSEIGNANT
# ================================================================

def calculer_commission_enseignant(
    enseignant_id,
    date_debut=None,
    date_fin=None
):
    """
    Calcule les commissions d'un enseignant pour une période.

    Si aucune période n'est indiquée, utilise le mois courant.
    """

    try:
        # ========================================================
        # PÉRIODE PAR DÉFAUT : MOIS EN COURS
        # ========================================================

        if (
            not date_debut
            or not date_fin
        ):
            date_debut = (
                datetime.utcnow()
                .replace(
                    day=1,
                    hour=0,
                    minute=0,
                    second=0,
                    microsecond=0
                )
            )

            date_mois_suivant = (
                date_debut.replace(
                    day=28
                )
                + timedelta(
                    days=4
                )
            )

            date_fin = (
                date_mois_suivant.replace(
                    day=1
                )
                - timedelta(
                    microseconds=1
                )
            )

        # ========================================================
        # COMMISSIONS
        # ========================================================

        commissions = (
            Commission.query
            .filter(
                Commission.enseignant_id
                == enseignant_id,

                Commission.date_calcul.between(
                    date_debut,
                    date_fin
                )
            )
            .order_by(
                Commission.date_calcul.desc()
            )
            .all()
        )

        total_commission = sum(
            float(
                commission.montant_commission
                or 0
            )
            for commission in commissions
        )

        en_attente = sum(
            float(
                commission.montant_commission
                or 0
            )
            for commission in commissions
            if commission.statut == "pending"
        )

        payees = sum(
            float(
                commission.montant_commission
                or 0
            )
            for commission in commissions
            if commission.statut == "paid"
        )

        return {
            "total":
                round(
                    total_commission,
                    2
                ),

            "en_attente":
                round(
                    en_attente,
                    2
                ),

            "payees":
                round(
                    payees,
                    2
                ),

            "nombre":
                len(
                    commissions
                ),

            "commissions":
                [
                    commission.to_dict()
                    if hasattr(
                        commission,
                        "to_dict"
                    )
                    else commission

                    for commission
                    in commissions
                ]
        }

    except Exception as e:
        print(
            "⚠️ Erreur "
            "calculer_commission_enseignant : "
            f"{e}"
        )

        return {
            "total": 0,
            "en_attente": 0,
            "payees": 0,
            "nombre": 0,
            "commissions": []
        }


# ================================================================
# TRAITEMENT ADMINISTRATIF DES VERSEMENTS
# ================================================================

def traiter_versement_manuel(
    versement_id,
    action,
    reference_interac=None,
    preuve_versement=None
):
    """
    Traite une demande de versement manuel.
    """

    try:
        versement = db.session.get(
            VersementManuel,
            versement_id
        )

        if not versement:
            print(
                f"❌ Versement "
                f"{versement_id} non trouvé"
            )

            return (
                False,
                "Versement non trouvé"
            )

        # ========================================================
        # APPROUVER
        # ========================================================

        if action == "approuver":
            versement.statut = (
                "approved"
            )

            versement.date_versement = (
                datetime.utcnow()
            )

            if reference_interac:
                versement.reference_interac = (
                    reference_interac
                )

            if preuve_versement:
                versement.preuve_versement = (
                    preuve_versement
                )

            db.session.commit()

            print(
                f"✅ Versement "
                f"{versement_id} approuvé"
            )

            return (
                True,
                "Versement approuvé"
            )

        # ========================================================
        # REJETER
        # ========================================================

        if action == "rejeter":
            versement.statut = (
                "rejected"
            )

            db.session.commit()

            print(
                f"✅ Versement "
                f"{versement_id} rejeté"
            )

            return (
                True,
                "Versement rejeté"
            )

        # ========================================================
        # COMPLÉTER
        # ========================================================

        if action == "completer":
            versement.statut = (
                "complete"
            )

            versement.date_versement = (
                datetime.utcnow()
            )

            if reference_interac:
                versement.reference_interac = (
                    reference_interac
                )

            if preuve_versement:
                versement.preuve_versement = (
                    preuve_versement
                )

            db.session.commit()

            print(
                f"✅ Versement "
                f"{versement_id} complété"
            )

            return (
                True,
                "Versement complété"
            )

        return (
            False,
            "Action non reconnue"
        )

    except Exception as e:
        print(
            "❌ Erreur traitement "
            f"versement : {e}"
        )

        db.session.rollback()

        return (
            False,
            str(e)
        )


# ================================================================
# DEMANDE DE VERSEMENT MANUEL
# ================================================================

def demander_versement_manuel(
    enseignant_id,
    montant_total,
    email_interac,
    methode_paiement="interac"
):
    """
    Crée une demande de versement manuel pour un enseignant.
    """

    try:
        # ========================================================
        # ENSEIGNANT
        # ========================================================

        enseignant = db.session.get(
            User,
            enseignant_id
        )

        if (
            not enseignant
            or enseignant.role
            != "enseignant"
        ):
            print(
                f"❌ Enseignant "
                f"{enseignant_id} "
                "non trouvé ou invalide"
            )

            return (
                None,
                "Enseignant non trouvé"
            )

        # ========================================================
        # MONTANT DEMANDÉ
        # ========================================================

        try:
            montant_total = float(
                montant_total
            )

        except (
            TypeError,
            ValueError
        ):
            return (
                None,
                "Montant invalide"
            )

        if montant_total <= 0:
            return (
                None,
                "Le montant doit être supérieur à zéro"
            )

        # ========================================================
        # COMMISSIONS DISPONIBLES
        # ========================================================

        commissions_pending = (
            Commission.query
            .filter_by(
                enseignant_id=enseignant_id,
                statut="pending"
            )
            .all()
        )

        solde_pending = sum(
            float(
                commission.montant_commission
                or 0
            )
            for commission
            in commissions_pending
        )

        solde_pending = round(
            solde_pending,
            2
        )

        if montant_total > solde_pending:
            print(
                f"⚠️ Montant demandé "
                f"({montant_total:.2f}$) "
                f"> solde disponible "
                f"({solde_pending:.2f}$)"
            )

            return (
                None,
                "Solde insuffisant"
            )

        # ========================================================
        # FRAIS
        # ========================================================

        frais_transaction = 1.00

        montant_net = round(
            montant_total
            - frais_transaction,
            2
        )

        if montant_net < 0:
            montant_net = 0.0

        # ========================================================
        # CRÉER LA DEMANDE
        # ========================================================

        versement = VersementManuel(
            enseignant_id=
                enseignant_id,

            montant_total=
                montant_total,

            frais_transaction=
                frais_transaction,

            montant_net=
                montant_net,

            email_interac=
                email_interac,

            methode_paiement=
                methode_paiement,

            statut=
                "demande",

            date_demande=
                datetime.utcnow()
        )

        db.session.add(
            versement
        )

        db.session.commit()

        print(
            "✅ Demande de versement "
            f"créée pour enseignant "
            f"{enseignant_id}"
        )

        print(
            f"   Montant brut : "
            f"{montant_total:.2f}$"
        )

        print(
            f"   Frais : "
            f"{frais_transaction:.2f}$"
        )

        print(
            f"   Montant net : "
            f"{montant_net:.2f}$"
        )

        return (
            versement,
            "Demande créée avec succès"
        )

    except Exception as e:
        print(
            "❌ Erreur demande "
            f"versement : {e}"
        )

        db.session.rollback()

        return (
            None,
            str(e)
        )


# ================================================================
# COMPLÉTER UN VERSEMENT MANUEL
# ================================================================

def completer_versement_manuel(
    versement_id,
    reference_interac,
    preuve_versement=None
):
    """
    Complète un versement manuel et marque les commissions
    correspondantes comme payées.

    Important :
    le montant_total du VersementManuel n'est jamais modifié.
    """

    try:
        versement = db.session.get(
            VersementManuel,
            versement_id
        )

        if not versement:
            print(
                f"❌ Versement "
                f"{versement_id} non trouvé"
            )

            return (
                False,
                "Versement non trouvé"
            )

        # ========================================================
        # INFORMATIONS DU VERSEMENT
        # ========================================================

        versement.statut = (
            "complete"
        )

        versement.date_versement = (
            datetime.utcnow()
        )

        versement.reference_interac = (
            reference_interac
        )

        if preuve_versement:
            versement.preuve_versement = (
                preuve_versement
            )

        # ========================================================
        # COMMISSIONS EN ATTENTE
        # ========================================================

        commissions = (
            Commission.query
            .filter_by(
                enseignant_id=
                    versement.enseignant_id,

                statut=
                    "pending"
            )
            .order_by(
                Commission.date_calcul.asc()
            )
            .all()
        )

        # IMPORTANT :
        # on utilise une variable séparée.
        # On ne modifie jamais versement.montant_total.

        reste_a_imputer = float(
            versement.montant_total
            or 0
        )

        commissions_payees = 0

        montant_commissions_payees = 0.0

        for commission in commissions:
            montant_commission = float(
                commission.montant_commission
                or 0
            )

            if montant_commission <= 0:
                continue

            if (
                montant_commission
                <= reste_a_imputer
            ):
                commission.statut = (
                    "paid"
                )

                commission.date_versement_manuel = (
                    datetime.utcnow()
                )

                commission.reference_interac = (
                    reference_interac
                )

                reste_a_imputer = round(
                    reste_a_imputer
                    - montant_commission,
                    2
                )

                montant_commissions_payees += (
                    montant_commission
                )

                commissions_payees += 1

        db.session.commit()

        print(
            f"✅ Versement "
            f"{versement_id} complété"
        )

        print(
            f"   Commissions marquées payées : "
            f"{commissions_payees}"
        )

        print(
            f"   Total imputé : "
            f"{montant_commissions_payees:.2f}$"
        )

        print(
            f"   Reste non imputé : "
            f"{reste_a_imputer:.2f}$"
        )

        return (
            True,
            "Versement complété avec succès"
        )

    except Exception as e:
        print(
            "❌ Erreur complétion "
            f"versement : {e}"
        )

        db.session.rollback()

        return (
            False,
            str(e)
        )


# ================================================================
# RÉCUPÉRER LES COMMISSIONS D'UN ENSEIGNANT
# ================================================================

def get_commissions_enseignant(
    enseignant_id,
    statut=None
):
    """
    Récupère les commissions d'un enseignant.
    """

    query = (
        Commission.query
        .filter_by(
            enseignant_id=enseignant_id
        )
    )

    if statut:
        query = query.filter_by(
            statut=statut
        )

    return (
        query
        .order_by(
            Commission.date_calcul.desc()
        )
        .all()
    )


# ================================================================
# RÉCUPÉRER LES VERSEMENTS D'UN ENSEIGNANT
# ================================================================

def get_versements_enseignant(
    enseignant_id,
    statut=None
):
    """
    Récupère les versements d'un enseignant.
    """

    query = (
        VersementManuel.query
        .filter_by(
            enseignant_id=enseignant_id
        )
    )

    if statut:
        query = query.filter_by(
            statut=statut
        )

    return (
        query
        .order_by(
            VersementManuel.date_demande.desc()
        )
        .all()
    )


# ================================================================
# SOLDE DES COMMISSIONS
# ================================================================

def get_solde_commission(
    enseignant_id
):
    """
    Calcule le solde des commissions en attente
    d'un enseignant.
    """

    solde = (
        db.session.query(
            func.sum(
                Commission.montant_commission
            )
        )
        .filter(
            Commission.enseignant_id
            == enseignant_id,

            Commission.statut
            == "pending"
        )
        .scalar()
    )

    return round(
        float(solde or 0.0),
        2
    )


print(
    "✅ Module fonctions_commissions "
    "chargé avec succès"
)