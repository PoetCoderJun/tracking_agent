# Tracking Minimal Flow

## Goal

Tracking is split into two parts:

1. `tracking-init` skill
2. continuous tracking mini-agent

They do different jobs.

Path ownership should also stay split:

- `skills/tracking-init/` is the `tracking-init` skill surface.
- `skills/tracking-stop/` is the stop/clear skill surface.
- `capabilities/tracking/` is the continuous tracking Python runtime surface.

## 1. Tracking Init Skill

`tracking-init` is a one-shot skill used only to initialize the target.

It does three things:

1. read the latest world snapshot
2. identify the intended person, or keep clarifying with the user until the target is clear
3. initialize tracking memory after the target is confirmed

After confirmation, initialization writes:

- active target id
- target description
- initial tracking memory
- front/back reference crops when available

`tracking-init` does not own continuous follow-up.

## 2. World Snapshot

Tracking mini-agent only reads the low-frequency world snapshot.

Perception may also maintain `perception/latest_frame.jpg` as a stable direct image alias for the current snapshot frame.
That file is only a fast path for current visual grounding.
`snapshot.json` and historical frames remain the persisted truth.

The runtime model is:

- system1 / tracker may run internally at higher frequency
- world snapshot is persisted at low frequency
- tracking mini-agent reads only the latest snapshot truth

This is intentional:

- one second per snapshot is enough for system-2 style reasoning
- lower frequency reduces noise
- tracking decisions stay grounded in persisted truth instead of transient tracker internals

## 3. Continuous Tracking Mini-Agent

Continuous tracking is a backend mini-agent.

Its control flow is intentionally short:

1. derive trigger
2. `Re(trigger)`
3. `Act(observation)`
4. `persist(decision)`

The mini-agent should stay readable at a glance.

The internal file layout should support that readability:

- keep `capabilities/tracking/loop.py` as the supervisor entry
- keep `capabilities/tracking/agent.py` as the single-turn Re/Act entry
- move supporting code into explicit subpackages such as `runtime/`, `policy/`, `state/`, `artifacts/`, `entrypoints/`, and `evaluation/`
- avoid growing another flat pile of unrelated top-level tracking modules

## 4. Re

`Re()` observes:

- latest world snapshot frame
- latest detections carried by that snapshot
- current tracking state from `session.json`
- current tracking memory

`Re()` does not use:

- recent dialogue
- free-form user text
- raw high-frequency tracker state

Those are not part of continuous tracking evidence.

## 5. Act

`Act()` decides one of:

- `track`
- `wait`
- `ask`

It may also attach an optional memory effect.

`Act()` chooses based on:

- current snapshot detections
- current memory
- current target state
- trigger type

## 6. Trigger Types

There are exactly three trigger concepts:

### `chat_init`

- created by the init skill / runner path
- not derived by the continuous trigger logic
- used only to initialize or re-initialize a target

### `cadence_review`

- periodic review of whether the currently tracked person is still correct
- uses the latest world snapshot only

### `event_rebind`

- triggered when the latest snapshot shows that the bound target is gone or no longer trustworthy
- used to recover the correct current `track_id`

## 7. Persist

All continuous tracking authoritative state updates are persisted in one place.

That writer is responsible for:

- persisting assistant result text
- updating tracking state
- writing tracking memory
- enforcing stale-request safety

This is not a generic framework concept.
It is a narrow single-writer rule for tracking lifecycle truth, because async supervision, leases, and queued rewrite work make split writers error-prone.

## 8. Frequency Model

The intended runtime model is:

- internal tracker / system1 can be high frequency
- world snapshot persistence is low frequency
- tracking mini-agent cadence review is slower than tracker internals
- event rebind can trigger immediately on the next snapshot that shows loss

So:

- high frequency is an implementation detail of system1
- low frequency world snapshot is the only realtime input to tracking reasoning

## 9. Benchmark Rule

Benchmark should follow the same model as runtime:

- keep tracker continuity internally
- drive the mini-agent only from emitted world snapshots
- do not let benchmark use raw tracker frames as direct tracking-agent input
- reuse the same production tracking entry/supervision/writer surfaces instead of benchmark-private apply paths
