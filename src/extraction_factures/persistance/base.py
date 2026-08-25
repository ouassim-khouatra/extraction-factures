"""Modele relationnel (CDC EF-26, EF-27, EF-30).

Deux couches de stockage :
- l'extraction brute (JSON complet, colonne `extraction_brute`, jamais
  modifiee apres insertion) ;
- les tables normalisees ci-dessous, celles qu'interrogent les exports
  et l'interface de relecture.

SQLite via SQLAlchemy 2.0 : la couche d'abstraction imposee par le CDC,
qui rendra un passage a PostgreSQL indolore. Les montants sont stockes
en TEXTE (representation canonique du Decimal) pour garantir l'exactitude
au centime — un REAL SQLite perdrait la precision.

Journal d'audit (ENF-07) : table en ajout seul — aucune fonction du code
ne fait jamais d'UPDATE ni de DELETE dessus.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class DocumentDB(Base):
    __tablename__ = "document"

    id: Mapped[int] = mapped_column(primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)  # EF-02 / EF-28
    chemin_source: Mapped[str] = mapped_column(Text)
    nb_pages: Mapped[Optional[int]]
    voie_traitement: Mapped[Optional[str]] = mapped_column(String(20))  # EF-07
    statut: Mapped[str] = mapped_column(String(20), default="recu")  # EF-05
    message_echec: Mapped[Optional[str]] = mapped_column(Text)
    date_ingestion: Mapped[datetime] = mapped_column(default=datetime.now)
    extraction_brute: Mapped[Optional[str]] = mapped_column(Text)  # EF-26, jamais modifiee

    facture: Mapped[Optional["FactureDB"]] = relationship(back_populates="document")


class FournisseurDB(Base):
    __tablename__ = "fournisseur"

    id: Mapped[int] = mapped_column(primary_key=True)
    ice: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    nom: Mapped[Optional[str]] = mapped_column(Text)
    if_: Mapped[Optional[str]] = mapped_column("if_fiscal", String(20))
    adresse: Mapped[Optional[str]] = mapped_column(Text)
    ville: Mapped[Optional[str]] = mapped_column(Text)


class FactureDB(Base):
    __tablename__ = "facture"
    # EF-28 : unicite metier (ICE fournisseur, numero de facture).
    __table_args__ = (UniqueConstraint("ice_fournisseur", "numero_facture"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("document.id"))
    fournisseur_id: Mapped[Optional[int]] = mapped_column(ForeignKey("fournisseur.id"))
    ice_fournisseur: Mapped[Optional[str]] = mapped_column(String(20))
    numero_facture: Mapped[Optional[str]] = mapped_column(String(50))
    type_document: Mapped[Optional[str]] = mapped_column(String(20))
    date_emission: Mapped[Optional[str]] = mapped_column(String(10))   # ISO 8601
    date_echeance: Mapped[Optional[str]] = mapped_column(String(10))
    devise: Mapped[Optional[str]] = mapped_column(String(3))
    total_ht: Mapped[Optional[str]] = mapped_column(String(20))
    total_remise: Mapped[Optional[str]] = mapped_column(String(20))
    total_tva: Mapped[Optional[str]] = mapped_column(String(20))
    total_ttc: Mapped[Optional[str]] = mapped_column(String(20))
    timbre_fiscal: Mapped[Optional[str]] = mapped_column(String(20))
    acompte: Mapped[Optional[str]] = mapped_column(String(20))
    net_a_payer: Mapped[Optional[str]] = mapped_column(String(20))

    document: Mapped["DocumentDB"] = relationship(back_populates="facture")
    fournisseur: Mapped[Optional["FournisseurDB"]] = relationship()
    lignes: Mapped[list["LigneFactureDB"]] = relationship(
        cascade="all, delete-orphan", order_by="LigneFactureDB.numero_ligne"
    )
    bandes: Mapped[list["BandeTvaDB"]] = relationship(cascade="all, delete-orphan")
    drapeaux: Mapped[list["DrapeauRelectureDB"]] = relationship(cascade="all, delete-orphan")


class LigneFactureDB(Base):
    __tablename__ = "ligne_facture"

    id: Mapped[int] = mapped_column(primary_key=True)
    facture_id: Mapped[int] = mapped_column(ForeignKey("facture.id"))
    numero_ligne: Mapped[Optional[int]]
    designation: Mapped[Optional[str]] = mapped_column(Text)
    quantite: Mapped[Optional[str]] = mapped_column(String(20))
    unite: Mapped[Optional[str]] = mapped_column(String(10))
    prix_unitaire_ht: Mapped[Optional[str]] = mapped_column(String(20))
    montant_ht: Mapped[Optional[str]] = mapped_column(String(20))
    taux_tva: Mapped[Optional[str]] = mapped_column(String(10))


class BandeTvaDB(Base):
    __tablename__ = "bande_tva"

    id: Mapped[int] = mapped_column(primary_key=True)
    facture_id: Mapped[int] = mapped_column(ForeignKey("facture.id"))
    taux: Mapped[Optional[str]] = mapped_column(String(10))
    base_ht: Mapped[Optional[str]] = mapped_column(String(20))
    montant_tva: Mapped[Optional[str]] = mapped_column(String(20))


class DrapeauRelectureDB(Base):
    __tablename__ = "drapeau_relecture"

    id: Mapped[int] = mapped_column(primary_key=True)
    facture_id: Mapped[int] = mapped_column(ForeignKey("facture.id"))
    regle: Mapped[str] = mapped_column(String(10))
    severite: Mapped[str] = mapped_column(String(15))
    message: Mapped[str] = mapped_column(Text)
    champs: Mapped[Optional[str]] = mapped_column(Text)  # JSON


class JournalAuditDB(Base):
    __tablename__ = "journal_audit"

    id: Mapped[int] = mapped_column(primary_key=True)
    horodatage: Mapped[datetime] = mapped_column(default=datetime.now)
    evenement: Mapped[str] = mapped_column(String(30))
    document_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    detail: Mapped[Optional[str]] = mapped_column(Text)
