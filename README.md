# Hybrid LLM: model-switch and restart test samples

Three reproducible Python examples for examining what happens to recorded work state, external-effect uncertainty and permission checks when a processing adapter changes. This repository is **not a working local/cloud hybrid-LLM system**.

## Run

Use Python **3.11+** for all three examples. The first two require only the standard library; the third depends on a pinned published RPR package. The examples are not evidence of real LLM or Surface operation.

```bash
python3 continuity_guard_demo.py
python3 continuity_restart_fixture.py
```

Expected results: **21 passing tests** for `continuity_guard_demo.py`, **9** for `continuity_restart_fixture.py`, and **4** for `rpr_provider_swap_probe.py` (after installing RPR). Each suite tests a different boundary; the counts should not be treated as 34 interchangeable safety guarantees.

Neither program requires an API key, external network, AI model, or GPU. The 9-case program writes to two **temporary local SQLite files** and simulates abrupt subprocess termination; it does not call external services.

## What does this actually test?

The 21-case script models a *single* immutable record of a work item and a pure `choose_next` function. Selected cases exercise:

- Incomplete or stale evidence, invalid records and data-disclosure restrictions
- A simulated model label change that must **not** create new permissions
- Pending external-effect uncertainty that must **not** silently become completion or retry permission
- A synthetic "summary says approved" input that must **not** be accepted as authority
- JSON serialization and in-memory reconstruction of the record

In an early 16-test revision we discovered a regression: data marked non-shareable could still reach the publication candidate state if a separate approval flag was set. We moved the disclosure test ahead of the approval candidate and added negative cases, producing 21 passing synthetic tests.

## Second exercise: subprocess crash and readback

`continuity_restart_fixture.py` tests 9 synthetic scenarios using a temporary state SQLite DB and a separate mock-service SQLite DB. After a mock external write has committed, the child process is killed before it can acknowledge success. A fresh process using a different *stub adapter* refuses to resend until independent mock readback; a crash before the write remains unresolved after a missing readback. These are not actual model providers or Windows on Arm hardware measurements. Source blob after explicit-close fix: `f8b3ac53011879fc24d6cd352b31b64b856db73e`; tested on Linux Python 3.13.5, **9/9**.

## Published RPR integration: actual runtime, mock model-adapter swap

`rpr_provider_swap_probe.py` uses the **published** `responsibility-pathway-runtime==0.1.0a6`
package against two separate persisted SQLite files and four subprocess scenarios.
It does **not** require a real local/cloud LLM or credential.

```bash
python3 -m pip install "responsibility-pathway-runtime==0.1.0a6"
python3 rpr_provider_swap_probe.py
```

The original fixture (source Git blob `9ef8e40b3e5dbd363a35d4e0ebe110ce837c3c8a`) passed four tests with the pinned release on Ubuntu/Python 3.11 (2026-11-24). Its external writes are **mock SQLite**, the two providers are **deterministic stub functions**, and `AllowAllDevelopmentEvaluator` is test-only, not a real authorization policy. Check this repository's own public CI for independent execution of the published source.

## What this does **not** establish

- No real LLM or provider handoff is run; a model name is merely a field.
- No disk persistence, power-loss recovery, real retry, idempotency service, or real API effect is exercised.
- The `EXTERNALLY_VERIFIED` and `shareable` fields are **caller-supplied strings/booleans**. They are not cryptographic approval, provenance verification, clearance or policy enforcement.
- Returning `READY_FOR_SEPARATE_EXECUTOR` is **not permission to execute**.
- No Surface Laptop Ultra measurements, model quality, data security certification, real-world safety, or evidence of consciousness.

## Related existing work, not reinvented here

- [Responsibility Pathway Engineering (RPE)](https://github.com/YutoriKomeiji/responsibility-pathway-engineering): executable requirement/evidence/governance evaluation.
- [Responsibility Pathway Runtime (RPR)](https://github.com/YutoriKomeiji/responsibility-pathway-runtime): published alpha with persistent pathways, ambiguous-effects handling and bounded external-framework probes.
- [Responsibility Pathway OS (RPOS)](https://github.com/YutoriKomeiji/responsibility-pathway-os): published alpha with SQLite state, reconciliation, Human Gate and selected Lean 4 invariants.
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence), [Temporal AI](https://docs.temporal.io/ai), [Microsoft Agent Framework HITL](https://learn.microsoft.com/en-us/agent-framework/workflows/human-in-the-loop) already implement major continuation concepts.

This repository's value is a tiny, easy-to-read **negative-case worksheet**, not a new workflow engine or an implementation of the whole proposed hybrid LLM.

## Next work

Use real RPR/RPOS integration and compare with existing framework checkpointers on the *same* handoff/restart/approval fixtures. Record latency, correctness, false holds, and data clearance. No release claims until evidence exists.

## License / contributions

See [LICENSE](LICENSE) for the MIT terms covering this sample repository. Referenced external frameworks have their own license terms.
