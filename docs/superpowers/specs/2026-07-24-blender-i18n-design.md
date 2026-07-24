# Blender Internationalization Design

## Goal

Add native English and Simplified Chinese localization to Re-Rigify while
remaining compatible with Blender 4.2 through Blender 5.2. English remains the
source language. Simplified Chinese is selected through Blender's language
preference and uses Blender's add-on translation API.

## Compatibility

- Keep `blender_version_min = "4.2.0"` and the existing `bl_info` minimum.
- Use `bpy.app.translations.register()` and
  `bpy.app.translations.unregister()`, which are available throughout the
  supported Blender range.
- Register the Simplified Chinese catalog for both `zh_HANS` and the legacy
  `zh_CN` alias. Both locale keys reference the same translations.
- Treat `"*"` as the default translation context and `"Operator"` as the
  operator-label context. These stable string values avoid importing Blender
  merely to construct the catalog.
- Do not add a second language preference inside Re-Rigify. Blender's Interface
  language and translation toggles remain authoritative.

## Translation Module

Create `re_rigify/translations.py` as the single owner of localization data and
translation helpers.

It contains:

- The default-context Simplified Chinese messages.
- Operator-label messages under the operator context.
- A `TRANSLATIONS` dictionary in Blender's required
  `{locale: {(context, source): translation}}` shape.
- `register()` and `unregister()` wrappers using a stable module identifier.
- Small helpers that translate interface text or tooltips before interpolating
  dynamic values.

The helper functions import `bpy` lazily and return the English source text
when Blender is unavailable. Pure-Python modules and tests therefore remain
usable outside Blender.

The package registers translations before RNA classes, operators, and panels.
It unregisters UI and RNA classes first, then removes the translation catalog.
Repeated enable, disable, and script-reload cycles must not leave a registered
catalog behind.

## Message Handling

Static Blender UI metadata remains written in English:

- Panel and UI list labels.
- Operator `bl_label` and `bl_description`.
- RNA property names, descriptions, and enum item labels and descriptions.
- Literal labels and button text passed to `UILayout`.

Blender translates those strings automatically from the registered catalog
using their native contexts.

Dynamic messages use named templates. Code translates the complete template
before interpolation, for example:

```python
iface_("Added {count} bone(s)").format(count=count)
```

Code must not translate an already formatted string because runtime values
would make the catalog key unstable. Translated strings passed explicitly to a
layout are drawn with `translate=False` to avoid a second lookup.

Operator reports, validation failures, compatibility failures, import/export
errors, generation failures, and drive status messages follow the same
template-first rule. Tooltip-specific manual translation uses Blender's
tooltip translation function so the user's tooltip toggle is respected.

## Scope

Translate all user-visible Re-Rigify text:

- Panels, nested panels, UI lists, buttons, and empty-state labels.
- RNA property names and descriptions.
- Enum labels and descriptions.
- Operator names and tooltips.
- Operator information, warning, and error reports.
- Validation, compatibility, generation, and drive messages displayed by the
  UI.

Do not translate user or technical identifiers:

- Bone names and armature names.
- Rigify type identifiers and parameter identifiers.
- Bone collection names and color-set names.
- Glob patterns, rule IDs, JSON keys and values, paths, and file names.
- The Re-Rigify product name.

Extension manifest metadata remains English because the Blender add-on
translation catalog does not localize manifest fields.

## Error Handling

- Registration failure must not be silently ignored.
- Unregistration tolerates only the known case where the catalog is already
  absent during development reloads; unrelated errors still surface.
- Formatting placeholders are identical between the English source template
  and Simplified Chinese translation.
- Missing translations fall back to the original English string through
  Blender's native behavior.
- Translation helpers outside Blender fall back to English without importing a
  test stub for `bpy`.

## Testing

Pure-Python tests verify:

- The catalog contains `zh_HANS` and `zh_CN` and both map to the same messages.
- Every key is a `(context, source)` pair and every translation is a string.
- Operator labels use the operator context and ordinary UI text uses the
  default context.
- English and Chinese templates have identical named placeholders.
- User-visible static strings found in the supported UI, operator, and RNA
  declarations have Simplified Chinese entries.
- Dynamic reports and displayed validation messages use translation templates
  before formatting.
- Translation helpers fall back to English when `bpy` is unavailable.

Blender integration through Blender MCP on Blender 5.2 verifies:

- The connected application is Blender 5.2 and supports internationalization.
- Registering Re-Rigify exposes the Simplified Chinese catalog.
- Representative panel, operator, RNA label, tooltip, enum, and formatted
  report templates resolve to Simplified Chinese under `zh_HANS`.
- English source strings remain unchanged under English.
- Disabling Re-Rigify removes its catalog and leaves no registered classes or
  translation state.

The existing complete pure-Python suite remains passing. Existing Blender
integration coverage continues to use the supported extension entry point.
