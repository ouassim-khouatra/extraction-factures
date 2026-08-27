"""Demonstration d'une chaine OCR complete (reunion de suivi).

C'est la "chaine de reference obligatoire" de l'annexe B du CDC :
un moteur d'OCR classique (Tesseract) lit l'IMAGE de la facture, puis
on structure le texte obtenu et on le compare a la verite terrain.

Ce que fait le script, pour chaque facture de demonstration :
1. rend le PDF en image a 300 ppp (exigence EF-08 : 200-300 ppp) ;
2. fabrique une variante DEGRADEE (rotation, flou, bruit, compression
   JPEG) qui simule une photo de telephone (CDC 8.2) ;
3. passe les deux images a l'OCR -> texte brut (sauvegarde en .txt) ;
4. extrait 4 champs du texte OCR (numero, date, ICE, total TTC) avec
   les memes fonctions de normalisation que le pipeline ;
5. compare a la verite terrain et affiche le tableau des resultats.

Lancer :  uv run python demo_ocr.py
Tout est ecrit dans le dossier demo_ocr/ (images, textes OCR, bilan).
"""

import io
import json
import re
import shutil
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src" / "extraction_factures"))

import pymupdf
import pytesseract
from PIL import Image, ImageFilter

from extraction.normalisation import date_depuis_texte, montant_depuis_texte
from generateur.synthetique import generer_corpus
from schema.modeles import Facture

# --- Trouver Tesseract sous Windows meme s'il n'est pas dans le PATH ---
if shutil.which("tesseract") is None:
    candidats = [
        Path(r"C:\Users\perso\AppData\Local\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path.home() / "AppData" / "Local" / "Tesseract-OCR" / "tesseract.exe",
    ]
    trouve = next((c for c in candidats if c.exists()), None)
    if trouve is not None:
        pytesseract.pytesseract.tesseract_cmd = str(trouve)
    else:
        sys.exit(
            "Tesseract introuvable.\n"
            "Installe-le depuis https://github.com/UB-Mannheim/tesseract/wiki\n"
            "(coche « French » dans Additional language data), puis relance."
        )


def pdf_vers_image(chemin_pdf: Path, dpi: int = 300) -> Image.Image:
    """EF-08 : rendu de la page entre 200 et 300 ppp."""
    with pymupdf.open(chemin_pdf) as doc:
        pix = doc[0].get_pixmap(dpi=dpi)
        return Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")


def degrader(img: Image.Image) -> Image.Image:
    """Simule une photo de telephone : rotation, flou, bruit, JPEG (CDC 8.2)."""
    img = img.rotate(2.2, expand=True, fillcolor=255, resample=Image.BICUBIC)
    img = img.filter(ImageFilter.GaussianBlur(0.7))
    bruit = Image.effect_noise(img.size, 26).convert("L")
    img = Image.blend(img, bruit, alpha=0.12)
    tampon = io.BytesIO()
    img.convert("L").save(tampon, format="JPEG", quality=32)
    return Image.open(tampon).convert("L")


def ocr(img: Image.Image) -> str:
    try:
        return pytesseract.image_to_string(img, lang="fra")
    except pytesseract.TesseractError:
        return pytesseract.image_to_string(img, lang="eng")


def extraire_du_texte_ocr(texte: str) -> dict:
    """Mini-structuration du texte OCR — 4 champs, pour la demonstration.

    (La voie de production reste l'extraction native ; ici on montre la
    chaine OCR de reference et ses limites, chiffres a l'appui.)
    """
    champs: dict = {"numero": None, "date_emission": None, "ice": None, "total_ttc": None}

    m = re.search(r"\b([A-Z]{1,2}\s?-\s?20\d{2}\s?-\s?\d{4})\b", texte)
    if m:
        champs["numero"] = re.sub(r"\s", "", m.group(1))

    for ligne in texte.splitlines():
        if "mission" in ligne.lower() and champs["date_emission"] is None:
            champs["date_emission"] = date_depuis_texte(ligne)
        if champs["ice"] is None:
            m = re.search(r"ICE\D{0,4}(\d[\d\s]{12,22}\d)", ligne)
            if m:
                brut = re.sub(r"\s", "", m.group(1))
                champs["ice"] = brut
        if "TTC" in ligne.upper() and champs["total_ttc"] is None:
            nombres = re.findall(r"\d[\d\s\u00a0.,]*\d|\d", ligne)
            if nombres:
                champs["total_ttc"] = montant_depuis_texte(nombres[-1])
    if champs["date_emission"] is None:
        champs["date_emission"] = date_depuis_texte(texte)
    return champs


def comparer(extrait: dict, attendu: Facture) -> dict:
    def val(champ):
        return None if champ is None else champ.valeur

    verites = {
        "numero": val(attendu.numero_facture),
        "date_emission": val(attendu.date_emission),
        "ice": val(attendu.fournisseur.ice) if attendu.fournisseur else None,
        "total_ttc": val(attendu.total_ttc),
    }
    resultat = {}
    for nom, verite in verites.items():
        obtenu = extrait[nom]
        if isinstance(verite, Decimal) and isinstance(obtenu, Decimal):
            resultat[nom] = abs(verite - obtenu) <= Decimal("0.01")
        else:
            resultat[nom] = (obtenu == verite)
    return resultat


def principal(nb_factures: int = 3, graine: int = 7) -> None:
    dossier = Path("demo_ocr")
    if not (dossier / "factures").exists():
        generer_corpus(dossier / "factures", nb_coherentes=nb_factures,
                       nb_fautives=0, graine=graine)

    scores = {"propre": [], "degradee": []}
    print(f"{'document':<16}{'variante':<11}{'numero':<8}{'date':<7}{'ICE':<7}{'TTC':<6}")
    print("-" * 55)

    for chemin_json in sorted((dossier / "factures").rglob("*.json")):
        attendu = Facture.model_validate(
            json.loads(chemin_json.read_text(encoding="utf-8"))["facture"]
        )
        image = pdf_vers_image(chemin_json.with_suffix(".pdf"))
        variantes = {"propre": image, "degradee": degrader(image)}

        for nom_variante, img in variantes.items():
            img.save(dossier / f"{chemin_json.stem}_{nom_variante}.png")
            texte = ocr(img)
            (dossier / f"{chemin_json.stem}_{nom_variante}.txt").write_text(
                texte, encoding="utf-8"
            )
            resultat = comparer(extraire_du_texte_ocr(texte), attendu)
            scores[nom_variante].extend(resultat.values())
            coche = lambda b: "OK" if b else "RATE"
            print(f"{chemin_json.stem:<16}{nom_variante:<11}"
                  f"{coche(resultat['numero']):<8}{coche(resultat['date_emission']):<7}"
                  f"{coche(resultat['ice']):<7}{coche(resultat['total_ttc']):<6}")

    print("-" * 55)
    for nom_variante, valeurs in scores.items():
        taux = 100 * sum(valeurs) / len(valeurs) if valeurs else 0
        print(f"Exactitude OCR ({nom_variante:>8}) : {taux:5.1f}%  "
              f"({sum(valeurs)}/{len(valeurs)} champs)")
    print("\nRappel : la voie native (sans OCR) mesure 100% sur ces memes champs.")
    print(f"Images et textes OCR sauvegardes dans {dossier}/ .")


if __name__ == "__main__":
    principal()
