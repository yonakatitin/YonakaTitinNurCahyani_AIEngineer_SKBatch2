from typing import Literal, Optional
from pydantic import BaseModel

Confidence = Literal["high", "medium", "low"]


class Evidenced(BaseModel):
    evidence: Optional[str] = None  # kutipan verbatim dari CV
    confidence: Confidence = "low"


class Education(Evidenced):
    institution: Optional[str] = None
    degree: Optional[str] = None
    field_of_study: Optional[str] = None
    end_year: Optional[int] = None
    gpa: Optional[float] = None


class Experience(Evidenced):
    company: Optional[str] = None
    title: Optional[str] = None
    start: Optional[str] = None  # "YYYY-MM"
    end: Optional[str] = None    # "YYYY-MM" atau "present"
    employment_type: Literal[
        "internship", "full_time", "freelance", "project", "unknown"
    ] = "unknown"
    summary: Optional[str] = None


class Skill(Evidenced):
    name: str
    category: Literal["language", "framework", "tool", "domain", "other"] = "other"


class Project(Evidenced):
    name: Optional[str] = None
    description: Optional[str] = None
    tech: list[str] = []


class CandidateProfile(BaseModel):
    education: list[Education] = []
    experience: list[Experience] = []
    skills: list[Skill] = []
    projects: list[Project] = []
    certifications: list[Evidenced] = []
    extraction_notes: list[str] = []


class Recommendation(BaseModel):
    label: Literal["prioritize_review", "standard_review", "needs_clarification"]
    matched_criteria: list[dict]   # {criterion, evidence, confidence}
    missing_or_unclear: list[str]
    caveats: list[str]
    flags: list[str]
    requires_human_decision: Literal[True] = True
    rubric_version: str