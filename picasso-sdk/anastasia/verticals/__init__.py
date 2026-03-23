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
from .cars import CarsNeuron
from .activities import ActivitiesNeuron
from .insurance import InsuranceNeuron

__all__ = [
    "FlightsNeuron",
    "HotelsNeuron",
    "CarsNeuron",
    "ActivitiesNeuron",
    "InsuranceNeuron",
]
