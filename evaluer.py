"""Le harnais d'evaluation en une commande (CDC section 9.1) :

    uv run python evaluer.py
    uv run python evaluer.py --corpus data/synthetique
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src" / "extraction_factures"))

from evaluation.harnais import campagne, formater_rapport  # noqa: E402

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--corpus", default="data/synthetique", help="dossier PDF+JSON")
    p.add_argument("--resultats", default="eval_resultats", help="dossier des rapports dates")
    args = p.parse_args()

    metriques, chemin = campagne(Path(args.corpus), Path(args.resultats))
    print(formater_rapport(metriques))
    print(f"\nRapport enregistre : {chemin}")
