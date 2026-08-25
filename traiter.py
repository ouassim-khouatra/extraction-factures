"""Le pipeline complet en une commande (CDC 5.1 / 5.8 / EF-29) :

    uv run python traiter.py
    uv run python traiter.py --entree data/synthetique --base factures.db
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src" / "extraction_factures"))

from persistance.pipeline import exporter_csv, exporter_excel, traiter_dossier  # noqa: E402

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--entree", default="data/synthetique", help="dossier des fichiers a traiter")
    p.add_argument("--base", default="factures.db", help="fichier SQLite")
    p.add_argument("--exports", default="exports", help="dossier des exports CSV/Excel")
    args = p.parse_args()

    url = f"sqlite:///{args.base}"
    bilan = traiter_dossier(Path(args.entree), url)
    print("Bilan du lot :")
    for statut, nombre in sorted(bilan.items()):
        print(f"  {statut:14} {nombre}")

    c1, c2 = exporter_csv(url, Path(args.exports))
    xl = exporter_excel(url, Path(args.exports) / "factures.xlsx")
    print(f"\nExports : {c1}\n          {c2}\n          {xl}")
