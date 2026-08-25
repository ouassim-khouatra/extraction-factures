"""Lecture des PDF natifs (CDC EF-06 / EF-07 — la voie la plus rentable).

Un PDF natif contient deja son texte, exact et positionne : le lire
directement est plus rapide, plus fiable et plus economique que n'importe
quel modele de vision. Ce module :

1. detecte si un PDF possede une couche de texte exploitable (EF-06) ;
2. en extrait une Facture au schema canonique, chaque champ portant sa
   provenance (valeur brute lue + page).

C'est un extracteur DETERMINISTE, calibre sur des factures regulieres
(dont le corpus synthetique). Il constitue la reference de base ; la
structuration par modele de langage viendra s'y comparer (etude
comparative du CDC). Toute valeur introuvable reste simplement absente :
l'absence n'est jamais une erreur.
"""

import re
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pymupdf

from extraction.normalisation import (
    date_depuis_texte,
    montant_depuis_texte,
    taux_depuis_texte,
)
from schema.modeles import (
    BandeTVA,
    Champ,
    Facture,
    Fournisseur,
    LigneFacture,
    TypeDocument,
)

SEUIL_CARACTERES_PAR_PAGE = 50  # en dessous : couche de texte residuelle

# Libelle imprime -> nom du champ du schema (totaux en pied de facture)
LIBELLES_TOTAUX = {
    "Total HT": "total_ht",
    "Remise": "total_remise",
    "Total TVA": "total_tva",
    "TOTAL TTC": "total_ttc",
    "Timbre fiscal": "timbre_fiscal",
    "Acompte verse": "acompte",
    "NET A PAYER": "net_a_payer",
}


def detecter_couche_texte(chemin: Path) -> bool:
    """EF-06 : vrai si le PDF porte une couche de texte exploitable."""
    with pymupdf.open(chemin) as doc:
        if doc.page_count == 0:
            return False
        total = sum(len(page.get_text()) for page in doc)
        return total >= SEUIL_CARACTERES_PAR_PAGE * doc.page_count


def _lu(valeur, brute: Optional[str], page: int) -> Champ:
    return Champ.lu(valeur, brute=brute, page=page)


def _extraire_lignes(donnees: list[list], page: int) -> list[LigneFacture]:
    entete = [c.strip() if c else "" for c in donnees[0]]
    avec_taux = "TVA" in entete
    lignes = []
    for rang, cellules in enumerate(donnees[1:], start=1):
        cellules = [(c or "").strip() for c in cellules]
        designation, qte_unite, pu, montant = cellules[0], cellules[1], cellules[2], cellules[3]
        morceaux = qte_unite.split()
        quantite = montant_depuis_texte(morceaux[0]) if morceaux else None
        unite = morceaux[1] if len(morceaux) > 1 else None
        ligne = LigneFacture(
            numero_ligne=rang,
            designation=_lu(designation, designation, page) if designation else None,
            quantite=_lu(quantite, qte_unite, page) if quantite is not None else None,
            unite=_lu(unite, unite, page) if unite else None,
            prix_unitaire_ht=_lu(montant_depuis_texte(pu), pu, page)
            if montant_depuis_texte(pu) is not None else None,
            montant_ht=_lu(montant_depuis_texte(montant), montant, page)
            if montant_depuis_texte(montant) is not None else None,
        )
        if avec_taux and len(cellules) > 4 and taux_depuis_texte(cellules[4]) is not None:
            ligne.taux_tva = _lu(taux_depuis_texte(cellules[4]), cellules[4], page)
        lignes.append(ligne)
    return lignes


def _extraire_bandes(donnees: list[list], page: int) -> list[BandeTVA]:
    bandes = []
    for cellules in donnees[1:]:
        cellules = [(c or "").strip() for c in cellules]
        taux, base, montant = cellules[0], cellules[1], cellules[2]
        bandes.append(BandeTVA(
            taux=_lu(taux_depuis_texte(taux), taux, page)
            if taux_depuis_texte(taux) is not None else None,
            base_ht=_lu(montant_depuis_texte(base), base, page)
            if montant_depuis_texte(base) is not None else None,
            montant_tva=_lu(montant_depuis_texte(montant), montant, page)
            if montant_depuis_texte(montant) is not None else None,
        ))
    return bandes


def extraire_facture_native(chemin: Path) -> Facture:
    """Extrait une Facture d'un PDF natif. Champs introuvables : absents."""
    f = Facture()
    fournisseur = Fournisseur()

    with pymupdf.open(chemin) as doc:
        for num_page, page in enumerate(doc, start=1):
            lignes_texte = [l.strip() for l in page.get_text().splitlines() if l.strip()]

            # --- Tables (lignes d'articles, bandes de TVA) ---
            cellules_deja_vues: set[str] = set()
            for table in page.find_tables().tables:
                donnees = table.extract()
                if not donnees or not donnees[0]:
                    continue
                entete0 = (donnees[0][0] or "").strip()
                for rangee in donnees:
                    for c in rangee:
                        if c:
                            cellules_deja_vues.update(x.strip() for x in str(c).splitlines())
                if entete0 == "Designation":
                    f.lignes = _extraire_lignes(donnees, num_page)
                elif entete0 == "Taux":
                    f.bandes_tva = _extraire_bandes(donnees, num_page)

            # --- Lignes libellees, hors tables ---
            i = 0
            while i < len(lignes_texte):
                texte = lignes_texte[i]

                # Titre : "FACTURE  F-2026-0001" / "AVOIR AV-2026-0056"
                m = re.match(r"^(FACTURE|AVOIR)\s+(\S+)$", texte)
                if m and f.numero_facture is None:
                    type_doc = TypeDocument.AVOIR if m.group(1) == "AVOIR" else TypeDocument.FACTURE
                    f.type_document = _lu(type_doc, m.group(1), num_page)
                    f.numero_facture = _lu(m.group(2), m.group(2), num_page)
                    # La ligne suivante est le nom du fournisseur,
                    # celle d'apres son adresse ("rue — ville").
                    if i + 1 < len(lignes_texte):
                        nom = lignes_texte[i + 1]
                        fournisseur.nom = _lu(nom, nom, num_page)
                    if i + 2 < len(lignes_texte) and "—" in lignes_texte[i + 2]:
                        adresse, _, ville = lignes_texte[i + 2].partition("—")
                        fournisseur.adresse = _lu(adresse.strip(), lignes_texte[i + 2], num_page)
                        fournisseur.ville = _lu(ville.strip(), ville.strip(), num_page)
                    i += 1
                    continue

                m = re.search(r"ICE\s*:\s*(\d+)", texte)
                if m:
                    fournisseur.ice = _lu(m.group(1), texte, num_page)
                m = re.search(r"\bIF\s*:\s*(\d+)", texte)
                if m:
                    fournisseur.if_ = _lu(m.group(1), texte, num_page)

                m = re.match(r"Date d'emission\s*:\s*(.+)", texte)
                if m and date_depuis_texte(m.group(1)) is not None:
                    f.date_emission = _lu(date_depuis_texte(m.group(1)), m.group(1), num_page)
                m = re.match(r"Echeance\s*:\s*(.+)", texte)
                if m and date_depuis_texte(m.group(1)) is not None:
                    f.date_echeance = _lu(date_depuis_texte(m.group(1)), m.group(1), num_page)
                m = re.match(r"Devise\s*:\s*([A-Z]{3})\b", texte)
                if m:
                    f.devise = _lu(m.group(1), texte, num_page)
                m = re.match(r"Client\s*:\s*(.+)", texte)
                if m:
                    from schema.modeles import Client
                    f.client = Client(nom=_lu(m.group(1).strip(), m.group(1), num_page))
                m = re.match(r"Mode de paiement\s*:\s*(.+)", texte)
                if m:
                    f.mode_paiement = _lu(m.group(1).strip(), m.group(1), num_page)

                # Gabarit "TTC seul" : tout sur une ligne
                m = re.match(r"Montant TTC\s*:\s*(.+)", texte)
                if m and montant_depuis_texte(m.group(1)) is not None:
                    f.total_ttc = _lu(montant_depuis_texte(m.group(1)), m.group(1), num_page)
                m = re.match(r"TVA\s+(\d{1,2})\s*%\s+incluse", texte)
                if m and not f.bandes_tva:
                    f.bandes_tva = [BandeTVA(taux=_lu(Decimal(m.group(1)), texte, num_page))]

                # Totaux en pied : libelle sur une ligne, montant sur la suivante
                # (on ignore les cellules deja consommees par les tables).
                if texte not in cellules_deja_vues:
                    libelle = texte
                    champ_cible = LIBELLES_TOTAUX.get(libelle)
                    if champ_cible is None and libelle.startswith("Total TVA ("):
                        champ_cible = "total_tva"
                        taux_affiche = taux_depuis_texte(libelle)
                        if taux_affiche is not None:
                            f.extra["taux_affiche"] = str(taux_affiche)
                    if champ_cible is not None and i + 1 < len(lignes_texte):
                        montant = montant_depuis_texte(lignes_texte[i + 1])
                        if montant is not None:
                            setattr(f, champ_cible, _lu(montant, lignes_texte[i + 1], num_page))
                            i += 2
                            continue
                i += 1

    if any([fournisseur.nom, fournisseur.ice, fournisseur.if_, fournisseur.adresse]):
        f.fournisseur = fournisseur
    return f
