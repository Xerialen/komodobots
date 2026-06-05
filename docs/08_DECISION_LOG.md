# Decision Log

Status: living document.

Purpose:

Record major project decisions and the evidence that motivated them.

Format:

## Decision

Short title.

### Date

YYYY-MM-DD

### Decision

What was chosen?

### Alternatives Considered

What other options existed?

### Evidence

What findings, measurements, documents, or experiments informed the decision?

### Expected Consequences

What do we expect to happen because of this choice?

### Revisit Conditions

What evidence would justify revisiting the decision?

---

## Initial Decision

### Date

2026-06-05

### Decision

Start from KTX/Frogbots rather than building a new bot framework.

### Alternatives Considered

- New bot architecture.
- Continue directly toward custom simulation stack.

### Evidence

Current evidence is incomplete.

KTX/Frogbots already appear to provide server-native integration, physics participation, combat participation, and MVD recording.

### Expected Consequences

Lower initial implementation cost.

### Revisit Conditions

If movement cannot be isolated and replaced cleanly, or if Frogbot architecture proves excessively restrictive.
