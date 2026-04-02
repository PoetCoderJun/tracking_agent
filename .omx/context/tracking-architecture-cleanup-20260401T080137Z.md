# Tracking Architecture Cleanup

- Task: Refactor the tracking runtime to reduce orchestration sprawl, state duplication, and wrapper layering while preserving behavior.
- Desired outcome: cleaner boundaries, smaller high-complexity modules, and a simpler data flow with tests staying green.
- Known facts: runner.py and select_target.py are oversized; rewrite lifecycle spans multiple files; frame/rewrite state has multiple sources of truth.
- Constraints: no behavior regressions, no new dependencies, keep diffs reviewable, preserve current contracts unless simplifying internal surfaces only.
- Unknowns: smallest safe extraction boundary; how much subprocess wrapper removal is safe in one pass.
- Likely touchpoints: backend/agent/runner.py, backend/agent/context_views.py, skills/tracking/scripts/select_target.py, scripts/run_tracking_loop.py, scripts/run_tracking_stack.py, related tests.
