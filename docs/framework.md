# Framework — Agent-Operable Systems of Record

**Status:** working document. This is the conceptual framework behind Section III of the paper.

**Verification convention:** assertions about what commercial systems do or do not support are marked `[V]`. Every `[V]` must pass the verification procedure in §9 before the prose is used in the paper.

---

## 1. Terminology

The central noun is **agent-operable system of record**, not "agent-native ERP". The earlier term overstated scope — ERP implies a functional breadth this work does not claim — and understated the property being described, which is operability by a non-human principal and applies to any system of record.

> A system of record is **agent-operable** to the degree that a non-human principal can discover its capabilities, obtain an accurate account of an operation's consequences before that operation becomes effective, and execute it with correctness enforced by the system rather than assumed of the caller.

The distinction that matters is between *reachable* and *operable*. A system is reachable when a programmatic interface exists and an agent can invoke it. A system is operable when an agent that lacks the enterprise's tacit knowledge, that reasons imperfectly, and that may retry or resume in a fresh context can still be relied upon not to corrupt the record. Reachability is a property of the interface's existence; operability is a property of where responsibility for correctness sits.

Most systems of record today are reachable. The question this framework addresses is what separates that state from operability, and which of those properties can be supplied from outside the system.

---

## 2. The three-tier taxonomy

An earlier version of this framework used a binary taxonomy: properties were either layerable above a system of record or resident in its kernel. That taxonomy was withdrawn. It overstated what is unreachable from outside, and it obscured the fact that most of the interesting cases turn not on the property itself but on how completely the layer mediates access.

The replacement is three tiers, distinguished by what a property requires of its implementer.

| Tier | Name | Requirement |
|---|---|---|
| **L** | Layerable | Attainable by a layer above the system of record regardless of that system's own capability, because the property concerns the interface presented to the agent rather than the write path |
| **A** | Authoritative | Attainable by a layer only where that layer holds authoritative control of the write path, as specified by the control contract in §2.1 |
| **T** | Transactional | Requires participation in the system of record's own commit; not attainable by any external layer, however complete its coverage |

### 2.1 The control contract

Tier A properties are attainable without transactional access **if and only if** five conditions hold between the system of record and the control plane. Condition C1 is the complete-mediation principle (§8); the remaining four are what complete mediation requires in practice when the mediator is external.

**C1 — Exclusivity.** Every write path to the governed operations passes through the control plane. No residual route exists: not the system's own user interface, not batch jobs, not other integrations, not administrative tooling. A single unmediated path voids every Tier A property for the operations it can reach, not merely for the writes that use it.

**C2 — Completeness.** The control plane's action ontology covers every governed operation. Operations outside the ontology must be refused rather than passed through unexamined, because a pass-through is an unmediated path by another name.

**C3 — Fidelity.** The control plane's model of the system's state is accurate enough to support the decisions it makes on that basis, and any staleness is bounded and declared. A policy evaluated against a stale mirror produces a verdict the system will not honour.

**C4 — Attribution.** The system of record accepts and records the identity of the principal on whose behalf the control plane acts. Where it accepts only a service identity, evidence exists at the control plane but not at the system, and an auditor working from the system alone cannot attribute the action.

**C5 — Determinable outcome.** For every request, the control plane can establish whether the system applied it. Where an outcome is ambiguous — a timeout, a lost response — it must be resolvable by query rather than assumed, or repetition safety (§5, FR2) cannot be provided.

Where any condition fails, the affected properties fall back to Tier T for practical purposes: not because they are theoretically transactional, but because the layer cannot guarantee them.

### 2.2 Tier assignment

| Property | Tier | Reasoning |
|---|---|---|
| Capability discovery | L | Concerns what the agent can enumerate; a layer can publish its own catalog irrespective of the underlying interface |
| Operation semantics and descriptions | L | A layer authors the descriptions it presents; no write-path access required |
| Error taxonomy and retry guidance | L | The layer classifies and re-presents whatever the system returns |
| Capability introspection (what may this caller invoke) | L | A function of the layer's own authorization model |
| Autonomy envelope declaration | L | A published statement of what an agent is permitted to attempt |
| Rate and concurrency shaping | L | Applied at the layer's own boundary |
| Evaluation harness and conformance testing | L | Exercises the interface from outside |
| Policy enforcement | A | Only binding if no unmediated write path exists (C1, C2) |
| Duty separation between principals | A | Requires that every relevant action be observed by the enforcing layer |
| Approval gating of material operations | A | An approval that another path can bypass is advisory, not a control |
| Repetition safety | A | Requires both mediation and determinable outcomes (C5) |
| Evidence and attribution of actions | A | Evidence covering only mediated writes understates what occurred (C1, C4) |
| Causal traceability across documents | A | A trace assembled from mediated calls omits anything that bypassed the layer |
| Consequence disclosure with exact effects | T | Requires evaluating the operation against the system's own committed state at the moment of decision |
| Atomicity across record, ledger, evidence and event | T | Requires enlisting the system's transaction; an external layer cannot |
| Staleness detection bound to committed state | T | The layer can compare versions, but another writer may intervene between its check and the system's commit |
| Transactional event emission | T | An event emitted outside the system's transaction can survive a rollback or be lost after a commit |

**Why Tier T is irreducible.** Each Tier T property depends on the same thing: acting inside the boundary where the system decides that a change has happened. An external layer can approximate every one of them — simulate against a mirror, emit events after an apparent success, compare version tokens before writing — and each approximation is defeated by the same gap, which is the interval between the layer's observation and the system's commit. Narrowing that interval reduces the failure rate; it does not change the property from a guarantee into a probability. This is a statement about commit ownership, not about implementation effort. `[V]` — the claim that commonly available systems of record do not expose transaction enlistment to external callers requires a named source or must be softened.

---

## 3. Postures

Four architectures an enterprise can occupy. The fourth was added in revision: earlier versions treated layered approaches as a degraded case, which misrepresents the architecture most enterprises will actually deploy in the near term.

| # | Posture | Description | Attainable |
|---|---|---|---|
| 1 | Screen-era system of record | Operated through a user interface; the programmatic surface, where present, mirrors the data model and assumes an integrator's knowledge | Nothing reliably |
| 2 | System of record plus tool wrapper | The existing interface exposed as machine-enumerable tools, typically over a tool protocol. The agent can reach the system; the wrapper adds no enforcement and does not mediate other paths | Tier L |
| 3 | System of record plus authoritative control plane | A control plane holds exclusive mediation of governed operations and satisfies the control contract of §2.1 | Tier L and Tier A |
| 4 | Agent-operable system of record | The system itself implements the properties inside its own commit boundary | Tier L, A and T |

**Posture 2 is where most deployments sit.** `[V]` A tool wrapper is frequently described as making a system agent-ready. Under this framework it delivers exactly one tier, and the properties enterprises actually cite when they hesitate to give agents write access — policy that cannot be bypassed, evidence that covers everything, safety under retry — are not among them.

**Posture 3 is the realistic near-term target for an incumbent estate.** It is a strictly stronger position than Posture 2 and does not require replacing the system of record. Its cost is organizational rather than technical: condition C1 requires closing every other write path to the governed operations, which is usually harder than building the control plane.

**Posture 4 is not a migration target for an existing estate.** It applies to new entities, carve-outs, subsidiaries, and greenfield deployments. The framework's purpose is not to argue that enterprises should replace their systems of record, but to make precise what is given up by not doing so.

---

## 4. Readiness profile

Twelve dimensions. Nine were present in the original profile; three were added in revision — autonomy envelope, data freshness and temporal validity, and runtime evaluation — because the original set described the interface but not the conditions under which an agent is permitted to use it or the basis on which it is trusted over time.

A profile is a vector, not a score. The dimensions are not substitutes: a system with excellent semantics and no consequence disclosure is dangerous in a way that a system with poor semantics and full disclosure is not.

**Levels.** 0 absent · 1 present but implicit, requiring prior knowledge · 2 documented and machine-readable · 3 semantically complete for an agent without prior knowledge · 4 enforced by the system and independently verifiable.

| # | Dimension | 0 | 1 | 2 | 3 | 4 |
|---|---|---|---|---|---|---|
| 1 | Capability discovery | No programmatic surface | Endpoints exist, documented for humans | Machine-enumerable operations | Grouped by business capability, parameters self-describing | Plus introspection of what this caller may invoke |
| 2 | Operation semantics | Field names only | Types | Typed schema with descriptions | Purpose, preconditions, postconditions | Plus named compensating operation and stable error taxonomy |
| 3 | Consequence disclosure | None | Validation on submit | Partial preview of some effects | Full projection of records, ledger, policy verdict | Projection provably free of side effects and binding on the subsequent commit |
| 4 | Repetition safety | None | Caller detects duplicates after the fact | Caller-managed keys | Server-recognised keys | Server-enforced, including semantically identical requests from a fresh caller context |
| 5 | Compensation and recovery | Manual correction | Documented procedure | Reversing operations exist | Each operation names its reversal | Reversals are themselves evidenced operations; recovery path testable |
| 6 | Policy enforcement | Convention | Enforced in the user interface only | Enforced on the primary API | Enforced on every path, declaratively specified | Plus evaluated identically in disclosure and execution, so a preview is truthful |
| 7 | Non-human identity and delegation | Shared credentials | Service account | Role-scoped credentials | Per-operation scopes, distinct non-human identity | Plus verifiable delegation from a human principal with narrowing scope |
| 8 | Evidence and attribution | Application logs | System audit table | Queryable audit log | Per-action record naming actor and principal | Independently verifiable evidence not resting on trust in the producer |
| 9 | Causal traceability | Manual reconstruction | Document flow in the user interface | Linked records via API | Full causal chain queryable through the agent interface | Plus reconstruction of state as of any prior point |
| 10 | Autonomy envelope | Undefined | Informal convention | Documented limits | Declared per operation and per principal, machine-readable | Enforced, with refusals explaining the binding limit |
| 11 | Data freshness and temporal validity | Unknown | Best-effort | Staleness bounded and reported | Effective-dated data honoured in projections | State binding: an execution referencing stale observations is refused |
| 12 | Runtime evaluation | None | Manual testing | Sandbox available | Reproducible seed and deterministic verification | Continuous conformance testing across models, with published results |

`[V]` Any assertion in the prose that commercial systems typically occupy a particular level on a given dimension requires a named public example, or must be stated as a general tendency without attribution.

---

## 5. Functional requirements, not prescriptive mechanisms

An earlier version specified three mechanisms and treated their absence as the deficiency. That conflates a requirement with one way of meeting it, overstates the claim, and invites the objection that an alternative mechanism would serve equally well. The mechanisms are retained below as examples.

**FR1 — Consequence disclosure.** Before an operation becomes effective, the principal must be able to obtain an accurate account of what it would change and whether it is admissible. *Satisfied by:* a simulation mode returning the projected effects and the policy verdict; a reservation protocol; a system-native what-if evaluation. *Not satisfied by:* syntactic validation, which reports whether a request is well-formed rather than what it would do.

**FR2 — Repetition safety.** Repeated submission of the same intent must not produce repeated effects, including where the repetition originates from a principal with no memory of the earlier attempt. *Satisfied by:* caller-supplied idempotency keys where the caller's context persists; server-side fingerprinting of business intent where it does not; operations that are naturally idempotent. *Partially satisfied by:* caller-supplied keys alone, which protect a retried request but not a repeated intention — a distinction with empirical support in the evaluation.

**FR3 — Action accountability.** Every effective action must produce evidence sufficient to attribute it and to verify it independently of the system that produced it. *Satisfied by:* signed per-action records; hash-linked logs; external anchoring. *Not satisfied by:* an audit table the producing system can alter without detection.

---

## 6. Economics by risk tier

The cost of governance is proportional to consequence, not to volume. A pricing model organized by call count therefore misprices it: it charges most for the operations that need least protection, and it charges for the disclosure step that makes the rest safe.

| Tier | Operations | Governance cost | Pricing implication |
|---|---|---|---|
| R0 | Reads, traces, verification | None beyond serving the request | Free. Charging for the ability to check what happened discourages the behaviour the system depends on |
| R1 | Consequence disclosure | Projection and policy evaluation, no persistence | Free. Charging for disclosure creates an incentive to skip it, which is the opposite of the intent |
| R2 | Reversible operations | Policy evaluation and evidence | Priced, low |
| R3 | Irreversible or financially material operations | Policy, evidence, and the retention that makes evidence durable | Priced by materiality |
| R4 | Control operations — policy change, key rotation, period close | Rare, high consequence, elevated assurance | Platform fee rather than per-operation |

Two consequences follow. A refusal costs the enterprise nothing, so a well-governed deployment pays less than a careless one — unusual, and it requires a coherent explanation to a buyer. And where every effective action already produces an evidence record, that record is the natural unit of account, which makes an invoice reconcilable against the customer's own record rather than against a vendor's meter. `[V]` The claim that prevailing consumption-based pricing in this category is not customer-reconcilable requires a source or must be softened to an observation about the pricing model's structure.

---

## 7. Positioning constraints

- Vendor-neutral framing and open-standard protocols are a principled constraint and a competitive position, not a limitation.
- The primary commercial wedge is high-growth software companies outgrowing entry-level accounting systems; physical-goods distributors are secondary. Recorded for consistency with the product work; not a claim the paper makes.

---

## 8. Attribution and prior art

The enforcement-coverage bound in §2.1, condition C1, is a restatement of complete mediation. It must be cited, not presented as novel.

- J. P. Anderson, *Computer Security Technology Planning Study*, ESD-TR-73-51, 1972.
- J. H. Saltzer and M. D. Schroeder, "The Protection of Information in Computer Systems," *Proceedings of the IEEE*, vol. 63, no. 9, 1975.

The observability finding in the evaluation — that principals avoided duplication by querying rather than by using the safety mechanism available to them, and that a partially applicable guarantee displaced their own caution — is an instance of automation complacency.

- R. Parasuraman and V. Riley, "Humans and Automation: Use, Misuse, Disuse, Abuse," *Human Factors*, vol. 39, no. 2, 1997.

TODO — prior art for the tier argument itself, if any exists. Layered enforcement above an unmodified system is old ground in security architecture; a citation would strengthen §2.

---

## 9. Verification procedure

Every assertion marked `[V]`, and every assertion elsewhere in this document about what a commercial system does or does not support — named or unnamed — requires a public source. Verdicts:

- **supported-named** — at least one named public system, with URL and exact supporting text
- **supported-general** — the tendency is real but no named example carries it; soften to a general statement in the prose
- **needs-narrowing** — true only under stated conditions; record the narrower wording
- **drop** — no public support

Silence in vendor documentation is not evidence of a missing capability. Where public documentation does not address write semantics, repetition safety, or approval routing, record "docs silent" and treat the dimension as unscored rather than scoring it low.

### 9.1 Verification table

TODO — populated by the verification pass.
