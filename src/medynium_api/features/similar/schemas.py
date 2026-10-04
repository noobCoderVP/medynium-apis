from typing import Literal

from pydantic import BaseModel, Field


class MatchParts(BaseModel):
    embedding: float = Field(description="How alike the two case descriptions are (0 to 1).")
    diagnoses: float = Field(description="Overlap of active diagnoses (0 to 1).")
    medicines: float = Field(description="Overlap of current medicines (0 to 1).")
    labs: float = Field(description="Agreement of abnormal results (0 to 1).")
    age: float = Field(description="How close the ages are (0 to 1).")


class LabComparison(BaseModel):
    test: str
    this_value: float
    other_value: float
    unit: str | None
    this_flag: str | None
    other_flag: str | None


class SimilarPatient(BaseModel):
    patient_id: str
    name: str
    age: int | None
    sex: str | None
    score: float = Field(description="The blended match, 0 to 1. A ranking aid, not a probability.")
    parts: MatchParts
    why: list[str] = Field(description="The reasons, in words, taken from real records.")
    shared_diagnoses: list[str]
    shared_medicines: list[str]
    lab_comparison: list[LabComparison]


class SimilarResponse(BaseModel):
    patient_id: str
    ready: bool = Field(
        description="False while this patient's case vector is still being built after a change."
    )
    items: list[SimilarPatient]
    requested: int
    scoring: Literal["blend", "structured", "embedding"]
    weight_embedding: float
    note: str | None = None
    disclaimer: str
