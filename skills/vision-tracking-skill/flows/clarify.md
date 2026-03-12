# Clarify Flow

Use this flow when the target remains ambiguous or the user needs to correct the system.

## Triggers

- Main Agent returns `needs_clarification=true`
- user says the system is following the wrong person
- user adds a distinguishing clue such as “I mean the taller one on the left”

## Actions

1. Ask only one short, high-signal follow-up question.
2. Focus on discriminating traits, position, or recent action.
3. Store the clarification as a note in the active session.
4. Re-run the next localization turn with the clarification included as human guidance.

## Runtime mapping

- `scripts/session_store.py` to inspect the active session
- `scripts/session_store.py --action add-clarification` to persist the note
- `scripts/main_agent_locate.py --clarification-note ...` to re-run localization with the user correction
- `scripts/runtime_state.py --action reuse` if the clarification reruns the same batch
