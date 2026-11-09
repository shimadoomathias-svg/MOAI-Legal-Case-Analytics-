from datetime import date
from pydantic import BaseModel, ConfigDict, Field

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
