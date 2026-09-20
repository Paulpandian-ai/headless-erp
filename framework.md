# Framework — Agent-Operable Systems of Record

**Status:** working document. This is the conceptual framework behind Section III of the paper.

**Provenance note:** the structure and design decisions below are recorded; the sections marked `TODO` hold prose developed elsewhere and must be filled in from the source session before this document is used for claim verification. Do not verify or cite the `TODO` sections until they contain the real content — an empty or reconstructed claim is worse than a missing one.

---

## 1. Terminology

The central noun is **agent-operable system of record**, not "agent-native ERP". The earlier term overstated the scope (ERP implies functional breadth this work does not claim) and understated the property being described (operability by a non-human principal, which applies to any system of record).

TODO — the full definition as drafted, including what distinguishes *operable* from *reachable*.

---

## 2. The three-tier taxonomy

The earlier binary taxonomy (layerable / kernel-resident) was withdrawn after review. It overstated what is unreachable above a system of record, and real architectures show gradation rather than a boundary.

| Tier | Name | Requirement |
|---|---|---|
| **Tier L** | Layerable | Achievable above the system of record regardless of that system's coverage |
| **Tier A** | Authoritative | Requires authoritative control of the write path, via a control contract |
| **Tier T** | Transactional | Requires transactional access to the system of record; irreducible to a set of external properties |

TODO — the precise criterion separating each tier, and the argument for why Tier T is irreducible.

### 2.1 The control contract

Tier A properties are attainable without transactional access *if and only if* the system of record and the control plane satisfy a control contract.

TODO — the contract's conditions as drafted.

### 2.2 Tier assignment of each property

TODO — the table assigning each governance property (pre-commitment inspection, idempotency, policy enforcement, evidence, compensation, staleness detection, and the rest) to L, A or T, with the reasoning per row.

**Note for verification:** every row in this table that asserts something about what a commercial system can or cannot support is a claim requiring a named public source.

---

## 3. Postures

Four postures, covering the architectures an enterprise can actually be in.

| Posture | Description |
|---|---|
| 1 | TODO |
| 2 | TODO |
| 3 | TODO |
| 4 | System of record plus authoritative control plane — the near-term incumbent-estate architecture |

Posture 4 was added in revision to treat the realistic near-term case seriously rather than dismissing layered approaches.

TODO — the full posture descriptions and what each can and cannot attain.

---

## 4. Readiness profile — twelve dimensions

Expanded from the original nine. The three added in revision are **autonomy envelope**, **data freshness and temporal validity**, and **runtime evaluation**.

| # | Dimension | What it measures |
|---|---|---|
| 1 | TODO | |
| 2 | TODO | |
| 3 | TODO | |
| 4 | TODO | |
| 5 | TODO | |
| 6 | TODO | |
| 7 | TODO | |
| 8 | TODO | |
| 9 | TODO | |
| 10 | Autonomy envelope | TODO |
| 11 | Data freshness and temporal validity | TODO |
| 12 | Runtime evaluation | TODO |

TODO — level definitions per dimension, and any scoring guidance.

**Note for verification:** any dimension whose description asserts what commercial systems typically provide is a claim requiring a source, or must be softened to a general statement.

---

## 5. Functional requirements rather than prescriptive mechanisms

Three prescriptive mechanisms were replaced during revision by the functional requirements they serve. Mechanisms are one way of satisfying a requirement; presenting them as the requirement overstates the claim and invites rejection.

TODO — the three requirements as restated, with the mechanisms named as examples rather than as the claim.

---

## 6. Economics by risk tier

The economics model is organized by risk tier rather than by transaction volume.

TODO — the model as drafted.

---

## 7. Positioning constraints

- Vendor-neutral framing and open-standard protocols are a principled constraint and a competitive position, not a limitation.
- The primary commercial wedge is high-growth software companies outgrowing entry-level accounting systems; physical-goods distributors are secondary. (Recorded for consistency with the product work; not a claim the paper makes.)

---

## 8. Attribution and prior art

The enforcement-coverage bound is a restatement of the complete-mediation principle. It must be cited, not presented as novel:

- J. P. Anderson, *Computer Security Technology Planning Study*, ESD-TR-73-51, 1972.
- J. H. Saltzer and M. D. Schroeder, "The Protection of Information in Computer Systems," *Proceedings of the IEEE*, vol. 63, no. 9, 1975.

TODO — any further prior art the framework leans on, particularly for the tier argument and for automation complacency (Parasuraman and Riley, 1997, is the likely citation for the observability finding in Section V).

---

## 9. Claims requiring verification

Every assertion in this document about what a commercial system does or does not support — named or unnamed — requires a public source. Verdicts:

- **supported-named** — at least one named public system, with URL and exact supporting text
- **supported-general** — the tendency is real but no named example carries it; soften to a general statement in the prose
- **needs-narrowing** — true only under stated conditions; give the narrower wording
- **drop** — no public support

Silence in vendor documentation is not evidence of a missing capability. Where the public docs do not address write semantics, idempotency, or approval routing, say so explicitly rather than inferring a gap.

TODO — the verification table, once the pass has run.
