"""
dispatch_policies.py

Each function here is a dispatch policy: given the active train, its
follower, and the current simulation state, decide whether the active
train should go now or wait. simulator.py calls one of these every
time a train reaches a departure decision.

Every policy takes the same inputs and returns the same shape of
output (True = go, False = wait), so simulate() and benchmark.py (once
it exists) can swap between them without caring which one is running.

CIRCULAR IMPORT NOTE: this file imports SimulationState from
simulator.py (below), and simulator.py needs manualPolicy from here as
its default dispatch policy. simulator.py resolves this by importing
manualPolicy lazily, INSIDE simulate()'s function body rather than at
the top of the file - see simulator.py's module docstring for the
full explanation of why that's safe.
"""

from typing import Optional

from simulator import (
    SimulationState,
    _cumulativeDistance,
    _earliestArrivalAtStation,
    _nextPassingStationIndex,
    _nextScheduledStopIndex,
    _remainingTimetableSlack,
    _scheduledSeconds,
)
from entities import Train


def manualPolicy(activeTrain: Train, followingTrain: Optional[Train], state: SimulationState) -> bool:
    """
    Ask the user directly whether the active train should depart now.
    Same signature as greedyPolicy/lookaheadPolicy below, so swapping
    it out later is a one-line change to simulate()'s dispatchPolicy
    argument.
    """
    print(f"  ({followingTrain.headcode} is currently the nearest train behind {activeTrain.headcode})")

    while True:
        answer = input(f"  Should {activeTrain.headcode} depart now? (y/n): ").strip().lower()
        if answer in ("y", "n"):
            return answer == "y"
        print("  Please enter 'y' or 'n'.")


def greedyPolicy(activeTrain: Train, followingTrain: Train, state: SimulationState) -> bool:
    """
    Decide using only the active train and its immediate follower - no
    lookahead beyond the next station (unlike lookaheadPolicy below).
    Compares the weighted cost of going now (delay this adds to
    followingTrain) against the weighted cost of waiting here (delay
    this adds to activeTrain), and picks whichever is cheaper.

    CONTROL STATION: where the overtake could actually happen. A
    station with only 1 platform can never host one (matches the
    single-platform auto-dispatch rule elsewhere), so this searches
    forward for the next station with >= 2. Two cases:
      - followingTrain genuinely behind (gap > 0): the search INCLUDES
        activeTrain's current station - since dispatch policies are
        never even called from a 1-platform station, the current one
        already qualifies, so this resolves to "here" (holding only
        ever happens at the current station in this engine anyway).
      - followingTrain exactly TIED with activeTrain (gap == 0 - e.g.
        both starting together, the normal starting condition): the
        CURRENT station isn't a meaningful future opportunity for
        either of them - there's nothing left to "arrive" for, since
        both are already there - so the search starts from the NEXT
        station instead, projecting forward to wherever a genuine
        difference could still emerge.

    KNOWN LIMITATIONS (stated plainly, not glossed over):
    - only ever considers the ONE immediate follower passed in, not a
      whole queue of trains that might be backed up behind it
    - doesn't account for cascading effects further down the line -
      holding here to help this follower might cause a DIFFERENT
      conflict later that this function can't see
    - the "cost of going" estimate (STEP 3 below) assumes clear track
      once the follower catches up to the active train - it doesn't
      model a THIRD, unrelated train also being in the way
    - both cost estimates use each train's remaining timetable SLACK
      (via _remainingTimetableSlack) to convert raw delay into delay
      that actually reaches the final weighted-lateness objective, but
      this is still an estimate, not an exact simulation of the rest
      of either train's journey - that's what lookaheadPolicy is for
    """
    activeState = state.trainStates[activeTrain.headcode]
    followingState = state.trainStates[followingTrain.headcode]
    scenario = state.scenario
    currentTimeSeconds = state.currentTimeSeconds

    activeSpeed = activeTrain.maxSpeed
    followingSpeed = followingTrain.maxSpeed

    if followingSpeed <= activeSpeed:
        # can never catch up while both run freely - no decision to make
        return True

    activePosition = _cumulativeDistance(activeState, scenario)
    followingPosition = _cumulativeDistance(followingState, scenario)
    gap = activePosition - followingPosition  # 0 for a genuine tie, never negative - the caller guarantees followingTrain is at or behind activeTrain

    relativeSpeed = followingSpeed - activeSpeed
    catchUpTime = gap / relativeSpeed  # 0 immediately for a tie - they're already "caught up"

    # Bound this first check by when activeTrain's OWN next scheduled
    # stop actually FREES the shared block - which is arrival if that
    # stop has >= 2 platforms (the follower can use a different one
    # without needing activeTrain to leave first), but not until
    # DEPARTURE if it only has 1 (the follower can't get past at all
    # while activeTrain still occupies its only platform).
    nextStopIndex = _nextScheduledStopIndex(activeState, scenario)
    nextStopStation = scenario.line.stations[nextStopIndex]
    arrivalAtNextStop = _earliestArrivalAtStation(activeState, nextStopIndex, currentTimeSeconds, scenario)
    if nextStopStation.platforms == 1:
        scheduledAtNextStop = _scheduledSeconds(activeTrain, nextStopStation.name)  # always set - it's a scheduled stop by construction
        freeTime = max(arrivalAtNextStop, scheduledAtNextStop)
    else:
        freeTime = arrivalAtNextStop

    catchUpAbsoluteTime = currentTimeSeconds + catchUpTime

    if catchUpAbsoluteTime >= freeTime:
        # the follower can't catch up before activeTrain would free the
        # block anyway - no real conflict for this decision to resolve
        return True

    # STEP 1 - find the control station (see docstring above)
    controlStationIndex = _nextPassingStationIndex(scenario, activeState.currentStationIndex, inclusive=(gap > 0))
    controlStation = scenario.line.stations[controlStationIndex]

    # STEP 2 - is there currently room for the follower there? Only
    # meaningful when the follower hasn't already arrived (gap > 0) -
    # for a tie, controlStation is a genuinely different, future
    # station neither of our two trains occupies yet, so counting
    # CURRENT occupancy there wouldn't even involve them.
    platformsHere = state.platformOccupancy[controlStation.name]
    if len(platformsHere) >= controlStation.platforms and gap > 0:
        # no room for the follower to overtake here even if activeTrain
        # waited (e.g. a third train is already using the spare
        # platform) - waiting wouldn't create an opportunity, so go
        return True

    # STEP 3 - cost of GOING now: once the follower catches up, it
    # STOPS COMPLETELY (this engine has no "crawling behind" - a
    # blocked train parks at the boundary until the block is free, see
    # _advanceTrain) and stays stopped until activeTrain frees the
    # block. So the delay this causes is simply that stopped duration -
    # not a distance/speed comparison, since the follower isn't moving
    # at any reduced speed during it, it's moving at zero.
    blockingDelay = max(freeTime - catchUpAbsoluteTime, 0.0)

    followingSlack = _remainingTimetableSlack(followingState, state, currentTimeSeconds)
    additionalFinalDelayToFollowing = max(blockingDelay - followingSlack, 0.0)
    goCost = additionalFinalDelayToFollowing * followingTrain.priorityWeight

    # STEP 4 - cost of WAITING. For a genuine follower (gap > 0), this
    # is how long activeTrain needs to hold for followingTrain to
    # reach and claim a platform at the control station. For an exact
    # TIE (gap == 0, e.g. both starting together), that arrival-time
    # comparison is the WRONG model entirely: if activeTrain waits,
    # followingTrain is no longer excluded by isHeld and departs almost
    # immediately, and activeTrain's OWN hold is released again within
    # a tick or two once followingTrain is no longer tied with/behind
    # it (see _refreshHeldTrains) - waiting here is essentially FREE,
    # not something to compare against a future station's arrival time.
    if gap > 0:
        followingClaimTime = _earliestArrivalAtStation(followingState, controlStationIndex, currentTimeSeconds, scenario)
        activeArrivalAtControl = _earliestArrivalAtStation(activeState, controlStationIndex, currentTimeSeconds, scenario)
        waitTime = max(followingClaimTime - activeArrivalAtControl, 0.0)

        if waitTime <= 0:
            # the follower would already be there (or arrive no later
            # than activeTrain naturally would) - no actual wait needed
            return True

        activeSlack = _remainingTimetableSlack(activeState, state, currentTimeSeconds)
        additionalFinalDelayToActive = max(waitTime - activeSlack, 0.0)
        waitCost = additionalFinalDelayToActive * activeTrain.priorityWeight
    else:
        waitCost = 0.0

    # STEP 5 - compare. An exact tie favours GO (keeps things moving,
    # avoids indefinite dithering on a knife-edge decision).
    return waitCost >= goCost


def lookaheadPolicy(
    activeTrain: Train,
    followingTrain: Train,
    state: SimulationState,
    lookaheadStations: int = 2,
) -> bool:
    """
    Same decision as greedyPolicy, but simulates `lookaheadStations`
    stations ahead for both the "go" and "wait" branches, and picks
    whichever gives the better total weighted score over that window.

    Not implemented yet.
    """
    raise NotImplementedError

# The optimal dispatcher is intentionally exhaustive rather than
# heuristic.  It searches the complete binary decision tree once, then
# replays the best decision sequence on the real simulation.
#
# These are module-level on purpose: optimalSearch() is called by
# simulator.py as an ordinary dispatch policy, so the policy needs to
# remember both the solved order and where the real simulation currently
# is in that order.
_optimalDispatchOrder = None
_optimalDispatchIndex = 0
_optimalScenario = None


class _NeedMoreDispatchDecisions(Exception):
    """Internal signal used to stop a test simulation at a tree node."""
    pass


def _optimalScore(state: SimulationState) -> float:
    """Return the final weighted lateness score for a completed simulation."""
    score = 0.0
    for trainState in state.trainStates.values():
        score += trainState.train.priorityWeight * trainState.lastArrivalDelay
    return score


def _runOptimalBranch(initialState: SimulationState, decisionOrder):
    """
    Replay one proposed dispatch sequence from the true starting state.

    The branch stops as soon as it encounters a policy decision which is
    not yet present in decisionOrder.  This gives the DFS a new binary
    tree node to expand without having to duplicate any of the simulator's
    movement/block/platform rules here.

    Returns:
        (completedState, None) if the whole simulation finished, or
        (None, nextDecisionIndex) if another decision is required.
    """
    from simulator import simulate
    from copy import deepcopy

    testState = deepcopy(initialState)
    decisionIndex = 0

    def branchPolicy(activeTrain, followingTrain, state):
        nonlocal decisionIndex

        if decisionIndex >= len(decisionOrder):
            raise _NeedMoreDispatchDecisions

        decision = decisionOrder[decisionIndex]
        decisionIndex += 1
        return decision

    try:
        simulate(
            testState,
            dispatchPolicy=branchPolicy,
            verbose=False,
        )
    except _NeedMoreDispatchDecisions:
        return None, decisionIndex

    if not all(trainState.status == "finished" for trainState in testState.trainStates.values()):
        # This branch did not produce a complete simulation. Treat it as
        # invalid rather than letting one deadlocked branch prevent the
        # solver from examining the remaining branches.
        return "deadlock", None

    return testState, None


def _searchOptimal(initialState: SimulationState, decisionOrder, bestResult):
    """Depth-first exhaustive search of every dispatch decision sequence."""
    completedState, nextDecisionIndex = _runOptimalBranch(initialState, decisionOrder)

    if completedState == "deadlock":
        return

    if completedState is not None:
        score = _optimalScore(completedState)
        if score < bestResult[0]:
            bestResult[0] = score
            bestResult[1] = decisionOrder.copy()
        return

    # Both decisions are legal at this point.  Search GO first, then WAIT.
    # No tree-node objects are needed: decisionOrder itself is the DFS path.
    decisionOrder.append(True)
    _searchOptimal(initialState, decisionOrder, bestResult)
    decisionOrder.pop()

    decisionOrder.append(False)
    _searchOptimal(initialState, decisionOrder, bestResult)
    decisionOrder.pop()


def optimalSearch(activeTrain: Train, followingTrain: Optional[Train], state: SimulationState) -> bool:
    """
    Exhaustively search all legal dispatch/wait decisions once for the
    current scenario, then replay the lowest-score decision order.

    This function deliberately has the same signature as the other
    dispatch policies because simulator.py calls it as a policy.  On the
    first call for a scenario it reconstructs the true starting state and
    searches from t=0; after that, calls simply consume the stored bool
    sequence one item at a time.
    """
    global _optimalDispatchOrder, _optimalDispatchIndex, _optimalScenario

    # A new scenario needs a new solution.  For the same scenario, the
    # expensive search is performed only once.
    if _optimalScenario is not state.scenario:
        _optimalScenario = state.scenario
        _optimalDispatchOrder = None
        _optimalDispatchIndex = 0

    # Solve only the first time this scenario reaches a real dispatch
    # decision.  The state passed into this call may already have had an
    # earlier train processed during the same simulation tick, so rebuild
    # the exact starting state from the immutable Scenario.
    if _optimalDispatchOrder is None:
        from scenario_input import createSimulationState

        initialState = createSimulationState(state.scenario)
        bestResult = [float("inf"), None]

        _searchOptimal(initialState, [], bestResult)

        if bestResult[1] is None:
            raise RuntimeError("optimalSearch could not find a completed dispatch sequence.")

        _optimalDispatchOrder = bestResult[1]
        _optimalDispatchIndex = 0

        print(
            f"Optimal dispatch search complete: "
            f"score = {bestResult[0]:.1f}, "
            f"decisions = {len(_optimalDispatchOrder)}"
        )

    if _optimalDispatchIndex >= len(_optimalDispatchOrder):
        raise RuntimeError(
            "optimalSearch ran out of stored dispatch decisions before the simulation finished. "
            "The simulation's dispatch-call sequence differs from the one used during the search."
        )

    decision = _optimalDispatchOrder[_optimalDispatchIndex]
    _optimalDispatchIndex += 1
    return decision


POLICIES = {
    "manual": manualPolicy,
    "greedy": greedyPolicy,
    "lookahead": lookaheadPolicy,
    "optimal": optimalSearch,
}
