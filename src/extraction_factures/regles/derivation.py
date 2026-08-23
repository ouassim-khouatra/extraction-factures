"""Regles de derivation (CDC section 5.5, RD-01 a RD-08).

Principe fondamental, a relire avant d'ecrire chaque regle :

    Une regle de derivation ne s'applique QUE si la valeur cible n'a pas
    ete lue sur le document. Si la valeur a ete lue ET qu'elle est
    derivable, on ne derive pas : on COMPARE — et c'est alors une regle
    de validation (module validation.py).

Tout champ produit ici porte source=DERIVE + la reference de la regle,
pour ne jamais etre confondu avec un champ lu (CDC section 4.b).

Implementees en exemple : RD-01, RD-05.
A ecrire toi-meme sur le meme modele : RD-02, RD-03, RD-04, RD-06,
RD-07, RD-08 (les enonces exacts sont dans le tableau 5.5 du CDC).
Methode : ecris d'abord le test dans tests/, puis la regle.
"""

from decimal import Decimal
from typing import Callable, Optional

from regles.commun import arrondi, present
from schema.modeles import Champ, Facture


def taux_unique(f: Facture) -> Optional[Decimal]:
    """Le taux de TVA du document, s'il est unique et identifiable.

    On regarde d'abord les bandes de TVA, sinon les lignes.
    S'il y a plusieurs taux distincts (facture multi-taux), on renvoie
    None : les derivations globales HT/TTC ne sont alors pas applicables
    telles quelles (c'est RD-04, par bande, qui prend le relais).
    """
    taux = {b.taux.valeur for b in f.bandes_tva if b.taux is not None and present(b.taux)}
    if not taux:
        taux = {
            ligne.taux_tva.valeur
            for ligne in f.lignes
            if ligne.taux_tva is not None and present(ligne.taux_tva)
        }
    if len(taux) == 1:
        seul = taux.pop()
        return seul
    return None


# ---------------------------------------------------------------------------
# Regles implementees (exemples a imiter)
# ---------------------------------------------------------------------------


def rd_01(f: Facture) -> bool:
    """TTC et taux connus, HT absent -> HT = TTC / (1 + taux), TVA = TTC - HT.

    C'est LA regle qui traite le cas "facture affichant uniquement le TTC"
    de la section 4.1 du CDC.
    """
    # 1. La cible (total_ht) doit etre ABSENTE — on n'ecrase jamais un champ lu.
    if present(f.total_ht):
        return False
    # 2. Les ingredients doivent etre presents.
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


def rd_05(f: Facture) -> bool:
    """HT et TVA connus, TTC absent -> TTC = HT + TVA + port + timbre - remise.

    Illustre le motif "termes presents seulement" : port, timbre et remise
    n'entrent dans la formule que s'ils existent. Leur absence n'est pas
    une erreur, c'est juste un terme de moins.
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


def rd_02(f: Facture) -> bool:
    """HT et taux connus, TVA absente -> TVA = HT x taux.

    Le TTC est ensuite produit automatiquement par RD-05 au tour suivant
    de la boucle (chainage) : resultat final conforme au tableau 5.5 du CDC.
    """
    # 1. La cible (total_tva) doit etre ABSENTE — on n'ecrase jamais un champ lu.
    if present(f.total_tva):
        return False
    # 2. Les ingredients doivent etre presents.
    if not present(f.total_ht):
        return False
    taux = taux_unique(f)
    if taux is None:
        return False

    assert f.total_ht is not None and f.total_ht.valeur is not None
    tva = arrondi(f.total_ht.valeur * taux / Decimal("100"))
    f.total_tva = Champ.derive(tva, "RD-02")
    return True
def rd_06(f: Facture) -> bool:
    """TTC et acompte connus, net a payer absent -> net = TTC - acompte - escompte."""
    # 1. La cible ne doit pas avoir ete lue sur le document.
    #    Ici, la cible c'est le net a payer.
    if present(f.net_a_payer):
        return False
    # 2. Les deux ingredients obligatoires doivent etre presents.
    if not present(f.total_ttc, f.acompte):
        return False

    # 3. Le calcul : le TTC moins l'avance deja versee.
    net = f.total_ttc.valeur - f.acompte.valeur
    # 4. Terme optionnel (meme motif que dans rd_05) :
    #    l'escompte ne se soustrait que s'il est present.
    if f.escompte is not None and present(f.escompte):
        net -= f.escompte.valeur
    # 5. On enregistre le resultat, marque comme derive par quelle regle ?
    f.net_a_payer = Champ.derive(arrondi(net), "RD-06")
    return True
def rd_07(f: Facture) -> bool:
    """Qte et PU connus au niveau ligne, montant HT absent -> qte x PU - remise."""
    changement = False
    for ligne in f.lignes:
        # 1. Le montant est deja imprime sur cette ligne ? On n'y touche pas.
        if present(ligne.montant_ht):
            continue
        # 2. Il manque la quantite ou le prix ? On ne peut rien calculer, on saute.
        if not present(ligne.quantite, ligne.prix_unitaire_ht):
            continue
        # 3. Le calcul de base.
        montant = ligne.quantite.valeur * ligne.prix_unitaire_ht.valeur
        # 4. La remise de ligne, seulement si elle existe.
        if ligne.montant_remise is not None and present(ligne.montant_remise):
            montant -= ligne.montant_remise.valeur
        # 5. On range le resultat avec son etiquette.
        ligne.montant_ht = Champ.derive(arrondi(montant), "RD-07")
        changement = True
    return changement
# ---------------------------------------------------------------------------
# TODO stagiaire — a implementer semaine 2, test d'abord
# ---------------------------------------------------------------------------
#
# def rd_02(f): "HT et taux connus, TTC absent -> TVA = HT x taux, TTC = HT + TVA"
# def rd_03(f): "HT et TVA connus, taux absent -> taux = TVA / HT, normalise RD-08"
# def rd_04(f): "Lignes presentes, totaux absents -> agregation par taux, somme des bandes"
# def rd_06(f): "TTC et acompte connus, net absent -> net = TTC - acompte - escompte"
# def rd_07(f): "Qte, PU, remise connus au niveau ligne -> montant_ht_ligne"
# def rd_08(taux): "Aligner un taux calcule sur le bareme si ecart < 0,5 point"
#                  (fonction utilitaire appelee par RD-03, pas une regle sur Facture)


# Ordre d'application. Certaines derivations en debloquent d'autres
# (ex. RD-04 produit des totaux que RD-05 peut ensuite utiliser), d'ou
# la boucle en point fixe dans appliquer_derivations.
REGLES_DERIVATION: list[Callable[[Facture], bool]] = [
    rd_01,
    rd_05,
    rd_02,
    rd_06,
    rd_07,

    # rd_02, rd_03, rd_04, rd_06, rd_07 : a ajouter au fur et a mesure
]


def appliquer_derivations(f: Facture, max_passes: int = 10) -> list[str]:
    """Applique les regles jusqu'a ce que plus rien ne change.

    Retourne la liste des regles appliquees (pour le journal / la tracabilite).
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
