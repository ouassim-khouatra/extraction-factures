"""Regles de derivation (CDC section 5.5, RD-01 a RD-08).

Principe fondamental, a relire avant chaque regle :

    Une regle de derivation ne s'applique QUE si la valeur cible n'a pas
    ete lue sur le document. Si la valeur a ete lue ET qu'elle est
    derivable, on ne derive pas : on COMPARE — et c'est alors une regle
    de validation (module validation.py).

Tout champ produit ici porte source=DERIVE + la reference de la regle,
pour ne jamais etre confondu avec un champ lu (CDC section 4.b).
"""

from decimal import Decimal
from typing import Callable, Optional

from regles.commun import (
    BAREME_TVA,
    ECART_ALIGNEMENT_TAUX,
    arrondi,
    present,
)
from schema.modeles import BandeTVA, Champ, Facture


def taux_unique(f: Facture) -> Optional[Decimal]:
    """Le taux de TVA du document, s'il est unique et identifiable.

    On regarde d'abord les bandes de TVA, sinon les lignes.
    S'il y a plusieurs taux distincts (facture multi-taux), on renvoie
    None : les derivations globales ne s'appliquent pas telles quelles
    (c'est RD-04, par bande, qui prend le relais).
    """
    taux = {b.taux.valeur for b in f.bandes_tva if b.taux is not None and present(b.taux)}
    if not taux:
        taux = {
            ligne.taux_tva.valeur
            for ligne in f.lignes
            if ligne.taux_tva is not None and present(ligne.taux_tva)
        }
    if len(taux) == 1:
        return taux.pop()
    return None


def rd_08_aligner_taux(taux: Decimal) -> tuple[Decimal, bool]:
    """RD-08 — aligne un taux calcule sur le bareme legal.

    Si l'ecart avec un taux legal est inferieur a 0,5 point, on aligne.
    Sinon on conserve la valeur calculee (arrondie) : RV-08 la signalera
    comme hors bareme, ce qui enverra le document en relecture — c'est
    exactement le comportement voulu par le CDC ("conserver et signaler").
    Fonction utilitaire appelee par RD-03 ; pas une regle sur Facture.
    """
    for legal in BAREME_TVA:
        if abs(taux - legal) < ECART_ALIGNEMENT_TAUX:
            return legal, True
    return arrondi(taux), False


# ---------------------------------------------------------------------------
# Regles sur les totaux
# ---------------------------------------------------------------------------


def rd_01(f: Facture) -> bool:
    """TTC et taux connus, HT absent -> HT = TTC / (1 + taux), TVA = TTC - HT.

    C'est LA regle qui traite le cas "facture affichant uniquement le TTC"
    de la section 4.1 du CDC.
    """
    if present(f.total_ht):
        return False
    if not present(f.total_ttc):
        return False
    taux = taux_unique(f)
    if taux is None:
        return False

    assert f.total_ttc is not None and f.total_ttc.valeur is not None
    ttc = f.total_ttc.valeur
    ht = arrondi(ttc / (Decimal("1") + taux / Decimal("100")))
    f.total_ht = Champ.derive(ht, "RD-01")

    if not present(f.total_tva):
        f.total_tva = Champ.derive(arrondi(ttc - ht), "RD-01")
    return True


def rd_02(f: Facture) -> bool:
    """HT et taux connus, TVA absente -> TVA = HT x taux.

    Le TTC est ensuite produit automatiquement par RD-05 au tour suivant
    de la boucle (chainage) : resultat final conforme au tableau 5.5 du CDC.
    """
    if present(f.total_tva):
        return False
    if not present(f.total_ht):
        return False
    taux = taux_unique(f)
    if taux is None:
        return False

    assert f.total_ht is not None and f.total_ht.valeur is not None
    tva = arrondi(f.total_ht.valeur * taux / Decimal("100"))
    f.total_tva = Champ.derive(tva, "RD-02")
    return True


def rd_03(f: Facture) -> bool:
    """HT et TVA connus, taux absent -> taux = TVA / HT, normalise par RD-08.

    Le taux calcule est range dans une bande de TVA creee pour l'occasion
    (le schema n'a pas de champ "taux global" : une facture mono-taux est
    simplement une facture a une seule bande).
    """
    if f.bandes_tva:
        return False
    if any(l.taux_tva is not None and present(l.taux_tva) for l in f.lignes):
        return False  # les lignes portent deja l'info taux : RD-04 s'en charge
    if not present(f.total_ht, f.total_tva):
        return False

    assert f.total_ht is not None and f.total_ht.valeur is not None
    assert f.total_tva is not None and f.total_tva.valeur is not None
    ht = f.total_ht.valeur
    if ht == 0:
        return False
    taux_calcule = f.total_tva.valeur / ht * Decimal("100")
    taux, _aligne = rd_08_aligner_taux(taux_calcule)

    f.bandes_tva.append(
        BandeTVA(
            taux=Champ.derive(taux, "RD-03"),
            base_ht=Champ.derive(arrondi(ht), "RD-03"),
            montant_tva=Champ.derive(arrondi(f.total_tva.valeur), "RD-03"),
        )
    )
    return True


def rd_04(f: Facture) -> bool:
    """Lignes presentes, totaux absents -> agregation par taux, somme des bandes.

    Trois etages, chacun conditionnel :
      a) total HT = somme des montants HT des lignes (- remise globale) ;
      b) bandes de TVA construites en groupant les lignes par taux ;
      c) total TVA = somme des montants de TVA des bandes.
    NB (regle de gestion a confirmer avec le comptable) : le port n'entre
    pas dans le total HT ici — il rejoint le calcul au niveau TTC (RD-05),
    conformement a la formule du CDC.
    """
    if not f.lignes:
        return False
    changement = False

    montants_lignes = [
        l.montant_ht.valeur
        for l in f.lignes
        if l.montant_ht is not None and present(l.montant_ht)
    ]
    toutes_les_lignes_ont_un_ht = len(montants_lignes) == len(f.lignes)

    # a) total HT
    if toutes_les_lignes_ont_un_ht and not present(f.total_ht):
        total = sum(montants_lignes, start=Decimal("0"))
        if f.total_remise is not None and present(f.total_remise):
            assert f.total_remise.valeur is not None
            total -= f.total_remise.valeur
        f.total_ht = Champ.derive(arrondi(total), "RD-04")
        changement = True

    # b) bandes de TVA
    if not f.bandes_tva and toutes_les_lignes_ont_un_ht:
        toutes_les_lignes_ont_un_taux = all(
            l.taux_tva is not None and present(l.taux_tva) for l in f.lignes
        )
        if toutes_les_lignes_ont_un_taux:
            bases_par_taux: dict[Decimal, Decimal] = {}
            for l in f.lignes:
                assert l.taux_tva is not None and l.taux_tva.valeur is not None
                assert l.montant_ht is not None and l.montant_ht.valeur is not None
                taux = l.taux_tva.valeur
                bases_par_taux[taux] = bases_par_taux.get(taux, Decimal("0")) + l.montant_ht.valeur
            for taux, base in sorted(bases_par_taux.items()):
                f.bandes_tva.append(
                    BandeTVA(
                        taux=Champ.derive(taux, "RD-04"),
                        base_ht=Champ.derive(arrondi(base), "RD-04"),
                        montant_tva=Champ.derive(arrondi(base * taux / Decimal("100")), "RD-04"),
                    )
                )
            changement = True

    # c) total TVA = somme des bandes
    if f.bandes_tva and not present(f.total_tva):
        montants_bandes = [
            b.montant_tva.valeur
            for b in f.bandes_tva
            if b.montant_tva is not None and present(b.montant_tva)
        ]
        if len(montants_bandes) == len(f.bandes_tva):
            f.total_tva = Champ.derive(
                arrondi(sum(montants_bandes, start=Decimal("0"))), "RD-04"
            )
            changement = True

    return changement


def rd_05(f: Facture) -> bool:
    """HT et TVA connus, TTC absent -> TTC = HT + TVA + port + timbre - remise.

    Illustre le motif "termes presents seulement" : port, timbre et remise
    n'entrent dans la formule que s'ils existent.
    """
    if present(f.total_ttc):
        return False
    if not present(f.total_ht, f.total_tva):
        return False

    assert f.total_ht is not None and f.total_ht.valeur is not None
    assert f.total_tva is not None and f.total_tva.valeur is not None
    ttc = f.total_ht.valeur + f.total_tva.valeur
    if f.total_port is not None and present(f.total_port):
        assert f.total_port.valeur is not None
        ttc += f.total_port.valeur
    if f.timbre_fiscal is not None and present(f.timbre_fiscal):
        assert f.timbre_fiscal.valeur is not None
        ttc += f.timbre_fiscal.valeur
    if f.total_remise is not None and present(f.total_remise):
        assert f.total_remise.valeur is not None
        ttc -= f.total_remise.valeur

    f.total_ttc = Champ.derive(arrondi(ttc), "RD-05")
    return True


def rd_06(f: Facture) -> bool:
    """TTC et acompte connus, net a payer absent -> net = TTC - acompte - escompte."""
    if present(f.net_a_payer):
        return False
    if not present(f.total_ttc, f.acompte):
        return False

    assert f.total_ttc is not None and f.total_ttc.valeur is not None
    assert f.acompte is not None and f.acompte.valeur is not None
    net = f.total_ttc.valeur - f.acompte.valeur
    if f.escompte is not None and present(f.escompte):
        assert f.escompte.valeur is not None
        net -= f.escompte.valeur
    f.net_a_payer = Champ.derive(arrondi(net), "RD-06")
    return True


def rd_07(f: Facture) -> bool:
    """Qte et PU connus au niveau ligne, montant HT absent -> qte x PU - remise."""
    changement = False
    for ligne in f.lignes:
        if present(ligne.montant_ht):
            continue
        if not present(ligne.quantite, ligne.prix_unitaire_ht):
            continue
        assert ligne.quantite is not None and ligne.quantite.valeur is not None
        assert ligne.prix_unitaire_ht is not None and ligne.prix_unitaire_ht.valeur is not None
        montant = ligne.quantite.valeur * ligne.prix_unitaire_ht.valeur
        if ligne.montant_remise is not None and present(ligne.montant_remise):
            assert ligne.montant_remise.valeur is not None
            montant -= ligne.montant_remise.valeur
        ligne.montant_ht = Champ.derive(arrondi(montant), "RD-07")
        changement = True
    return changement


# Ordre d'application. Certaines derivations en debloquent d'autres
# (ex. RD-07 remplit les lignes, RD-04 en tire les totaux, RD-05 conclut
# au TTC) : la boucle en point fixe de appliquer_derivations refait des
# tours tant que quelque chose change.
REGLES_DERIVATION: list[Callable[[Facture], bool]] = [
    rd_01,
    rd_02,
    rd_03,
    rd_04,
    rd_05,
    rd_06,
    rd_07,
]


def appliquer_derivations(f: Facture, max_passes: int = 10) -> list[str]:
    """Applique les regles jusqu'a ce que plus rien ne change.

    Retourne la liste des regles appliquees (tracabilite / journal).
    `max_passes` est un garde-fou contre une boucle infinie si une regle
    est mal ecrite (une regle bien ecrite devient inapplicable une fois
    sa cible remplie, puisque la cible est alors presente).
    """
    appliquees: list[str] = []
    for _ in range(max_passes):
        changement = False
        for regle in REGLES_DERIVATION:
            if regle(f):
                appliquees.append(regle.__name__)
                changement = True
        if not changement:
            break
    return appliquees
