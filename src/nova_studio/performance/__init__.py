"""Character performance core (Phase 2).

Pure rules with no UI, network or hardware dependency:

* ``characters`` — Character Studio identity rules (approve, lock, version
  history, production readiness).
* ``engines`` — what a generation engine declares it can actually do.
* ``planner`` — plans each shot against those declarations and reports every
  blocker instead of pretending the work can be done.
"""
