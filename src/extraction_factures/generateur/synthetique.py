"""Generateur de factures synthetiques (CDC sections 8.2 et 8.3).

Produit des couples (PDF, JSON de verite terrain) :
- le PDF ressemble a une vraie facture marocaine (3 gabarits varies) ;
- le JSON suit EXACTEMENT le schema canonique (source de verite unique) :
  c'est l'etiquette parfaite et gratuite dont parle le CDC.

Deux modes :
- factures COHERENTES : tous les montants tombent juste. Le generateur
  s'auto-controle : chaque facture produite passe valider() sans erreur.
- factures FAUTIVES (section 8.3) : une incoherence deliberee est
  injectee (total faux, ligne qui ne somme pas, ICE a 14 chiffres, taux
  hors bareme, net a payer incoherent). Elles doivent TOUTES etre
  attrapees par le filet de validation — c'est ce que testent les tests.

Reproductibilite (ENF-04) : tout l'aleatoire passe par une graine fixee.
"""

import json
import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from regles.commun import arrondi
from regles.validation import a_des_erreurs, valider
from schema.modeles import (
    BandeTVA,
    Champ,
    Facture,
    Fournisseur,
    LigneFacture,
    TypeDocument,
)

# ---------------------------------------------------------------------------
# Donnees de base
# ---------------------------------------------------------------------------

FOURNISSEURS = [
    ("ATLAS FOURNITURES SARL", "12 rue des Orangers", "Casablanca"),
    ("MAROC NEGOCE SA", "45 avenue Hassan II", "Rabat"),
    ("STE IMPRIMERIE DU SUD", "8 bd Mohammed V", "Marrakech"),
    ("TECHNO DISTRIB SARL AU", "Zone industrielle Gzenaya", "Tanger"),
    ("COMPTOIR DE L'EMBALLAGE", "3 rue Oued Souss", "Sale"),
]

CLIENTS = ["SOCIETE DEMO SARL", "ETABLISSEMENTS KARAM", "OFFICE MODERNE SA"]

# (designation, unite, prix mini, prix maxi)
ARTICLES = [
    ("Papier A4 80g (ramette)", "u", 35, 60),
    ("Cartouche d'encre noire", "u", 180, 420),
    ("Classeur a levier dos 75mm", "u", 12, 30),
    ("Prestation de maintenance", "h", 150, 400),
    ("Toner laser compatible", "u", 500, 900),
    ("Stylos bille (boite de 50)", "bte", 60, 120),
    ("Enveloppes C5 (boite de 500)", "bte", 25, 55),
    ("Transport et manutention", "u", 40, 150),
]

TAUX_COURANTS = [Decimal("20")] * 5 + [Decimal("10"), Decimal("14"), Decimal("7")]

GABARITS = ("detaillee", "remise", "ttc_seule")

FAUTES = (
    "total_ttc_faux",
    "ligne_ne_somme_pas",
    "ice_14_chiffres",
    "taux_hors_bareme",
    "net_a_payer_faux",
)


def _montant_fr(d: Decimal) -> str:
    """1234.56 -> '1 234,56' : le format qui sera imprime sur le PDF.

    On le stocke aussi dans valeur_brute : c'est exactement la chaine que
    l'extraction devra normaliser en semaine 3 (EF-18).
    """
    return f"{d:,.2f}".replace(",", "\u00a0").replace(".", ",")


def _lu(valeur, brute: Optional[str] = None) -> Champ:
    return Champ.lu(valeur, brute=brute)


def _ice(rng: random.Random) -> str:
    return "".join(rng.choices("0123456789", k=15))


# ---------------------------------------------------------------------------
# Construction d'une facture coherente
# ---------------------------------------------------------------------------


def _lignes_aleatoires(rng: random.Random, taux_choisis: list[Decimal],
                       avec_taux_ligne: bool) -> list[LigneFacture]:
    lignes = []
    for i in range(rng.randint(2, 6)):
        designation, unite, pmin, pmax = rng.choice(ARTICLES)
        qte = Decimal(rng.randint(1, 20))
        pu = Decimal(rng.randrange(pmin * 4, pmax * 4)) / 4  # pas de 0,25
        montant = arrondi(qte * pu)
        taux = rng.choice(taux_choisis)
        lignes.append(
            LigneFacture(
                numero_ligne=i + 1,
                designation=_lu(designation),
                unite=_lu(unite),
                quantite=_lu(qte, brute=str(qte)),
                prix_unitaire_ht=_lu(pu, brute=_montant_fr(pu)),
                montant_ht=_lu(montant, brute=_montant_fr(montant)),
                taux_tva=_lu(taux, brute=f"{taux}%") if avec_taux_ligne else None,
            )
        )
    return lignes


def facture_coherente(rng: random.Random, numero: int) -> tuple[Facture, str]:
    """Construit une facture arithmetiquement parfaite. Retourne (facture, gabarit)."""
    gabarit = rng.choice(GABARITS)
    est_avoir = gabarit == "detaillee" and rng.random() < 0.12

    nom, adresse, ville = rng.choice(FOURNISSEURS)
    emission = date(2026, rng.randint(1, 8), rng.randint(1, 28))
    prefixe = "AV" if est_avoir else "F"

    f = Facture(
        type_document=_lu(TypeDocument.AVOIR if est_avoir else TypeDocument.FACTURE),
        numero_facture=_lu(f"{prefixe}-2026-{numero:04d}"),
        date_emission=_lu(emission),
        date_echeance=_lu(emission + timedelta(days=rng.choice([30, 45, 60]))),
        devise=_lu("MAD"),
        fournisseur=Fournisseur(
            nom=_lu(nom),
            adresse=_lu(adresse),
            ville=_lu(ville),
            ice=_lu(_ice(rng)),
            if_=_lu(str(rng.randint(10_000_000, 99_999_999))),
        ),
    )
    if rng.random() < 0.7:
        f.client = None  # certains gabarits n'affichent pas le client
    else:
        from schema.modeles import Client

        f.client = Client(nom=_lu(rng.choice(CLIENTS)))

    if gabarit == "ttc_seule":
        # Cas 4.1 du CDC : la facture n'affiche qu'un TTC + le taux applique.
        taux = rng.choice(TAUX_COURANTS)
        ttc = arrondi(Decimal(rng.randrange(200, 20_000)) / 2)
        f.total_ttc = _lu(ttc, brute=_montant_fr(ttc))
        f.bandes_tva = [BandeTVA(taux=_lu(taux, brute=f"{taux}%"))]
        return f, gabarit

    if gabarit == "remise":
        # Mono-taux, remise globale en pied (cas 4.1). La remise s'impute
        # sur le HT (convention RV-02) ; la TVA est calculee sur le net.
        taux = rng.choice(TAUX_COURANTS)
        f.lignes = _lignes_aleatoires(rng, [taux], avec_taux_ligne=False)
        brut = sum((l.montant_ht.valeur for l in f.lignes), start=Decimal("0"))
        remise = arrondi(brut * Decimal(rng.randint(3, 10)) / 100)
        ht = arrondi(brut - remise)
        tva = arrondi(ht * taux / 100)
        ttc = arrondi(ht + tva)
        f.total_remise = _lu(remise, brute=_montant_fr(remise))
        f.total_ht = _lu(ht, brute=_montant_fr(ht))
        f.total_tva = _lu(tva, brute=_montant_fr(tva))
        f.total_ttc = _lu(ttc, brute=_montant_fr(ttc))
        f.extra["taux_affiche"] = str(taux)
        return f, gabarit

    # gabarit "detaillee" : lignes + bandes + totaux (+ options)
    multi = rng.random() < 0.4
    taux_choisis = rng.sample(TAUX_COURANTS, 2) if multi else [rng.choice(TAUX_COURANTS)]
    taux_choisis = list(dict.fromkeys(taux_choisis)) or [Decimal("20")]
    f.lignes = _lignes_aleatoires(rng, taux_choisis, avec_taux_ligne=True)

    bases: dict[Decimal, Decimal] = {}
    for l in f.lignes:
        bases[l.taux_tva.valeur] = bases.get(l.taux_tva.valeur, Decimal("0")) + l.montant_ht.valeur
    f.bandes_tva = [
        BandeTVA(
            taux=_lu(taux, brute=f"{taux}%"),
            base_ht=_lu(arrondi(base), brute=_montant_fr(arrondi(base))),
            montant_tva=_lu(arrondi(base * taux / 100), brute=_montant_fr(arrondi(base * taux / 100))),
        )
        for taux, base in sorted(bases.items())
    ]
    ht = arrondi(sum(bases.values(), start=Decimal("0")))
    tva = arrondi(sum((b.montant_tva.valeur for b in f.bandes_tva), start=Decimal("0")))
    ttc = ht + tva

    if rng.random() < 0.15:  # timbre fiscal (paiement especes)
        timbre = arrondi(ttc * Decimal("0.0025"))
        f.timbre_fiscal = _lu(timbre, brute=_montant_fr(timbre))
        f.mode_paiement = _lu("Especes")
        ttc = arrondi(ttc + timbre)

    f.total_ht = _lu(ht, brute=_montant_fr(ht))
    f.total_tva = _lu(tva, brute=_montant_fr(tva))
    f.total_ttc = _lu(ttc, brute=_montant_fr(ttc))

    if not est_avoir and rng.random() < 0.3:  # acompte deja verse (cas 4.1)
        acompte = arrondi(ttc * Decimal(rng.randint(20, 50)) / 100)
        net = arrondi(ttc - acompte)
        f.acompte = _lu(acompte, brute=_montant_fr(acompte))
        f.net_a_payer = _lu(net, brute=_montant_fr(net))

    return f, gabarit


# ---------------------------------------------------------------------------
# Injection de fautes (section 8.3)
# ---------------------------------------------------------------------------


def injecter_faute(f: Facture, rng: random.Random, faute: Optional[str] = None) -> str:
    """Rend la facture deliberement incoherente. Retourne le nom de la faute."""
    possibles = list(FAUTES)
    if not f.lignes:
        possibles.remove("ligne_ne_somme_pas")
    if f.total_ttc is None:
        possibles.remove("total_ttc_faux")
    if f.net_a_payer is None:
        possibles.remove("net_a_payer_faux")
    if not f.bandes_tva and not f.lignes:
        possibles.remove("taux_hors_bareme")
    choix = faute if faute in possibles else rng.choice(possibles)

    decalage = Decimal(rng.randint(2, 9))  # > tolerance, bien visible
    if choix == "total_ttc_faux":
        f.total_ttc = _lu(arrondi(f.total_ttc.valeur + decalage))
    elif choix == "ligne_ne_somme_pas":
        l = rng.choice([l for l in f.lignes if l.montant_ht is not None])
        l.montant_ht = _lu(arrondi(l.montant_ht.valeur + decalage))
    elif choix == "ice_14_chiffres":
        assert f.fournisseur is not None and f.fournisseur.ice is not None
        f.fournisseur.ice = _lu(f.fournisseur.ice.valeur[:14])
    elif choix == "taux_hors_bareme":
        cible_bande = f.bandes_tva[0] if f.bandes_tva else None
        if cible_bande is not None:
            cible_bande.taux = _lu(Decimal("19"))
        else:
            f.lignes[0].taux_tva = _lu(Decimal("19"))
    elif choix == "net_a_payer_faux":
        f.net_a_payer = _lu(arrondi(f.net_a_payer.valeur + decalage))
    return choix


# ---------------------------------------------------------------------------
# Rendu PDF (ReportLab)
# ---------------------------------------------------------------------------

PALETTES = {
    "detaillee": (colors.HexColor("#1a3d5c"), colors.HexColor("#eef3f7")),
    "remise": (colors.HexColor("#5c1a1a"), colors.HexColor("#f7efee")),
    "ttc_seule": (colors.HexColor("#1a5c33"), colors.HexColor("#eef7f1")),
}


def _p(texte: str, taille: int = 9, gras: bool = False, couleur=colors.black) -> Paragraph:
    style = ParagraphStyle(
        "s", fontSize=taille, leading=taille + 3,
        fontName="Helvetica-Bold" if gras else "Helvetica", textColor=couleur,
    )
    return Paragraph(texte, style)


def rendre_pdf(f: Facture, gabarit: str, chemin: Path) -> None:
    fonce, clair = PALETTES[gabarit]
    doc = SimpleDocTemplate(
        str(chemin), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
    )
    story = []

    titre = "AVOIR" if (
        f.type_document is not None and f.type_document.valeur is TypeDocument.AVOIR
    ) else "FACTURE"
    story.append(_p(f"{titre}&nbsp;&nbsp;{f.numero_facture.valeur}", 16, True, fonce))
    story.append(Spacer(1, 4 * mm))

    fo = f.fournisseur
    bloc_fournisseur = (
        f"<b>{fo.nom.valeur}</b><br/>{fo.adresse.valeur} — {fo.ville.valeur}<br/>"
        f"ICE : {fo.ice.valeur} &nbsp;&nbsp; IF : {fo.if_.valeur}"
    )
    bloc_meta = (
        f"Date d'emission : {f.date_emission.valeur.strftime('%d/%m/%Y')}<br/>"
        f"Echeance : {f.date_echeance.valeur.strftime('%d/%m/%Y')}<br/>"
        f"Devise : {f.devise.valeur}"
    )
    if f.client is not None and f.client.nom is not None:
        bloc_meta += f"<br/>Client : {f.client.nom.valeur}"
    entete = Table(
        [[_p(bloc_fournisseur), _p(bloc_meta)]],
        colWidths=[95 * mm, 79 * mm],
    )
    entete.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), clair),
        ("BOX", (0, 0), (-1, -1), 0.5, fonce),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(entete)
    story.append(Spacer(1, 6 * mm))

    if f.lignes:
        avec_taux = any(l.taux_tva is not None for l in f.lignes)
        tete = ["Designation", "Qte", "PU HT", "Montant HT"] + (["TVA"] if avec_taux else [])
        donnees = [tete]
        for l in f.lignes:
            rang = [
                l.designation.valeur,
                f"{l.quantite.valeur} {l.unite.valeur}",
                _montant_fr(l.prix_unitaire_ht.valeur),
                _montant_fr(l.montant_ht.valeur),
            ]
            if avec_taux:
                rang.append(f"{l.taux_tva.valeur}%" if l.taux_tva is not None else "")
            donnees.append(rang)
        largeur = [72, 22, 28, 32] + ([20] if avec_taux else [])
        t = Table(donnees, colWidths=[w * mm for w in largeur])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), fonce),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, clair]),
        ]))
        story.append(t)
        story.append(Spacer(1, 5 * mm))

    if f.bandes_tva and gabarit == "detaillee":
        donnees = [["Taux", "Base HT", "Montant TVA"]]
        for b in f.bandes_tva:
            donnees.append([
                f"{b.taux.valeur}%",
                _montant_fr(b.base_ht.valeur) if b.base_ht is not None else "",
                _montant_fr(b.montant_tva.valeur) if b.montant_tva is not None else "",
            ])
        t = Table(donnees, colWidths=[20 * mm, 35 * mm, 35 * mm], hAlign="LEFT")
        t.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ]))
        story.append(t)
        story.append(Spacer(1, 5 * mm))

    totaux: list[tuple[str, Decimal]] = []
    if f.total_ht is not None:
        totaux.append(("Total HT", f.total_ht.valeur))
    if f.total_remise is not None:
        totaux.append(("Remise", f.total_remise.valeur))
        if "taux_affiche" in f.extra:
            totaux.append((f"Total TVA ({f.extra['taux_affiche']}%)", f.total_tva.valeur))
    elif f.total_tva is not None:
        totaux.append(("Total TVA", f.total_tva.valeur))
    if f.timbre_fiscal is not None:
        totaux.append(("Timbre fiscal", f.timbre_fiscal.valeur))
    if f.total_ttc is not None:
        totaux.append(("TOTAL TTC", f.total_ttc.valeur))
    if f.acompte is not None:
        totaux.append(("Acompte verse", f.acompte.valeur))
    if f.net_a_payer is not None:
        totaux.append(("NET A PAYER", f.net_a_payer.valeur))

    if gabarit == "ttc_seule":
        taux = f.bandes_tva[0].taux.valeur if f.bandes_tva else Decimal("20")
        story.append(_p(f"Montant TTC : <b>{_montant_fr(f.total_ttc.valeur)} MAD</b>", 13, False, fonce))
        story.append(Spacer(1, 2 * mm))
        story.append(_p(f"TVA {taux}% incluse", 9))
    else:
        donnees = [[lib, _montant_fr(m)] for lib, m in totaux]
        t = Table(donnees, colWidths=[45 * mm, 35 * mm], hAlign="RIGHT")
        t.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("LINEABOVE", (0, -1), (-1, -1), 0.8, fonce),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ]))
        story.append(t)

    story.append(Spacer(1, 8 * mm))
    if f.mode_paiement is not None:
        story.append(_p(f"Mode de paiement : {f.mode_paiement.valeur}", 8, couleur=colors.grey))
    story.append(_p("Merci de votre confiance.", 8, couleur=colors.grey))
    doc.build(story)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def generer_corpus(
    dossier: Path,
    nb_coherentes: int = 500,
    nb_fautives: int = 50,
    graine: int = 42,
) -> dict[str, int]:
    """Genere le corpus complet. Retourne un petit bilan chiffre."""
    rng = random.Random(graine)
    d_ok = dossier / "coherentes"
    d_ko = dossier / "fautes"
    d_ok.mkdir(parents=True, exist_ok=True)
    d_ko.mkdir(parents=True, exist_ok=True)

    for i in range(1, nb_coherentes + 1):
        f, gabarit = facture_coherente(rng, i)
        anomalies = valider(f)
        if a_des_erreurs(anomalies):  # auto-controle du generateur
            raise RuntimeError(f"Facture generee incoherente ({i}) : {anomalies}")
        rendre_pdf(f, gabarit, d_ok / f"{f.numero_facture.valeur}.pdf")
        etiquette = {"faute": None, "gabarit": gabarit,
                     "facture": f.model_dump(mode="json", by_alias=True, exclude_none=True)}
        (d_ok / f"{f.numero_facture.valeur}.json").write_text(
            json.dumps(etiquette, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    for i in range(1, nb_fautives + 1):
        f, gabarit = facture_coherente(rng, 9000 + i)
        faute = injecter_faute(f, rng)
        anomalies = valider(f)
        if not a_des_erreurs(anomalies):  # le filet DOIT attraper (CDC 8.3)
            raise RuntimeError(f"Faute {faute} non detectee : defaut bloquant")
        rendre_pdf(f, gabarit, d_ko / f"{f.numero_facture.valeur}.pdf")
        etiquette = {"faute": faute, "gabarit": gabarit,
                     "facture": f.model_dump(mode="json", by_alias=True, exclude_none=True)}
        (d_ko / f"{f.numero_facture.valeur}.json").write_text(
            json.dumps(etiquette, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return {"coherentes": nb_coherentes, "fautives": nb_fautives}
