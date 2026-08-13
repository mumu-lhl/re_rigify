"""Built-in Re-Rigify presets for standard armature naming conventions."""

from __future__ import annotations

from copy import deepcopy

from .core import (
    DEFAULT_COMPATIBILITY,
    FORMAT_NAME,
    RIGIFY_DEFAULT_COLOR_SETS,
    SCHEMA_VERSION,
    ConfigError,
    normalize_config,
)
from .translations import format_iface


def _color_sets() -> list[dict]:
    return [
        {
            "name": name,
            "active": list(active),
            "normal": list(normal),
            "select": list(select),
            "standard_colors_lock": True,
        }
        for name, active, normal, select in RIGIFY_DEFAULT_COLOR_SETS
    ]


def _compat(**overrides) -> dict:
    value = dict(DEFAULT_COMPATIBILITY)
    value.update(overrides)
    return value


def _bone(
    name: str,
    rigify_type: str,
    *,
    chain: list[str] | None = None,
    parameters: dict | None = None,
    force_connect: bool = False,
    **compat_overrides,
) -> dict:
    return {
        "bone_name": name,
        "rigify_type": rigify_type,
        "chain_bones": list(chain or []),
        "parameters": dict(parameters or {}),
        "compatibility": _compat(
            force_connect_chain=force_connect,
            **compat_overrides,
        ),
    }


def _coll(
    name: str,
    title: str,
    row: int,
    order: int,
    color: str,
    visible: bool,
    rules: list[dict] | None = None,
) -> dict:
    return {
        "name": name,
        "ui_title": title,
        "ui_row": row,
        "row_order": order,
        "color_set": color,
        "visible_after_generation": visible,
        "rules": list(rules or []),
    }


def _exact(*names: str) -> list[dict]:
    return [{"kind": "EXACT", "pattern": name} for name in names]


def _glob(*patterns: str) -> list[dict]:
    return [{"kind": "GLOB", "pattern": pattern} for pattern in patterns]


def _fk_tweak(fk: str | None = None, tweak: str | None = None, **extra) -> dict:
    params = dict(extra)
    if fk is not None:
        params["fk_layers_extra"] = True
        params["fk_coll_refs"] = [fk]
    if tweak is not None:
        params["tweak_layers_extra"] = True
        params["tweak_coll_refs"] = [tweak]
    return params


def _finger(side: str, root: str, *rest: str) -> dict:
    chain = [f"{root}.{side}", *[f"{name}.{side}" for name in rest]]
    return _bone(
        chain[0],
        "limbs.super_finger",
        chain=chain,
        force_connect=True,
        parameters=_fk_tweak(tweak=f"Fingers Tweak.{side}"),
    )


def build_mmd_jp_payload() -> dict:
    """Fixed preset for standard Japanese MMD armatures.

    Bone names follow common MMD JP keys (MikuMikuRig MMD_JP.json) plus the
    Re-Rigify conventions used in this project:

    - spine: 腰 → 上半身 → 上半身2
    - toe: つま先.*
    - heel: Extra.* as limbs.leg explicit-chain item 5; if missing on the
      source armature, generation creates it only on the temporary metarig
    - eyes: 目.L/R as face.skin_eye (eyeball target/master). Synthetic lids are
      only generation scaffolding and are hidden afterward; Face holds eyes only
    - shoulder widget: shoulder
    - UI rows are spaced so Root/Torso/Head/Face are not jammed on one button row
    """
    bones = [
        _bone(
            "肩.L",
            "basic.super_copy",
            parameters={
                "make_control": True,
                "make_widget": True,
                "super_copy_widget_type": "shoulder",
            },
        ),
        _bone(
            "肩.R",
            "basic.super_copy",
            parameters={
                "make_control": True,
                "make_widget": True,
                "super_copy_widget_type": "shoulder",
            },
        ),
        _bone(
            "腕.L",
            "limbs.arm",
            chain=["腕.L", "ひじ.L", "手首.L"],
            parameters=_fk_tweak(fk="Arm FK.L", tweak="Arm Tweak.L"),
        ),
        _bone(
            "腕.R",
            "limbs.arm",
            chain=["腕.R", "ひじ.R", "手首.R"],
            parameters=_fk_tweak(fk="Arm FK.R", tweak="Arm Tweak.R"),
        ),
        _bone(
            "足.L",
            "limbs.leg",
            chain=["足.L", "ひざ.L", "足首.L", "つま先.L", "Extra.L"],
            parameters=_fk_tweak(fk="Leg FK.L", tweak="Leg Tweak.L"),
        ),
        _bone(
            "足.R",
            "limbs.leg",
            chain=["足.R", "ひざ.R", "足首.R", "つま先.R", "Extra.R"],
            parameters=_fk_tweak(fk="Leg FK.R", tweak="Leg Tweak.R"),
        ),
        _finger("L", "親指０", "親指１", "親指２"),
        _finger("L", "人指１", "人指２", "人指３"),
        _finger("L", "中指１", "中指２", "中指３"),
        _finger("L", "薬指１", "薬指２", "薬指３"),
        _finger("L", "小指１", "小指２", "小指３"),
        _finger("R", "親指０", "親指１", "親指２"),
        _finger("R", "人指１", "人指２", "人指３"),
        _finger("R", "中指１", "中指２", "中指３"),
        _finger("R", "薬指１", "薬指２", "薬指３"),
        _finger("R", "小指１", "小指２", "小指３"),
        _bone(
            "腰",
            "spines.basic_spine",
            chain=["腰", "上半身", "上半身2"],
            parameters={
                **_fk_tweak(fk="Torso FK", tweak="Torso Tweak"),
                "make_fk_controls": True,
                "pivot_pos": 1,
            },
        ),
        _bone(
            "首",
            "spines.super_head",
            chain=["首", "頭"],
            parameters=_fk_tweak(tweak="Head Tweak"),
        ),
        _bone(
            "目.L",
            "face.skin_eye",
            skin_eye_compatibility=True,
            # Standard MMD faces look along -Y; AUTO needs eyelid landmarks.
            eye_forward_axis="-Y",
            synthetic_lids_fallback=True,
        ),
        _bone(
            "目.R",
            "face.skin_eye",
            skin_eye_compatibility=True,
            eye_forward_axis="-Y",
            synthetic_lids_fallback=True,
        ),
    ]

    collections = [
        _coll(
            "Root",
            "Root",
            1,
            0,
            "Root",
            True,
            _exact("全ての親", "センター", "グルーブ"),
        ),
        _coll(
            "Torso",
            "Torso",
            1,
            1,
            "Special",
            True,
            _exact("腰", "下半身", "上半身", "上半身2"),
        ),
        _coll("Torso FK", "FK", 2, 0, "FK", False),
        _coll("Torso Tweak", "Tweak", 2, 1, "Tweak", False),
        _coll("Head", "Head", 3, 0, "Special", True, _exact("首", "頭")),
        _coll(
            "Face",
            "Face",
            3,
            1,
            "Special",
            True,
            _exact("目.L", "目.R"),
        ),
        _coll("Head Tweak", "Tweak", 3, 2, "Tweak", False),
        _coll(
            "Arm.L",
            "Arm.L",
            5,
            0,
            "IK",
            True,
            _exact("肩.L", "腕.L", "ひじ.L", "手首.L"),
        ),
        _coll(
            "Arm.R",
            "Arm.R",
            5,
            1,
            "IK",
            True,
            _exact("肩.R", "腕.R", "ひじ.R", "手首.R"),
        ),
        _coll("Arm FK.L", "FK", 6, 0, "FK", False),
        _coll("Arm FK.R", "FK", 6, 1, "FK", False),
        _coll("Arm Tweak.L", "Tweak", 7, 0, "Tweak", False),
        _coll("Arm Tweak.R", "Tweak", 7, 1, "Tweak", False),
        _coll(
            "Leg.L",
            "Leg.L",
            9,
            0,
            "IK",
            True,
            _exact("足.L", "ひざ.L", "足首.L", "つま先.L", "Extra.L"),
        ),
        _coll(
            "Leg.R",
            "Leg.R",
            9,
            1,
            "IK",
            True,
            _exact("足.R", "ひざ.R", "足首.R", "つま先.R", "Extra.R"),
        ),
        _coll("Leg FK.L", "FK", 10, 0, "FK", False),
        _coll("Leg FK.R", "FK", 10, 1, "FK", False),
        _coll("Leg Tweak.L", "Tweak", 11, 0, "Tweak", False),
        _coll("Leg Tweak.R", "Tweak", 11, 1, "Tweak", False),
        _coll(
            "Fingers.L",
            "Fingers.L",
            13,
            0,
            "Extra",
            True,
            _glob("人指*.L", "中指*.L", "薬指*.L", "小指*.L", "親指*.L"),
        ),
        _coll(
            "Fingers.R",
            "Fingers.R",
            13,
            1,
            "Extra",
            True,
            _glob("人指*.R", "中指*.R", "薬指*.R", "小指*.R", "親指*.R"),
        ),
        _coll("Fingers Tweak.L", "Tweak", 14, 0, "Tweak", False),
        _coll("Fingers Tweak.R", "Tweak", 14, 1, "Tweak", False),
    ]

    return normalize_config(
        {
            "format": FORMAT_NAME,
            "schema_version": SCHEMA_VERSION,
            "bones": bones,
            "bone_rules": [],
            "collections": collections,
            "color_sets": _color_sets(),
            "root_color_set": "Root",
        }
    )


PRESET_BUILDERS = {
    "mmd_jp": {
        "name": "MMD",
        "description": "Standard MMD armature names",
        "build": build_mmd_jp_payload,
    },
}


def list_presets() -> list[tuple[str, str, str]]:
    return [
        (key, meta["name"], meta["description"])
        for key, meta in PRESET_BUILDERS.items()
    ]


def build_preset_payload(preset_id: str) -> dict:
    meta = PRESET_BUILDERS.get(preset_id)
    if meta is None:
        raise ConfigError(
            format_iface(
                "Unknown built-in preset: {preset_id}",
                preset_id=preset_id,
            )
        )
    return deepcopy(meta["build"]())


def preset_enum_items(_self=None, _context=None):
    """Blender EnumProperty items callback."""
    return [
        (key, meta["name"], meta["description"], index)
        for index, (key, meta) in enumerate(PRESET_BUILDERS.items())
    ]
