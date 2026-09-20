"""
entities.py

The STATIC input data for a scenario - the things that don't change
once you've defined them: what the line looks like, and what trains
are meant to run on it. Nothing in this file changes as a simulation
runs; that "changing" data (positions, delays, occupancy) belongs in
simulator.py instead.

"""

from dataclasses import dataclass
from typing import List, Dict


@dataclass
class Station:
    name: str
    platforms: int


@dataclass
class Section:
    """The stretch of track between two consecutive stations, divided
    into block sections by signals. Absolute block signalling means
    only one train may occupy any one block at a time."""
    fromStation: str
    toStation: str
    distance: float       # total distance covered by this section
    numSignals: int       # number of signals along this section
    # NOTE: how numSignals translates into number/length of blocks
    # is a decision for later - not defined yet.


@dataclass
class Line:
    """The full line: an ordered list of stations, and the
    section of track connecting each consecutive pair."""
    stations: List[Station]
    sections: List[Section]   # expected: len(sections) == len(stations) - 1


@dataclass
class Train:
    headcode: str                # must be exactly 4 characters
    maxSpeed: float              # distance units per second (converted from the per-hour value the user enters)
    stops: List[str]             # station names this train calls at, in order
    timetable: Dict[str, float]  # station name -> scheduled time there, in SECONDS (converted from minutes at input time)
    priorityWeight: float        # used in the weight * max(0, actual - scheduled) score


@dataclass
class Scenario:
    """One full problem instance: a line plus every train running on it."""
    line: Line
    trains: List[Train]
