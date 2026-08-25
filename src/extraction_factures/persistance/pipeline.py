"""Pipeline de bout en bout (CDC 5.1, 5.8) :

    dossier d'entree -> extraction -> regles -> decision -> base -> exports

Garanties portees par ce module :
- EF-02/EF-03 : chaque fichier est identifie par son empreinte SHA-256 ;
  un fichier deja traite est signale comme doublon, jamais retraite.
- EF-04 : l'echec d'un document n'interrompt pas le lot.
- EF-05 : statuts recu / en_cours / auto_accepte / a_relire / valide / echec.
- EF-07 : routage — couche de texte fiable -> chaine native ; sinon le
  document part en relecture avec un drapeau explicite (la chaine
  visuelle est hors perimetre reduit, decision documentee).
- EF-28 : idempotence — rejouer un lot ne cree aucun doublon.
- EF-29 : exports CSV (UTF-8 BOM, point-virgule) et Excel, un volet
  en-tetes + un volet lignes relies par l'identifiant de facture.
- ENF-02 : aucun montant ni identifiant en clair dans les journaux.
"""

import csv
import hashlib
import json
from pathlib import Path
from typing import Optional

from openpyxl import Workbook
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from extraction.lecteur_natif import detecter_couche_texte, extraire_facture_native
from persistance.base import (
    BandeTvaDB,
    Base,
    DocumentDB,
    DrapeauRelectureDB,
    FactureDB,
    FournisseurDB,
    JournalAuditDB,
    LigneFactureDB,
)
from regles.derivation import appliquer_derivations
from regles.validation import a_des_erreurs, valider
from schema.modeles import Champ, Facture

EXTENSIONS = {".pdf"}  # JPEG/PNG/TIFF/HEIC arriveront avec la chaine visuelle


def _sha256(chemin: Path) -> str:
    return hashlib.sha256(chemin.read_bytes()).hexdigest()


def _texte(champ: Optional[Champ]) -> Optional[str]:
    if champ is None or champ.valeur is None:
        return None
    return str(champ.valeur)


def _journal(session: Session, evenement: str, sha: Optional[str], detail: str = "") -> None:
    # ENF-02 : le detail ne contient jamais de montant ni d'identifiant fiscal.
    session.add(JournalAuditDB(evenement=evenement, document_sha256=sha, detail=detail))


def _fournisseur(session: Session, f: Facture) -> Optional[FournisseurDB]:
    if f.fournisseur is None:
        return None
    ice = _texte(f.fournisseur.ice)
    nom = _texte(f.fournisseur.nom)
    if ice:
        existant = session.scalar(select(FournisseurDB).where(FournisseurDB.ice == ice))
        if existant:
            return existant
    elif nom:
        existant = session.scalar(select(FournisseurDB).where(FournisseurDB.nom == nom))
        if existant:
            return existant
    nouveau = FournisseurDB(
        ice=ice, nom=nom, if_=_texte(f.fournisseur.if_),
        adresse=_texte(f.fournisseur.adresse), ville=_texte(f.fournisseur.ville),
    )
    session.add(nouveau)
    session.flush()
    return nouveau


def traiter_document(session: Session, chemin: Path) -> str:
    """Traite un fichier et retourne le statut final (EF-05)."""
    sha = _sha256(chemin)

    deja = session.scalar(select(DocumentDB).where(DocumentDB.sha256 == sha))
    if deja is not None:  # EF-03 : doublon, on ne retraite pas
        _journal(session, "doublon", sha, chemin.name)
        return "doublon"

    doc = DocumentDB(sha256=sha, chemin_source=str(chemin), statut="en_cours")
    session.add(doc)
    session.flush()
    _journal(session, "recu", sha, chemin.name)

    try:
        if not detecter_couche_texte(chemin):
            # EF-07 : voie visuelle — hors perimetre reduit, donc relecture.
            doc.voie_traitement = "visuel"
            doc.statut = "a_relire"
            facture_db = FactureDB(document_id=doc.id)
            session.add(facture_db)
            session.flush()
            session.add(DrapeauRelectureDB(
                facture_id=facture_db.id, regle="EF-07", severite="erreur",
                message="Pas de couche de texte exploitable : chaine visuelle "
                        "requise (hors perimetre reduit).",
            ))
            _journal(session, "route_visuel", sha)
            return doc.statut

        doc.voie_traitement = "texte_natif"
        facture = extraire_facture_native(chemin)
        doc.extraction_brute = facture.model_dump_json(by_alias=True, exclude_none=True)

        appliquer_derivations(facture)
        anomalies = valider(facture)
        doc.statut = "a_relire" if a_des_erreurs(anomalies) else "auto_accepte"

        fournisseur_db = _fournisseur(session, facture)
        facture_db = FactureDB(
            document_id=doc.id,
            fournisseur_id=fournisseur_db.id if fournisseur_db else None,
            ice_fournisseur=fournisseur_db.ice if fournisseur_db else None,
            numero_facture=_texte(facture.numero_facture),
            type_document=_texte(facture.type_document),
            date_emission=_texte(facture.date_emission),
            date_echeance=_texte(facture.date_echeance),
            devise=_texte(facture.devise),
            total_ht=_texte(facture.total_ht),
            total_remise=_texte(facture.total_remise),
            total_tva=_texte(facture.total_tva),
            total_ttc=_texte(facture.total_ttc),
            timbre_fiscal=_texte(facture.timbre_fiscal),
            acompte=_texte(facture.acompte),
            net_a_payer=_texte(facture.net_a_payer),
        )
        session.add(facture_db)
        session.flush()

        for l in facture.lignes:
            session.add(LigneFactureDB(
                facture_id=facture_db.id, numero_ligne=l.numero_ligne,
                designation=_texte(l.designation), quantite=_texte(l.quantite),
                unite=_texte(l.unite), prix_unitaire_ht=_texte(l.prix_unitaire_ht),
                montant_ht=_texte(l.montant_ht), taux_tva=_texte(l.taux_tva),
            ))
        for b in facture.bandes_tva:
            session.add(BandeTvaDB(
                facture_id=facture_db.id, taux=_texte(b.taux),
                base_ht=_texte(b.base_ht), montant_tva=_texte(b.montant_tva),
            ))
        for a in anomalies:
            session.add(DrapeauRelectureDB(
                facture_id=facture_db.id, regle=a.regle,
                severite=a.severite.value, message=a.message,
                champs=json.dumps(a.champs, ensure_ascii=False),
            ))
        _journal(session, doc.statut, sha)
        return doc.statut

    except Exception as erreur:  # EF-04 : on marque, on continue
        doc.statut = "echec"
        doc.message_echec = f"{type(erreur).__name__}: {erreur}"
        _journal(session, "echec", sha, type(erreur).__name__)
        return doc.statut


def traiter_dossier(dossier: Path, url_base: str = "sqlite:///factures.db") -> dict:
    """Traite tous les fichiers d'un dossier (recursif). Retourne le bilan."""
    engine = create_engine(url_base)
    Base.metadata.create_all(engine)

    bilan = {"auto_accepte": 0, "a_relire": 0, "echec": 0, "doublon": 0}
    with Session(engine) as session:
        for chemin in sorted(dossier.rglob("*")):
            if chemin.suffix.lower() not in EXTENSIONS:
                continue
            statut = traiter_document(session, chemin)
            bilan[statut] = bilan.get(statut, 0) + 1
            session.commit()  # un commit par document : un echec n'annule pas le lot
    return bilan


# ---------------------------------------------------------------------------
# Exports (EF-29)
# ---------------------------------------------------------------------------

ENTETES_COLONNES = [
    "facture_id", "statut", "numero_facture", "type_document", "date_emission",
    "date_echeance", "devise", "fournisseur_nom", "fournisseur_ice",
    "total_ht", "total_remise", "total_tva", "total_ttc", "timbre_fiscal",
    "acompte", "net_a_payer",
]
LIGNES_COLONNES = [
    "facture_id", "numero_ligne", "designation", "quantite", "unite",
    "prix_unitaire_ht", "montant_ht", "taux_tva",
]


def _rangees(url_base: str) -> tuple[list[list], list[list]]:
    engine = create_engine(url_base)
    entetes, lignes = [], []
    with Session(engine) as session:
        for facture in session.scalars(select(FactureDB).order_by(FactureDB.id)):
            entetes.append([
                facture.id, facture.document.statut, facture.numero_facture,
                facture.type_document, facture.date_emission, facture.date_echeance,
                facture.devise,
                facture.fournisseur.nom if facture.fournisseur else None,
                facture.ice_fournisseur, facture.total_ht, facture.total_remise,
                facture.total_tva, facture.total_ttc, facture.timbre_fiscal,
                facture.acompte, facture.net_a_payer,
            ])
            for l in facture.lignes:
                lignes.append([
                    facture.id, l.numero_ligne, l.designation, l.quantite,
                    l.unite, l.prix_unitaire_ht, l.montant_ht, l.taux_tva,
                ])
    return entetes, lignes


def exporter_csv(url_base: str, dossier_sortie: Path) -> tuple[Path, Path]:
    """Deux CSV relies par facture_id — UTF-8 avec BOM, point-virgule,
    pour un Excel francophone (EF-29)."""
    dossier_sortie.mkdir(parents=True, exist_ok=True)
    entetes, lignes = _rangees(url_base)
    chemin_entetes = dossier_sortie / "factures_entetes.csv"
    chemin_lignes = dossier_sortie / "factures_lignes.csv"
    for chemin, colonnes, rangees in (
        (chemin_entetes, ENTETES_COLONNES, entetes),
        (chemin_lignes, LIGNES_COLONNES, lignes),
    ):
        with open(chemin, "w", newline="", encoding="utf-8-sig") as fichier:
            plume = csv.writer(fichier, delimiter=";")
            plume.writerow(colonnes)
            plume.writerows(rangees)
    return chemin_entetes, chemin_lignes


def exporter_excel(url_base: str, chemin: Path) -> Path:
    """Un classeur Excel : feuille en-tetes + feuille lignes (EF-29)."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    entetes, lignes = _rangees(url_base)
    classeur = Workbook()
    feuille1 = classeur.active
    feuille1.title = "entetes"
    feuille1.append(ENTETES_COLONNES)
    for r in entetes:
        feuille1.append(r)
    feuille2 = classeur.create_sheet("lignes")
    feuille2.append(LIGNES_COLONNES)
    for r in lignes:
        feuille2.append(r)
    classeur.save(chemin)
    return chemin
