# Management Simulator

The simulator is an authenticated option inside Simulacrum. It is not a
leadership quiz. The manager sees reports, 1:1s, delivery signals, and later
consequences. Hidden persona state is never shown directly.

## Current Slice

The current module implements a twenty-session curriculum loop:

- start with five simulated employees and a too-large mission
- choose what product evidence to track
- generate simulated-week reports from hidden persona state
- conduct guarded 1:1 conversations
- interview candidates with constrained behavioral probes rather than a clean
  self-report scorecard
- spend finite daily attention on 1:1s or artifact investigation rather than
  seeing every signal for free
- inspect noisy artifact packets from planning, Slack, code review, stakeholder,
  and calendar channels
- watch work move through scoped, in-progress, review, rework, done, and
  maintenance states, including handoff debt when an owner leaves
- write an end-of-day notebook: observations, hypotheses, questions, decision,
  prediction, and what would change the manager's mind
- advance the world asynchronously and let consequences surface
- make a hire in week 1, terminate two roles in week 2, optionally use one
  backfill slot, then operate through changing goals and incidents
- survive a roadmap pivot and an unexpected dependency-holder leave event that
  test whether the manager built redundancy rather than just short-term output
- request a hypervisor report with -5..+5 alignment by person trait, team
  dynamic, product complication, and crisis outcome

## Architecture

`fly/management_sim/` is split into:

- `persona_store.py` loads 30 tracked persona files
- `latent_state.py` applies deterministic action effects and seeded world ticks
- `observations.py` converts hidden state into concrete, indirect clues
- `relationships.py` maintains hidden pairwise trust, friction, dependency,
  knowledge flow, and generates multi-channel artifact packets
- `work.py` models closure, detail, tracking, decision force, work-state
  transitions, and handoff debt
- `interviews.py` generates noisy candidate interview signals from constrained
  prompts without exposing hidden persona state
- `guard.py` blocks prompt injection/state probing and audits output leakage
- `artifacts.py` generates reports and persona dialogue
- `persistence.py` stores runs, snapshots, artifacts, turns, and event logs
- `service.py` orchestrates the curriculum, notebook, milestones, and world tick
- `assessor.py` emits evidence-backed alignment reports using prediction
  resolution, calibration, and sustainability rather than action labels alone
- `router.py` mounts authenticated `/api/management-sim/*` endpoints

The event log is append-only. Hidden-state snapshots are materialized views
with hashes so the assessor can reconstruct why a conclusion exists without
showing the manager the hidden values.

## Next Phases

The module is ready to expand into:

1. Roadmap refinement and initial 1:1 discovery.
2. Five-resume hiring pool, two interviews, one hire.
3. Layoff/backfill decisions under salary and backfill-fund constraints.
4. Multi-week operations with pairwise friction, knowledge silos, and changing
   goals.
5. Emergent crises caused by earlier construction choices.
6. Persistent manager memory and longer-term hypervisor reports.

## Causal Contract

The simulator models a small number of load-bearing dynamics:

1. Intrinsic motivation minus extrinsic friction determines battery, burnout,
   output, and retention risk.
2. Mastery, autonomy, and purpose fit determine whether a person becomes more
   engaged or quietly atrophies.
3. Team composition, redundancy, interface cleanliness, and dependency chains
   determine whether work survives stress.
4. Manager attention determines what becomes knowable; ignored signals stay
   hidden until they become consequences.
5. Actions have delayed, noisy effects. The manager gets one timeline, not an
   alternate-history oracle.
6. A well-built team should survive discontinuity better than a team that only
   looked productive under static conditions.

Roadmap pressure is separate from delivery velocity. Clarifying scope reduces
future pressure even if the team appears to move faster today; pushing scope
raises future pressure even if the current dashboard improves.

The rule for every phase is the same: the manager should infer, investigate,
predict, and adapt. The sim should not reveal the answer key.
