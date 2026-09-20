"""
presets.py

Hardcoded example scenarios for quick testing, so you don't have to
type in a full line and timetable by hand every time you want to try
something out - this file is about providing ready-made examples.
"""

from entities import Station, Section, Line, Train, Scenario
from scenario_input import createSimulationState
from simulator import SimulationState


def getPresetSimulationState() -> SimulationState:
    """
    Small test scenario: a 3-station line with 2 trains - one local
    and one express.
    """
    stations = [
        Station(name="Kings Cross", platforms=3),
        Station(name="Finsbury Park", platforms=1),
        Station(name="Peterborough", platforms=2),
    ]

    sections = [
        Section(fromStation="Kings Cross", toStation="Finsbury Park", distance=5.0, numSignals=2),
        Section(fromStation="Finsbury Park", toStation="Peterborough", distance=10.0, numSignals=3),
    ]

    trains = [
        Train(
            headcode="1A06",
            maxSpeed=100.0 / 3600,
            stops=["Kings Cross", "Finsbury Park", "Peterborough"],
            timetable={"Kings Cross": 0.0, "Finsbury Park": 600.0, "Peterborough": 1500.0},
            priorityWeight=1.0,
        ),
        Train(
            headcode="2E57",
            maxSpeed=120.0 / 3600,
            stops=["Kings Cross", "Peterborough"],
            timetable={"Kings Cross": 120.0, "Peterborough": 720.0},
            priorityWeight=2.0,
        ),
    ]

    scenario = Scenario(line=Line(stations=stations, sections=sections), trains=trains)
    return createSimulationState(scenario)


def _buildServiceTimetable(line: Line, stops: list[str], startMinute: float, speed: float, marginSeconds: float) -> dict[str, float]:
    """Build a physically achievable timetable for a preset service."""
    stationIndexes = {station.name: index for index, station in enumerate(line.stations)}
    timetable = {}
    currentTime = startMinute * 60.0

    for stopIndex, stationName in enumerate(stops):
        timetable[stationName] = currentTime

        if stopIndex == len(stops) - 1:
            break

        fromIndex = stationIndexes[stationName]
        toIndex = stationIndexes[stops[stopIndex + 1]]
        distance = sum(line.sections[index].distance for index in range(fromIndex, toIndex))
        currentTime += distance / speed + marginSeconds

    return timetable


def getLargePresetSimulationState() -> SimulationState:
    """
    Larger multi-service scenario: a 6-station route with 2 trains.

    Services include all-stations, semi-fast and express patterns, with
    several multi-platform stations to create genuine dispatch choices.
    """
    stationData = [
        ("Kings Cross", 2),
        ("Stevenage", 4),
        ("Cambridge", 5),
        ("Ely", 4),
        ("Peterborough", 5),
        ("Newcastle", 2),
    ]
    stations = [Station(name=name, platforms=platforms) for name, platforms in stationData]

    distances = [
        16.0,
        12.0,
        10.0,
        13.0,
        11.0,
    ]
    signals = [
        1,
        1,
        1,
        1,
        1,
    ]

    sections = [
        Section(
            fromStation=stations[index].name,
            toStation=stations[index + 1].name,
            distance=distances[index],
            numSignals=signals[index],
        )
        for index in range(len(stations) - 1)
    ]

    line = Line(stations=stations, sections=sections)
    allStations = [station.name for station in stations]

    localStops = allStations
    cambridgeStops = allStations
    semiFastStops = ["Kings Cross", "Stevenage", "Cambridge", "Ely", "Peterborough", "Newcastle"]
    expressStops = ["Kings Cross", "Stevenage", "Peterborough", "Newcastle"]
    easternStops = ["Kings Cross", "Cambridge", "Ely", "Peterborough", "Newcastle"]

    serviceDefinitions = [
        ("1A01", 100.0 / 3600, localStops, 0.0, 1.0, 45.0),
        ("2E11", 135.0 / 3600, expressStops, 5.0, 4.0, 25.0),
    ]

    trains = []
    for headcode, speed, stops, startMinute, weight, marginSeconds in serviceDefinitions:
        trains.append(
            Train(
                headcode=headcode,
                maxSpeed=speed,
                stops=stops,
                timetable=_buildServiceTimetable(line, stops, startMinute, speed, marginSeconds),
                priorityWeight=weight,
            )
        )

    scenario = Scenario(line=line, trains=trains)
    return createSimulationState(scenario)
