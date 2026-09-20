"""
dispatch_policies.py

Each function here is a dispatch policy: given the active train, its
follower, and the current simulation state, decide whether the active
train should go now or wait. simulator.py calls one of these every
time a train reaches a departure decision.

Every policy takes the same inputs and returns the same shape of
output (True = go, False = wait).
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
    lookahead beyond the next station. Compares the weighted cost of 
    going now (delay this adds to followingTrain) against the weighted 
    cost of waiting here (delay this adds to activeTrain), and picks 
    whichever is cheaper.

    CONTROL STATION: where the overtake could actually happen. A
    station with only 1 platform can never host one (matches the
    single-platform auto-dispatch rule elsewhere), so this searches
    forward for the next station with >= 2. Two cases:
      - followingTrain genuinely behind (gap > 0): the search includes
        activeTrain's current station - since dispatch policies are
        never even called from a 1-platform station, the current one
        already qualifies, so this resolves to "here" (holding only
        ever happens at the current station in this engine anyway).
      - followingTrain exactly tied with activeTrain (gap == 0 - e.g.
        both starting together, the normal starting condition): the
        CURRENT station isn't a meaningful future opportunity for
        either of them - there's nothing left to "arrive" for, since
        both are already there - so the search starts from the NEXT
        station instead, projecting forward to wherever a genuine
        difference could still emerge.

    KNOWN LIMITATIONS:
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
    gap = activePosition - followingPosition

    relativeSpeed = followingSpeed - activeSpeed
    catchUpTime = gap / relativeSpeed  # 0 immediately for a tie - they're already "caught up"

    # Bound this first check by when activeTrain's own next scheduled
    # stop actually frees the shared block - which is arrival if that
    # stop has >= 2 platforms (the follower can use a different one
    # without needing activeTrain to leave first), but not until
    # departure if it only has 1 (the follower can't get past at all
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

    # STEP 2 - is there currently room for the follower there? 
    platformsHere = state.platformOccupancy[controlStation.name]
    if len(platformsHere) >= controlStation.platforms and gap > 0:
        # no room for the follower to overtake here even if activeTrain
        # waited (e.g. a third train is already using the spare
        # platform) - waiting wouldn't create an opportunity, so go
        return True

    # STEP 3 - cost of going now: once the follower catches up, it
    # stops completely (this engine has no "crawling behind" - a
    # blocked train parks at the boundary until the block is free, see
    # _advanceTrain) and stays stopped until activeTrain frees the
    # block.
    blockingDelay = max(freeTime - catchUpAbsoluteTime, 0.0)

    followingSlack = _remainingTimetableSlack(followingState, state, currentTimeSeconds)
    additionalFinalDelayToFollowing = max(blockingDelay - followingSlack, 0.0)
    goCost = additionalFinalDelayToFollowing * followingTrain.priorityWeight

    # STEP 4 - cost of waiting. For a genuine follower (gap > 0), this
    # is how long activeTrain needs to hold for followingTrain to
    # reach and claim a platform at the control station. For an exact
    # tie (gap == 0, e.g. both starting together), that arrival-time
    # comparison is the wrong model entirely: if activeTrain waits,
    # followingTrain is no longer excluded by isHeld and departs almost
    # immediately, and activeTrain's own hold is released again within
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

    # STEP 5 - compare. An exact tie favours go.
    return waitCost >= goCost


# The optimal dispatcher is intentionally exhaustive rather than
# heuristic. It searches the complete binary decision tree once, then
# replays the best decision sequence on the real simulation.
#
# Two optimisations keep that exhaustive search as small as possible:
#   1. branch-and-bound: as soon as the weighted delay of trains which
#      have ALREADY finished cannot beat the best complete solution, the
#      branch is abandoned. Future trains can only add non-negative cost.
#   2. multiprocessing: a shallow frontier of independent subtrees is
#      built, then those subtrees are searched by separate processes so
#      multiple CPU cores can work at the same time.
#
# These are module-level on purpose: optimalSearch() is called by
# simulator.py as an ordinary dispatch policy, so the policy needs to
# remember both the solved order and where the real simulation currently
# is in that order.
_optimalDispatchOrder = None
_optimalDispatchIndex = 0
_optimalScenario = None

# Set only inside multiprocessing workers. The Value is shared between
# processes, so a better result found by one worker immediately becomes a
# pruning bound for the others as well.
_workerSharedBestScore = None


class _NeedMoreDispatchDecisions(Exception):
    """Internal signal used to stop a test simulation at a tree node."""
    pass


def _optimalScore(state: SimulationState) -> float:
    """Return the final weighted lateness score for a completed simulation."""
    return sum(
        trainState.train.priorityWeight * trainState.lastArrivalDelay
        for trainState in state.trainStates.values()
    )


def _finishedWeightedDelay(state: SimulationState) -> float:
    """Return the O(1) running lower bound maintained by simulator.py."""
    return state.finishedWeightedDelay


def _currentBestScore(localBestResult) -> float:
    """Return the tightest pruning bound currently known to this process."""
    bestScore = localBestResult[0]
    if _workerSharedBestScore is not None:
        bestScore = min(bestScore, _workerSharedBestScore.value)
    return bestScore


def _publishBestScore(score: float) -> None:
    """Publish a new incumbent score to the other worker processes."""
    if _workerSharedBestScore is None:
        return

    # multiprocessing.Value supplies a process-safe lock. Re-check while
    # holding it so two workers finishing at almost the same time cannot
    # overwrite a better result with a worse one.
    with _workerSharedBestScore.get_lock():
        if score < _workerSharedBestScore.value:
            _workerSharedBestScore.value = score


def _runOptimalBranch(initialState: SimulationState, decisionOrder, bestScore=float("inf")):
    """
    Replay one proposed dispatch sequence from the true starting state.

    The branch stops as soon as it encounters a policy decision which is
    not yet present in decisionOrder. This gives the DFS a new binary tree
    node to expand without duplicating any simulator movement/block/platform
    rules here.

    It also stops immediately when the weighted delay of trains which have
    already finished is >= bestScore. That partial score is a valid lower
    bound because unfinished trains can only add non-negative delay.

    Returns:
        ("complete", completedState) if the whole simulation finished,
        ("node", nextDecisionIndex) if another decision is required,
        ("pruned", None) if branch-and-bound proves it cannot improve,
        ("deadlock", None) if the simulation fails to finish.
    """
    from simulator import simulate
    from copy import deepcopy

    testState = deepcopy(initialState)
    decisionIndex = 0
    wasPruned = False

    def branchPolicy(activeTrain, followingTrain, state):
        nonlocal decisionIndex

        if decisionIndex >= len(decisionOrder):
            raise _NeedMoreDispatchDecisions

        decision = decisionOrder[decisionIndex]
        decisionIndex += 1
        return decision

    def shouldPrune(state):
        nonlocal wasPruned

        # Keep the worker's shared bound live: if another core finds a better
        # complete result while this simulation is running, this branch can use
        # the tighter bound on its very next tick.
        liveBestScore = bestScore
        if _workerSharedBestScore is not None:
            liveBestScore = min(liveBestScore, _workerSharedBestScore.value)

        if _finishedWeightedDelay(state) >= liveBestScore:
            wasPruned = True
            return True
        return False

    try:
        simulate(
            testState,
            dispatchPolicy=branchPolicy,
            verbose=False,
            abortCondition=shouldPrune,
        )
    except _NeedMoreDispatchDecisions:
        return "node", decisionIndex

    if wasPruned:
        return "pruned", None

    if not all(trainState.status == "finished" for trainState in testState.trainStates.values()):
        return "deadlock", None

    return "complete", testState


def _searchOptimal(initialState: SimulationState, decisionOrder, bestResult):
    """Depth-first exhaustive search below one decision-tree node."""
    status, result = _runOptimalBranch(
        initialState,
        decisionOrder,
        bestScore=_currentBestScore(bestResult),
    )

    if status in ("deadlock", "pruned"):
        return

    if status == "complete":
        score = _optimalScore(result)
        if score < bestResult[0]:
            bestResult[0] = score
            bestResult[1] = decisionOrder.copy()
            _publishBestScore(score)
        return

    # Both decisions are legal at this point. Search GO first, then WAIT.
    # No tree-node objects are needed: decisionOrder itself is the DFS path.
    decisionOrder.append(True)
    _searchOptimal(initialState, decisionOrder, bestResult)
    decisionOrder.pop()

    decisionOrder.append(False)
    _searchOptimal(initialState, decisionOrder, bestResult)
    decisionOrder.pop()


def _findFirstCompleteSolution(initialState: SimulationState):
    """
    Find one complete solution quickly to seed branch-and-bound.

    This is not the optimisation search itself; it simply follows the same
    go-first DFS until the first completed leaf. Having a finite score before
    parallel search starts means every worker can prune immediately.
    """
    decisionOrder = []

    def find():
        status, result = _runOptimalBranch(initialState, decisionOrder)

        if status == "complete":
            return _optimalScore(result), decisionOrder.copy()
        if status in ("deadlock", "pruned"):
            return None

        decisionOrder.append(True)
        found = find()
        decisionOrder.pop()
        if found is not None:
            return found

        decisionOrder.append(False)
        found = find()
        decisionOrder.pop()
        return found

    return find()


def _buildParallelFrontier(initialState: SimulationState, targetSubtrees: int, bestScore: float):
    """
    Build a shallow set of real decision-tree nodes to distribute to workers.

    Expanding actual nodes rather than blindly generating bit strings avoids
    creating meaningless prefixes when a scenario finishes after fewer
    decisions than the requested split depth.
    """
    frontier = [[]]

    while len(frontier) < targetSubtrees:
        expandedAnything = False
        nextFrontier = []

        for prefix in frontier:
            status, _ = _runOptimalBranch(initialState, prefix, bestScore=bestScore)

            if status == "node":
                nextFrontier.append(prefix + [True])
                nextFrontier.append(prefix + [False])
                expandedAnything = True
            elif status == "complete":
                # The initial solution already gives us a complete incumbent.
                # A complete prefix at this stage has no subtree left to search.
                continue
            # deadlocked/pruned prefixes are discarded.

        if not expandedAnything:
            break

        frontier = nextFrontier
        if not frontier:
            break

    return frontier


def _initialiseOptimalWorker(sharedBestScore):
    """ProcessPool initializer: attach this worker to the shared incumbent."""
    global _workerSharedBestScore
    _workerSharedBestScore = sharedBestScore


def _searchOptimalSubtree(initialState: SimulationState, prefix, initialBestScore: float):
    """Worker entry point: search one independent subtree."""
    bestResult = [initialBestScore, None]
    _searchOptimal(initialState, prefix.copy(), bestResult)
    return bestResult[0], bestResult[1]


def _searchOptimalParallel(initialState: SimulationState):
    """Search the exhaustive decision tree across all available CPU cores."""
    import os
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor, as_completed

    firstSolution = _findFirstCompleteSolution(initialState)
    if firstSolution is None:
        return [float("inf"), None]

    initialBestScore, initialBestOrder = firstSolution
    bestResult = [initialBestScore, initialBestOrder]

    cpuCount = max(1, os.cpu_count() or 1)

    # Process startup/pickling costs more than it saves on tiny search trees.
    # The first complete path gives a cheap estimate of tree depth, so keep
    # small scenarios serial and reserve multiprocessing for genuinely larger
    # searches. The exhaustive algorithm and result are unchanged either way.
    minimumParallelDepth = 8
    if cpuCount == 1 or len(initialBestOrder) < minimumParallelDepth:
        _searchOptimal(initialState, [], bestResult)
        return bestResult

    targetSubtrees = max(2, cpuCount * 2)
    frontier = _buildParallelFrontier(initialState, targetSubtrees, initialBestScore)

    if len(frontier) <= 1:
        _searchOptimal(initialState, [], bestResult)
        return bestResult

    workerCount = min(cpuCount, len(frontier))

    # Use the platform's default multiprocessing context. On Windows this is
    # spawn; on Linux it is normally fork. multiprocessing.Value is shared
    # memory, so workers can cheaply see a better score found by another core.
    context = multiprocessing.get_context()
    sharedBestScore = context.Value("d", initialBestScore, lock=True)

    with ProcessPoolExecutor(
        max_workers=workerCount,
        mp_context=context,
        initializer=_initialiseOptimalWorker,
        initargs=(sharedBestScore,),
    ) as executor:
        futures = [
            executor.submit(_searchOptimalSubtree, initialState, prefix, initialBestScore)
            for prefix in frontier
        ]

        for future in as_completed(futures):
            score, order = future.result()
            if order is not None and score < bestResult[0]:
                bestResult[0] = score
                bestResult[1] = order

    return bestResult


def optimalSearch(activeTrain: Train, followingTrain: Optional[Train], state: SimulationState) -> bool:
    """
    Exhaustively search all legal dispatch/wait decisions once for the
    current scenario, then replay the lowest-score decision order.

    The search uses branch-and-bound pruning plus multiprocessing, but the
    result is still exhaustive: a branch is pruned only when its already-fixed
    cost is at least the best complete score, so it cannot contain a better
    solution.
    """
    global _optimalDispatchOrder, _optimalDispatchIndex, _optimalScenario

    if _optimalScenario is not state.scenario:
        _optimalScenario = state.scenario
        _optimalDispatchOrder = None
        _optimalDispatchIndex = 0

    if _optimalDispatchOrder is None:
        from scenario_input import createSimulationState

        initialState = createSimulationState(state.scenario)
        bestResult = _searchOptimalParallel(initialState)

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
    "optimal": optimalSearch,
}
