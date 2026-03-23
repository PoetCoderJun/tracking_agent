# Clarify Flow

Use this flow when the target remains ambiguous or the user needs to correct the system.

## Triggers

- Main Agent returns `needs_clarification=true`
- the user says the system is following the wrong person
- the user adds a distinguishing clue such as “I mean the taller one on the left”

## Actions

1. Ask only one short, high-signal follow-up question.
2. Focus on discriminating stable appearance traits first. Use static position only as secondary support.
3. Store the clarification as a note in the active session.
4. Re-run the next localization turn with the clarification included as human guidance.

## Runtime mapping

- main runtime: `scripts/pi_backend_bridge.py --tool reply` to ask a focused clarification question, then `--tool track` after the user answers
- direct adapter path: `scripts/pi_agent_adapter.py invoke --tool reply` or `--tool track` depending on whether the turn is asking or re-localizing
- integration harness: `scripts/main_agent_locate.py --clarification-note ... --detections-json ...` re-runs localization inside `scripts/track_from_description.py`
