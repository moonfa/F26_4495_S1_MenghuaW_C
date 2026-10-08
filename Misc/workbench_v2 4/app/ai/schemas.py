from typing import Literal
from pydantic import BaseModel, Field

Status = Literal["holding", "strengthened", "weakened", "broken", "unverified"]
Level3 = Literal["low", "medium", "high"]
View = Literal["constructive", "neutral", "cautious"]


class Assumption(BaseModel):
    id: str = Field(pattern=r"^a\d+$")
    statement: str = Field(min_length=1, max_length=220)
    status: Status = "unverified"
    evidence: list[str] = Field(default_factory=list, max_length=3)   # "metric=value" or short fact
    kill_criteria: str = Field(min_length=1, max_length=220)          # what would prove it wrong
    confidence: Level3 = "medium"
    causal_mechanism: str = Field(default="", max_length=260)       # observation -> mechanism -> financial consequence
    materiality: Level3 = "medium"
    missing_evidence: str = Field(default="", max_length=220)       # what data would test it, and where to find it
    warning_trigger: str = Field(default="", max_length=220)        # worth investigating (may be a lagging result)
    time_horizon: str = Field(default="", max_length=40)


class Profile(BaseModel):
    classification: str = Field(max_length=120)
    business_model: str = Field(max_length=900)
    moat: str = Field(max_length=700)
    key_drivers: list[str] = Field(max_length=4)
    key_risks: list[str] = Field(max_length=4)       # mechanisms, not generic labels
    bear_case: str = Field(max_length=800)
    valuation_view: str = Field(max_length=600)      # what the current price appears to assume


class MonitorItem(BaseModel):
    indicator: str = Field(max_length=120)
    why: str = Field(max_length=200)
    trigger: str = Field(max_length=160)
    why_this_level: str = Field(default="", max_length=120)


class BaselineOutput(BaseModel):
    one_liner: str = Field(min_length=1, max_length=240)
    view: View
    assumptions: list[Assumption] = Field(min_length=3, max_length=5)
    profile: Profile
    monitor: list[MonitorItem] = Field(min_length=2, max_length=5)
    valuation_implication: str = Field(default="", max_length=450)
    consensus_gap: str = Field(default="", max_length=260)
    report_markdown: str = Field(min_length=1, max_length=3000)


class TItem(BaseModel):
    k: str
    t: str


class TranslationOutput(BaseModel):
    items: list[TItem]


class AssumptionUpdate(BaseModel):
    id: str
    new_status: Status
    reason: str = Field(min_length=1, max_length=300)    # must cite evidence
    evidence: list[str] = Field(default_factory=list, max_length=3)


class Change(BaseModel):
    what: str = Field(max_length=200)
    so_what: str = Field(max_length=260)


class UpdateOutput(BaseModel):
    one_liner: str = Field(min_length=1, max_length=240)
    view: View
    view_change: Literal["up", "unchanged", "down"]
    assumption_updates: list[AssumptionUpdate] = Field(default_factory=list, max_length=6)
    new_assumptions: list[Assumption] = Field(default_factory=list, max_length=2)
    changes: list[Change] = Field(min_length=1, max_length=3)
    what_changed: list[Literal["earnings", "valuation", "thesis"]] = Field(default_factory=list, max_length=3)
    valuation_note: str = Field(default="", max_length=400)
    monitor_adds: list[MonitorItem] = Field(default_factory=list, max_length=2)
    rebaseline_recommended: bool = False
    rebaseline_reason: str = Field(default="", max_length=300)
    narrative: str = Field(min_length=1, max_length=1800)
