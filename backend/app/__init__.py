"""InvestABull backend application package.

Sub-packages:
    schemas  - Pydantic models shared across tools, agents, and the API layer.
    tools    - Thin, strictly-typed wrappers around external data providers.
    rag      - SEC 10-K ingestion + ChromaDB retrieval pipeline.
    agents   - Specialist agent prompts and CrewAI bindings.
    services - Orchestration/service functions consumed by FastAPI + CrewAI.
"""

__version__ = "0.1.0"
