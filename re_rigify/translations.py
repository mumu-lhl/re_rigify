"""Native Blender translations for Re-Rigify."""

from __future__ import annotations


DEFAULT_CONTEXT = "*"
OPERATOR_CONTEXT = "Operator"
TRANSLATION_DOMAIN = f"{__name__}.catalog"

_ZH_HANS_DEFAULT = {
    "Bone": "骨骼",
    "Rigify Type": "Rigify 类型",
    "Parameters": "参数",
    "Match": "匹配",
    "Exact": "精确",
    "Glob": "通配符",
    "Collection": "集合",
    "Color Set": "颜色集",
    "Active": "活动",
    "Normal": "常规",
    "Select": "选中",
}

_ZH_HANS_OPERATOR = {}

_ZH_HANS = {
    **{
        (DEFAULT_CONTEXT, source): translated
        for source, translated in _ZH_HANS_DEFAULT.items()
    },
    **{
        (OPERATOR_CONTEXT, source): translated
        for source, translated in _ZH_HANS_OPERATOR.items()
    },
}

TRANSLATIONS = {
    "zh_HANS": _ZH_HANS,
    "zh_CN": _ZH_HANS,
}


def _translate(function_name: str, message: str) -> str:
    try:
        import bpy
    except ModuleNotFoundError:
        return message
    function = getattr(bpy.app.translations, function_name)
    return function(message, DEFAULT_CONTEXT)


def iface_(message: str) -> str:
    return _translate("pgettext_iface", message)


def tip_(message: str) -> str:
    return _translate("pgettext_tip", message)


def format_iface(message: str, /, **values: object) -> str:
    return iface_(message).format(**values)


def format_tip(message: str, /, **values: object) -> str:
    return tip_(message).format(**values)


def register() -> None:
    import bpy
    bpy.app.translations.register(TRANSLATION_DOMAIN, TRANSLATIONS)


def unregister() -> None:
    import bpy
    try:
        bpy.app.translations.unregister(TRANSLATION_DOMAIN)
    except RuntimeError as exc:
        if "not registered" not in str(exc).lower():
            raise
