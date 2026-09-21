"""
main.py

The command-line entry point. Asks whether to build a custom network
or use a preset scenario, displays the starting state, asks which
dispatcher to use, then runs the simulation with that choice.
"""

from scenario_input import buildStartingSimulationState
from display import showSimulationState
from presets import getPresetSimulationState, getLargePresetSimulationState
from simulator import simulate
from dispatch_policies import manualPolicy, greedyPolicy, optimalSearch


def chooseStartingSimulationState():
    print("Which scenario would you like to use?")
    print("1. Smaller preset scenario")
    print("2. Larger preset scenario")
    print("3. Create my own scenario")

    while True:
        choice = input("Enter 1, 2, or 3: ")
        if choice in ("1", "2", "3"):
            break
        print("Please enter 1, 2, or 3.")

    if choice == "1":
        return getPresetSimulationState(), False
    elif choice == "2":
        return getLargePresetSimulationState(), False
    else:
        return buildStartingSimulationState(), True

def chooseDispatcher():
    print("Which dispatcher would you like to use for this simulation?")
    print("1. Manual - you decide at each departure point")
    print("2. Greedy - uses the greedy decision policy")
    print("3. Optimal - exhaustively searches for the lowest final score")

    while True:
        choice = input("Enter 1, 2, or 3: ")
        if choice in ("1", "2", "3"):
            break
        print("Please enter 1, 2, or 3.")

    if choice == "1":
        return manualPolicy, "manual"
    elif choice == "2":
        return greedyPolicy, "greedy"
    else:
        return optimalSearch, "optimal"


def main():
    simulationState, isCustomScenario = chooseStartingSimulationState()

    linesToPrint = showSimulationState(simulationState)
    print()
    for line in linesToPrint:
        print(line)

    if isCustomScenario and linesToPrint and max(len(line) for line in linesToPrint) > 230:
        print()
        print("Some lines in this scenario are more than about 230 characters long.")
        print("You may need to zoom out or widen the terminal for the UI to display properly.")

    print()
    dispatchPolicy, dispatchName = chooseDispatcher()

    if dispatchName == "manual":
        print("You'll be using the manual dispatcher for this simulation - whenever a train")
        print("is able to depart, you'll be asked to decide whether it should go now or wait.")
    elif dispatchName == "greedy":
        print("You'll be using the greedy dispatcher for this simulation.")
    else:
        print("You'll be using the optimal dispatcher for this simulation.")
        print("It will exhaustively search the dispatch tree once, then replay the best order.")

    input("Press enter to start the simulation...")
    print()

    simulate(simulationState, dispatchPolicy=dispatchPolicy)


if __name__ == "__main__":
    main()
    input()
