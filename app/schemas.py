from datetime import date
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

class JurisdictionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    country_code: str
    legal_system: str
    region: str

class CaseCreate(BaseModel):
    case_reference: str = Field(min_length=1, max_length=180)
    title: str = Field(min_length=1, max_length=240)
    jurisdiction_id: int
    court_id: int | None = None
    decision_date: date | None = None
    summary: str = ""
    facts: str = ""
    data_status: str = "researcher-entered"

class CaseUpdate(BaseModel):
    case_reference: str | None = Field(default=None, min_length=1, max_length=180)
    title: str | None = Field(default=None, min_length=1, max_length=240)
    jurisdiction_id: int | None = None
    court_id: int | None = None
    decision_date: date | None = None
    summary: str | None = None
    facts: str | None = None
    data_status: str | None = None

class CaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    case_reference: str
    title: str
    decision_date: date | None
    year: int | None
    jurisdiction_id: int
    court_id: int | None
    summary: str
    facts: str
    data_status: str

class SentenceCreate(BaseModel):
    sentence_type: str = Field(min_length=1, max_length=80)
    duration_months: float | None = Field(default=None, ge=0)
    fine_amount: float | None = Field(default=None, ge=0)
    currency: str = Field(default="", max_length=3)
    is_suspended: bool = False
    notes: str = ""

class OutcomeCreate(BaseModel):
    outcome_type: str = Field(min_length=1, max_length=60)
    notes: str = ""
    sentences: list[SentenceCreate] = Field(default_factory=list)

class OffenceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    category: str = Field(default="Unclassified", max_length=120)
    role: str = Field(default="charged", max_length=30)

class SourceCreate(BaseModel):
    source_type: str = Field(default="judgment", max_length=60)
    title: str = Field(default="", max_length=240)
    url: str = ""
    citation: str = Field(default="", max_length=240)
    accessed_on: date | None = None

class ResearchDataCreate(BaseModel):
    offences: list[OffenceCreate] = Field(default_factory=list)
    outcomes: list[OutcomeCreate] = Field(default_factory=list)
    sources: list[SourceCreate] = Field(default_factory=list)
