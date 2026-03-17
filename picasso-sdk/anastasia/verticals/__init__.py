"""
ANASTASiA Vertical Neurons — Travel vertical orchestration layer.

Each vertical (flights, hotels, cars, cruises) is a separate neuron module
that manages its own set of API integrations through the Module Registry.

Verticals are installed independently under the ANASTASiA platform.
Each vertical knows how to search, deduplicate, merge, and book through
its configured API modules.

MYSTES KYRIOS LLC — Confidential.
"""

from .flights import FlightsNeuron
from .hotels import HotelsNeuron

__all__ = ["FlightsNeuron", "HotelsNeuron"]
