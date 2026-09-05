# AI Usage

## Tools Used

- Claude Code (Sonnet 5) via CLI, used throughout implementation and documentation for this project.

## What I Delegated

- Initial implementation of client.py, sources/*.py, normalize.py, run.py, \_\_main\_\_.py against your own SPEC.md/PLAN.md.
- Full test suite (test_normalize.py, test_client_retry.py, test_source_*.py, test_run_integration.py).
- Drafting SPEC.md/PLAN.md/README.md updates after gap analyses.

## Spec Review Feedback and How I Responded

- Had Claude run a gap analysis of SPEC.md/PLAN.md against the actual code.
  It surfaced four things that were true in the implementation but
  undocumented: the deadline-cancellation asymmetry (a cancelled source
  contributes zero products vs. retry-exhaustion which keeps pages already
  fetched), the Source C limiter mislabeled "leaky bucket" (it's actually
  sliding-window), the bool-as-int guard on Source B's price field, and the
  run summary JSON shape never being spec'd at all.
- I reviewed each proposed doc change against the actual source code before
  accepting it (via a diff before merging into my working copy) rather than
  taking the analysis at face value — all four held up and were merged as-is.

## Verification Process

- python -m pytest -v, 50/50 passing.
- Manually ran the mock server under every MOCK_SCENARIO value (standard, source-b-down, slow, no-failures, bad-data-heavy) and inspected each output/run-*.json against SPEC.md's acceptance criteria myself, including confirming the trickiest case (deadline cancellation, --deadline + slow) actually produces deadline_exceeded: true with source_c zeroed out.

## An AI Output I Challenged/Rejected/Validated

- I pushed back that returning rejected records inline in the run's JSON output isn't the same as real logging, and asked whether we should add actual structured logging instead. Claude's counter was that for a one-shot CLI at this scale, the JSON rejected array already satisfies the "nothing is silently discarded" goal, and that adding a full logging layer was scope creep relative to task.md's 4-hour budget — but conceded structured logging (JSON-line records per event, tagged with a run_id) was a legitimate gap and added it to PLAN.md's "What I'd Do With More Time" rather than building it.
- Outcome: I accepted the scope argument for this submission, but the disagreement is preserved as a named limitation rather than silently dropped — I wanted a log stream, we shipped a structured JSON artifact instead, and the gap between the two is called out explicitly.

## Final Review Findings and How I Responded

- Asked for a full audit against task.md for drift. Found one real issue: SPEC.md + PLAN.md had grown past the "one or two pages" guidance (peaked at ~2,811 combined words) from cumulative doc-polish edits. Responded with a trim pass that cut it to ~2,271 words (~19% reduction) while preserving all substantive content — you should note this as "AI flagged its own scope creep in the docs and fixed it without being asked to cut content, just to cut length."
- Also confirmed via git diff --stat against origin/main that no source code drifted and the mock service was never touched.

## What I'd Improve With More Time

- Run the task.md compliance/spec-vs-implementation audit continuously, not just once at the end. The doc drift past the "one or two pages" guidance only surfaced because I asked for a full audit late; catching it after each editing round instead of retroactively would show tighter iteration.
- Set an explicit doc length budget up front, before drafting. SPEC.md/PLAN.md grew from a series of individually-reasonable additions to well past guidance; a stated target from the start keeps each edit self-limiting instead of requiring a trim pass later.
- Resolve the logging-vs-JSON-output tradeoff during spec review, before implementation, not after. This is the one from the "challenged" section — deciding observability approach at the spec stage (where task.md's workflow says it belongs) instead of discovering the gap post-hoc would have turned it into a design decision rather than a deferred item.