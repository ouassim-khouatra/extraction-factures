"""Genere le corpus synthetique (a lancer depuis la racine du projet) :

    uv run python generer_corpus.py
    uv run python generer_corpus.py --nombre 500 --fautes 50 --graine 42
"""

import argparse
import sys
from pathlib import Path

# Rend les modules de src/extraction_factures importables hors pytest.
sys.path.insert(0, str(Path(__file__).parent / "src" / "extraction_factures"))

from generateur.synthetique import generer_corpus  # noqa: E402

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--nombre", type=int, default=500, help="factures coherentes")
    p.add_argument("--fautes", type=int, default=50, help="factures fautives")
    p.add_argument("--graine", type=int, default=42, help="graine aleatoire (ENF-04)")
    p.add_argument("--sortie", default="data/synthetique", help="dossier de sortie")
    args = p.parse_args()

    bilan = generer_corpus(
        Path(args.sortie),
        nb_coherentes=args.nombre,
        nb_fautives=args.fautes,
        graine=args.graine,
    )
    print(f"Corpus genere dans {args.sortie}/ : "
          f"{bilan['coherentes']} coherentes + {bilan['fautives']} fautives.")
