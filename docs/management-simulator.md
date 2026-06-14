# Management Simulator

The simulator is an authenticated option inside Simulacrum. It is not a
leadership quiz. The manager sees reports, 1:1s, delivery signals, and later
consequences. Hidden persona state is never shown directly.

## First Honest Slice

The current module implements one weekly loop:

- start with five simulated employees and a too-large mission
- generate weekly reports from hidden persona state
- conduct guarded 1:1 conversations
- choose one explicit manager action per week
- advance the week and let consequences surface
- request a hypervisor report with -5..+5 alignment by person trait, team
  dynamic, product complication, and crisis outcome

## Architecture

`fly/management_sim/` is split into:

- `persona_store.py` loads 27 tracked persona files
- `latent_state.py` applies deterministic action effects and weekly drift
- `guard.py` blocks prompt injection/state probing and audits output leakage
- `artifacts.py` generates reports and persona dialogue
- `persistence.py` stores runs, snapshots, artifacts, turns, and event logs
- `service.py` orchestrates the weekly loop
- `assessor.py` emits evidence-backed alignment reports
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

The rule for every phase is the same: the manager should infer, investigate,
and adapt. The sim should not reveal the answer key.
