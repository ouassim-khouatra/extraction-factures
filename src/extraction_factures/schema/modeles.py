"""Schema canonique — Annexe A du CDC.

Les trois proprietes non negociables de ce module :

1. TOUS les champs sont optionnels, sans exception. Un bon de livraison sans
   montant est un enregistrement valide, pas une extraction ratee.
2. Chaque valeur extraite est enveloppee dans `Champ`, qui porte sa provenance
   (Annexe A.5) : d'ou elle vient, ce qu'on a lu exactement, quelle confiance.
3. Ce fichier est la SOURCE DE VERITE UNIQUE (exigence 6.3 du CDC).
   Le JSON Schema pour le decodage contraint, la validation des sorties du
   modele et la documentation derivent tous d'ici. Aucune seconde definition
   du schema ne doit exister ailleurs.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Generic, Literal, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Provenance (Annexe A.5)
# ---------------------------------------------------------------------------


class Source(str, Enum):
    """D'ou vient la valeur d'un champ (ENF-03 : tracabilite)."""

    LU = "lu"          # lue telle quelle sur le document
    DERIVE = "derive"  # recalculee par une regle RD-xx
    CORRIGE = "corrige"  # corrigee par un humain en relecture


class Champ(BaseModel, Generic[T]):
    """Une valeur + sa provenance. Tout champ metier est un Champ[...].

    Exemple : un total TTC lu "1 234,56 DH" sur la page 1 donne
        Champ(valeur=Decimal("1234.56"), valeur_brute="1 234,56 DH",
              source=Source.LU, page=1, confiance=0.98)
    """

    valeur: Optional[T] = None
    valeur_brute: Optional[str] = None  # chaine telle que lue sur le document
    source: Source = Source.LU
    regle: Optional[str] = None  # ex. "RD-01" si source == DERIVE
    confiance: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    page: Optional[int] = None
    zone: Optional[tuple[float, float, float, float]] = None  # x0, y0, x1, y1
    # nom de la lecture -> valeur brute produite par cette lecture (EF-13/EF-14)
    # ex. {"passe_1": "1 234,56", "passe_2": "1234.56"}
    lectures: dict[str, Optional[str]] = Field(default_factory=dict)

    # -- Constructeurs de confort -------------------------------------------

    @classmethod
    def lu(
        cls,
        valeur: T,
        brute: Optional[str] = None,
        confiance: Optional[float] = None,
        page: Optional[int] = None,
    ) -> "Champ[T]":
        """Champ lu sur le document."""
        return cls(
            valeur=valeur, valeur_brute=brute, source=Source.LU,
            confiance=confiance, page=page,
        )

    @classmethod
    def derive(cls, valeur: T, regle: str) -> "Champ[T]":
        """Champ recalcule par une regle de derivation (jamais confondable
        avec un champ lu : source + reference de la regle, CDC section 4.b)."""
        return cls(valeur=valeur, source=Source.DERIVE, regle=regle)


# ---------------------------------------------------------------------------
# Document (Annexe A.1) — le fichier physique
# ---------------------------------------------------------------------------


class StatutDocument(str, Enum):
    RECU = "recu"
    EN_COURS = "en_cours"
    AUTO_ACCEPTE = "auto_accepte"
    A_RELIRE = "a_relire"
    VALIDE = "valide"
    ECHEC = "echec"


class Document(BaseModel):
    document_id: Optional[str] = None
    chemin_source: Optional[str] = None
    sha256: Optional[str] = None  # cle d'idempotence (EF-02/EF-28)
    type_mime: Optional[str] = None
    nb_pages: Optional[int] = None
    voie_traitement: Optional[Literal["texte_natif", "visuel"]] = None  # EF-07
    statut: StatutDocument = StatutDocument.RECU
    date_ingestion: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Tiers (fournisseur / client)
# ---------------------------------------------------------------------------


class Fournisseur(BaseModel):
    # populate_by_name : permet d'ecrire if_=... en Python
    # tout en acceptant "if" dans le JSON ("if" est un mot reserve Python).
    model_config = ConfigDict(populate_by_name=True)

    nom: Optional[Champ[str]] = None
    adresse: Optional[Champ[str]] = None
    ville: Optional[Champ[str]] = None
    pays: Optional[Champ[str]] = None
    ice: Optional[Champ[str]] = None  # 15 chiffres — controle RV-09
    if_: Optional[Champ[str]] = Field(default=None, alias="if")
    rc: Optional[Champ[str]] = None
    cnss: Optional[Champ[str]] = None
    patente: Optional[Champ[str]] = None
    tva_intra: Optional[Champ[str]] = None
    siret: Optional[Champ[str]] = None
    iban: Optional[Champ[str]] = None
    telephone: Optional[Champ[str]] = None
    email: Optional[Champ[str]] = None


class Client(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    nom: Optional[Champ[str]] = None
    adresse: Optional[Champ[str]] = None
    ice: Optional[Champ[str]] = None
    if_: Optional[Champ[str]] = Field(default=None, alias="if")
    rc: Optional[Champ[str]] = None


# ---------------------------------------------------------------------------
# Ligne de facture (Annexe A.3) et bande de TVA (Annexe A.4)
# ---------------------------------------------------------------------------


class LigneFacture(BaseModel):
    numero_ligne: Optional[int] = None
    code_article: Optional[Champ[str]] = None
    designation: Optional[Champ[str]] = None
    quantite: Optional[Champ[Decimal]] = None
    unite: Optional[Champ[str]] = None
    prix_unitaire_ht: Optional[Champ[Decimal]] = None
    taux_remise: Optional[Champ[Decimal]] = None    # en %
    montant_remise: Optional[Champ[Decimal]] = None
    montant_ht: Optional[Champ[Decimal]] = None
    taux_tva: Optional[Champ[Decimal]] = None       # en %
    montant_tva: Optional[Champ[Decimal]] = None
    montant_ttc: Optional[Champ[Decimal]] = None


class BandeTVA(BaseModel):
    """Recapitulatif par taux : indispensable pour les factures multi-taux."""

    taux: Optional[Champ[Decimal]] = None      # en %
    base_ht: Optional[Champ[Decimal]] = None
    montant_tva: Optional[Champ[Decimal]] = None


# ---------------------------------------------------------------------------
# Facture — en-tete (Annexe A.2)
# ---------------------------------------------------------------------------


class TypeDocument(str, Enum):
    FACTURE = "facture"
    AVOIR = "avoir"  # convention de signe a figer avec le comptable (sect. 4.1)
    BON_DE_LIVRAISON = "bon_de_livraison"
    DEVIS = "devis"
    INCONNU = "inconnu"


class Facture(BaseModel):
    type_document: Optional[Champ[TypeDocument]] = None
    numero_facture: Optional[Champ[str]] = None

    date_emission: Optional[Champ[date]] = None
    date_echeance: Optional[Champ[date]] = None
    date_livraison: Optional[Champ[date]] = None

    devise: Optional[Champ[str]] = None  # ISO 4217, defaut configurable (EF-19)

    fournisseur: Optional[Fournisseur] = None
    client: Optional[Client] = None

    reference_commande: Optional[Champ[str]] = None
    reference_bl: Optional[Champ[str]] = None
    mode_paiement: Optional[Champ[str]] = None
    conditions_paiement: Optional[Champ[str]] = None

    total_ht: Optional[Champ[Decimal]] = None
    total_remise: Optional[Champ[Decimal]] = None
    total_port: Optional[Champ[Decimal]] = None
    total_tva: Optional[Champ[Decimal]] = None
    total_ttc: Optional[Champ[Decimal]] = None
    timbre_fiscal: Optional[Champ[Decimal]] = None
    escompte: Optional[Champ[Decimal]] = None
    acompte: Optional[Champ[Decimal]] = None
    net_a_payer: Optional[Champ[Decimal]] = None
    montant_en_lettres: Optional[Champ[str]] = None  # controle croise optionnel

    lignes: list[LigneFacture] = Field(default_factory=list)
    bandes_tva: list[BandeTVA] = Field(default_factory=list)

    # EF-15 : tout ce qui a ete lu mais n'entre pas dans le schema.
    # Aucune information n'est perdue.
    extra: dict[str, Any] = Field(default_factory=dict)
