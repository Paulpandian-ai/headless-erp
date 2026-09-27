# Framework — Agent-Operable Systems of Record

**Status:** working document. This is the conceptual framework behind Section III of the paper.

**Verification convention:** assertions about what commercial systems do or do not support are marked `[V]`. Every `[V]` must pass the verification procedure in §9 before the prose is used in the paper. The pass of 2026-09-27 resolved the four inline markers then present; its results, sources and the narrowings applied are in §9.1. Marks added later are unresolved until that table records them.

---

## 1. Terminology

The central noun is **agent-operable system of record**, not "agent-native ERP". The earlier term overstated scope — ERP implies a functional breadth this work does not claim — and understated the property being described, which is operability by a non-human principal and applies to any system of record.

> A system of record is **agent-operable** to the degree that a non-human principal can discover its capabilities, obtain an accurate account of an operation's consequences before that operation becomes effective, and execute it with correctness enforced by the system rather than assumed of the caller.

The distinction that matters is between *reachable* and *operable*. A system is reachable when a programmatic interface exists and an agent can invoke it. A system is operable when an agent that lacks the enterprise's tacit knowledge, that reasons imperfectly, and that may retry or resume in a fresh context can still be relied upon not to corrupt the record. Reachability is a property of the interface's existence; operability is a property of where responsibility for correctness sits.

Reachability is now routine rather than remarkable: SAP, Microsoft Dataverse, Dynamics 365 Business Central and Xero all publish programmatic interfaces over their records, and some now publish tool-protocol front ends over those interfaces as well (§3, Posture 2). The question this framework addresses is what separates that state from operability, and which of those properties can be supplied from outside the system.

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

**Why Tier T is irreducible.** Each Tier T property depends on the same thing: acting inside the boundary where the system decides that a change has happened. An external layer can approximate every one of them — simulate against a mirror, emit events after an apparent success, compare version tokens before writing — and each approximation is defeated by the same gap, which is the interval between the layer's observation and the system's commit. Narrowing that interval reduces the failure rate; it does not change the property from a guarantee into a probability. This is a statement about commit ownership, not about implementation effort.

What the interfaces of commonly available systems document is atomicity *within one request*. SAP Gateway treats an OData `$batch` change set as "an atomic unit of work" and as "one Logical Unit of Work (LUW), ensuring its 'all or nothing' character"; Microsoft Dataverse states that in a change set "all the operations are considered *atomic*", so that "if any one of the operations fails, the batch request rolls back any completed operations". That is the system executing a group of the caller's operations under its own transaction — not the caller participating in the system's commit. An external layer still cannot place its own evidence record, policy verdict or event inside that boundary, which is what the Tier T properties require. A protocol for the stronger thing exists: WS-AtomicTransaction specifies durable two-phase commit for web services. This framework makes no claim that no system of record implements it — the interface documentation surveyed for §9 does not address external enlistment, and silence is not evidence of absence.

---

## 3. Postures

Four architectures an enterprise can occupy. The fourth was added in revision: earlier versions treated layered approaches as a degraded case, which misrepresents the architecture most enterprises will actually deploy in the near term.

| # | Posture | Description | Attainable |
|---|---|---|---|
| 1 | Screen-era system of record | Operated through a user interface; the programmatic surface, where present, is shaped by the data model — entity sets and page objects rather than business operations — leaving the caller to supply the process knowledge | Nothing reliably |
| 2 | System of record plus tool wrapper | The existing interface exposed as machine-enumerable tools, typically over a tool protocol. The wrapper adds properties at its own boundary — which tools a caller may invoke, rate limits, its own logs — and does not claim exclusive mediation of the operations it exposes | Tier L |
| 3 | System of record plus authoritative control plane | A control plane holds exclusive mediation of governed operations and satisfies the control contract of §2.1 | Tier L and Tier A |
| 4 | Agent-operable system of record | The system itself implements the properties inside its own commit boundary | Tier L, A and T |

**Posture 2 is what the tool-protocol offerings on the market amount to.** Microsoft's Business Central MCP Server turns API page objects into tools — "each allowed operation (read, create, modify, update, delete, or bound action) results in a corresponding tool" — gated by per-tool `Allow Read` / `Allow Create` / `Allow Modify` / `Allow Delete` permissions, read-only by default; SAP offers the same shape over SAP APIs through Integration Suite. The documented additions are authorization scoping, rate limiting and logging, which are Tier L properties on this framework's own taxonomy. That documentation does not address policy that cannot be bypassed, evidence that covers everything, or safety under retry, and their absence is not inferred from that silence (§9). The narrower point is sufficient: a wrapper that does not hold exclusive mediation of an operation cannot supply the Tier A properties for it, because those are properties of the write path and not of the interface. How many deployments occupy this posture is not something we have a source for, and the paper does not assert it.

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

Any assertion in the prose that commercial systems typically occupy a particular level on a given dimension requires a named public example, or must be stated as a general tendency without attribution. §9.1 records the named reference points established so far, and the dimensions on which the documentation surveyed is silent — those are unscored, not scored low.

---

## 5. Functional requirements, not prescriptive mechanisms

An earlier version specified three mechanisms and treated their absence as the deficiency. That conflates a requirement with one way of meeting it, overstates the claim, and invites the objection that an alternative mechanism would serve equally well. The mechanisms are retained below as examples.

**FR1 — Consequence disclosure.** Before an operation becomes effective, the principal must be able to obtain an accurate account of what it would change and whether it is admissible. *Satisfied by:* a simulation mode returning the projected effects and the policy verdict; a reservation protocol; a system-native what-if evaluation. *Not satisfied by:* syntactic validation, which reports whether a request is well-formed rather than what it would do.

**FR2 — Repetition safety.** Repeated submission of the same intent must not produce repeated effects, including where the repetition originates from a principal with no memory of the earlier attempt. *Satisfied by:* caller-supplied idempotency keys where the caller's context persists; server-side fingerprinting of business intent where it does not; operations that are naturally idempotent. *Partially satisfied by:* caller-supplied keys alone, which protect a retried request but not a repeated intention — a distinction with empirical support in the evaluation: when the same instruction reached a fresh agent session, 8 of 9 runs created a second document because each session minted its own key, while the same interruption inside one session produced no duplicate in 44 runs (`results/dup01-keys`, `results/resilience/`). Commercial practice sits at the first of these: Xero, for example, documents an `Idempotency-Key` header and returns the cached response when a key repeats, and says nothing about a semantically identical request arriving under a different key.

**FR3 — Action accountability.** Every effective action must produce evidence sufficient to attribute it and to verify it independently of the system that produced it. *Satisfied by:* signed per-action records; hash-linked logs; external anchoring. *Not satisfied by:* an audit table the producing system can alter without detection.

---

## 6. Economics by risk tier

The cost of governance is proportional to consequence, not to volume. A pricing model organized by call count therefore misprices it: reads and disclosure calls are the cheapest to serve and the most numerous, so a per-call meter charges most for what needs least protection and puts a price on the disclosure step that makes the rest safe. This is an argument about the structure of per-call pricing, not a report of any vendor's price list.

| Tier | Operations | Governance cost | Pricing implication |
|---|---|---|---|
| R0 | Reads, traces, verification | None beyond serving the request | Free. Charging for the ability to check what happened discourages the behaviour the system depends on |
| R1 | Consequence disclosure | Projection and policy evaluation, no persistence | Free. Charging for disclosure creates an incentive to skip it, which is the opposite of the intent |
| R2 | Reversible operations | Policy evaluation and evidence | Priced, low |
| R3 | Irreversible or financially material operations | Policy, evidence, and the retention that makes evidence durable | Priced by materiality |
| R4 | Control operations — policy change, key rotation, period close | Rare, high consequence, elevated assurance | Platform fee rather than per-operation |

Two consequences follow. A refusal costs the enterprise nothing, so a well-governed deployment pays less than a careless one — unusual, and it requires a coherent explanation to a buyer. And where every effective action already produces an evidence record, that record is the natural unit of account, which makes an invoice reconcilable against the customer's own record rather than against a vendor's meter. The contrast is with metering in a vendor-defined unit: Microsoft Copilot Studio bills in Copilot Credits, which "measure the time and effort your agent needs to retrieve information, respond to prompts, and use any actions or custom skills", in a quantity that "depends on the complexity of the task the agent completes". A customer can read the vendor's reports of that quantity but cannot derive it from its own records. That is one named platform rather than a survey, and no stronger claim about prevailing practice is made here.

---

## 7. Positioning constraints

- Vendor-neutral framing and open-standard protocols are a principled constraint and a competitive position, not a limitation.
- The primary commercial wedge is high-growth software companies outgrowing entry-level accounting systems; physical-goods distributors are secondary. Recorded for consistency with the product work; not a claim the paper makes.

---

## 8. Attribution and prior art

The enforcement-coverage bound in §2.1, condition C1, is a restatement of complete mediation. It must be cited, not presented as novel.

- J. P. Anderson, *Computer Security Technology Planning Study*, ESD-TR-73-51, ESD/AFSC, Hanscom AFB, Bedford, MA, Oct. 1972.
- J. H. Saltzer and M. D. Schroeder, "The Protection of Information in Computer Systems," *Proceedings of the IEEE*, vol. 63, no. 9, pp. 1278–1308, Sep. 1975, doi:10.1109/PROC.1975.9939.

The observability finding in the evaluation — that principals avoided duplication by querying rather than by using the safety mechanism available to them, and that a partially applicable guarantee displaced their own caution — is an instance of automation complacency.

- R. Parasuraman and V. Riley, "Humans and Automation: Use, Misuse, Disuse, Abuse," *Human Factors*, vol. 39, no. 2, pp. 230–253, Jun. 1997, doi:10.1518/001872097778543886.

The tier argument itself has antecedents, and §2 should be presented as an application of them to systems of record rather than as a new result.

- **What an external monitor can and cannot enforce.** F. B. Schneider, "Enforceable Security Policies," *ACM Transactions on Information and System Security*, vol. 3, no. 1, pp. 30–50, Feb. 2000. Schneider characterises the class EM of policies enforceable by mechanisms that "monitor execution and stop it when the security policy they enforce is about to be violated," and shows the class is bounded: a policy that is not a safety property is not EM-enforceable. The L/A boundary in §2 is the same argument carried into a setting where the monitor is a control plane and the executions are business operations.
- **Enforceability as a taxonomy by mechanism class.** K. W. Hamlen, G. Morrisett and F. B. Schneider, "Computability Classes for Enforcement Mechanisms," *ACM Transactions on Programming Languages and Systems*, vol. 28, no. 1, pp. 175–205, 2006. Gives a taxonomy of enforceable policies by the class of mechanism — static analysis, execution monitoring, program rewriting — which is the closest prior structure to the three tiers here.
- **Enforcement above unmodified commercial software.** T. Fraser, L. Badger and M. Feldman, "Hardening COTS Software with Generic Software Wrappers," *Proceedings of the 1999 IEEE Symposium on Security and Privacy*, May 1999. The paper's wrappers are "protected, non-bypassable kernel-resident software extensions for augmenting security without modification of COTS source" — Posture 3's proposition, and the reason C1 is stated as non-bypassability rather than as coverage.
- **The gap that makes Tier T irreducible.** M. Bishop and M. Dilger, "Checking for Race Conditions in File Accesses," *Computing Systems*, vol. 9, no. 2, pp. 131–152, Spring 1996. The time-of-check-to-time-of-use flaw — "the binding of a name to an object changes between repeated references" — is the established name for the interval between an external check and the effective operation, which is what defeats every external approximation of a Tier T property.
- **What participation in a commit would require.** *Web Services Atomic Transaction (WS-AtomicTransaction) Version 1.2*, OASIS, 2009, which specifies durable two-phase commit for web services. Cited to show the mechanism Tier T would need is specified rather than unimaginable; §2.2 makes no claim about which systems implement it.

---

## 9. Verification procedure

Every assertion marked `[V]`, and every assertion elsewhere in this document about what a commercial system does or does not support — named or unnamed — requires a public source. Verdicts:

- **supported-named** — at least one named public system, with URL and exact supporting text
- **supported-general** — the tendency is real but no named example carries it; soften to a general statement in the prose
- **needs-narrowing** — true only under stated conditions; record the narrower wording
- **drop** — no public support

Silence in vendor documentation is not evidence of a missing capability. Where public documentation does not address write semantics, repetition safety, or approval routing, record "docs silent" and treat the dimension as unscored rather than scoring it low.

### 9.1 Verification table

Pass of 2026-09-27, against this document at commit `9594b55`. Sources were read on that date; vendor documentation changes, so a claim's verdict is only as current as its retrieval. Where a page's body could not be retrieved (several vendor portals render client-side), that is recorded as a retrieval failure and **not** as documentation silence.

| # | Location | Claim as written | Verdict | Source and exact supporting text |
|---|---|---|---|---|
| V1 | §2.2, "Why Tier T is irreducible" | Commonly available systems of record do not expose transaction enlistment to external callers | **needs-narrowing** — applied | SAP Gateway `$batch`: "A change set is an atomic unit of work that is made up of an unordered group of one or more of the insert, update or delete operations"; "Every change set is treated as one Logical Unit of Work (LUW), ensuring its 'all or nothing' character" (https://help.sap.com/doc/saphelp_ssb/1.0/en-US/90/dc8363306c47d3b2fca1398f5de94b/content.htm). Microsoft Dataverse: "When multiple operations are contained in a change set, all the operations are considered *atomic*. An atomic operation means that if any one of the operations fails, the batch request rolls back any completed operations" (https://learn.microsoft.com/en-us/power-apps/developer/data-platform/webapi/execute-batch-operations-using-web-api). Neither page addresses external enlistment or two-phase commit — **docs silent**, so no absence is claimed. WS-AtomicTransaction (OASIS v1.2, 2009) specifies the protocol that would be required: "an OASIS specification for coordinating distributed transactions among web services, enabling a group of services to complete a transaction with all-or-nothing (atomic) semantics". **Narrowing applied:** the prose now states what is documented — atomicity *within one request*, the system executing the caller's group under its own transaction — and explicitly disclaims the general negative |
| V2a | §3, Posture 2 paragraph | "Posture 2 is where most deployments sit" | **supported-general** — softened | No public survey of deployment postures was found. What is sourceable is that the offerings exist and have this shape (V2b, V2c). **Softened to:** "Posture 2 is what the tool-protocol offerings on the market amount to", with an explicit statement that the share of deployments is not asserted |
| V2b | §3, Posture 2 paragraph | A tool wrapper is frequently described as making a system agent-ready | **supported-named** | Microsoft, *Configure Business Central MCP Server*: "The Business Central MCP Server enables AI clients to connect to your environments, so agents within those clients can perform a range of interactions and tasks"; page description: "enable AI agents to access and interact with your Business Central data and processes" (https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/ai/configure-mcp-server). Stronger "AI-agent ready" phrasing appears in SAP community posts rather than vendor documentation, so the prose cites the vendor wording |
| V2c | §3 table, Posture 2 row | "the wrapper adds no enforcement and does not mediate other paths" | **needs-narrowing** — applied | Same Microsoft page: tools are gated per object by `Allow Read`, `Allow Create`, `Allow Modify`, `Allow Delete`, `Allow Bound Actions`; "By default, the MCP Server gives agents read-only access to all exposed Business Central API pages"; `Unblock Edit Tools` "when turned off, all these permissions are set to `false` making the tools read-only". So a wrapper does add authorization scoping at its own boundary — Tier L on this framework's taxonomy — and "no enforcement" overstates. On other write paths the page is **silent**: tools are generated from the same API page objects the regular API exposes, and no exclusivity is claimed either way. **Narrowing applied** to the table row and the paragraph |
| V3 | §4, standing instruction | Any prose claim that commercial systems typically occupy a level needs a named example | **not applicable** — no such claim in this document; instruction retained and pointed at the reference points below | — |
| V4 | §6, closing paragraph | Prevailing consumption-based pricing in this category is not customer-reconcilable | **needs-narrowing** — applied | Microsoft, *Standard harness licensing* (Copilot Studio): "Copilot Credits measure the time and effort your agent needs to retrieve information, respond to prompts, and use any actions or custom skills. The number of Copilot Credits counted for each response or action depends on the complexity of the task the agent completes"; pay-as-you-go: "your organization pays only for the actual number of Copilot Credits its agents use during the month" (https://learn.microsoft.com/en-us/microsoft-copilot-studio/billing-licensing). The billed quantity therefore turns on the vendor's assessment of task complexity; vendor-side monitoring and an estimator are documented, nothing customer-derivable. **Narrowing applied:** one named platform, no claim about prevailing practice |
| U1 | §1, closing paragraph | "Most systems of record today are reachable" | **supported-general** as a population claim; **supported-named** as an existence claim — rewritten | Programmatic interfaces documented for SAP (OData/Gateway, above), Microsoft Dataverse (above), Business Central (above) and Xero (https://developer.xero.com/documentation/guides/idempotent-requests/idempotency/). **Rewritten to:** "Reachability is now routine rather than remarkable", naming those systems, with "most" removed |
| U2 | §3 table, Posture 1 row | The programmatic surface "mirrors the data model and assumes an integrator's knowledge" | **needs-narrowing** — applied | Data-model shaping is sourceable: Dataverse operates on entity sets (`accounts`, `contacts`, `tasks`); Business Central generates one tool per API page object, named `ListAPIV2 - Customer_PAG30009`, `CreateAPIV2 - Customer_PAG30009` and so on. "Assumes an integrator's knowledge" is interpretation, not documentation. **Narrowing applied:** the row now states the data-model shaping and says the caller is left to supply the process knowledge |
| U3 | §5, FR2 | Caller-supplied keys protect a retried request but not a repeated intention; "empirical support in the evaluation" | **supported-named** (internal evidence, plus a named commercial reference point) | This repository: `results/dup01-keys` — three vendors, each retry in a fresh session minted a different key (`po-bolt-hose10m-20-20260912-01` then `po-bolt-hose10m-20-20260912`, and so on), and the kernel applied both; `results/resilience/` — the same interruption inside one session produced no duplicate in 44 runs. Commercial reference point: Xero documents an `Idempotency-Key` header and "will cache the response to these requests and if subsequent requests are made with the same idempotency key, they won't be processed and instead the cached response will be returned", for "POST, PUT and PATCH"; the page does not address a semantically identical request arriving under a *different* key. **Applied:** the prose now cites both |
| U4 | §6, opening paragraph | Per-call pricing "charges for the disclosure step that makes the rest safe" | **needs-narrowing** — applied | No vendor price list was found that charges for a simulate/preview step; the observation is a property of per-call metering as a model. **Narrowing applied:** the paragraph now says so explicitly |
| U5 | §8 | Anderson 1972; Saltzer and Schroeder 1975; Parasuraman and Riley 1997 | **supported-named** (bibliographic) | Anderson, ESD-TR-73-51: "ESD-TR-73-51, ESD/AFSC, Hanscom AFB, Bedford, MA (Oct. 1972)" (https://seclab.cs.ucdavis.edu/projects/history/seminal.html; report at https://csrc.nist.gov/files/pubs/conference/1998/10/08/proceedings-of-the-21st-nissc-1998/final/docs/early-cs-papers/ande72a.pdf). Saltzer and Schroeder: "Complete mediation: Every access to every object must be checked for authority" (https://web.mit.edu/Saltzer/www/publications/protection/Basic.html), *Proc. IEEE* 63(9), 1975, pp. 1278–1308, doi:10.1109/PROC.1975.9939. Parasuraman and Riley, *Human Factors* 39(2), June 1997, pp. 230–253 (https://journals.sagepub.com/doi/10.1518/001872097778543886). **Applied:** page ranges and DOI added where missing |
| U6 | §8, prior art for the tier argument | Prior art for layered enforcement above an unmodified system | **supported-named** — written into §8 | Schneider, *ACM TISSEC* 3(1):30–50, 2000: mechanisms that "monitor execution and stop it when the security policy they enforce is about to be violated"; a policy that is not a safety property is not EM-enforceable (https://www.cs.cornell.edu/fbs/publications/EnfSecPols.pdf, definitions quoted from https://www.cs.cornell.edu/courses/cs513/2005fa/NL18.html). Hamlen, Morrisett and Schneider, *ACM TOPLAS* 28(1):175–205, 2006, "a taxonomy of enforceable security policies" by mechanism class (https://www.cs.cornell.edu/fbs/publications/EnfClasses.pdf). Fraser, Badger and Feldman, IEEE S&P 1999: "protected, non-bypassable kernel-resident software extensions for augmenting security without modification of COTS source" (https://ieeexplore.ieee.org/document/821530/; abstract via the publisher listing — the IEEE page body was not retrievable). Bishop and Dilger, *Computing Systems* 9(2):131–152, 1996: "the binding of a name to an object changes between repeated references" (https://nob.cs.ucdavis.edu/bishop/papers/1996-compsys/) |

**Named reference points for §4.** Established by this pass, for the paper to cite rather than generalise: repetition safety — Xero at level 3 (server-recognised keys; silent on the fresh-context case, which is level 4); capability discovery and introspection — Business Central MCP Server at level 2–3 with per-tool permissions; atomicity — SAP Gateway change sets and Dataverse change sets provide it *within a request*, which is not the level-4 property in dimension 3.

**Documentation silence recorded, not scored.** None of the vendor pages read for this pass addresses approval routing for agent-initiated writes; none addresses whether other write paths remain open when a tool wrapper is added; and no page addresses repetition safety for a semantically identical request under a new key. Per §9 these dimensions are unscored for those systems. Retrieval failures, separately: SAP Help Portal and SAP Business Accelerator Hub pages, the IEEE Xplore and ACM Digital Library article pages, and the Xero documentation body all render client-side or refuse automated fetches; where a quotation above came from a search index of the same URL rather than the page body, that is stated.

**Not re-verified here.** The four claims in the repository's own documentation (AgentCore Gateway targets and outbound API-key authorization; `google-adk`'s `mcp<2` pin; Gemini 2.5 Pro availability; Claude Code's header-versus-OAuth behaviour) were verified on 2026-09-19 and the narrowings applied in commit `56f45c5`. If the paper's prose repeats any of them, it should reuse those verdicts and sources.
