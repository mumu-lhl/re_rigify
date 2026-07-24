# Re-Rigify

Re-Rigify stores reusable Rigify type, parameter, bone collection, and generated-rig UI layouts for existing armatures.

## Requirements

- Blender 4.2 or newer
- The bundled Rigify add-on enabled

## Languages

Re-Rigify follows Blender's **Edit → Preferences → Interface → Language**
setting. The add-on provides English and Simplified Chinese translations.
Enable **Translation → Interface** for labels and **Tooltips** for
descriptions. Blender 4.2–5.2 are supported.

## Use

Install the extension archive, select an armature, and open **3D View → Sidebar → Re-Rigify**. Configure Rigify types for selected bones, define flat bone collections with exact or case-sensitive Glob rules, validate, then generate. The source armature is never converted in place.

Bone fields search every bone in the active armature. In Pose or Edit Mode Blender also shows its native bone eyedropper. Rigify parameters load and save automatically through an isolated helper; the source pose bones are not modified. `__ReRigify_Parameter_Carrier__` is created only on demand, flushed into `parameters_json`, and removed before saving, so it is not required in a saved project.

Chain-based Rigify types can use an ordered **Explicit Chain**. The first entry must be the configured root; for example, an UMA torso uses `Hip, Waist, Spine, Chest` on `Hip = spines.basic_spine`. Re-Rigify connects and reparents only the temporary metarig copy. Leaving the list empty keeps inferred-topology behavior.

Use **Mirror Configuration to Opposite Side** after configuring one side. Rigify's native naming logic recognizes `.L/.R`, `_L/_R`, and `-L/-R`, so `Arm_L` is copied to `Arm_R`. Bone-name references nested in the parameters are mirrored too. An existing opposite-side configuration is updated.

The mirror command processes every checked configuration at once; if none are checked it mirrors only the active row. Do not check both sides of the same pair. **Copy Parameters to Selected Same Type** uses the active row as the source and copies its parameters to all checked rows with the same Rigify type, which is useful for finger roots and other repeated rigs.

The bone list arrows move all checked configurations by one position while preserving their relative order. With no checked rows, they move only the active configuration. Preset export preserves the displayed order.

**Bone Matching Rules** apply one Rigify type and one native parameter set to every exact or case-sensitive Glob match. Rules run from top to bottom, and the last matching rule wins. Rule matches stay out of the manual bone list. The active rule preview shows only final matches after later-rule precedence. Validation and generation materialize those matches temporarily, while export stores only canonical rules and manual rows.

Enable **Apply as Chain and Force Connect** when one rule matches every member of several linear chains. Re-Rigify groups final winning matches by source parenting, assigns the Rigify type only to each chain root, and connects coincident child joints only on the temporary Metarig. The source armature remains unchanged. Branches, gaps, short chains, and unsupported Rigify types are rejected during validation.

Renaming a configured bone collection updates every matching `*_coll_refs` entry in both manual bone and bone-rule parameters. Removing a collection removes those references. Each collection also has a **Visible After Generation** switch that controls the resulting Rigify collection state.

Parameter synchronization is event-driven: it runs when switching entries, mirroring, validating, importing/exporting, generating, saving the blend file, or disabling the extension. There is no recurring polling timer.

After generation, Re-Rigify automatically keeps the original mesh binding and adds world-space drive constraints to the original armature through generated adapter bones. Each adapter preserves the source rest transform while inheriting the chosen Rigify target, so differently oriented or differently parented skeletons stay in bind pose and follow the controls correctly. Targets are resolved in `DEF-name`, `ORG-name`, then same-name order unless generation provides an explicit mapping. The panel shows the internally linked rig and can remove only constraints and adapter bones created by Re-Rigify; regenerating reconnects them automatically.

The source armature keeps a link to its generated rig. Every generation creates a temporary metarig, assigns the existing rig as Rigify's target, updates that same rig object, and then deletes all temporary metarigs. Existing `<source>_rig` objects are discovered by name for projects created before the target link was added.

Configured-bone rows use checkboxes for batch selection. Both **Add to Collection** and the collection-rule `+` add every checked bone; if none are checked they use the active list item. New collection configurations start on Rigify UI row 1; if an older configuration leaves every collection on row 0, generation promotes the first collection to row 1 on the metarig copy because Rigify requires at least one UI collection button.

Configuration import and export use versioned UTF-8 JSON. Schema version 1 includes optional `chain_bones`, persistent bone rules, collection visibility, and native Rigify collection-reference lists. Missing values receive backward-compatible defaults. Imports are rejected as a whole when bone names, Rigify types, explicit chains, collection slots, or match rules are invalid.
