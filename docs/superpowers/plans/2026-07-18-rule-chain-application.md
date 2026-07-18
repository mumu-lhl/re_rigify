# Rule Chain Application Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in rule mode that groups winning matches into linear chains, force-connects only the temporary Metarig, and assigns the Rigify type only to each chain root.

**Architecture:** Pure rule precedence and topology grouping live in `core.py`; Blender topology extraction and incremental RNA synchronization live in `rules.py`. Chain-enabled rules materialize root-only bone rows with exact `chain_bones`, allowing the existing Metarig topology stage to connect children without modifying the source armature.

**Tech Stack:** Python 3, Blender 5.2 RNA, Rigify, `unittest`, Blender MCP, jj.

## Global Constraints

- Use Blender MCP only for Blender execution; never launch a Blender process.
- Preserve schema version `1`; the plugin is not distributed.
- `apply_as_chain` defaults to `false`.
- Rule precedence remains ordered and last-match-wins.
- Chain mode initially supports `limbs.super_finger` and `limbs.spline_tentacle`, minimum two bones each.
- Never connect, reparent, or reposition source-armature bones.
- A chain must be linear, endpoint-aligned, and fully contained in one winning rule result.
- Canonical export excludes materialized managed rows.
- Keep the current `.blend` unsaved.
- Use `rtk` for every shell command and jj for commits.

---

### Task 1: Pure Chain-Aware Rule Resolution

**Files:**
- Modify: `re_rigify/core.py`
- Modify: `tests/test_core.py`

**Interfaces:**
- Consumes: existing `resolve_bone_rules`, `normalize_config`, `ConfigError`, and `DEFAULT_COMPATIBILITY`.
- Produces:
  - `CHAIN_RULE_MIN_LENGTHS: dict[str, int]`
  - `resolve_bone_rule_rows(bone_names, rules, parents=None, aligned_edges=None) -> list[dict]`
  - `materialize_bone_rules(payload, bone_names, parents=None, aligned_edges=None) -> dict`
  - topology-aware optional parameters on `validate_config`.

- [ ] **Step 1: Add failing normalization and topology tests**

Add imports in `tests/test_core.py`:

```python
from re_rigify.core import (
    CHAIN_RULE_MIN_LENGTHS,
    ConfigError,
    materialize_bone_rules,
    normalize_config,
    resolve_bone_rule_rows,
)
```

Add the following tests:

```python
class ChainBoneRuleTests(unittest.TestCase):
    NAMES = [
        "HairA_00", "HairA_01",
        "HairB_00", "HairB_01", "HairB_02",
    ]
    PARENTS = {
        "HairA_00": "Head",
        "HairA_01": "HairA_00",
        "HairB_00": "Head",
        "HairB_01": "HairB_00",
        "HairB_02": "HairB_01",
        "Head": None,
    }
    ALIGNED = {
        ("HairA_00", "HairA_01"),
        ("HairB_00", "HairB_01"),
        ("HairB_01", "HairB_02"),
    }

    def rule(self, **overrides):
        return {
            "rule_id": "hair",
            "kind": "GLOB",
            "pattern": "Hair*",
            "rigify_type": "limbs.spline_tentacle",
            "parameters": {},
            "apply_as_chain": True,
            **overrides,
        }

    def test_normalize_defaults_chain_mode_off(self):
        payload = {
            "format": "re-rigify",
            "schema_version": 1,
            "bones": [],
            "bone_rules": [{
                "rule_id": "hair",
                "kind": "GLOB",
                "pattern": "Hair*",
                "rigify_type": "limbs.spline_tentacle",
                "parameters": {},
            }],
            "collections": [],
            "color_sets": [],
        }
        self.assertFalse(
            normalize_config(payload)["bone_rules"][0]["apply_as_chain"],
        )

    def test_chain_rule_materializes_only_ordered_roots(self):
        rows = resolve_bone_rule_rows(
            self.NAMES, [self.rule()], self.PARENTS, self.ALIGNED,
        )
        self.assertEqual(
            [(row["bone_name"], row["chain_bones"]) for row in rows],
            [
                ("HairA_00", ["HairA_00", "HairA_01"]),
                ("HairB_00", ["HairB_00", "HairB_01", "HairB_02"]),
            ],
        )

    def test_later_rule_splits_chain_before_grouping(self):
        rows = resolve_bone_rule_rows(
            self.NAMES,
            [
                self.rule(),
                self.rule(
                    rule_id="tail",
                    kind="EXACT",
                    pattern="HairB_02",
                    rigify_type="basic.raw_copy",
                    apply_as_chain=False,
                ),
            ],
            self.PARENTS,
            self.ALIGNED,
        )
        self.assertEqual(
            [(row["bone_name"], row["chain_bones"]) for row in rows],
            [
                ("HairA_00", ["HairA_00", "HairA_01"]),
                ("HairB_00", ["HairB_00", "HairB_01"]),
                ("HairB_02", []),
            ],
        )

    def test_chain_rule_rejects_branch(self):
        parents = {
            **self.PARENTS,
            "HairB_X": "HairB_00",
        }
        with self.assertRaisesRegex(ConfigError, "branches at 'HairB_00'"):
            resolve_bone_rule_rows(
                [*self.NAMES, "HairB_X"],
                [self.rule()],
                parents,
                {*self.ALIGNED, ("HairB_00", "HairB_X")},
            )

    def test_chain_rule_rejects_disjoint_edge(self):
        with self.assertRaisesRegex(
            ConfigError, "disjoint edge 'HairB_01' -> 'HairB_02'",
        ):
            resolve_bone_rule_rows(
                self.NAMES,
                [self.rule()],
                self.PARENTS,
                self.ALIGNED - {("HairB_01", "HairB_02")},
            )

    def test_chain_rule_rejects_cycle_without_a_root(self):
        with self.assertRaisesRegex(ConfigError, "no reachable root"):
            resolve_bone_rule_rows(
                ["HairA_00", "HairA_01"],
                [self.rule()],
                {
                    "HairA_00": "HairA_01",
                    "HairA_01": "HairA_00",
                },
                {
                    ("HairA_00", "HairA_01"),
                    ("HairA_01", "HairA_00"),
                },
            )

    def test_chain_rule_rejects_short_component(self):
        with self.assertRaisesRegex(ConfigError, "requires at least 2 bones"):
            resolve_bone_rule_rows(
                ["HairA_00"],
                [self.rule()],
                self.PARENTS,
                set(),
            )

    def test_chain_rule_rejects_unsupported_type(self):
        with self.assertRaisesRegex(ConfigError, "does not support chain rules"):
            resolve_bone_rule_rows(
                self.NAMES,
                [self.rule(rigify_type="basic.raw_copy")],
                self.PARENTS,
                self.ALIGNED,
            )

    def test_materialization_omits_claimed_children(self):
        payload = {
            "format": "re-rigify",
            "schema_version": 1,
            "bones": [],
            "bone_rules": [self.rule()],
            "collections": [],
            "color_sets": [],
        }
        resolved = materialize_bone_rules(
            payload,
            self.NAMES,
            self.PARENTS,
            self.ALIGNED,
        )
        self.assertEqual(
            [
                (item["bone_name"], item["chain_bones"])
                for item in resolved["bones"]
            ],
            [
                ("HairA_00", ["HairA_00", "HairA_01"]),
                ("HairB_00", ["HairB_00", "HairB_01", "HairB_02"]),
            ],
        )
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
rtk python3 -m unittest tests.test_core.ChainBoneRuleTests
```

Expected: import failure for `CHAIN_RULE_MIN_LENGTHS` or
`resolve_bone_rule_rows`.

- [ ] **Step 3: Normalize the new rule field and register supported chain types**

In `re_rigify/core.py`, extend the existing explicit-chain registry and add the
rule registry:

```python
EXPLICIT_CHAIN_MIN_LENGTHS = {
    "limbs.arm": 3,
    "limbs.super_finger": 2,
    "limbs.spline_tentacle": 2,
    "spines.basic_spine": 3,
    "spines.super_head": 2,
}

CHAIN_RULE_MIN_LENGTHS = {
    "limbs.super_finger": 2,
    "limbs.spline_tentacle": 2,
}
```

In the `bone_rules` normalization loop, add:

```python
"apply_as_chain": _require_type(
    item.get("apply_as_chain", False),
    bool,
    f"bone_rules[{index}].apply_as_chain",
),
```

- [ ] **Step 4: Implement topology-aware row resolution**

Add this function after `resolve_bone_rules`:

```python
def resolve_bone_rule_rows(
    bone_names: Iterable[str],
    rules: Iterable[dict[str, Any]],
    parents: dict[str, str | None] | None = None,
    aligned_edges: set[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    names = list(bone_names)
    rule_list = list(rules)
    winners = resolve_bone_rules(names, rule_list)
    if not any(rule.get("apply_as_chain", False) for rule in rule_list):
        return [{
            "bone_name": name,
            "rule": winners[name],
            "chain_bones": [],
        } for name in names if name in winners]
    if parents is None or aligned_edges is None:
        raise ConfigError("chain bone rules require source bone topology")

    children: dict[str, list[str]] = {name: [] for name in names}
    for child in names:
        parent = parents.get(child)
        if parent in children:
            children[parent].append(child)

    def same_winner(left: str, right: str) -> bool:
        return (
            left in winners
            and right in winners
            and winners[left]["rule_id"] == winners[right]["rule_id"]
        )

    rows = []
    claimed = set()
    for name in names:
        rule = winners.get(name)
        if rule is None:
            continue
        if not rule.get("apply_as_chain", False):
            rows.append({
                "bone_name": name,
                "rule": rule,
                "chain_bones": [],
            })
            claimed.add(name)
            continue
        minimum = CHAIN_RULE_MIN_LENGTHS.get(rule["rigify_type"])
        if minimum is None:
            raise ConfigError(
                f"bone rule {rule['pattern']!r} Rigify type "
                f"{rule['rigify_type']!r} does not support chain rules"
            )
        parent = parents.get(name)
        if parent is not None and same_winner(parent, name):
            continue
        chain = [name]
        current = name
        while True:
            matched_children = [
                child for child in children.get(current, ())
                if same_winner(current, child)
            ]
            if len(matched_children) > 1:
                raise ConfigError(
                    f"bone rule {rule['pattern']!r} chain branches "
                    f"at {current!r}"
                )
            if not matched_children:
                break
            child = matched_children[0]
            if (current, child) not in aligned_edges:
                raise ConfigError(
                    f"bone rule {rule['pattern']!r} has disjoint edge "
                    f"{current!r} -> {child!r}"
                )
            chain.append(child)
            current = child
        if len(chain) < minimum:
            raise ConfigError(
                f"bone rule {rule['pattern']!r} chain at {name!r} "
                f"requires at least {minimum} bones"
            )
        claimed.update(chain)
        rows.append({
            "bone_name": name,
            "rule": rule,
            "chain_bones": chain,
        })

    expected = {
        name for name, rule in winners.items()
        if rule.get("apply_as_chain", False)
    }
    unreachable = expected - claimed
    if unreachable:
        raise ConfigError(
            "chain bone rule topology has no reachable root for "
            f"{sorted(unreachable)!r}"
        )
    return rows
```

- [ ] **Step 5: Make materialization root-only**

Change `materialize_bone_rules` to:

```python
def materialize_bone_rules(
    payload: dict[str, Any],
    bone_names: Iterable[str],
    parents: dict[str, str | None] | None = None,
    aligned_edges: set[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    config = normalize_config(payload)
    names = list(bone_names)
    winners = resolve_bone_rules(names, config["bone_rules"])
    rows = resolve_bone_rule_rows(
        names, config["bone_rules"], parents, aligned_edges,
    )
    rows_by_name = {row["bone_name"]: row for row in rows}
    resolved = []
    emitted = set()

    def materialized(row):
        rule = row["rule"]
        return {
            "bone_name": row["bone_name"],
            "rigify_type": rule["rigify_type"],
            "chain_bones": list(row["chain_bones"]),
            "parameters": deepcopy(rule["parameters"]),
            "compatibility": deepcopy(DEFAULT_COMPATIBILITY),
        }

    for item in config["bones"]:
        name = item["bone_name"]
        if name not in winners:
            resolved.append(item)
        elif name in rows_by_name:
            resolved.append(materialized(rows_by_name[name]))
            emitted.add(name)
        # A chain child won by a rule is intentionally omitted.

    for row in rows:
        if row["bone_name"] not in emitted:
            resolved.append(materialized(row))
    return {**config, "bones": resolved}
```

- [ ] **Step 6: Pass optional topology through validation**

Change the signature:

```python
def validate_config(
    payload: dict[str, Any],
    bone_names: Iterable[str],
    available_rig_types: Iterable[str],
    parents: dict[str, str | None] | None = None,
    aligned_edges: set[tuple[str, str]] | None = None,
) -> ValidationResult:
```

At the start, preserve order separately:

```python
ordered_names = list(bone_names)
names = set(ordered_names)
```

Change effective materialization to:

```python
effective = materialize_bone_rules(
    config, ordered_names, parents, aligned_edges,
)
```

- [ ] **Step 7: Run pure tests and verify GREEN**

Run:

```bash
rtk python3 -m unittest tests.test_core.ChainBoneRuleTests
rtk python3 -m unittest discover -s tests -p 'test_*.py'
rtk git diff --check
```

Expected: all chain tests pass and the complete suite reports zero failures.

- [ ] **Step 8: Commit**

```bash
rtk jj commit -m "feat(core): resolve chain-aware bone rules"
```

---

### Task 2: RNA Persistence and Incremental Root Synchronization

**Files:**
- Modify: `re_rigify/blender_config.py`
- Modify: `re_rigify/rules.py`
- Modify: `re_rigify/operators.py`
- Modify: `tests/test_ui_source.py`
- Modify: `tests/blender_integration.py`

**Interfaces:**
- Consumes: Task 1 `resolve_bone_rule_rows`, topology-aware
  `materialize_bone_rules`, and `validate_config`.
- Produces:
  - `rule.apply_as_chain`
  - `armature_rule_topology(armature) -> tuple[dict, set]`
  - root-only `sync_bone_rules(armature)`.

- [ ] **Step 1: Add failing source and Blender integration assertions**

In `tests/test_ui_source.py`, extend the RNA source test:

```python
self.assertIn("apply_as_chain", source)
```

In `tests/blender_integration.py`, create a five-bone, two-chain armature and
assert:

```python
rule.apply_as_chain = True
added, updated, removed = sync_bone_rules(chain_source.data)
assert (added, updated, removed) == (2, 0, 0)
assert [item.bone_name for item in chain_settings.bones] == [
    "HairA_00", "HairB_00",
]
assert [
    [entry.bone_name for entry in item.chain_bones]
    for item in chain_settings.bones
] == [
    ["HairA_00", "HairA_01"],
    ["HairB_00", "HairB_01", "HairB_02"],
]
canonical = armature_to_payload(
    chain_source.data, include_managed=False,
)
assert canonical["bone_rules"][0]["apply_as_chain"] is True
```

- [ ] **Step 2: Run source test and verify RED**

Run:

```bash
rtk python3 -m unittest tests.test_ui_source
```

Expected: failure because `apply_as_chain` is absent from
`RERIGIFY_PG_BoneRule`.

- [ ] **Step 3: Add RNA storage and JSON round trip**

In `RERIGIFY_PG_BoneRule` add:

```python
apply_as_chain: BoolProperty(
    name="Apply as Chain and Force Connect",
    default=False,
)
```

In `armature_to_payload`, serialize:

```python
"apply_as_chain": rule.apply_as_chain,
```

In `payload_to_armature`, load:

```python
rule.apply_as_chain = source["apply_as_chain"]
```

- [ ] **Step 4: Extract Blender topology**

In `re_rigify/rules.py`, import `resolve_bone_rule_rows` and add:

```python
TOPOLOGY_EPSILON = 1e-6


def armature_rule_topology(armature) -> tuple[
    dict[str, str | None],
    set[tuple[str, str]],
]:
    parents = {
        bone.name: bone.parent.name if bone.parent else None
        for bone in armature.bones
    }
    aligned_edges = {
        (bone.parent.name, bone.name)
        for bone in armature.bones
        if bone.parent
        and (bone.head_local - bone.parent.tail_local).length
        <= TOPOLOGY_EPSILON
    }
    return parents, aligned_edges
```

Extend `rule_dicts` with:

```python
"apply_as_chain": rule.apply_as_chain,
```

- [ ] **Step 5: Synchronize only resolved roots**

Replace the winner loop in `sync_bone_rules` with topology-aware rows:

```python
rules = rule_dicts(settings)
parents, aligned_edges = armature_rule_topology(armature)
winners = (
    resolve_bone_rules(armature.bones.keys(), rules) if rules else {}
)
rows = (
    resolve_bone_rule_rows(
        armature.bones.keys(), rules, parents, aligned_edges,
    )
    if rules else []
)
desired = {row["bone_name"]: row for row in rows}
claimed_names = set(winners)
active_name = (
    settings.bones[settings.active_bone_index].bone_name
    if settings.bones else None
)
active_root = next(
    (
        row["bone_name"] for row in rows
        if active_name in row["chain_bones"]
    ),
    active_name,
)
remove_indices = [
    index for index, item in enumerate(settings.bones)
    if (
        item.managed_rule_id and item.bone_name not in desired
        or item.bone_name in claimed_names and item.bone_name not in desired
    )
]
added = updated = 0
with suspend_carrier_updates():
    for index in reversed(remove_indices):
        settings.bones.remove(index)
    for row in rows:
        bone_name = row["bone_name"]
        rule = row["rule"]
        item = next(
            (
                candidate for candidate in settings.bones
                if candidate.bone_name == bone_name
            ),
            None,
        )
        if item is None:
            item = settings.bones.add()
            item.bone_name = bone_name
            added += 1
        else:
            updated += 1
        item.managed_rule_id = rule["rule_id"]
        item.rigify_type = rule["rigify_type"]
        item.parameters_json = json.dumps(
            rule["parameters"], ensure_ascii=False, sort_keys=True,
        )
        apply_chain_bones_to_item(item, row["chain_bones"])
        _apply_compatibility_to_item(item, DEFAULT_COMPATIBILITY)
    if active_root:
        settings.active_bone_index = next(
            (
                index for index, item in enumerate(settings.bones)
                if item.bone_name == active_root
            ),
            min(
                settings.active_bone_index,
                max(0, len(settings.bones) - 1),
            ),
        )
return added, updated, len(remove_indices)
```

Keep parentheses around both removal predicates to avoid precedence ambiguity.

- [ ] **Step 6: Pass source topology through workflows**

In `re_rigify/operators.py`, import `armature_rule_topology`. In
`validate_active` use:

```python
parents, aligned_edges = armature_rule_topology(obj.data)
result = validate_config(
    payload,
    obj.data.bones.keys(),
    available_rig_types(),
    parents,
    aligned_edges,
)
```

In import validation use:

```python
parents, aligned_edges = armature_rule_topology(obj.data)
resolved = materialize_bone_rules(
    payload,
    obj.data.bones.keys(),
    parents,
    aligned_edges,
)
result = validate_config(
    payload,
    obj.data.bones.keys(),
    available_rig_types(),
    parents,
    aligned_edges,
)
```

- [ ] **Step 7: Verify Blender MCP RED/GREEN scenario**

Reload the add-on through the connected Blender MCP after canonically
snapshotting all armatures. Create a temporary armature with:

```text
Head
├─ HairA_00 → HairA_01
└─ HairB_00 → HairB_01 → HairB_02
```

Keep every child `use_connect = False`, but make each child head equal its
parent tail. Add one `Hair*` rule with:

```python
rule.rigify_type = "limbs.spline_tentacle"
rule.apply_as_chain = True
```

Assert:

```python
assert sync_bone_rules(data) == (2, 0, 0)
assert [item.bone_name for item in settings.bones] == [
    "HairA_00", "HairB_00",
]
assert all(
    not data.bones[name].use_connect
    for name in ("HairA_01", "HairB_01", "HairB_02")
)
```

Delete only the temporary object/data and remove the carrier.

- [ ] **Step 8: Run all tests and commit**

Run:

```bash
rtk python3 -m py_compile re_rigify/*.py tests/*.py
rtk python3 -m unittest discover -s tests -p 'test_*.py'
rtk git diff --check
rtk jj commit -m "feat(config): persist chain-aware rules"
```

Expected: zero failures and a clean diff check before the commit.

---

### Task 3: Rule UI, Carrier Root Selection, and Rigify Generation

**Files:**
- Modify: `re_rigify/ui.py`
- Modify: `README.md`
- Modify: `tests/test_ui_source.py`
- Modify: `tests/blender_integration.py`

**Interfaces:**
- Consumes: Task 2 `rule.apply_as_chain`,
  `armature_rule_topology`, and root-only synchronization.
- Produces: rule checkbox UI, root-based rule parameter carrier, and a
  successful spline-tentacle integration path.

- [ ] **Step 1: Add failing UI source tests**

In `tests/test_ui_source.py`, find `RERIGIFY_PT_BoneRules` through the AST and
assert it draws:

```python
self.assertIn(
    "apply_as_chain",
    {
        call.args[1].value
        for call in ast.walk(panel)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "prop"
        and len(call.args) > 1
        and isinstance(call.args[1], ast.Constant)
    },
)
```

- [ ] **Step 2: Run the source test and verify RED**

Run:

```bash
rtk python3 -m unittest tests.test_ui_source
```

Expected: failure because the rule panel does not draw `apply_as_chain`.

- [ ] **Step 3: Draw the chain switch**

In `RERIGIFY_PT_BoneRules.draw`, after the pattern field add:

```python
layout.prop(rule, "apply_as_chain")
```

When the switch is active, add an informational line:

```python
if rule.apply_as_chain:
    layout.label(
        text="Only chain roots receive the Rigify type",
        icon="LINKED",
    )
```

- [ ] **Step 4: Resolve the rule carrier from the first chain root**

Change `_rule_source_bone` in `re_rigify/ui.py`:

```python
def _rule_source_bone(source, rule_index):
    from .rules import armature_rule_topology, rule_dicts
    from .core import resolve_bone_rule_rows

    rules = rule_dicts(source.data.re_rigify)
    parents, aligned_edges = armature_rule_topology(source.data)
    rows = resolve_bone_rule_rows(
        source.data.bones.keys(),
        [rules[rule_index]],
        parents,
        aligned_edges,
    )
    return rows[0]["bone_name"]
```

Existing catches for `ConfigError`, `IndexError`, `StopIteration`, and invalid
JSON continue to make unmatched or invalid rules show an error instead of
writing ID data during panel drawing.

- [ ] **Step 5: Document chain rule behavior**

Add to `README.md` after the bone matching rules paragraph:

```markdown
Enable **Apply as Chain and Force Connect** when one rule matches every member
of several linear chains. Re-Rigify groups final winning matches by source
parenting, assigns the Rigify type only to each chain root, and connects
coincident child joints only on the temporary Metarig. The source armature
remains unchanged. Branches, gaps, short chains, and unsupported Rigify types
are rejected during validation.
```

- [ ] **Step 6: Run a full temporary Rigify MCP generation**

Through connected Blender MCP only:

1. Create a temporary armature with two disconnected source chains whose
   internal endpoints coincide.
2. Add a chain-enabled `Hair*` rule using `limbs.spline_tentacle`.
3. Add one configured UI collection matching `Hair*`.
4. Call `synchronized_payload`, `validate_active`, and `generate_rig`.
5. Assert generation succeeds and contains spline-tentacle master controls for
   both roots.
6. Assert all source child `use_connect` values remain false.
7. Delete every object created after the test's pre-snapshot, remove orphaned
   temporary armature data, and remove the parameter carrier.

Capture these exact result fields:

```python
{
    "managed_roots": ["HairA_00", "HairB_00"],
    "chain_lengths": [2, 3],
    "source_connected_children": 0,
    "generated": True,
    "helper_absent": True,
}
```

- [ ] **Step 7: Run all tests and commit**

Run:

```bash
rtk python3 -m py_compile re_rigify/*.py tests/*.py
rtk python3 -m unittest discover -s tests -p 'test_*.py'
rtk git diff --check
rtk jj commit -m "feat(ui): configure rules as connected chains"
```

Expected: zero failures.

---

### Task 4: Repair and Regenerate the Current Open Project

**Files:**
- No repository files unless verification exposes a regression.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: corrected in-memory rule state and verified generated rig.

- [ ] **Step 1: Snapshot current state through Blender MCP**

Capture without saving:

```python
source = bpy.data.objects["1003_トウカイテイオー_arm"]
canonical = armature_to_payload(
    source.data, include_managed=False,
)
generated = source.re_rigify_generated_rig
hips_basis = generated.pose.bones["hips"].matrix_basis.copy()
source_bind = {
    bone.name: bone.matrix.copy() for bone in source.pose.bones
}
```

Also record the rule ID whose pattern is `Sp_He_Hair*`.

- [ ] **Step 2: Reload and restore the add-on**

Using Blender MCP:

1. Flush and remove the parameter carrier.
2. Canonically snapshot all Re-Rigify armatures.
3. Unregister the add-on.
4. Reload `core`, `compatibility`, `rigify_adapter`, `blender_config`, `rules`,
   `drive`, `generate`, `operators`, and `ui`.
5. Register the add-on.
6. Restore every canonical snapshot with `payload_to_armature`.

Do not save the `.blend`.

- [ ] **Step 3: Enable chain mode on the current hair rule**

Find the stable rule ID or `Sp_He_Hair*` pattern and set:

```python
rule.apply_as_chain = True
added, updated, removed = sync_bone_rules(source.data)
```

Assert:

```python
assert [
    item.bone_name for item in source.data.re_rigify.bones
    if item.managed_rule_id == rule.rule_id
] == [
    "Sp_He_Hair0_C_00",
    "Sp_He_Hair0_L_00",
    "Sp_He_Hair2_L_00",
    "Sp_He_Hair2_R_00",
    "Sp_He_Hair4_C_00",
    "Sp_He_Hair4_L_00",
    "Sp_He_Hair4_R_00",
]
assert sorted(
    len(item.chain_bones)
    for item in source.data.re_rigify.bones
    if item.managed_rule_id == rule.rule_id
) == [2, 2, 3, 3, 3, 3, 6]
```

Assert the 15 source child bones still have `use_connect == False`.

- [ ] **Step 4: Validate, generate, and reconnect**

Use:

```python
checked, errors = validate_active(bpy.context)
assert checked == source
assert errors == ()
payload = synchronized_payload(source, include_managed=True)
generated = generate_rig(bpy.context, source, payload)
mapped, unmatched = connect_source_to_rig(source, generated)
```

Assert:

```python
assert mapped == 277
assert unmatched == []
assert source.re_rigify_generated_rig == generated
```

Confirm generated spline objects or master controls exist for all seven hair
chain roots and no ownership-conflict warning is emitted.

- [ ] **Step 5: Verify bind pose and restore the hips control**

After view-layer update compute:

```python
bind_max_delta = max(
    abs(source.pose.bones[name].matrix[row][col] - before[row][col])
    for name, before in source_bind.items()
    for row in range(4)
    for col in range(4)
)
assert bind_max_delta < 1e-5
```

Restore:

```python
generated.pose.bones["hips"].matrix_basis = hips_basis
bpy.context.view_layer.update()
remove_parameter_carrier()
```

Assert the explicit torso chain remains:

```python
["Hip", "Waist", "Spine", "Chest"]
```

Do not save the `.blend`.

- [ ] **Step 6: Run final repository verification**

Run:

```bash
rtk python3 -m py_compile re_rigify/*.py tests/*.py
rtk python3 -m unittest discover -s tests -p 'test_*.py'
rtk git diff --check
rtk jj status
```

Expected: zero failures, no whitespace errors, and a clean jj working copy.
