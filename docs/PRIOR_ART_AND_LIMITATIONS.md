# Prior Art and Limitations

This repository is a **synthetic teaching sample**, not a novel durable workflow engine or an integrated hybrid-LLM system.

## Existing implementations to compare against

| Project | Already implemented/documented features | What the teaching sample adds |
| --- | --- | --- |
| [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence) | Checkpoints, durable state with configured checkpointers, human review and resume | A short, isolated fail-closed decision example, not a feature advantage |
| [Temporal AI](https://docs.temporal.io/ai) | Durable workflows, AI provider calls and provider switching | No equivalent Temporal deployment or service is tested here |
| [Microsoft Agent Framework HITL](https://learn.microsoft.com/en-us/agent-framework/workflows/human-in-the-loop) | Checkpoint and resume around human review | No Microsoft framework integration has been tested here |
| [OpenAI Agents SDK HITL](https://openai.github.io/openai-agents-python/human_in_the_loop/) | Approval interruption and serializable run state | This sample has no real agent run state |
| [Letta memory](https://docs.letta.com/configuration/memory) | Persistent stateful agent memory | This example does not implement model memory or memory consolidation |
| [Responsibility Pathway Engineering](https://github.com/YutoriKomeiji/responsibility-pathway-engineering) | Action evaluation, responsibility handoff, human-gate indication | This small example does not replace RPE |
| [Responsibility Pathway Runtime](https://github.com/YutoriKomeiji/responsibility-pathway-runtime) | Persistent attempts, ambiguous external effects, reconciliation and resume controls | RPR is more complete in its declared scope; no integration is demonstrated here |
| [Responsibility Pathway OS](https://github.com/YutoriKomeiji/responsibility-pathway-os) | SQLite-based responsibility state, recovery paths, selected formal invariants | RPOS is more complete in its declared scope; no integration is demonstrated here |

The goal of a future hybrid-local-cloud design is to test whether the **same independently validated data-clearance, unresolved-effect and authority contracts** can be preserved when a task moves across different model providers. A compositional implementation is not yet demonstrated.

The **additional 9-case** subprocess test uses two temporary SQLite databases and two deterministic stubs. It does not demonstrate real LLM swap, actual external API reliability, Windows/Arm compatibility, or independently verified Human Gate.

The third probe is distinct: it exercises an **actual installed RPR 0.1.0a6 runtime**
against subprocess crashes, reconciliations and a mock provider change (four
passing tests in a prior controlled CI run). Neither trained model weights nor a
cloud provider API is involved, and all external effects are simulated in SQLite.
The public repository's own CI is the independently accessible reproduction surface.
The public RPR release already implements restart/recovery; this sample tests
an integration boundary, not invention of persistent workflows.

## Explicit non-claims

- `model` is a label, not an LLM adapter.
- `round_trip()` performs in-memory JSON serialization; it does not persist to a real storage device or recover from a crash.
- `shareable` and `approval_source` are synthetic caller inputs and do not verify authorization or information classification.
- `READY_FOR_SEPARATE_EXECUTOR` is a suggestion, not an execution credential.
- 21 passing tests do not prove production safety or model interchangeability.
- There is no claim of "first", "only", novel workflow primitives, security certification, or Surface Laptop Ultra benchmark results.

## Reproduction and falsification

Run `python3 continuity_guard_demo.py` with Python 3.9+ and inspect each assertion. Add negative cases that contradict expected behavior. When comparing against real frameworks, use identical initial task states, permission scopes, external effect ambiguity, checkpoint boundaries and failure outcomes.

If an existing framework achieves the same required behavior with less cost and complexity, that is evidence **against** adding a separate runtime layer.
