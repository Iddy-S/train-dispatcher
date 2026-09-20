# Train Dispatcher

A Python simulation of a railway dispatching problem, where the objective is to decide when trains should be dispatched immediately and when they should be held to allow other services to pass.

The simulation compares three different dispatching strategies: a manual dispatcher, a fast greedy heuristic, and an exhaustive optimal solver.

## Usage

Run `main.py` to start the program.

The program allows you to:

* choose from preset railway scenarios
* create a custom scenario
* choose between the manual, greedy and optimal dispatchers
* observe the trains as they travel through the network
* compare the resulting weighted delay scores

All required Python files should be kept in the same directory.

## What the simulation models

The simulation represents a railway line consisting of stations, platforms, signals and track sections. Each train has a maximum speed, a timetable and a priority weight.

The objective of the dispatchers is to minimise the **total weighted final delay** of all trains. This means that delays to higher-priority trains have a greater effect on the final score.

The simulation uses several simplifications compared with a real railway:

* Trains accelerate and brake instantly, so they are either stationary or travelling at their maximum speed.
* Strict absolute-block signalling is used, with a maximum of one train in each block.
* Trains are treated as infinitely thin, so each train occupies only one block at a time.
* Traffic travels in one direction and there are no junctions or branching routes between stations.
* Points at stations change instantly.
* There are no speed limits; trains travel at their maximum speed whenever they are moving.
* There is only one track between stations, so overtaking can only take place at stations with multiple platforms.
* All trains start at the first station and finish at the last station.
* Dwell time at stations is very short, but a train cannot depart before its scheduled departure time.

These assumptions make it possible to focus on the dispatching problem rather than the many additional constraints of a real railway.

## The dispatchers

### 1. Manual dispatcher

The manual dispatcher allows the user to make each dispatch decision. At each opportunity, the program asks whether a train should depart immediately or wait for another train.

Soft-lock prevention is included so that the user's decisions cannot leave a train permanently unable to reach the end of the line.

### 2. Greedy dispatcher

The greedy dispatcher is an automatic heuristic designed to make decisions quickly.

It first checks whether the following train could realistically catch the active train before it reaches a suitable passing point. If there is a potential conflict, it estimates the weighted delay caused by allowing the active train to depart compared with holding it.

The algorithm runs in constant time for each dispatch decision, O(1), because it only considers the current trains and relevant parts of the timetable rather than searching through future dispatch sequences.

As a heuristic, it does not guarantee an optimal solution, but it can make decisions very quickly.

### 3. Optimal dispatcher

The optimal dispatcher exhaustively searches through the possible dispatch decisions using a depth-first search.

Each dispatch decision creates two possible branches:

* dispatch the train immediately
* hold the train

The search continues until all trains have completed their journeys. The weighted final delay is then calculated for each completed possibility, and the dispatch sequence with the lowest score is selected.

This guarantees an optimal solution for the simulated scenario, provided the exhaustive search is allowed to complete.

Because the number of possible decision sequences grows exponentially, this dispatcher is intended for small scenarios. Larger scenarios can become computationally expensive.

## Limitations

This project is a simplified model rather than a realistic railway simulator. In particular, it does not model realistic acceleration, braking distances, speed restrictions, signalling systems such as ETCS, junction conflicts, passenger behaviour or detailed platform operations.

The optimal dispatcher is also computationally limited by the exponential growth of the search space.
