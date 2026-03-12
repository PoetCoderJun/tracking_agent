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

- `PiAgentCore.add_clarification(...)`
- `SessionStore.add_clarification_note(...)`
