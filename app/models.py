from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

class Jurisdiction(Base):
    __tablename__ = "jurisdictions"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    country_code: Mapped[str] = mapped_column(String(12), default="")
    legal_system: Mapped[str] = mapped_column(String(80), default="Not specified")
    region: Mapped[str] = mapped_column(String(80), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    courts: Mapped[list["Court"]] = relationship(back_populates="jurisdiction")
    cases: Mapped[list["CaseRecord"]] = relationship(back_populates="jurisdiction")

class Court(Base):
    __tablename__ = "courts"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180), index=True)
    level: Mapped[str] = mapped_column(String(100), default="Unspecified")
    location: Mapped[str] = mapped_column(String(180), default="")
    jurisdiction_id: Mapped[int] = mapped_column(ForeignKey("jurisdictions.id"), index=True)
    jurisdiction: Mapped[Jurisdiction] = relationship(back_populates="courts")
    cases: Mapped[list["CaseRecord"]] = relationship(back_populates="court")
    __table_args__ = (UniqueConstraint("name", "jurisdiction_id", name="uq_court_name_jurisdiction"),)

class Offence(Base):
    __tablename__ = "offences"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180), index=True)
    category: Mapped[str] = mapped_column(String(120), default="Unclassified")
    jurisdiction_id: Mapped[int | None] = mapped_column(ForeignKey("jurisdictions.id"), nullable=True)
    cases: Mapped[list["CaseOffence"]] = relationship(back_populates="offence")

class CaseRecord(Base):
    __tablename__ = "cases"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_reference: Mapped[str] = mapped_column(String(180), index=True)
    title: Mapped[str] = mapped_column(String(240), default="Untitled case")
    decision_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    facts: Mapped[str] = mapped_column(Text, default="")
    court_id: Mapped[int | None] = mapped_column(ForeignKey("courts.id"), nullable=True)
    jurisdiction_id: Mapped[int] = mapped_column(ForeignKey("jurisdictions.id"), index=True)
    data_status: Mapped[str] = mapped_column(String(30), default="synthetic")
    source_notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    jurisdiction: Mapped[Jurisdiction] = relationship(back_populates="cases")
    court: Mapped[Court | None] = relationship(back_populates="cases")
    offences: Mapped[list["CaseOffence"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    outcomes: Mapped[list["CaseOutcome"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    sources: Mapped[list["CaseSource"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    factors: Mapped[list["CaseFactor"]] = relationship(back_populates="case", cascade="all, delete-orphan")

class CaseOffence(Base):
    __tablename__ = "case_offences"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    offence_id: Mapped[int] = mapped_column(ForeignKey("offences.id"), index=True)
    role: Mapped[str] = mapped_column(String(30), default="charged")
    case: Mapped[CaseRecord] = relationship(back_populates="offences")
    offence: Mapped[Offence] = relationship(back_populates="cases")
    __table_args__ = (UniqueConstraint("case_id", "offence_id", "role", name="uq_case_offence_role"),)

class CaseOutcome(Base):
    __tablename__ = "case_outcomes"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    outcome_type: Mapped[str] = mapped_column(String(60), index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    case: Mapped[CaseRecord] = relationship(back_populates="outcomes")
    sentences: Mapped[list["Sentence"]] = relationship(back_populates="outcome", cascade="all, delete-orphan")

class Sentence(Base):
    __tablename__ = "sentences"
    id: Mapped[int] = mapped_column(primary_key=True)
    outcome_id: Mapped[int] = mapped_column(ForeignKey("case_outcomes.id", ondelete="CASCADE"), index=True)
    sentence_type: Mapped[str] = mapped_column(String(80))
    duration_months: Mapped[float | None] = mapped_column(Float, nullable=True)
    fine_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="")
    is_suspended: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    outcome: Mapped[CaseOutcome] = relationship(back_populates="sentences")

class CaseSource(Base):
    __tablename__ = "case_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    source_type: Mapped[str] = mapped_column(String(60), default="judgment")
    title: Mapped[str] = mapped_column(String(240), default="")
    url: Mapped[str] = mapped_column(Text, default="")
    citation: Mapped[str] = mapped_column(String(240), default="")
    accessed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    case: Mapped[CaseRecord] = relationship(back_populates="sources")

class Researcher(Base):
    __tablename__ = "researchers"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160), default="")
    role: Mapped[str] = mapped_column(String(30), default="researcher")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CaseFactor(Base):
    __tablename__ = "case_factors"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    factor_type: Mapped[str] = mapped_column(String(30), default="mitigating")
    category: Mapped[str] = mapped_column(String(100), default="Other")
    description: Mapped[str] = mapped_column(Text)
    case: Mapped[CaseRecord] = relationship(back_populates="factors")
