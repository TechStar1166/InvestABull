"""SEC filing schemas consumed by the Filings specialist agent."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import RiskSeverity, SourceCitation


class RiskItem(BaseModel):
    """A single discrete risk extracted from a filing or other source."""

    category: str = Field(
        ...,
        description=(
            "Short taxonomic label, e.g. 'regulatory', 'supply_chain', "
            "'cybersecurity', 'litigation', 'macro', 'competition'."
        ),
    )
    title: str = Field(..., max_length=200)
    description: str = Field(
        ...,
        max_length=1_500,
        description="One short paragraph describing the risk, grounded in the source.",
    )
    severity: RiskSeverity = RiskSeverity.MEDIUM
    source_section: str | None = Field(
        default=None,
        description="Filing section where the risk originated (e.g. '10-K Item 1A').",
    )
    citation: SourceCitation


class FilingSectionSummary(BaseModel):
    """Distilled summary for a specific 10-K section."""

    section: str = Field(
        ...,
        description=(
            "Canonical section name: 'business_overview', 'risk_factors', "
            "'mdna', 'competition', 'legal_proceedings', 'other'."
        ),
    )
    summary: str = Field(..., max_length=3_000)
    key_points: list[str] = Field(default_factory=list, max_length=15)
    citations: list[SourceCitation] = Field(default_factory=list)


class FilingsFindings(BaseModel):
    """Aggregated payload emitted by the Filings agent."""

    filing_type: str = Field(default="10-K", description="e.g. '10-K', '10-Q'.")
    filing_period: str | None = Field(
        default=None, description="Fiscal period covered, e.g. 'FY2024'."
    )
    accession_number: str | None = None
    filed_on: str | None = Field(
        default=None, description="ISO date the filing was submitted to the SEC."
    )

    sections: list[FilingSectionSummary] = Field(default_factory=list)
    notable_risks: list[RiskItem] = Field(default_factory=list)
