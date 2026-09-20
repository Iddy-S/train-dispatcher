"""
simulator.py

The core, second-by-second simulation loop. Tracks where every train
physically is, moves them forward in time, and enforces the two hard
physical rules that must NEVER be broken regardless of dispatch
strategy:
  1. A train can never enter a block that's already occupied (no SPAD).
  2. A train can never leave a station before its scheduled departure
     time for that stop.

Whenever a train can depart (its time has come, and the next block
is free) but there's a genuine choice about whether it's tactically
worth waiting, that choice is delegated to a "dispatch policy"
function - see dispatch_policies.py. manualPolicy there just asks you
directly; swap it for greedyPolicy once that's written, by passing it
as simulate()'s dispatchPolicy argument.

Modelling Simplifications:
- Each Section splits into (numSignals + 1) equal-length blocks.
- Trains are treated as point-sized - a train occupies exactly one
  block at a time, never overlaps two.
- maxSpeed is stored in distance units PER SECOND (converted at input
  time from the per-hour value the user enters).
- Train.timetable stores SECONDS (converted at input time in
  scenario_input.py) - so no further conversion is needed here.
- All trains still start at the first station (v1 simplification from
  earlier in the project).
- Two trains are considered "tied" (genuinely ambiguous who's really
  last) whenever they're at the exact same cumulative distance - this
  covers both trains literally sharing a station AND a train blocked
  right at a station's entrance while another is already inside it
  (same distance, by construction). Any tie always asks the dispatch
  policy, rather than trying to auto-rank tied trains - see
  _othersAtSamePosition.
- A station with exactly one platform always auto-dispatches: a
  follower can never overtake there anyway (no second platform to wait
  in), so holding is never beneficial and there's no real decision.
- A train passing through a station (no scheduled stop there) still
  occupies a platform and goes through the SAME departure decision as
  a stopping train, one tick later - there might be another train
  waiting there that should go first. The 1-tick delay this adds is a
  deliberate, accepted trade-off.
- Once the dispatcher says "wait" for a train, it is marked isHeld and
  will NOT be asked again by _attemptDeparture while isHeld is set -
  it's skipped unconditionally, no matter what else changes. isHeld is
  only ever cleared by _refreshHeldTrains, called once per tick AFTER
  all movement has happened, via two checks (see that function's
  docstring for the full reasoning):
    1. Definitive - has this train become the genuine last live train
       (nothing live behind it anywhere, per _findFollowingTrain /
       _othersAtSamePosition, which already exclude held AND finished
       trains)? If so it's un-held immediately, regardless of anything
       else. This is what catches a follower simply finishing its
       journey - movement-tracking alone can never see that, since a
       finished train stops being tracked via block/station occupancy
       entirely, so nothing "moves into" a trackable position to
       trigger a movement-based check.
    2. Heuristic (fallback) - has the occupant of the position two
       steps behind this station changed since it was held (stations
       count as a step, same as a block - see _snapshotTwoBack)? If
       there's no valid "two back" position at all (the train is held
       at the very start of the line), there's nothing to compare
       against, so it stays held via this check specifically - though
       check 1 above can still clear it regardless.
  This is deliberately eager (run for every held train every tick)
  rather than lazy (checked inside _attemptDeparture itself), since
  _attemptDeparture can return early for unrelated reasons (its own
  next block still occupied) without ever reaching a check placed
  there - checking separately, unconditionally, avoids that gap.
- Held trains are excluded from _findFollowingTrain and
  _othersAtSamePosition entirely: a train that's already been told to
  wait isn't a live competitor for anyone else's "am I last" check, so
  it can neither force another train to ask unnecessarily nor block it
  from auto-dispatching. Combined with the DEFINITIVE check above, this
  resolves the softlock risk that used to exist here: previously, if
  two tied trains were BOTH told to wait, neither could ever be
  reconsidered, and the simulation would just stall. Now, whichever of
  them is evaluated first sees zero LIVE competitors (the other, still
  held, is excluded) and un-holds/auto-dispatches - and once THAT one
  actually finishes or moves away, the DEFINITIVE check un-sticks the
  other one too, even if it's sitting at the very first station with
  no movement-based reference point at all.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from entities import Scenario, Train, Section

BlockId = Tuple[int, int]  # (sectionIndex, blockIndexWithinSection)


def numBlocksInSection(section: Section) -> int:
    return section.numSignals + 1


def blockLength(section: Section) -> float:
    return section.distance / numBlocksInSection(section)


@dataclass
class TrainState:
    """Everything about a single train that changes as the simulation
    runs."""
    train: Train
    status: str = "at_station"                   # "at_station" | "in_transit" | "finished"
    currentStationIndex: Optional[int] = 0       # valid when status == "at_station"
    currentSectionIndex: Optional[int] = None    # valid when status == "in_transit"
    currentBlockIndex: Optional[int] = None      # valid when status == "in_transit"
    distanceIntoBlock: float = 0.0
    lastArrivalDelay: float = 0.0                # seconds late at the most recent stop reached (for logging)
    isHeld: bool = False                         # True if the dispatcher was last asked and said "wait"
    heldSnapshot: object = None                  # occupant 2 positions behind, at the moment we were told to wait


@dataclass
class SimulationState:
    """A full snapshot of the world at one point in time."""
    scenario: Scenario
    trainStates: Dict[str, TrainState] = field(default_factory=dict)       # headcode -> TrainState
    blockOccupancy: Dict[BlockId, str] = field(default_factory=dict)       # blockId -> headcode occupying it
    platformOccupancy: Dict[str, List[str]] = field(default_factory=dict)  # station name -> headcodes there
    currentTimeSeconds: float = 0.0  # kept in sync by simulate() every tick - lets a dispatch policy see "now" without it being threaded through as an explicit argument everywhere
    finishedWeightedDelay: float = 0.0  # running objective contribution from trains whose journeys are already complete; used by optimal branch-and-bound


def _printBoard(state: SimulationState, verbose: bool) -> None:
    """Print the current board via display.showSimulationState(). Local
    import to avoid a circular import (display.py imports from this
    file) - see the module docstring for why this is safe."""
    if not verbose:
        return
    from display import showSimulationState
    for line in showSimulationState(state):
        print(line)
    print()


def _scheduledSeconds(train: Train, stationName: str) -> Optional[float]:
    """train.timetable stores seconds directly (converted at input
    time). Returns None if this train has no scheduled stop at this
    station at all (e.g. it just passes through) - callers should
    treat None as "no schedule constraint here", not as an error."""
    return train.timetable.get(stationName)


def _currentLateness(trainState: TrainState, state: SimulationState, currentTimeSeconds: int) -> float:
    """How many seconds overdue this train currently is for departing
    wherever it's sitting right now. 0 if it's not at a station, or
    isn't yet due to leave, or has no schedule here at all."""
    if trainState.status != "at_station":
        return 0.0
    station = state.scenario.line.stations[trainState.currentStationIndex]
    scheduledTime = _scheduledSeconds(trainState.train, station.name)
    if scheduledTime is None:
        return 0.0
    return max(0.0, currentTimeSeconds - scheduledTime)


def _urgencyScore(trainState: TrainState, state: SimulationState, currentTimeSeconds: int) -> float:
    """weight * max(lateness, 0.1). NOT currently used anywhere - kept
    as a simple, general "how urgent is this train right now" measure
    in case a future policy wants one. greedyPolicy ended up using
    _remainingTimetableSlack instead, which properly accounts for each
    train's own remaining schedule rather than just its current
    lateness at this one stop."""
    lateness = _currentLateness(trainState, state, currentTimeSeconds)
    return trainState.train.priorityWeight * max(lateness, 0.1)


def _nextPassingStationIndex(
    scenario: Scenario,
    currentStationIndex: int,
    inclusive: bool = False,
) -> int:
    """
    Return the next station at which an overtake could be accommodated.

    A passing station is any station with at least two platforms. When
    ``inclusive`` is true, the current station itself is considered; this
    is useful when the active train and its follower are genuinely
    separated and the current station is already a valid passing point.
    If there is no later multi-platform station, return the final station.
    """
    startIndex = currentStationIndex if inclusive else currentStationIndex + 1

    for stationIndex in range(startIndex, len(scenario.line.stations)):
        if scenario.line.stations[stationIndex].platforms >= 2:
            return stationIndex

    return len(scenario.line.stations) - 1


def _stationPosition(stationIndex: int, scenario: Scenario) -> float:
    """Distance from the very first station to a given station index."""
    return sum(s.distance for s in scenario.line.sections[:stationIndex])


def _cumulativeDistance(trainState: TrainState, scenario: Scenario) -> float:
    """How far along the whole line (measured from the first station)
    this train currently is - used to work out who is ahead/behind."""
    if trainState.status == "finished":
        return sum(s.distance for s in scenario.line.sections)

    if trainState.status == "at_station":
        return _stationPosition(trainState.currentStationIndex, scenario)

    distanceBeforeThisSection = _stationPosition(trainState.currentSectionIndex, scenario)
    section = scenario.line.sections[trainState.currentSectionIndex]
    distanceIntoSection = trainState.currentBlockIndex * blockLength(section) + trainState.distanceIntoBlock
    return distanceBeforeThisSection + distanceIntoSection


def _earliestArrivalAtStation(trainState: TrainState, targetStationIndex: int, fromTimeSeconds: float, scenario: Scenario) -> float:
    """
    Estimate the earliest time this train could physically reach
    targetStationIndex, starting from its current physical position,
    counting from fromTimeSeconds (normally just the current
    simulation time). Properly accounts for the train's OWN scheduled
    stops in between - it can't depart one before its scheduled time,
    even if it arrives early - so this isn't just distance/speed.

    Assumes clear track from here on - it does not model this train
    getting blocked by some third, unrelated train along the way, and
    ignores the ~1-tick platform-occupancy delay a genuine pass-through
    station adds in the real simulation. Both are judged not to matter
    at the timescales involved here.

    Precondition: targetStationIndex must be at or ahead of wherever
    this train currently is - this function only looks forward.
    """
    train = trainState.train
    sections = scenario.line.sections
    stations = scenario.line.stations

    if trainState.status == "in_transit":
        section = sections[trainState.currentSectionIndex]
        numRemainingFullBlocks = numBlocksInSection(section) - trainState.currentBlockIndex - 1
        remainingInSection = (blockLength(section) - trainState.distanceIntoBlock) + numRemainingFullBlocks * blockLength(section)
        currentTime = fromTimeSeconds + remainingInSection / train.maxSpeed
        currentStationIndex = trainState.currentSectionIndex + 1  # the station this leg is heading toward
    else:
        # "at_station" - callers shouldn't ask this for a "finished" train
        currentTime = fromTimeSeconds
        currentStationIndex = trainState.currentStationIndex

    # currentTime is now the earliest moment this train physically
    # reaches currentStationIndex. From here: if this isn't the
    # target, clamp for a scheduled stop HERE (this also correctly
    # covers the very first station reached from an in-transit start,
    # not just ones reached later), then travel to the next station -
    # repeat until the target is reached. We deliberately never clamp
    # AT the target itself - we care about arrival there, not departure.
    while currentStationIndex < targetStationIndex:
        scheduledTime = _scheduledSeconds(train, stations[currentStationIndex].name)
        if scheduledTime is not None:
            currentTime = max(currentTime, scheduledTime)
        section = sections[currentStationIndex]  # the section leaving this station
        currentTime += section.distance / train.maxSpeed
        currentStationIndex += 1

    return currentTime


def _nextScheduledStopIndex(trainState: TrainState, scenario: Scenario) -> int:
    """
    The next station index (strictly after this train's current
    position) that IS one of its scheduled stops. Used to approximate
    "where would this train next stop and free up a block" - see
    greedyPolicy. Falls back to the line's final station if nothing
    is found first, though in practice the final station is always a
    scheduled stop for every train, so the loop will always find it.
    """
    train = trainState.train
    stations = scenario.line.stations
    finalIndex = len(stations) - 1

    startIndex = trainState.currentSectionIndex + 1 if trainState.status == "in_transit" else trainState.currentStationIndex + 1

    for stationIndex in range(startIndex, finalIndex + 1):
        if _scheduledSeconds(train, stations[stationIndex].name) is not None:
            return stationIndex
    return finalIndex


def _remainingTimetableSlack(trainState: TrainState, state: SimulationState, currentTimeSeconds: float) -> float:
    """
    How much extra delay this train's FINAL arrival could still absorb
    before it actually counts as late - scheduled final arrival minus
    the earliest it could possibly still get there. 0 if it's already
    cutting it as fine as possible (or is already going to be late
    regardless).
    """
    scenario = state.scenario
    finalIndex = len(scenario.line.stations) - 1
    finalStationName = scenario.line.stations[finalIndex].name

    earliestFinalArrival = _earliestArrivalAtStation(trainState, finalIndex, currentTimeSeconds, scenario)
    scheduledFinalArrival = _scheduledSeconds(trainState.train, finalStationName)  # always set - the final station is always a required stop
    return max(scheduledFinalArrival - earliestFinalArrival, 0.0)


def _findFollowingTrain(headcode: str, state: SimulationState) -> Optional[Train]:
    """
    The nearest other unfinished, not-held train with a strictly
    smaller real distance than this one - i.e. a genuine, unambiguous,
    live physical follower. Deliberately returns None when other
    trains are tied at the exact same distance (raw distance can't
    meaningfully rank trains that are literally in the same place -
    that case is handled separately by _othersAtSamePosition, which
    forces asking rather than guessing).

    Held trains are excluded entirely: a held train has already been
    told to wait and isn't going anywhere for now, so it shouldn't
    count as a live competitor for "am I the last train". Counting
    held trains here was causing a potential softlock - two trains
    could each be waiting on the other's held status forever, with
    neither ever getting a chance to auto-dispatch.
    """
    myDistance = _cumulativeDistance(state.trainStates[headcode], state.scenario)

    best = None
    bestDistance = None
    for otherHeadcode, otherState in state.trainStates.items():
        if otherHeadcode == headcode or otherState.status == "finished" or otherState.isHeld:
            continue
        otherDistance = _cumulativeDistance(otherState, state.scenario)
        if otherDistance < myDistance and (best is None or otherDistance > bestDistance):
            best = otherState.train
            bestDistance = otherDistance
    return best


def _walkBackward(stationIndex: int, scenario: Scenario):
    """
    Yields positions walking backward from (but not including) the
    given station, through the combined sequence of blocks AND
    stations (a station counts as one step, same as a block). Each
    yielded position is ('block', sectionIndex, blockIndex) or
    ('station', stationIndex).
    """
    idx = stationIndex
    while idx > 0:
        section = scenario.line.sections[idx - 1]
        for b in reversed(range(numBlocksInSection(section))):
            yield ("block", idx - 1, b)
        idx -= 1
        yield ("station", idx)


_NO_REFERENCE_POSITION = object()  # sentinel: there IS no position two steps back (too close to line start) - distinct from a real position that's simply empty (which is None)


def _occupantOf(position, state: SimulationState):
    """Whatever headcode(s) currently occupy a position from
    _walkBackward - a single headcode (or None if that block is
    genuinely empty) for a block, or a sorted tuple of headcodes for a
    station (which can hold several, and is () if empty)."""
    if position[0] == "block":
        _, sectionIdx, blockIdx = position
        return state.blockOccupancy.get((sectionIdx, blockIdx))
    else:
        _, stationIdx = position
        stationName = state.scenario.line.stations[stationIdx].name
        return tuple(sorted(state.platformOccupancy.get(stationName, [])))


def _snapshotTwoBack(stationIndex: int, state: SimulationState):
    """
    A comparable snapshot of whoever occupies the position exactly two
    steps behind this station (stations count as steps too - see
    _walkBackward). Returns _NO_REFERENCE_POSITION if we're too close
    to the start of the line for "two steps back" to exist at all -
    deliberately NOT None, since None is also the legitimate value for
    "that position exists but is currently empty", and the two must be
    told apart (an empty-but-real position should still count as
    "unchanged" if it stays empty; a nonexistent position never should).
    """
    positions = list(_walkBackward(stationIndex, state.scenario))
    if len(positions) < 2:
        return _NO_REFERENCE_POSITION
    return _occupantOf(positions[1], state)


def _refreshHeldTrains(state: SimulationState) -> None:
    """
    Called once per tick, after all movement for that tick has already
    happened. For every currently-held train, two separate checks can
    clear isHeld:

    1. Definitve: has this train become the genuine last live train -
       i.e. do _findFollowingTrain and _othersAtSamePosition (which
       already exclude held and finished trains) now agree that
       NOTHING live is behind it anywhere? If so, there's no decision
       left to make at all, and isHeld is cleared regardless of
       anything else. This is what catches a follower simply FINISHING
       its journey - that's not something the movement-based check
       below can ever detect, since a finished train isn't tracked via
       block/station occupancy any more, so nothing "moves into" a
       trackable position to trigger it. Missing this case was a real
       bug: a train held at the very first station (see point 2) could
       stay stuck forever even after every other train had completed
       its journey and left the line entirely.

    2. Heuristic: (only checked if 1 didn't already clear it): has
       whatever occupies the position two steps behind this train's
       station (stations count as a step, same as a block - see
       _snapshotTwoBack) changed since it was held? If there's no valid
       "two back" position at all (the train is held at the very first
       station, where most trains begin), there's nothing to compare
       against, so it stays held via this check specifically - it does
       NOT get cleared every tick just because there's no reference.

    Doing this here - eagerly, driven by movement - rather than lazily
    inside _attemptDeparture matters: _attemptDeparture can return
    early for unrelated reasons (e.g. its own next block is still
    occupied) without ever reaching a check placed there, which could
    leave isHeld stuck stale. Checking every held train here instead,
    unconditionally, once per tick, avoids that.
    """
    for trainState in state.trainStates.values():
        if not trainState.isHeld or trainState.status != "at_station":
            continue

        headcode = trainState.train.headcode

        if _findFollowingTrain(headcode, state) is None and not _othersAtSamePosition(headcode, state):
            # nothing live is behind this train anywhere - it's
            # unambiguously the last train now, regardless of what the
            # movement heuristic below would otherwise conclude.
            trainState.isHeld = False
            trainState.heldSnapshot = None
            continue

        snapshot = _snapshotTwoBack(trainState.currentStationIndex, state)
        if snapshot is _NO_REFERENCE_POSITION:
            continue  # nothing to compare against - stays held, not cleared
        if snapshot != trainState.heldSnapshot:
            trainState.isHeld = False
            trainState.heldSnapshot = None


def _othersAtSamePosition(headcode: str, state: SimulationState) -> List[Train]:
    """
    Every other unfinished, not-held train currently at the exact same
    cumulative distance as this one - whether it's literally sitting at
    the same station, or stuck at a block boundary right at that
    station's entrance (which, by construction, is the same distance
    as being just inside it - a train blocked right outside a station
    and one already on its platform are physically just as ambiguous
    as two trains sharing a platform). If this is non-empty, we can NOT
    safely say "nothing is behind me" even though _findFollowingTrain
    found no strictly-smaller follower - so the caller should always
    ask.

    Held trains are excluded for the same reason as in
    _findFollowingTrain: one has already been told to wait and isn't a
    live competitor, so it shouldn't force an ask (or block an
    auto-dispatch) for anyone else - see that function's docstring for
    the softlock this prevents.
    """
    myDistance = _cumulativeDistance(state.trainStates[headcode], state.scenario)

    others = []
    for otherHeadcode, otherState in state.trainStates.items():
        if otherHeadcode == headcode or otherState.status == "finished" or otherState.isHeld:
            continue
        if _cumulativeDistance(otherState, state.scenario) == myDistance:
            others.append(otherState.train)
    return others


def _attemptDeparture(headcode: str, state: SimulationState, currentTimeSeconds: int, dispatchPolicy, verbose: bool) -> None:
    trainState = state.trainStates[headcode]
    train = trainState.train
    stationIndex = trainState.currentStationIndex
    station = state.scenario.line.stations[stationIndex]

    scheduledTime = _scheduledSeconds(train, station.name)
    if scheduledTime is not None and currentTimeSeconds < scheduledTime:
        return  # not yet due to depart - hard rule, not a choice
    # if scheduledTime is None, this train has no scheduled stop here at
    # all (it's just passing through) - no time-based constraint, it's
    # immediately eligible to be considered for departure

    if stationIndex == len(state.scenario.line.stations) - 1:
        return  # already at the final station - should already be "finished", not here

    nextBlockId = (stationIndex, 0)  # first block of the section leaving this station
    if state.blockOccupancy.get(nextBlockId) is not None:
        return  # next block occupied - must wait, no decision to make (no SPAD)

    if trainState.isHeld:
        # denied dispatch previously - do NOT ask again here. The only
        # way this clears is _refreshHeldTrains (called once per tick,
        # after all movement has happened) detecting that something
        # relevant has actually moved - see that function.
        return

    if verbose:
        print(f"t={currentTimeSeconds}s: {headcode} is ready to leave {station.name}.")

    if station.platforms == 1:
        # only one platform here means a follower could never overtake
        # by waiting anyway (there's no second platform for it to sit
        # in while this train dwells) - holding is never beneficial,
        # so there's no real decision to make, regardless of who else
        # is around.
        shouldGo = True
        if verbose:
            print(f"  ({station.name} has only one platform - no overtaking possible here, departing automatically)")
    else:
        followingTrain = _findFollowingTrain(headcode, state)
        othersHere = _othersAtSamePosition(headcode, state)

        if followingTrain is None and not othersHere:
            # nobody is behind this train anywhere on the line, so it
            # can never block anyone by going - no possible conflict.
            shouldGo = True
            if verbose:
                print(f"  (no train behind {headcode} - departing automatically)")
        else:
            if followingTrain is None:
                # tied with at least one other train at this exact
                # station - genuinely ambiguous who's "last", so always
                # ask rather than guess. Just need someone to name/pass
                # to the policy; which one of the tied trains doesn't
                # matter here.
                followingTrain = othersHere[0]
            shouldGo = dispatchPolicy(train, followingTrain, state)

    if shouldGo:
        trainState.isHeld = False
        trainState.heldSnapshot = None
        state.platformOccupancy[station.name].remove(headcode)
        state.blockOccupancy[nextBlockId] = headcode
        trainState.status = "in_transit"
        trainState.currentSectionIndex = stationIndex
        trainState.currentBlockIndex = 0
        trainState.distanceIntoBlock = 0.0
        if verbose:
            print(f"t={currentTimeSeconds}s: {headcode} departs {station.name}")
        _printBoard(state, verbose)
    else:
        trainState.isHeld = True
        trainState.heldSnapshot = _snapshotTwoBack(stationIndex, state)


def _advanceTrain(headcode: str, state: SimulationState, currentTimeSeconds: int, verbose: bool) -> None:
    trainState = state.trainStates[headcode]
    train = trainState.train
    if trainState.status != "in_transit":
        return

    remainingThisTick = train.maxSpeed  # distance covered in this 1-second tick

    while remainingThisTick > 0 and trainState.status == "in_transit":
        section = state.scenario.line.sections[trainState.currentSectionIndex]
        thisBlockLength = blockLength(section)
        spaceLeftInBlock = thisBlockLength - trainState.distanceIntoBlock

        if remainingThisTick < spaceLeftInBlock:
            trainState.distanceIntoBlock += remainingThisTick
            remainingThisTick = 0
            break

        numBlocks = numBlocksInSection(section)
        isLastBlockOfSection = trainState.currentBlockIndex == numBlocks - 1

        if not isLastBlockOfSection:
            nextBlockId = (trainState.currentSectionIndex, trainState.currentBlockIndex + 1)
            if state.blockOccupancy.get(nextBlockId) is not None:
                trainState.distanceIntoBlock = thisBlockLength  # park at the end, blocked - no SPAD
                break
            oldBlockId = (trainState.currentSectionIndex, trainState.currentBlockIndex)
            state.blockOccupancy[oldBlockId] = None
            state.blockOccupancy[nextBlockId] = headcode
            trainState.currentBlockIndex += 1
            trainState.distanceIntoBlock = 0.0
            remainingThisTick -= spaceLeftInBlock
            if verbose:
                print(f"t={currentTimeSeconds}s: {headcode} passes a signal, entering block {nextBlockId}")
            _printBoard(state, verbose)
            continue

        # last block of the section - arriving at the next station
        nextStationIndex = trainState.currentSectionIndex + 1
        nextStation = state.scenario.line.stations[nextStationIndex]
        isFinalStation = nextStationIndex == len(state.scenario.line.stations) - 1

        # every train entering a station occupies a platform, whether or
        # not it's a scheduled stop for it - this means a passing-through
        # train still gets a proper departure decision one tick later
        # (see _attemptDeparture), rather than sailing through unasked.
        platformsHere = state.platformOccupancy[nextStation.name]
        if len(platformsHere) >= nextStation.platforms:
            trainState.distanceIntoBlock = thisBlockLength  # park at the end, blocked - no room here
            break

        oldBlockId = (trainState.currentSectionIndex, trainState.currentBlockIndex)
        state.blockOccupancy[oldBlockId] = None
        platformsHere.append(headcode)

        scheduledTime = _scheduledSeconds(train, nextStation.name)
        if scheduledTime is not None:
            trainState.lastArrivalDelay = max(0.0, currentTimeSeconds - scheduledTime)
            if verbose:
                lateMsg = f", {trainState.lastArrivalDelay:.0f}s late" if trainState.lastArrivalDelay > 0 else " on time"
                print(f"t={currentTimeSeconds}s: {headcode} arrives at {nextStation.name}{lateMsg}")
        else:
            trainState.lastArrivalDelay = 0.0
            if verbose:
                print(f"t={currentTimeSeconds}s: {headcode} reaches {nextStation.name} (not a scheduled stop)")

        if isFinalStation:
            trainState.status = "finished"
            # This value is now permanent: the train has reached the final
            # station, so its contribution to the objective cannot change.
            # Keeping the running total here makes optimal-search pruning O(1).
            state.finishedWeightedDelay += train.priorityWeight * trainState.lastArrivalDelay
        else:
            trainState.status = "at_station"

        trainState.currentStationIndex = nextStationIndex
        trainState.currentSectionIndex = None
        trainState.currentBlockIndex = None
        trainState.distanceIntoBlock = 0.0
        remainingThisTick = 0  # a station always ends this tick's movement, whether stopping or not
        _printBoard(state, verbose)


def simulate(
    simulationState: SimulationState,
    dispatchPolicy=None,
    maxSeconds: int = 100_000,
    verbose: bool = True,
    abortCondition=None,
) -> SimulationState:
    """
    Run the simulation one second at a time, mutating and returning the
    SimulationState you pass in, until every train has finished or
    maxSeconds is reached (a safety net in case two trains end up
    deadlocked, blocking each other forever).

    abortCondition is an optional internal optimisation hook. If supplied,
    it is called after each tick and the simulation stops early when it
    returns True. Normal dispatchers leave it as None. The optimal search
    uses it for branch-and-bound pruning.

    dispatchPolicy defaults to dispatch_policies.manualPolicy, imported
    lazily here (see the module docstring for why it can't be a normal
    top-of-file import).
    """
    if dispatchPolicy is None:
        from dispatch_policies import manualPolicy
        dispatchPolicy = manualPolicy

    state = simulationState
    scenario = state.scenario
    currentTimeSeconds = 0

    while currentTimeSeconds <= maxSeconds:
        if all(ts.status == "finished" for ts in state.trainStates.values()):
            break

        state.currentTimeSeconds = currentTimeSeconds

        for train in scenario.trains:
            if state.trainStates[train.headcode].status == "at_station":
                _attemptDeparture(train.headcode, state, currentTimeSeconds, dispatchPolicy, verbose)

        for train in scenario.trains:
            _advanceTrain(train.headcode, state, currentTimeSeconds, verbose)

        _refreshHeldTrains(state)

        if abortCondition is not None and abortCondition(state):
            break

        currentTimeSeconds += 1
    else:
        if verbose:
            print(f"Simulation stopped after {maxSeconds}s without every train finishing - check for a deadlock.")

    allFinished = all(trainState.status == "finished" for trainState in state.trainStates.values())
    if allFinished and verbose:
        finalScore = sum(
            trainState.train.priorityWeight * trainState.lastArrivalDelay
            for trainState in state.trainStates.values()
        )
        print(f"Final weighted delay score: {finalScore:.1f}")

    return state
