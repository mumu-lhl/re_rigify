# Re-Rigify

Re-Rigify stores reusable Rigify type, parameter, bone collection, and generated-rig UI layouts for existing armatures.

## Requirements

- Blender 4.2 or newer
- The bundled Rigify add-on enabled

## Use

Install the extension archive, select an armature, and open **3D View → Sidebar → Re-Rigify**. Configure Rigify types for selected bones, define flat bone collections with exact or case-sensitive Glob rules, validate, then generate. The source armature is never converted in place.

Configuration import and export use versioned UTF-8 JSON. Imports are rejected as a whole when bone names, Rigify types, collection slots, or match rules are invalid.
