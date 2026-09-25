"""Blender-independent configuration validation and bone matching."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from fnmatch import fnmatchcase
import re
from typing import Any, Iterable

from .translations import format_iface, iface_


FORMAT_NAME = "re-rigify"
SCHEMA_VERSION = 1

DEFAULT_COMPATIBILITY = {
    "force_connect_chain": False,
    "skin_eye_compatibility": False,
    "roll_bones_enabled": False,
    "upper_arm_roll_bone": "",
    "forearm_roll_bone": "",
    "eye_forward_axis": "AUTO",
    "upper_lid_pattern": "",
    "lower_lid_pattern": "",
    "synthetic_lids_fallback": False,
    "super_finger_primary_axis": "AUTO",
    "super_finger_roll_alignment": "AUTO",
}

SUPER_FINGER_PRIMARY_AXES = frozenset(
    {"AUTO", "+X", "-X", "+Y", "-Y", "+Z", "-Z"}
)
SUPER_FINGER_ROLL_ALIGNMENTS = frozenset(
    {"AUTO", "GLOBAL_POS_Z", "GLOBAL_NEG_Y"}
)

EXPLICIT_CHAIN_MIN_LENGTHS = {
    "limbs.arm": 3,
    "limbs.leg": 3,
    "limbs.super_finger": 2,
    "limbs.simple_tentacle": 2,
    "limbs.spline_tentacle": 2,
    "spines.basic_spine": 3,
    "spines.basic_tail": 2,
    "spines.super_head": 2,
}

# Chain types generation/compatibility resolve via unique-child parenting
# rather than keyword topology (arm/leg/spine/head).
UNIQUE_CHILD_CHAIN_RIG_TYPES = frozenset({
    "limbs.super_finger",
    "limbs.simple_tentacle",
    "limbs.spline_tentacle",
    "spines.basic_tail",
})

CHAIN_RULE_MIN_LENGTHS = {
    "limbs.super_finger": 2,
    "limbs.spline_tentacle": 2,
}

RIGIFY_DEFAULT_COLOR_SETS = (
    ("Root", (0.5490, 1.0, 1.0), (0.4353, 0.1843, 0.4157), (0.3140, 0.7840, 1.0)),
    ("IK", (0.5490, 1.0, 1.0), (0.6039, 0.0, 0.0), (0.3140, 0.7840, 1.0)),
    ("Special", (0.5490, 1.0, 1.0), (0.9569, 0.7882, 0.0471), (0.3140, 0.7840, 1.0)),
    ("Tweak", (0.5490, 1.0, 1.0), (0.0392, 0.2118, 0.5804), (0.3140, 0.7840, 1.0)),
    ("FK", (0.5490, 1.0, 1.0), (0.1176, 0.5686, 0.0353), (0.3140, 0.7840, 1.0)),
    ("Extra", (0.5490, 1.0, 1.0), (0.9686, 0.2510, 0.0941), (0.3140, 0.7840, 1.0)),
)


def move_selected_indices(
    item_count: int,
    selected_indices: Iterable[int],
    direction: int,
) -> tuple[tuple[int, int], ...]:
    if direction not in {-1, 1}:
        raise ValueError("direction must be -1 or 1")
    selected = {
        index for index in selected_indices
        if 0 <= index < item_count
    }
    operations = []
    ordered = sorted(selected, reverse=direction > 0)
    for source in ordered:
        target = source + direction
        if not 0 <= target < item_count or target in selected:
            continue
        operations.append((source, target))
        selected.remove(source)
        selected.add(target)
    return tuple(operations)


class ConfigError(ValueError):
    pass


def unique_blender_name(name: str, existing_names: Iterable[str]) -> str:
    existing = set(existing_names)
    if name not in existing:
        return name
    match = re.fullmatch(r"(.*?)(?:\.(\d{3}))?", name)
    base = match.group(1) if match else name
    index = 1
    while f"{base}.{index:03d}" in existing:
        index += 1
    return f"{base}.{index:03d}"


@dataclass(frozen=True)
class ValidationResult:
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


def choose_drive_target(
    source_bone_name: str,
    target_bone_names: Iterable[str],
    explicit: dict[str, str] | None = None,
) -> str | None:
    names = set(target_bone_names)
    explicit_target = (explicit or {}).get(source_bone_name)
    if explicit_target in names:
        return explicit_target
    for candidate in (f"ORG-{source_bone_name}", f"DEF-{source_bone_name}", source_bone_name):
        if candidate in names:
            return candidate
    return None


def choose_drive_spec(
    source_bone_name: str,
    target_bone_names: Iterable[str],
    transform_explicit: dict[str, str] | None = None,
    rotation_explicit: dict[str, str] | None = None,
) -> tuple[str, str] | None:
    names = set(target_bone_names)
    rotation_target = (rotation_explicit or {}).get(source_bone_name)
    if rotation_target in names:
        return rotation_target, "ROTATION"
    target = choose_drive_target(source_bone_name, names, transform_explicit)
    return (target, "TRANSFORM") if target is not None else None

def _bones_reachable_from_root(
    root: str,
    operations: Iterable[tuple[str, str, bool]],
) -> set[str]:
    """Follow parent→child topology ops from root only (never upward)."""
    children: dict[str, list[str]] = {}
    for parent, child, _connected in operations:
        children.setdefault(parent, []).append(child)
    found = {root}
    queue = [root]
    while queue:
        current = queue.pop(0)
        for child in children.get(current, ()):
            if child not in found:
                found.add(child)
                queue.append(child)
    return found


def configured_drive_bone_names(
    bone_configs: Iterable[dict[str, Any]],
    parents: dict[str, str | None] | None = None,
) -> set[str]:
    """Source bones that should receive post-generate drive constraints.

    Coverage is:
    - configured roots
    - explicit chain members
    - when *parents* is provided and there is no explicit chain:
      - ``limbs.arm`` / ``limbs.leg`` / spine / head via ``infer_rigify_topology``
      - ``limbs.super_finger`` / tentacle / ``spines.basic_tail`` via
        ``unique_child_chain``

    Collection membership alone does not count. Topology expansion only walks
    parent→child from the root, so ``spines.super_head`` does not pull in the
    neck's parent, and one finger does not claim a sibling finger.
    """
    names: set[str] = set()
    for config in bone_configs:
        root = config.get("bone_name")
        if not isinstance(root, str) or not root:
            continue
        names.add(root)
        explicit_chain = [
            bone for bone in (config.get("chain_bones") or ())
            if isinstance(bone, str) and bone
        ]
        names.update(explicit_chain)
        if explicit_chain or parents is None:
            continue
        if root not in parents:
            continue
        rig_type = config.get("rigify_type") or ""
        if rig_type in UNIQUE_CHILD_CHAIN_RIG_TYPES:
            try:
                names.update(unique_child_chain(root, parents))
            except ConfigError:
                pass
            continue
        try:
            operations = infer_rigify_topology([config], parents)
        except ConfigError:
            continue
        names.update(_bones_reachable_from_root(root, operations))
    return names




def rerigify_mirror_name(name: str) -> str:
    """Mirror bone and collection names for both suffix and prefix naming conventions."""
    try:
        from rigify.utils.naming import mirror_name
        m = mirror_name(name)
        if m != name:
            return m
    except ImportError:
        pass
    # Suffix fallback when rigify is not available
    match = re.search(r"([._-])([LR])$", name, re.IGNORECASE)
    if match:
        sep, side = match.groups()
        opp = "R" if side.upper() == "L" else "L"
        opp = opp.lower() if side.islower() else opp
        return name[:match.start()] + sep + opp
    # Prefix L/R (e.g. LArm -> RArm, LShoulder -> RShoulder, LEye_0_0 -> REye_0_0)
    if re.match(r"^L(?=[A-Z_])", name):
        return "R" + name[1:]
    if re.match(r"^R(?=[A-Z_])", name):
        return "L" + name[1:]
    # Prefix Left/Right
    if re.match(r"^Left(?=[A-Z_])", name):
        return "Right" + name[4:]
    if re.match(r"^Right(?=[A-Z_])", name):
        return "Left" + name[5:]
    if "左" in name:
        return name.replace("左", "右")
    if "右" in name:
        return name.replace("右", "左")
    return name


def mirror_parameter_value(value: Any, name_mapper) -> Any:
    """Recursively mirror bone-name strings inside Rigify parameter values."""
    if isinstance(value, dict):
        return {key: mirror_parameter_value(item, name_mapper) for key, item in value.items()}
    if isinstance(value, list):
        return [mirror_parameter_value(item, name_mapper) for item in value]
    if isinstance(value, str):
        return name_mapper(value)
    return value


def normalize_compatibility(value: object, path: str = "compatibility") -> dict[str, Any]:
    value = _require_type(value, dict, path)
    result = dict(DEFAULT_COMPATIBILITY)
    for name in (
        "force_connect_chain", "skin_eye_compatibility", "synthetic_lids_fallback",
        "roll_bones_enabled",
    ):
        if name in value:
            result[name] = _require_type(value[name], bool, f"{path}.{name}")
    for name in (
        "upper_lid_pattern", "lower_lid_pattern",
        "upper_arm_roll_bone", "forearm_roll_bone",
    ):
        if name in value:
            result[name] = _require_type(value[name], str, f"{path}.{name}")
    if "eye_forward_axis" in value:
        axis = _require_type(value["eye_forward_axis"], str, f"{path}.eye_forward_axis")
        if axis not in {"AUTO", "+X", "-X", "+Y", "-Y"}:
            raise ConfigError(
                format_iface(
                    "{path}.eye_forward_axis is invalid",
                    path=path,
                )
            )
        result["eye_forward_axis"] = axis
    if "super_finger_primary_axis" in value:
        axis = _require_type(
            value["super_finger_primary_axis"],
            str,
            f"{path}.super_finger_primary_axis",
        )
        if axis not in SUPER_FINGER_PRIMARY_AXES:
            raise ConfigError(
                format_iface(
                    "{path} is invalid",
                    path=f"{path}.super_finger_primary_axis",
                )
            )
        result["super_finger_primary_axis"] = axis
    if "super_finger_roll_alignment" in value:
        alignment = _require_type(
            value["super_finger_roll_alignment"],
            str,
            f"{path}.super_finger_roll_alignment",
        )
        if alignment not in SUPER_FINGER_ROLL_ALIGNMENTS:
            raise ConfigError(
                format_iface(
                    "{path} is invalid",
                    path=f"{path}.super_finger_roll_alignment",
                )
            )
        result["super_finger_roll_alignment"] = alignment
    return result


def mirror_compatibility(value: dict[str, Any], name_mapper) -> dict[str, Any]:
    result = normalize_compatibility(value)
    result["upper_lid_pattern"] = name_mapper(result["upper_lid_pattern"])
    result["lower_lid_pattern"] = name_mapper(result["lower_lid_pattern"])
    result["upper_arm_roll_bone"] = name_mapper(result["upper_arm_roll_bone"])
    result["forearm_roll_bone"] = name_mapper(result["forearm_roll_bone"])
    result["eye_forward_axis"] = {
        "+X": "-X",
        "-X": "+X",
    }.get(result["eye_forward_axis"], result["eye_forward_axis"])
    if result["super_finger_roll_alignment"] == "AUTO":
        result["super_finger_primary_axis"] = {
            "+X": "-X",
            "-X": "+X",
            "+Y": "-Y",
            "-Y": "+Y",
            "+Z": "-Z",
            "-Z": "+Z",
        }.get(
            result["super_finger_primary_axis"],
            result["super_finger_primary_axis"],
        )
    return result


def unique_child_chain(root: str, parents: dict[str, str | None]) -> list[str]:
    if root not in parents:
        raise ConfigError(
            format_iface(
                "bone does not exist: {bone_name!r}",
                bone_name=root,
            )
        )
    children: dict[str, list[str]] = {name: [] for name in parents}
    for child, parent in parents.items():
        if parent:
            children.setdefault(parent, []).append(child)
    chain = [root]
    while True:
        candidates = sorted(children.get(chain[-1], ()))
        if not candidates:
            return chain
        if len(candidates) > 1:
            raise ConfigError(
                format_iface(
                    "{bone_name!r} has ambiguous child chain: {children}",
                    bone_name=chain[-1],
                    children=", ".join(candidates),
                )
            )
        chain.append(candidates[0])


def remove_collection_references(parameters: dict[str, Any], collection_name: str) -> dict[str, Any]:
    result = dict(parameters)
    for name, value in parameters.items():
        if name.endswith("_coll_refs") and isinstance(value, list):
            result[name] = [item for item in value if item != collection_name]
    return result


def rename_collection_references(
    parameters: dict[str, Any],
    old_name: str,
    new_name: str,
) -> dict[str, Any]:
    result = dict(parameters)
    for name, value in parameters.items():
        if name.endswith("_coll_refs") and isinstance(value, list):
            result[name] = [
                new_name if item == old_name else item for item in value
            ]
    return result


def resolve_bone_rules(
    bone_names: Iterable[str],
    rules: Iterable[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    names = list(bone_names)
    winners: dict[str, dict[str, Any]] = {}
    for rule in rules:
        if rule["kind"] == "EXACT":
            matches = [rule["pattern"]] if rule["pattern"] in names else []
        else:
            matches = [
                name for name in names if fnmatchcase(name, rule["pattern"])
            ]
        if not matches:
            raise ConfigError(
                format_iface(
                    "{kind} bone rule {pattern!r} matched no bones",
                    kind=rule["kind"],
                    pattern=rule["pattern"],
                )
            )
        for name in matches:
            winners[name] = rule
    return {name: winners[name] for name in names if name in winners}


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
        raise ConfigError(
            iface_("chain bone rules require source bone topology")
        )

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
                format_iface(
                    "bone rule {pattern!r} Rigify type {rigify_type!r} "
                    "does not support chain rules",
                    pattern=rule["pattern"],
                    rigify_type=rule["rigify_type"],
                )
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
                    format_iface(
                        "bone rule {pattern!r} chain branches at {bone_name!r}",
                        pattern=rule["pattern"],
                        bone_name=current,
                    )
                )
            if not matched_children:
                break
            child = matched_children[0]
            if (current, child) not in aligned_edges:
                raise ConfigError(
                    format_iface(
                        "bone rule {pattern!r} has disjoint edge "
                        "{parent!r} -> {child!r}",
                        pattern=rule["pattern"],
                        parent=current,
                        child=child,
                    )
                )
            chain.append(child)
            current = child
        if len(chain) < minimum:
            raise ConfigError(
                format_iface(
                    "bone rule {pattern!r} chain at {bone_name!r} "
                    "requires at least {minimum} bones",
                    pattern=rule["pattern"],
                    bone_name=name,
                    minimum=minimum,
                )
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
            format_iface(
                "chain bone rule topology has no reachable root for {bones!r}",
                bones=sorted(unreachable),
            )
        )
    return rows


def preview_bone_rule(
    bone_names: Iterable[str],
    rules: Iterable[dict[str, Any]],
    rule_id: str,
    parents: dict[str, str | None] | None = None,
    aligned_edges: set[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    rows = resolve_bone_rule_rows(
        bone_names, rules, parents, aligned_edges,
    )
    selected = [
        row for row in rows
        if row["rule"]["rule_id"] == rule_id
    ]
    preview_names = [
        bone_name
        for row in selected
        for bone_name in (row["chain_bones"] or [row["bone_name"]])
    ]
    return {
        "bone_names": preview_names,
        "chain_count": sum(
            bool(row["chain_bones"]) for row in selected
        ),
        "rows": selected,
    }


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
    for row in rows:
        if row["bone_name"] not in emitted:
            resolved.append(materialized(row))
    return {**config, "bones": resolved}


def infer_rigify_topology(
    bone_configs: Iterable[dict[str, Any]], parents: dict[str, str | None]
) -> list[tuple[str, str, bool]]:
    """Infer common Rigify chains from disconnected production-skeleton parenting."""
    children: dict[str, list[str]] = {name: [] for name in parents}
    for child, parent in parents.items():
        if parent:
            children.setdefault(parent, []).append(child)

    def normalized(name: str) -> str:
        return name.lower().replace(".", "_").replace("-", "_")

    def descendants(root: str) -> list[str]:
        result, queue = [], list(children.get(root, ()))
        while queue:
            name = queue.pop(0)
            result.append(name)
            queue.extend(children.get(name, ()))
        return result

    def find(root: str, keywords: tuple[str, ...], *, exclude: set[str] | None = None) -> str | None:
        excluded = exclude or set()
        for keyword in keywords:
            for name in descendants(root):
                if name not in excluded and keyword in normalized(name):
                    return name
        return None

    operations: list[tuple[str, str, bool]] = []
    for config in bone_configs:
        root = config["bone_name"]
        rig_type = config["rigify_type"]
        explicit_chain = list(config.get("chain_bones", []))
        if explicit_chain:
            if rig_type == "limbs.leg":
                # Rigify leg: thigh→knee→foot→toe connected; optional heel
                # under foot, unconnected. Explicit chains do not invent a heel.
                main_chain = explicit_chain[:4]
                operations.extend(
                    (parent, child, True)
                    for parent, child in zip(main_chain, main_chain[1:])
                )
                if len(explicit_chain) >= 5:
                    foot = explicit_chain[2]
                    operations.append((foot, explicit_chain[4], False))
            else:
                operations.extend(
                    (parent, child, True)
                    for parent, child in zip(explicit_chain, explicit_chain[1:])
                )
            continue
        if rig_type == "limbs.arm":
            lower = find(root, ("elbow", "forearm", "lower_arm", "ひじ"))
            hand = find(lower, ("wrist", "hand", "手首")) if lower else None
            if not lower or not hand:
                raise ConfigError(
                    format_iface(
                        "{root!r} ({rigify_type}) requires an upper-arm, "
                        "forearm/elbow, and hand/wrist chain",
                        root=root,
                        rigify_type=rig_type,
                    )
                )
            operations.extend(((root, lower, True), (lower, hand, True)))
        elif rig_type == "limbs.leg":
            knee = find(root, ("knee", "shin", "lower_leg", "ひざ"))
            foot = (
                find(knee, ("ankle_offset", "foot", "ankle", "足首"))
                if knee else None
            )
            toe = find(foot, ("toe", "つま先")) if foot else None
            heel = None
            if knee and foot and toe:
                heel = find(knee, ("heel", "extra"), exclude={foot, toe})
                if heel is None:
                    heel = next(
                        (
                            name for name in descendants(knee)
                            if name not in {foot, toe}
                            and "ankle" in normalized(name)
                            and "offset" not in normalized(name)
                        ),
                        None,
                    )
            if not knee or not foot or not toe:
                raise ConfigError(
                    format_iface(
                        "{root!r} ({rigify_type}) requires thigh, knee/shin, "
                        "foot, and toe bones",
                        root=root,
                        rigify_type=rig_type,
                    )
                )
            operations.extend(
                ((root, knee, True), (knee, foot, True), (foot, toe, True))
            )
            if heel is not None:
                operations.append((foot, heel, False))
        elif rig_type == "spines.basic_spine":
            chain = [root]
            current = root
            while len(chain) < 8:
                direct = children.get(current, [])
                preferred = [
                    name for name in direct
                    if any(
                        key in normalized(name)
                        for key in ("spine", "chest", "torso", "上半身")
                    )
                ]
                if len(preferred) == 1:
                    current = preferred[0]
                elif len(direct) == 1:
                    current = direct[0]
                else:
                    break
                chain.append(current)
            if len(chain) < 3:
                raise ConfigError(
                    format_iface(
                        "{root!r} ({rigify_type}) requires a chain of "
                        "at least 3 bones",
                        root=root,
                        rigify_type=rig_type,
                    )
                )
            operations.extend((parent, child, True) for parent, child in zip(chain, chain[1:]))
        elif rig_type == "spines.super_head":
            head = find(root, ("head", "頭"))
            if not head:
                raise ConfigError(
                    format_iface(
                        "{root!r} ({rigify_type}) requires a connected "
                        "head child",
                        root=root,
                        rigify_type=rig_type,
                    )
                )
            if parent := parents.get(root):
                operations.append((parent, root, False))
            operations.append((root, head, True))
    return operations

def _toe_marker_geometry(
    foot: dict[str, Any],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Build a short connected toe marker extending forward from the foot bone tail."""
    foot_head = tuple(float(v) for v in foot["head"])
    foot_tail = tuple(float(v) for v in foot["tail"])
    dx = foot_tail[0] - foot_head[0]
    dy = foot_tail[1] - foot_head[1]
    dz = foot_tail[2] - foot_head[2]
    foot_len = sum((a - b) ** 2 for a, b in zip(foot_head, foot_tail)) ** 0.5
    if foot_len < 1e-4:
        dx, dy, dz, foot_len = 0.0, -0.1, 0.0, 0.1
    toe_len = max(foot_len * 0.4, 0.04)
    scale = toe_len / foot_len
    head = foot_tail
    tail = (foot_tail[0] + dx * scale, foot_tail[1] + dy * scale, foot_tail[2] + dz * scale)
    return head, tail


def _heel_marker_geometry(
    foot: dict[str, Any],
    toe: dict[str, Any],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Build a short unconnected heel marker under the foot bone."""
    foot_head = tuple(float(v) for v in foot["head"])
    foot_tail = tuple(float(v) for v in foot["tail"])
    toe_head = tuple(float(v) for v in toe["head"])
    foot_len = sum((a - b) ** 2 for a, b in zip(foot_head, foot_tail)) ** 0.5
    length = max(foot_len * 0.35, 0.03)
    ground_z = min(foot_tail[2], toe_head[2]) * 0.5
    if ground_z <= 0:
        ground_z = foot_tail[2] * 0.3
    if ground_z > foot_tail[2]:
        ground_z = foot_tail[2] * 0.5
    head = (foot_head[0], foot_head[1], ground_z)
    tail = (head[0], head[1] + length, head[2])
    return head, tail


def plan_missing_leg_heels(
    bone_configs: Iterable[dict[str, Any]],
    bones: dict[str, dict[str, Any]],
    parents: dict[str, str | None] | None = None,
) -> list[dict[str, Any]]:
    """Plan temporary heel (and toe if needed) markers for limbs.leg when the source has none.

    Rigify requires an unconnected heel under the foot, and at least 4 main chain
    bones (thigh->knee->foot->toe). Re-Rigify keeps the source armature unchanged
    and only materializes these bones on the temporary metarig copy.
    """
    parent_map = dict(parents or {})
    children: dict[str, list[str]] = {name: [] for name in parent_map}
    for child, parent in parent_map.items():
        if parent:
            children.setdefault(parent, []).append(child)

    def normalized(name: str) -> str:
        return name.lower().replace(".", "_").replace("-", "_")

    def descendants(root: str) -> list[str]:
        result, queue = [], list(children.get(root, ()))
        while queue:
            name = queue.pop(0)
            result.append(name)
            queue.extend(children.get(name, ()))
        return result

    def find(
        root: str | None,
        keywords: tuple[str, ...],
        *,
        exclude: set[str] | None = None,
    ) -> str | None:
        if not root:
            return None
        excluded = exclude or set()
        for keyword in keywords:
            for name in descendants(root):
                if name not in excluded and keyword in normalized(name):
                    return name
        return None

    plans: list[dict[str, Any]] = []
    used_names = set(bones)

    for config in bone_configs:
        if config.get("rigify_type") != "limbs.leg":
            continue
        root = config["bone_name"]
        explicit_chain = list(config.get("chain_bones") or [])
        foot_name = None
        toe_name = None
        heel_name = None
        toe_dict = None

        if explicit_chain:
            if len(explicit_chain) < 3:
                continue
            foot_name = explicit_chain[2]
            if len(explicit_chain) == 3:
                if foot_name in bones:
                    toe_name = unique_blender_name(f"{root}_toe", used_names)
                    toe_head, toe_tail = _toe_marker_geometry(bones[foot_name])
                    plans.append({
                        "name": toe_name,
                        "parent": foot_name,
                        "head": toe_head,
                        "tail": toe_tail,
                        "use_connect": True,
                    })
                    used_names.add(toe_name)
                    toe_dict = {"head": toe_head, "tail": toe_tail}
                heel_name = unique_blender_name(f"{root}_heel", used_names)
            else:
                toe_name = explicit_chain[3]
                toe_dict = bones.get(toe_name)
                if len(explicit_chain) >= 5:
                    heel_name = explicit_chain[4]
                else:
                    heel_name = unique_blender_name(f"{root}_heel", used_names)
        else:
            knee = find(root, ("knee", "shin", "lower_leg", "ひざ"))
            foot_name = (
                find(knee, ("ankle_offset", "foot", "ankle", "足首"))
                if knee else None
            )
            toe_name = find(foot_name, ("toe", "つま先")) if foot_name else None
            toe_dict = bones.get(toe_name) if toe_name else None
            heel_name = None
            if knee and foot_name and toe_name:
                heel_name = find(knee, ("heel", "extra"), exclude={foot_name, toe_name})
                if heel_name is None:
                    heel_name = next(
                        (
                            name for name in descendants(knee)
                            if name not in {foot_name, toe_name}
                            and "ankle" in normalized(name)
                            and "offset" not in normalized(name)
                        ),
                        None,
                    )
            if heel_name is not None:
                continue
            if not foot_name or not toe_name:
                continue
            heel_name = unique_blender_name(f"{root}_heel", used_names)

        if not foot_name or not toe_name or not heel_name:
            continue
        if heel_name in bones:
            continue
        if foot_name not in bones or toe_dict is None:
            continue

        head, tail = _heel_marker_geometry(bones[foot_name], toe_dict)
        plans.append({
            "name": heel_name,
            "parent": foot_name,
            "head": head,
            "tail": tail,
            "use_connect": False,
        })
        used_names.add(heel_name)

    return plans


def arrange_collection_layout(collections: list[dict]) -> list[dict]:
    """Arrange bone collections into standard categorized UI rows.

    Layout rules from Re-Rigify convention:
    - Row 1: Root, Torso
    - Row 2: Torso FK, Torso Tweak
    - Row 3: Head, Face, Head Tweak
    - Row 4: <empty>
    - Row 5: Arm.L, Arm.R
    - Row 6: Arm FK.L, Arm FK.R
    - Row 7: Arm Tweak.L, Arm Tweak.R
    - Row 8: <empty>
    - Row 9: Leg.L, Leg.R
    - Row 10: Leg FK.L, Leg FK.R
    - Row 11: Leg Tweak.L, Leg Tweak.R
    - Row 12: <empty>
    - Row 13: Fingers.L, Fingers.R
    - Row 14: Fingers Tweak.L, Fingers Tweak.R
    - Row 15+: Other collections
    """
    has_finger_ik = any(
        any(k in c.get("name", "").lower() for k in ("finger", "指", "thumb", "index", "pinky", "ring"))
        and bool(re.search(r"(?:^|[\s._-])IK(?:$|[\s._-])", c.get("name", "").upper()))
        for c in collections
    )

    def categorize(name: str):
        upper = name.upper()
        lower = name.lower()
        is_fk = bool(re.search(r"(?:^|[\s._-])FK(?:$|[\s._-])", upper))
        is_ik = bool(re.search(r"(?:^|[\s._-])IK(?:$|[\s._-])", upper))
        is_tweak = "TWEAK" in upper

        if re.search(r"(?:^|[\s._-])L(?:$|[\s._-])", upper) or "左" in name or "left" in lower:
            side_idx = 0
        elif re.search(r"(?:^|[\s._-])R(?:$|[\s._-])", upper) or "右" in name or "right" in lower:
            side_idx = 1
        else:
            side_idx = 2

        if (
            lower == "root"
            or lower in {"root", "center", "全ての親"}
            or (("root" in lower or "center" in lower) and not is_fk and not is_tweak)
        ):
            return 1, (0, side_idx, name), "Root", "Root", True
        elif any(k in lower for k in ("torso", "spine", "腰", "上半身", "下半身")):
            if is_fk:
                return 2, (0, side_idx, name), "FK", "FK", False
            elif is_tweak:
                return 2, (1, side_idx, name), "Tweak", "Tweak", False
            else:
                return 1, (1, side_idx, name), "Torso", "Special", True
        elif any(k in lower for k in ("head", "neck", "首", "頭")):
            if is_tweak:
                return 3, (2, side_idx, name), "Tweak", "Tweak", False
            else:
                return 3, (0, side_idx, name), "Head", "Special", True
        elif any(k in lower for k in ("face", "顔", "目", "eye")):
            if is_tweak:
                return 3, (2, side_idx, name), "Tweak", "Tweak", False
            else:
                return 3, (1, side_idx, name), "Face", "Special", True
        elif any(k in lower for k in ("arm", "hand", "肩", "腕", "手首")):
            if is_fk:
                return 6, (side_idx, name), "FK", "FK", False
            elif is_tweak:
                return 7, (side_idx, name), "Tweak", "Tweak", False
            else:
                return 5, (side_idx, name), name, "IK", True
        elif any(k in lower for k in ("leg", "foot", "足", "thigh", "shin", "knee")):
            if is_fk:
                return 10, (side_idx, name), "FK", "FK", False
            elif is_tweak:
                return 11, (side_idx, name), "Tweak", "Tweak", False
            else:
                return 9, (side_idx, name), name, "IK", True
        elif any(k in lower for k in ("finger", "指", "thumb", "index", "pinky", "ring")):
            if is_tweak:
                tweak_row = 15 if has_finger_ik else 14
                return tweak_row, (side_idx, name), "Tweak", "Tweak", False
            elif is_ik:
                return 14, (side_idx, name), "IK", "IK", False
            else:
                return 13, (side_idx, name), name, "Extra", True
        else:
            vis = not (is_fk or is_tweak)
            color = "FK" if is_fk else ("Tweak" if is_tweak else "Special")
            return 16, (side_idx, name), name, color, vis

    rows: dict[int, list[tuple[Any, dict]]] = {}
    for col in collections:
        item = deepcopy(col)
        name = item.get("name", "")
        row_id, sort_key, title, color_set, visible = categorize(name)
        item["ui_row"] = row_id
        item["ui_title"] = title
        item["color_set"] = item.get("color_set") or color_set
        item["visible_after_generation"] = visible
        rows.setdefault(row_id, []).append((sort_key, item))

    result = []
    for row_id in sorted(rows.keys()):
        items_in_row = rows[row_id]
        items_in_row.sort(key=lambda pair: pair[0])
        for order, (_sort_key, item) in enumerate(items_in_row):
            item["row_order"] = order
            result.append(item)

    return result



def _require_type(value: Any, expected: type, path: str) -> Any:
    if not isinstance(value, expected):
        raise ConfigError(
            format_iface(
                "{path} must be {expected}",
                path=path,
                expected=expected.__name__,
            )
        )
    return value


def normalize_config(payload: dict[str, Any]) -> dict[str, Any]:
    _require_type(payload, dict, "configuration")
    if payload.get("format") != FORMAT_NAME:
        raise ConfigError(
            format_iface(
                "format must be {format_name!r}",
                format_name=FORMAT_NAME,
            )
        )
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ConfigError(
            format_iface(
                "unsupported schema_version: {version!r}",
                version=payload.get("schema_version"),
            )
        )

    bones = _require_type(payload.get("bones"), list, "bones")
    bone_rules = _require_type(payload.get("bone_rules", []), list, "bone_rules")
    collections = _require_type(payload.get("collections"), list, "collections")
    color_sets = _require_type(payload.get("color_sets", []), list, "color_sets")
    root_color_set = _require_type(
        payload.get("root_color_set", ""), str, "root_color_set",
    )
    normalized_bones: list[dict[str, Any]] = []
    normalized_bone_rules: list[dict[str, Any]] = []
    normalized_collections: list[dict[str, Any]] = []
    normalized_color_sets: list[dict[str, Any]] = []

    for index, item in enumerate(bones):
        item = _require_type(item, dict, f"bones[{index}]")
        bone_name = _require_type(item.get("bone_name"), str, f"bones[{index}].bone_name")
        rigify_type = _require_type(item.get("rigify_type"), str, f"bones[{index}].rigify_type")
        chain_bones = _require_type(
            item.get("chain_bones", []), list, f"bones[{index}].chain_bones"
        )
        for chain_index, chain_bone in enumerate(chain_bones):
            _require_type(
                chain_bone,
                str,
                f"bones[{index}].chain_bones[{chain_index}]",
            )
        parameters = _require_type(item.get("parameters", {}), dict, f"bones[{index}].parameters")
        compatibility = normalize_compatibility(
            item.get("compatibility", {}),
            f"bones[{index}].compatibility",
        )
        if rigify_type not in EXPLICIT_CHAIN_MIN_LENGTHS:
            chain_bones = []
        normalized_bones.append({
            "bone_name": bone_name,
            "rigify_type": rigify_type,
            "chain_bones": list(chain_bones),
            "parameters": parameters,
            "compatibility": compatibility,
        })

    for index, item in enumerate(bone_rules):
        item = _require_type(item, dict, f"bone_rules[{index}]")
        rule_id = _require_type(
            item.get("rule_id"), str, f"bone_rules[{index}].rule_id",
        )
        kind = _require_type(
            item.get("kind"), str, f"bone_rules[{index}].kind",
        )
        pattern = _require_type(
            item.get("pattern"), str, f"bone_rules[{index}].pattern",
        )
        rigify_type = _require_type(
            item.get("rigify_type"), str, f"bone_rules[{index}].rigify_type",
        )
        parameters = _require_type(
            item.get("parameters", {}), dict, f"bone_rules[{index}].parameters",
        )
        apply_as_chain = _require_type(
            item.get("apply_as_chain", False),
            bool,
            f"bone_rules[{index}].apply_as_chain",
        )
        if not rule_id:
            raise ConfigError(
                format_iface(
                    "{path} is empty",
                    path=f"bone_rules[{index}].rule_id",
                )
            )
        if kind not in {"EXACT", "GLOB"}:
            raise ConfigError(
                format_iface(
                    "{path} is invalid",
                    path=f"bone_rules[{index}].kind",
                )
            )
        if not pattern:
            raise ConfigError(
                format_iface(
                    "{path} is empty",
                    path=f"bone_rules[{index}].pattern",
                )
            )
        normalized_bone_rules.append({
            "rule_id": rule_id,
            "kind": kind,
            "pattern": pattern,
            "rigify_type": rigify_type,
            "parameters": parameters,
            "apply_as_chain": apply_as_chain,
        })

    for index, item in enumerate(collections):
        item = _require_type(item, dict, f"collections[{index}]")
        name = _require_type(item.get("name"), str, f"collections[{index}].name")
        ui_title = _require_type(item.get("ui_title", ""), str, f"collections[{index}].ui_title")
        ui_row = _require_type(item.get("ui_row", 0), int, f"collections[{index}].ui_row")
        row_order = _require_type(item.get("row_order", 0), int, f"collections[{index}].row_order")
        color_set = _require_type(item.get("color_set", ""), str, f"collections[{index}].color_set")
        visible_after_generation = _require_type(
            item.get("visible_after_generation", True),
            bool,
            f"collections[{index}].visible_after_generation",
        )
        if ui_row < 0 or row_order < 0:
            raise ConfigError(
                format_iface(
                    "{path} row values must be non-negative",
                    path=f"collections[{index}]",
                )
            )
        rules = _require_type(item.get("rules", []), list, f"collections[{index}].rules")
        normalized_rules = []
        for rule_index, rule in enumerate(rules):
            rule = _require_type(rule, dict, f"collections[{index}].rules[{rule_index}]")
            kind = rule.get("kind")
            pattern = rule.get("pattern")
            if kind not in {"EXACT", "GLOB"}:
                raise ConfigError(
                    format_iface(
                        "{path} is invalid",
                        path=(
                            f"collections[{index}].rules[{rule_index}].kind"
                        ),
                    )
                )
            _require_type(pattern, str, f"collections[{index}].rules[{rule_index}].pattern")
            if not pattern:
                raise ConfigError(
                    format_iface(
                        "{path} is empty",
                        path=(
                            f"collections[{index}].rules[{rule_index}].pattern"
                        ),
                    )
                )
            normalized_rules.append({"kind": kind, "pattern": pattern})
        normalized_collections.append({
            "name": name,
            "ui_title": ui_title,
            "ui_row": ui_row,
            "row_order": row_order,
            "color_set": color_set,
            "visible_after_generation": visible_after_generation,
            "rules": normalized_rules,
        })

    for index, item in enumerate(color_sets):
        item = _require_type(item, dict, f"color_sets[{index}]")
        name = _require_type(item.get("name"), str, f"color_sets[{index}].name")
        colors = {}
        for field in ("active", "normal", "select"):
            value = _require_type(item.get(field), list, f"color_sets[{index}].{field}")
            if len(value) != 3 or any(not isinstance(component, (int, float)) for component in value):
                raise ConfigError(
                    format_iface(
                        "{path} must contain three numbers",
                        path=f"color_sets[{index}].{field}",
                    )
                )
            if any(component < 0.0 or component > 1.0 for component in value):
                raise ConfigError(
                    format_iface(
                        "{path} values must be between 0 and 1",
                        path=f"color_sets[{index}].{field}",
                    )
                )
            colors[field] = [float(component) for component in value]
        standard_colors_lock = _require_type(
            item.get("standard_colors_lock", False), bool,
            f"color_sets[{index}].standard_colors_lock",
        )
        normalized_color_sets.append({
            "name": name,
            **colors,
            "standard_colors_lock": standard_colors_lock,
        })

    normalized = {
        "format": FORMAT_NAME,
        "schema_version": SCHEMA_VERSION,
        "bones": normalized_bones,
        "bone_rules": normalized_bone_rules,
        "collections": normalized_collections,
        "color_sets": normalized_color_sets,
    }
    if "root_color_set" in payload:
        normalized["root_color_set"] = root_color_set
    return normalized


def resolve_collection_rules(
    bone_names: Iterable[str],
    collections: Iterable[dict[str, Any]],
    allow_missing_exact: Iterable[str] | None = None,
) -> dict[str, list[str]]:
    names = list(bone_names)
    allowed_missing = set(allow_missing_exact or ())
    resolved: dict[str, list[str]] = {}
    for collection in collections:
        members: list[str] = []
        for rule in collection.get("rules", []):
            pattern = rule["pattern"]
            if rule["kind"] == "EXACT":
                matches = [pattern] if pattern in names else []
            else:
                matches = [name for name in names if fnmatchcase(name, pattern)]
            if not matches:
                if rule["kind"] == "EXACT" and pattern in allowed_missing:
                    continue
                raise ConfigError(
                    format_iface(
                        "{kind} pattern {pattern!r} in collection "
                        "{collection!r} matched no bones",
                        kind=rule["kind"],
                        pattern=pattern,
                        collection=collection["name"],
                    )
                )
            for name in matches:
                if name not in members:
                    members.append(name)
        resolved[collection["name"]] = members
    return resolved



def validate_config(
    payload: dict[str, Any],
    bone_names: Iterable[str],
    available_rig_types: Iterable[str],
    parents: dict[str, str | None] | None = None,
    aligned_edges: set[tuple[str, str]] | None = None,
) -> ValidationResult:
    try:
        config = normalize_config(payload)
    except ConfigError as exc:
        return ValidationResult((str(exc),))

    errors: list[str] = []
    ordered_names = list(bone_names)
    names = set(ordered_names)
    rig_types = set(available_rig_types)
    seen_bones: set[str] = set()
    seen_collections: set[str] = set()
    managed_collection_names = {item["name"] for item in config["collections"]}
    seen_color_sets: set[str] = set()
    occupied_slots: set[tuple[int, int]] = set()

    def validate_collection_refs(owner, parameters):
        for parameter, references in parameters.items():
            if not parameter.endswith("_coll_refs"):
                continue
            if (
                not isinstance(references, list)
                or any(not isinstance(ref, str) for ref in references)
            ):
                errors.append(
                    format_iface(
                        "{owner} parameter {parameter!r} must be a list "
                        "of collection names",
                        owner=owner,
                        parameter=parameter,
                    )
                )
                continue
            for reference in references:
                if reference not in managed_collection_names:
                    errors.append(
                        format_iface(
                            "{owner} parameter {parameter!r} references "
                            "unknown managed collection: {reference!r}",
                            owner=owner,
                            parameter=parameter,
                            reference=reference,
                        )
                    )

    for item in config["color_sets"]:
        name = item["name"]
        if not name:
            errors.append(iface_("color set name is empty"))
        elif name in seen_color_sets:
            errors.append(
                format_iface(
                    "duplicate color set: {name!r}",
                    name=name,
                )
            )
        seen_color_sets.add(name)

    root_color_set = config.get("root_color_set", "")
    if root_color_set and root_color_set not in seen_color_sets:
        errors.append(
            format_iface(
                "root control references unknown color set: {color_set!r}",
                color_set=root_color_set,
            )
        )

    seen_rule_ids = set()
    for rule in config["bone_rules"]:
        if rule["rule_id"] in seen_rule_ids:
            errors.append(
                format_iface(
                    "duplicate bone rule id: {rule_id!r}",
                    rule_id=rule["rule_id"],
                )
            )
        seen_rule_ids.add(rule["rule_id"])
        if rule["rigify_type"] not in rig_types:
            errors.append(
                format_iface(
                    "Rigify type is unavailable: {rigify_type!r}",
                    rigify_type=rule["rigify_type"],
                )
            )
        validate_collection_refs(
            f"bone rule {rule['pattern']!r}", rule["parameters"],
        )

    try:
        effective = materialize_bone_rules(
            config, ordered_names, parents, aligned_edges,
        )
    except ConfigError as exc:
        errors.append(str(exc))
        effective = config

    for item in effective["bones"]:
        name = item["bone_name"]
        if name in seen_bones:
            errors.append(
                format_iface(
                    "duplicate bone configuration: {bone_name!r}",
                    bone_name=name,
                )
            )
        seen_bones.add(name)
        if name not in names:
            errors.append(
                format_iface(
                    "bone does not exist: {bone_name!r}",
                    bone_name=name,
                )
            )
        if item["rigify_type"] not in rig_types:
            errors.append(
                format_iface(
                    "Rigify type is unavailable: {rigify_type!r}",
                    rigify_type=item["rigify_type"],
                )
            )
        chain_bones = item["chain_bones"]
        if chain_bones:
            if chain_bones[0] != name:
                errors.append(
                    format_iface(
                        "bone {bone_name!r} explicit chain must start with "
                        "the configured bone",
                        bone_name=name,
                    )
                )
            chain_seen: set[str] = set()
            for index, chain_bone in enumerate(chain_bones):
                if chain_bone not in names:
                    # limbs.leg heel may be synthesized only on the temporary metarig.
                    allow_synthetic_heel = (
                        item["rigify_type"] == "limbs.leg"
                        and index == 4
                        and len(chain_bones) >= 5
                        and all(part in names for part in chain_bones[:4])
                    )
                    if not allow_synthetic_heel:
                        errors.append(
                            format_iface(
                                "bone {bone_name!r} explicit chain bone does "
                                "not exist: {chain_bone!r}",
                                bone_name=name,
                                chain_bone=chain_bone,
                            )
                        )
                if chain_bone in chain_seen:
                    errors.append(
                        format_iface(
                            "bone {bone_name!r} explicit chain contains "
                            "duplicate bone: {chain_bone!r}",
                            bone_name=name,
                            chain_bone=chain_bone,
                        )
                    )
                chain_seen.add(chain_bone)
            minimum = EXPLICIT_CHAIN_MIN_LENGTHS.get(item["rigify_type"])
            if minimum is None:
                errors.append(
                    format_iface(
                        "bone {bone_name!r} Rigify type does not support "
                        "an explicit chain: {rigify_type!r}",
                        bone_name=name,
                        rigify_type=item["rigify_type"],
                    )
                )
            elif len(chain_bones) < minimum:
                errors.append(
                    format_iface(
                        "bone {bone_name!r} explicit chain requires at least "
                        "{minimum} bones",
                        bone_name=name,
                        minimum=minimum,
                    )
                )
        validate_collection_refs(f"bone {name!r}", item["parameters"])

    for item in config["collections"]:
        name = item["name"]
        if name in seen_collections:
            errors.append(
                format_iface(
                    "duplicate collection: {name!r}",
                    name=name,
                )
            )
        seen_collections.add(name)
        if item["color_set"] and item["color_set"] not in seen_color_sets:
            errors.append(
                format_iface(
                    "collection {name!r} references unknown color set: "
                    "{color_set!r}",
                    name=name,
                    color_set=item["color_set"],
                )
            )
        if item["ui_row"] > 0:
            slot = (item["ui_row"], item["row_order"])
            if slot in occupied_slots:
                errors.append(
                    format_iface(
                        "duplicate row_order {order} in UI row {row}",
                        order=slot[1],
                        row=slot[0],
                    )
                )
            occupied_slots.add(slot)

    try:
        dummy_bones = {
            bone_name: {"head": (0.0, 0.0, 0.0), "tail": (0.0, 0.0, 1.0)}
            for bone_name in names
        }
        synthetic_heels = {
            plan["name"]
            for plan in plan_missing_leg_heels(
                effective["bones"], dummy_bones, parents,
            )
        }
        resolve_collection_rules(
            names,
            config["collections"],
            allow_missing_exact=synthetic_heels,
        )
    except ConfigError as exc:
        errors.append(str(exc))
    return ValidationResult(tuple(errors))
