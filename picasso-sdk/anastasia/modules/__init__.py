"""
ANASTASiA Module Registry — Dynamic API Integration System

The Module Registry is a directory of API modules that ANASTASiA can
discover, load, and wire together dynamically based on available
credentials. Each module has:

1. A **client** — the actual API client (search, book, manage)
2. A **knowledge card** — structured metadata that ANASTASiA reads to
   understand capabilities, auth requirements, data formats, quirks
3. **Tools** — Claude function-calling schemas for the agent

The Module Director reads knowledge cards and creates optimal call
chains across all configured modules — like the neuron network,
but for API orchestration.

MYSTES KYRIOS LLC — Confidential.
"""

from .registry import ModuleRegistry, APIModule, KnowledgeCard
from .director import ModuleDirector

__all__ = [
    "ModuleRegistry",
    "APIModule",
    "KnowledgeCard",
    "ModuleDirector",
]
