# Transient Bone Rule Preview Design

## Goal

Keep rule-matched bones out of the ordinary bone configuration list. Show the
selected rule's effective matches in a read-only preview, while resolving rule
rows only when preview, validation, generation, or driving needs them.

## Stored Data

- `settings.bones` stores manual bone configurations only.
- `settings.bone_rules` remains the canonical rule configuration.
- Rule matches and chain rows are transient derived data.
- Preset schema remains unchanged.
- Legacy rows with `managed_rule_id` are removed during rule operations,
  validation, generation, and export.
- A manual row claimed by any effective rule is removed. Removing or changing
  the rule does not restore its previous manual parameters.

## Rule Resolution

Existing last-rule-wins behavior remains authoritative.

- Preview uses all rules, then selects bones whose final winning rule is the
  active rule.
- Non-chain rules preview each effective matched bone.
- Chain rules validate topology and preview every member of each resolved
  chain.
- Materialization creates temporary root rows for chain rules and temporary
  per-bone rows for non-chain rules.
- Resolution errors include no matches, unsupported chain type, branching,
  disjoint edges, short chains, and unreachable chain members.

## UI

The Bone Matching Rules panel gains a read-only preview for the active rule.

- The preview is stateless and backed by the source armature's bones rather
  than a saved cache.
- It shows only final effective matches; overridden matches are absent.
- Chain preview order follows resolved root-to-child chain order.
- A summary shows effective bone count and, for chain rules, chain count.
- Resolution failures replace the preview with an error message.
- The ordinary bone list hides legacy managed rows immediately, even before
  cleanup runs.
- The old synchronization action no longer materializes rows. Rule add,
  remove, and move operations clean obsolete managed or claimed manual rows.

## Data Flow

Canonical payload:

1. Flush parameter carriers.
2. Remove legacy managed rows and manual rows claimed by effective rules.
3. Serialize manual bones and bone rules without materialization.

Resolved payload:

1. Build the canonical payload.
2. Resolve rules using current bone names and topology.
3. Materialize rule rows into an in-memory payload.
4. Pass that payload to validation, Rigify generation, or drive mapping.

Export saves only the canonical payload because rules already contain their
Rigify type and parameters.

## Driver Helpers

Chain-rule driver helpers must not depend on `managed_rule_id` rows. They
resolve current rule rows directly and flatten members belonging to chain
rules. Those helpers keep `inherit_scale = "NONE"`; other helpers keep
`inherit_scale = "FULL"`.

## Error Handling

- Invalid rule JSON or topology produces the existing configuration error.
- UI preview catches the error and displays it without mutating stored data.
- Validation and generation stop with the same error.
- Cleanup is idempotent and safe when no legacy or claimed rows exist.

## Tests

- Pure tests verify effective per-rule previews and temporary materialization.
- Blender integration verifies ordinary bone rows stay manual-only.
- Integration verifies legacy managed rows and claimed manual rows are removed.
- UI source tests verify the preview list, summary, and managed-row filtering.
- Drive tests verify chain members are derived without managed rows and retain
  scale-inheritance behavior.
- Existing preset round-trip, Rigify generation, collection reference, and
  bind-pose tests remain passing.
