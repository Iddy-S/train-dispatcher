"""
scenario_input.py

Everything to do with getting data from the user and turning it into
entities.py objects. Kept separate from entities.py (which only
defines what a Station/Train/Scenario is, not how one gets built
from input), and separate from display.py (which goes the other way -
objects to text).
"""

from entities import Station, Section, Line, Train, Scenario
from display import showStationsNoSignals, showScenario
from simulator import TrainState, SimulationState


def _getUniqueStationName(prompt: str, stations) -> str:
    """Read a non-empty station name that has not already been used."""
    while True:
        stationName = input(prompt).strip()
        if not stationName:
            print("A station name cannot be empty.")
            continue
        if any(existing.name.casefold() == stationName.casefold() for existing in stations):
            print("That station name is already in use. Please enter a different name.")
            continue
        return stationName


def _getUniqueHeadcode(usedHeadcodes) -> str:
    """Read a 4-character headcode that has not already been used."""
    while True:
        headcode = input("Enter the headcode of the train: ").strip().upper()
        if len(headcode) != 4:
            print("A headcode must be 4 characters long exactly, like '1A06', '2E57', or '5D74'")
            continue
        if headcode in usedHeadcodes:
            print("That headcode is already in use. Please enter a different headcode.")
            continue
        usedHeadcodes.add(headcode)
        return headcode


def createStations():
    """
    Ask the user how many stations there are, then read each one's
    details, returning a list of Station objects and number of trains.
    """

    stations = []

    numStations = int(input("Enter the number of stations on the line: "))
    numTrains = int(input("Enter the number of trains on the line: "))
    print()

    for i in range(numStations):
        if i == 0:
            stationName = _getUniqueStationName("Enter the name of the first station: ", stations)
            while 1:
                stationPlatforms = int(input(f"Enter the number of platforms on {stationName}: "))
                if stationPlatforms >= numTrains:
                    break
                print(f"The first station must have at least {numTrains} platforms to fit all your trains when the simulation begins.")
            stations.append(Station(name=stationName, platforms=stationPlatforms))
        else:
            print()
            stationsUI = showStationsNoSignals(stations)
            for line in stationsUI:
                print(line)
            print()

            if i == numStations - 1:
                stationName = _getUniqueStationName("Enter the name of the last station: ", stations)
                while 1:
                    stationPlatforms = int(input(f"Enter the number of platforms on {stationName}: "))
                    if stationPlatforms >= numTrains:
                        break
                    print(f"The last station must have at least {numTrains} platforms to fit all your trains when the simulation ends.")
                stations.append(Station(name=stationName, platforms=stationPlatforms))
            else:
                stationName = _getUniqueStationName("Enter the name of the next station: ", stations)
                stationPlatforms = int(input(f"Enter the number of platforms on {stationName}: "))
                stations.append(Station(name=stationName, platforms=stationPlatforms))
    print()
    stationsUI = showStationsNoSignals(stations)
    for line in stationsUI:
        print(line)
    return stations, numTrains
            
    


def createSections(stations, trains):
    """
    Read the details of each section between consecutive stations
    (distance, number of signals), returning a list of Section objects.
    """

    sections = []

    for i in range(len(stations) - 1):
        section = Section(fromStation=stations[i].name, toStation=stations[i+1].name, distance=0, numSignals=0)
        sections.append(section)

    for i in range(len(stations) - 1):
        sections[i].distance = float(input(f"Enter the distance between {stations[i].name} and {stations[i+1].name} in miles: "))
        sections[i].numSignals = int(input("Enter the number of signals in this strech: "))

        linesToPrint = showScenario(Scenario(line=Line(stations=stations, sections=sections), trains=trains))
        print()
        for line in linesToPrint:
            print(line)
        print()

    return Scenario(line=Line(stations=stations, sections=sections), trains=trains)




def createTrains(stations, numTrains):
    """
    Ask how many trains there are, then read each one's details
    (headcode, speed, stops, timetable, priority weight), returning a
    list of Train objects.
    """

    trains = []
    usedHeadcodes = set()
    for train in range(numTrains):
        print(f"Train {train+1}/{numTrains}")
        headcode = _getUniqueHeadcode(usedHeadcodes)
        speed = float(input("Enter the speed of this train in miles per hour: ")) / 3600  # stored internally as miles per second
        weight = float(input("Enter the priority wieght of this train: "))
        print()
        if not len(trains):
            print("You can enter a time in two ways: as a plain number of minutes since the simulation starts (e.g. '90'), or as a 24-hour clock time using colons (e.g. '16:02' or '19:47:30').")

        timetable = {}
        stationStops = []
        stationsToSkip = 0
        for stationCount in range(len(stations)):
            if stationsToSkip:
                stationsToSkip -= 1
                continue
            if stationCount == 0:
                print(f"This train will begin its joruney at {stations[0].name}.")
                departureStation = stations[0]
            elif stationCount + 1 == len(stations):
                print(f"This train will end its journey at {stations[-1].name}.")
                departureStation = stations[-1]
            else:
                print("What is the next station this train would stop at?")
                validInputs = []
                for i in range(len(stations) - stationCount):
                    print(f"{i+1}. {stations[i+stationCount].name}")
                    validInputs.append(stations[i+stationCount].name)
                    validInputs.append(str(i+1))
                while 1:
                    inputStation = input("Enter the station name, or its number from the list above: ")
                    if inputStation not in validInputs:
                        print("That was not a valid station.")
                    else:
                        break
                if inputStation.isdigit():
                    departureStation = stations[int(inputStation)-1 + stationCount]
                else:
                    departureStation = stations[ int(validInputs[ validInputs.index(inputStation) + 1]) -1 + stationCount]
                stationsToSkip += validInputs.index(inputStation) // 2
                

            while 1:
                inputTime = input(f"Enter the time at which this train will be scheduled to depart {departureStation.name}: ")
                validFloat = True
                for char in inputTime:
                    if char not in ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '.']:
                        validFloat = False
                        break
                if validFloat:
                    departureTime = float(inputTime)
                    if len(stationStops):
                        prevTime = timetable[stationStops[-1]]
                        if prevTime >= departureTime:
                            print("Enter a time after the departure time of the previous station.")
                            continue
                    break
                else:
                    timeParts = inputTime.split(':')
                    validTime = False
                    if len(timeParts) == 2 or len(timeParts) == 3:
                        validTime = True
                        for part in timeParts:
                            if not part.isdigit():
                                validTime = False
                                break

                        
                        if validTime:
                            departureTime = 0.0 + int(timeParts[0])*60 + int(timeParts[1])
                            if len(timeParts) == 3:
                                departureTime += int(timeParts[2])/60
                            if len(stationStops):
                                prevTime = timetable[stationStops[-1]]
                                if prevTime >= departureTime:
                                    print("Enter a time after the departure time of the previous station.")
                                    continue
                            break
                    else:
                        print("Enter a valid time. To do so, either enter the number of minutes since a starting point, or use a 24 hour clock (eg '16:02' or '19:47:30' - you must use a colon)")

            stationStops.append(departureStation.name)
            timetable.update({departureStation.name : departureTime})
            print()

        timetable = {name: minutes * 60.0 for name, minutes in timetable.items()}  # store in seconds - everything above worked in minutes
        trains.append(Train(headcode=headcode, maxSpeed=speed, stops=stationStops, timetable=timetable, priorityWeight=weight))

    return trains

def createSimulationState(scenario):
    stations = scenario.line.stations
    trains = scenario.trains

    trainStates = {}
    blockOccupancy = {}
    platformOccupancy = {}
    platformOccupancy[stations[0].name] = []
    for train in trains:
        trainStates[train.headcode] = TrainState(train=train)
        platformOccupancy[stations[0].name].append(train.headcode)
    for i in range(len(scenario.line.sections)):
        for j in range(scenario.line.sections[i].numSignals + 1):
            blockOccupancy[(i,j)] = None
    for station in stations[1:]:
        platformOccupancy[station.name] = []
    
    return SimulationState(scenario=scenario, trainStates=trainStates, blockOccupancy=blockOccupancy, platformOccupancy=platformOccupancy)

def buildStartingSimulationState():
    """
    Run the full input process and return a completed Scenario.
    """

    stations, numTrains = createStations()
    print()
    trains = createTrains(stations, numTrains)
    scenario = createSections(stations, trains)

    simulationState = createSimulationState(scenario)
    
    return simulationState
