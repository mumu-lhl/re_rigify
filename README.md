# Re-Rigify

Re-Rigify stores reusable Rigify type, parameter, bone collection, and generated-rig UI layouts for existing armatures.

## Requirements

- Blender 4.2 or newer
- The bundled Rigify add-on enabled

## Use

Install the extension archive, select an armature, and open **3D View → Sidebar → Re-Rigify**. Configure Rigify types for selected bones, define flat bone collections with exact or case-sensitive Glob rules, validate, then generate. The source armature is never converted in place.

Bone fields search every bone in the active armature. In Pose or Edit Mode Blender also shows its native bone eyedropper. Rigify parameters load and save automatically through an isolated helper; the source pose bones are not modified.

Use **Mirror Configuration to Opposite Side** after configuring one side. Rigify's native naming logic recognizes `.L/.R`, `_L/_R`, and `-L/-R`, so `Arm_L` is copied to `Arm_R`. Bone-name references nested in the parameters are mirrored too. An existing opposite-side configuration is updated.

Parameter synchronization is event-driven: it runs when switching entries, mirroring, validating, importing/exporting, generating, saving the blend file, or disabling the extension. There is no recurring polling timer.

Configured-bone rows use checkboxes for batch selection. Both **Add to Collection** and the collection-rule `+` add every checked bone; if none are checked they use the active list item. New collection configurations start on Rigify UI row 1; if an older configuration leaves every collection on row 0, generation promotes the first collection to row 1 on the metarig copy because Rigify requires at least one UI collection button.

Configuration import and export use versioned UTF-8 JSON. Imports are rejected as a whole when bone names, Rigify types, collection slots, or match rules are invalid.
