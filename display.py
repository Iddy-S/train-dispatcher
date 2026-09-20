"""
display.py

Everything to do with turning entities.py objects BACK into readable
text for the user - the reverse direction of scenario_input.py.
Keeping this separate means: if you later want to change how output
looks (e.g. a nicer table, or colours), you only touch this file.
"""

from entities import Scenario, Station, Train, Line, Section
from simulator import SimulationState, TrainState


def showStationsNoSignals(stations):
    numStations = len(stations)

    # Top Line of Display
    topLine = ""
    for station in stations:
        stationNameLength = len(station.name)
        topLine += "┌"
        for i in range( max(stationNameLength + 2, 8) ):
            topLine += "─"
        topLine += "┐      "

    # Middle Line of Display
    midLine = ""
    for count, station in enumerate(stations):
        # Calculates what goes in the box, with sufficient padding
        stationName = station.name
        if len(stationName) < 6:
            missingChars = 6 - len(stationName)
            for i in range(missingChars // 2):
                stationName = " " + stationName
            missingChars = 6 - len(stationName)
            for i in range(missingChars):
                stationName += " "

        # Draws box
        if count == 0:
            midLine += "│"
        else:
            midLine += "┤"
        midLine += f" {stationName} "
        if count != numStations - 1:
            midLine += "├──────"
        else:
            midLine += "│"

    # Bottom Line of Display
    bottomLine = ""
    for station in stations:
            stationNameLength = len(station.name)
            bottomLine += "└"
            for i in range( max(stationNameLength + 2, 8) ):
                bottomLine += "─"
            bottomLine += "┘      "

    outputLines = [topLine, midLine, bottomLine]

    # Platform Lines in Display
    maxPlatforms = 0
    for station in stations:
        maxPlatforms = max(maxPlatforms, station.platforms)

    for i in range(maxPlatforms):
        line = ""
        stationCount = 0
        charsToSkip = 0
        for char in bottomLine:
            if charsToSkip:
                charsToSkip -= 1
                continue
            if char == "└":
                if stations[stationCount].platforms > i: # If the station has this many platforms
                    line += f" {i+1}. ____"
                    charsToSkip = len(f" {i+1}. ___")
                else:
                    line += " "
                stationCount += 1
            else:
                line += " "
        outputLines.append(line)

    return outputLines



def showScenario(scenario: Scenario):
    """
    Print a readable summary of the scenario that was built - the
    line's stations/sections, and the trains running on it. This 
    would only be used before trains start moving.

    """

    stations = scenario.line.stations
    sections = scenario.line.sections
    trains = scenario.trains

    paddedStationNames = []
    for station in stations:
        stationName = station.name
        if len(stationName) < 6:
            missingChars = 6 - len(stationName)
            for i in range(missingChars // 2 + 1):
                stationName = " " + stationName
            missingChars = 6 - len(stationName)
            for i in range(missingChars + 1):
                stationName += " "
        paddedStationNames.append(stationName)

    # Top Line of Display
    topLine = ""
    for count, station in enumerate(stations):
        topLine += "┌"
        for i in range(len(paddedStationNames[count])):
            topLine += "─"
        topLine += "┐"

        if count == len(stations) - 1:
            numSignals = 0
        else:
            numSignals = sections[count].numSignals
        for i in range(numSignals):
            topLine += "        O"
        topLine += "        "

    # Middle Line of Display
    midLine = ""
    for count, station in enumerate(stations):
        if count == 0:
            midLine += "│"
        else:
            midLine += "┤"
        midLine += paddedStationNames[count]
        if count == len(stations) - 1:
            midLine += "│"
        else:
            midLine += "├"
        
            if count == len(stations) - 1:
                numSignals = 0
            else:
                numSignals = sections[count].numSignals
            for i in range(numSignals):
                midLine += "────────┴"
            midLine += "────────"

    # Bottom Line of Display
    bottomLine = ""
    for count, station in enumerate(stations):
        bottomLine += "└"
        for i in range(len(paddedStationNames[count])):
            bottomLine += "─"
        bottomLine += "┘"

        if count == len(stations) - 1:
            numSignals = 0
        else:    
            numSignals = sections[count].numSignals
        for i in range(numSignals):
            bottomLine += "         "
        bottomLine += "        "

    outputLines = [topLine, midLine, bottomLine]

    # Platform Lines in Display
    maxPlatforms = 0
    for station in stations:
        maxPlatforms = max(maxPlatforms, station.platforms)

    for i in range(maxPlatforms):
        line = ""
        stationCount = 0
        charsToSkip = 0
        for count, char in enumerate(topLine):
            if charsToSkip:
                charsToSkip -= 1
                continue
            if char == "┌":
                if stations[stationCount].platforms > i: # If the station has this many platforms
                    if stationCount == 0 and i < len(trains):
                        line += f" {i+1}. {trains[i].headcode}"
                    else:
                        line += f" {i+1}. ____"
                    charsToSkip = len(f" {i+1}. ___")
                else:
                    line += " "
                stationCount += 1

            elif (char == "┐" or char == "O") and i == 0:
                if char == "┐":
                    if midLine[count] == "│":
                        line+= " "
                        continue
                line += "   ____  "
                charsToSkip = len("   ____ ")
            else:
                line += " "
        outputLines.append(line)    

    return outputLines




def showSimulationState(simulationState: SimulationState):
    """
    Print where each train currently is. For now, since there's no
    simulation yet, this can just mean each train's starting position
    - that's still a legitimate first version, not a shortcut.

    Not implemented yet.
    """
    #raise NotImplementedError

    stations = simulationState.scenario.line.stations
    sections = simulationState.scenario.line.sections
    trains = simulationState.scenario.trains

    paddedStationNames = []
    for station in stations:
        stationName = station.name
        if len(stationName) < 6:
            missingChars = 6 - len(stationName)
            for i in range(missingChars // 2 + 1):
                stationName = " " + stationName
            missingChars = 6 - len(stationName)
            for i in range(missingChars + 1):
                stationName += " "
        paddedStationNames.append(stationName)

    # Top Line of Display
    topLine = ""
    for count, station in enumerate(stations):
        topLine += "┌"
        for i in range(len(paddedStationNames[count])):
            topLine += "─"
        topLine += "┐"

        if count == len(stations) - 1:
            numSignals = 0
        else:
            numSignals = sections[count].numSignals
        for i in range(numSignals):
            topLine += "        O"
        topLine += "        "

    # Middle Line of Display
    midLine = ""
    for count, station in enumerate(stations):
        if count == 0:
            midLine += "│"
        else:
            midLine += "┤"
        midLine += paddedStationNames[count]
        if count == len(stations) - 1:
            midLine += "│"
        else:
            midLine += "├"
        
            if count == len(stations) - 1:
                numSignals = 0
            else:
                numSignals = sections[count].numSignals
            for i in range(numSignals):
                midLine += "────────┴"
            midLine += "────────"

    # Bottom Line of Display
    bottomLine = ""
    for count, station in enumerate(stations):
        bottomLine += "└"
        for i in range(len(paddedStationNames[count])):
            bottomLine += "─"
        bottomLine += "┘"

        if count == len(stations) - 1:
            numSignals = 0
        else:    
            numSignals = sections[count].numSignals
        for i in range(numSignals):
            bottomLine += "         "
        bottomLine += "        "

    outputLines = [topLine, midLine, bottomLine]

    # Platform Lines in Display
    maxPlatforms = 0
    for station in stations:
        maxPlatforms = max(maxPlatforms, station.platforms)

    for i in range(maxPlatforms):
        line = ""
        stationCount = 0
        charsToSkip = 0
        blockIndexWithinSection = 0
        for count, char in enumerate(topLine):
            if charsToSkip:
                charsToSkip -= 1
                continue
            if char == "┌":
                if stations[stationCount].platforms > i: # If the station has this many platforms
                    trainsAtCurrentStation = simulationState.platformOccupancy[stations[stationCount].name]
                    if i < len(trainsAtCurrentStation):
                        line += f" {i+1}. {trainsAtCurrentStation[i]}"
                    else:
                        line += f" {i+1}. ____"
                    charsToSkip = len(f" {i+1}. ___")
                else:
                    line += " "
                stationCount += 1
                blockIndexWithinSection = 0

            elif (char == "┐" or char == "O") and i == 0:
                if char == "┐":
                    if midLine[count] == "│":
                        line+= " "
                        continue
                if char == "O":
                    blockIndexWithinSection += 1
                headcode = simulationState.blockOccupancy[(stationCount - 1, blockIndexWithinSection)]
                if headcode == None:
                    headcode = "____"
                line += f"   {headcode}  "
                charsToSkip = len("   ____ ")

            else:
                line += " "
        outputLines.append(line)    

    return outputLines