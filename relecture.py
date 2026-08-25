"""Interface de relecture (CDC 5.9 — livrable n°6) :

    uv run streamlit run relecture.py

Ecran cote a cote (EF-31) : la facture a gauche, les champs a droite.
Les alertes bloquantes sont separees des simples signalements (EF-24),
les champs sont editables, et « Valider » enregistre les corrections
journalisees puis passe le document a l'etat valide (EF-25 / EF-33).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src" / "extraction_factures"))

import pymupdf
import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from persistance.base import Base
from persistance.logique_relecture import (
    CHAMPS_EDITABLES,
    appliquer_corrections,
    compteurs_statuts,
    documents_a_relire,
)

st.set_page_config(page_title="Relecture des factures", layout="wide")

URL_BASE = "sqlite:///factures.db"
engine = create_engine(URL_BASE)
Base.metadata.create_all(engine)


def image_page(chemin: str, num_page: int = 0) -> bytes | None:
    try:
        with pymupdf.open(chemin) as doc:
            page = doc[min(num_page, doc.page_count - 1)]
            return page.get_pixmap(dpi=110).tobytes("png")
    except Exception:
        return None


with Session(engine) as session:
    st.title("File de relecture")
    if "message" in st.session_state:
        st.success(st.session_state.pop("message"))

    compte = compteurs_statuts(session)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Auto-acceptes", compte.get("auto_accepte", 0))
    c2.metric("A relire", compte.get("a_relire", 0))
    c3.metric("Valides", compte.get("valide", 0))
    c4.metric("Echecs", compte.get("echec", 0))

    en_attente = documents_a_relire(session)
    if not en_attente:
        st.success("Aucun document en attente : la file de relecture est vide.")
        st.stop()

    auteur = st.sidebar.text_input("Votre nom (journal d'audit)", value="relecteur")
    libelles = {
        d.id: f"{(d.facture.numero_facture if d.facture else None) or Path(d.chemin_source).name}"
        for d in en_attente
    }
    choix = st.sidebar.selectbox(
        f"Document a verifier ({len(en_attente)} en attente)",
        options=list(libelles), format_func=libelles.get,
    )
    doc = next(d for d in en_attente if d.id == choix)
    facture = doc.facture

    gauche, droite = st.columns([1.15, 1])

    with gauche:
        st.subheader("Document")
        png = image_page(doc.chemin_source)
        if png:
            st.image(png, use_container_width=True)
        else:
            st.warning(f"Fichier introuvable ou illisible : {doc.chemin_source}")

    with droite:
        st.subheader("Verification")

        erreurs = [f for f in facture.drapeaux if f.severite == "erreur"]
        avertissements = [f for f in facture.drapeaux if f.severite == "avertissement"]
        for drapeau in erreurs:
            st.error(f"{drapeau.regle} — {drapeau.message}")
        for drapeau in avertissements:
            st.warning(f"{drapeau.regle} — {drapeau.message}")
        if not facture.drapeaux:
            st.info("Aucune regle en echec : verification visuelle simple.")

        champs_en_cause = set()
        for drapeau in erreurs:
            if drapeau.champs:
                import json as _json
                champs_en_cause.update(_json.loads(drapeau.champs))

        with st.form("correction"):
            saisies = {}
            for champ in CHAMPS_EDITABLES:
                marque = " ⚠" if champ in champs_en_cause else ""
                saisies[champ] = st.text_input(
                    champ + marque, value=getattr(facture, champ) or "",
                )
            envoye = st.form_submit_button("✅ Valider ce document", type="primary")

        if facture.lignes:
            st.caption("Lignes extraites (lecture seule)")
            st.dataframe(
                [
                    {
                        "n°": l.numero_ligne, "designation": l.designation,
                        "qte": l.quantite, "PU HT": l.prix_unitaire_ht,
                        "montant HT": l.montant_ht, "TVA": l.taux_tva,
                    }
                    for l in facture.lignes
                ],
                use_container_width=True, hide_index=True,
            )

    if envoye:
        corriges = appliquer_corrections(session, facture.id, saisies, auteur)
        message = (
            f"Document valide — {len(corriges)} champ(s) corrige(s) et journalises."
            if corriges else "Document valide sans correction."
        )
        st.session_state["message"] = message
        st.rerun()
