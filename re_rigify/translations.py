"""Native Blender translations for Re-Rigify."""

from __future__ import annotations


DEFAULT_CONTEXT = "*"
OPERATOR_CONTEXT = "Operator"
TRANSLATION_DOMAIN = f"{__name__}.catalog"

_ZH_HANS_DEFAULT = {
    "+X": "+X",
    "+Y": "+Y",
    "+Z": "+Z",
    "-X": "-X",
    "-Y": "-Y",
    "-Z": "-Z",
    "Active Bone Parameters": "活动骨骼参数",
    "Active Row": "活动行",
    "Add Checked Configs": "添加勾选的配置",
    "Add Viewport Selection": "添加视图选中项",
    "Add all selected Pose/Edit Mode bones, or the active bone as a fallback": (
        "添加姿态/编辑模式中所有选中的骨骼；没有选中项时添加活动骨骼"
    ),
    "Add bones selected in the 3D View while in Pose or Edit Mode": (
        "添加三维视图中姿态或编辑模式下选中的骨骼"
    ),
    "Add checked bones, or the active list bone if none are checked": (
        "添加勾选的骨骼；没有勾选项时添加列表中的活动骨骼"
    ),
    "Add missing default Rigify color sets without replacing existing sets": (
        "添加缺失的 Rigify 默认颜色集，不替换现有颜色集"
    ),
    "All": "全部",
    "Apply as Chain and Force Connect": "作为链应用并强制连接",
    "Automatic": "自动",
    "Apply": "应用",
    "Apply & Generate": "应用并生成",
    "Apply Built-in Preset": "应用内置预设",
    "Applied built-in preset {preset}": "已应用内置预设 {preset}",
    "Applied preset and generated rig ({mapped} driven, {unmatched} unmatched)": (
        "已应用预设并生成绑定（驱动 {mapped}，未匹配 {unmatched}）"
    ),
    "Built-in Preset": "内置预设",
    "Built-in Re-Rigify configuration preset": "Re-Rigify 内置配置预设",
    "Built-in preset applied": "已应用内置预设",
    "Generate After Apply": "应用后生成",
    "Generate and connect the Rigify rig immediately after applying the preset": (
        "应用预设后立即生成并连接 Rigify 绑定"
    ),
    "MMD JP": "MMD 日文",
    "Preset": "预设",
    "Preset applied, but generation was blocked by validation errors": (
        "预设已应用，但验证错误阻止了生成"
    ),
    "Preset rejected with {count} error(s)": "预设被拒绝，共 {count} 个错误",
    "Replace the armature Re-Rigify configuration with a built-in preset": (
        "用内置预设替换当前骨架的 Re-Rigify 配置"
    ),
    "Standard Japanese MMD armature names": "标准日文 MMD 骨架名称",
    "Unknown built-in preset: {preset_id}": "未知内置预设：{preset_id}",
    "Bone": "骨骼",
    "Bone Collections": "骨骼集合",
    "Bone Matching Rules": "骨骼匹配规则",
    "Bone Pattern": "骨骼模式",
    "Bone Setup": "骨骼设置",
    "Build Skin Eye Topology": "构建眼部蒙皮拓扑",
    "Button Title": "按钮标题",
    "Case-sensitive *, ? and [] pattern": "区分大小写的 *、? 和 [] 模式",
    "Collection Rules": "集合规则",
    "Color Sets": "颜色集",
    "Compatibility": "兼容性",
    "Configuration": "配置",
    "Copy the active bone's Rigify type and all parameters to checked bones": (
        "将活动骨骼的 Rigify 类型和全部参数复制到勾选的骨骼"
    ),
    "Drive Roll Bones": "驱动扭转骨",
    "Effective Matches": "最终匹配项",
    "Empty Row": "空行",
    "Explicit Chain": "显式链",
    "Export": "导出",
    "Eye Forward": "眼睛朝向",
    "Force Connected Chain": "强制连接链",
    "Forearm Roll": "前臂扭转骨",
    "Generate & Connect Rigify Rig": "生成并连接 Rigify 绑定",
    "Generated Rigify Rig": "已生成的 Rigify 绑定",
    "Hidden Collections": "隐藏的集合",
    "Hide": "隐藏",
    "Import": "导入",
    "Infer the horizontal viewing direction from eyelid bones": (
        "根据眼睑骨推断水平视线方向"
    ),
    "Loading Rigify parameters…": "正在加载 Rigify 参数…",
    "Lower Eyelids": "下眼睑",
    "Managed by a bone rule": "由骨骼规则管理",
    "Match one complete bone name": "匹配一个完整骨骼名称",
    "Mirror checked configurations, or the active configuration if none are checked": (
        "镜像勾选的配置；没有勾选项时镜像活动配置"
    ),
    "Move Left": "左移",
    "Move Right": "右移",
    "Move checked configurations, or the active configuration if none are checked": (
        "移动勾选的配置；没有勾选项时移动活动配置"
    ),
    "No bone rule": "没有骨骼规则",
    "No collection": "没有集合",
    "No configured bone": "没有已配置的骨骼",
    "None": "无",
    "Only chain roots receive the Rigify type": "仅链根节点会获得 Rigify 类型",
    "Order": "顺序",
    "Order in Row": "行内顺序",
    "Parameters save automatically": "参数会自动保存",
    "Primary Rotation Axis": "主旋转轴",
    "Use Rigify's native automatic axis selection": "使用 Rigify 原生的自动轴向选择",
    "Use positive X as the primary rotation axis": "使用 X 正方向作为主旋转轴",
    "Use negative X as the primary rotation axis": "使用 X 负方向作为主旋转轴",
    "Use positive Y as the primary rotation axis": "使用 Y 正方向作为主旋转轴",
    "Use negative Y as the primary rotation axis": "使用 Y 负方向作为主旋转轴",
    "Use positive Z as the primary rotation axis": "使用 Z 正方向作为主旋转轴",
    "Use negative Z as the primary rotation axis": "使用 Z 负方向作为主旋转轴",
    "Point the temporary eye bone along negative X": "将临时眼球骨指向 X 负方向",
    "Point the temporary eye bone along negative Y": "将临时眼球骨指向 Y 负方向",
    "Point the temporary eye bone along positive X": "将临时眼球骨指向 X 正方向",
    "Point the temporary eye bone along positive Y": "将临时眼球骨指向 Y 正方向",
    "Re-Rigify": "Re-Rigify",
    "Re-Rigify Metarig": "Re-Rigify 元绑定",
    "Re-Rigify Source Armature": "Re-Rigify 源骨架",
    "Remove only the Copy Transforms constraints created by Re-Rigify": (
        "仅移除 Re-Rigify 创建的复制变换约束"
    ),
    "Rigify Type": "Rigify 类型",
    "Rig Type": "绑定类型",
    "Rig UI Layout": "绑定界面布局",
    "Rule ID": "规则 ID",
    "Rule Parameters": "规则参数",
    "Root Control": "Root 控制器",
    "Root Control Color Set": "Root 控制器颜色集",
    "Rule matches no bones": "规则未匹配任何骨骼",
    "Select for Collection": "选择用于集合",
    "Standard Colors Lock": "锁定标准颜色",
    "Synthetic Eyelid Fallback": "合成眼睑回退",
    "UI Row": "界面行",
    "Upper Arm Roll": "上臂扭转骨",
    "Upper Eyelids": "上眼睑",
    "Visible After Generation": "生成后可见",
    "Select an armature object": "请选择骨架对象",
    "Rigify is not enabled": "Rigify 未启用",
    "Invalid stored parameter JSON: {error}": "已存储的参数 JSON 无效：{error}",
    "Select an armature": "请选择骨架",
    "Select one or more armature bones": "请选择一个或多个骨架骨骼",
    "Added {added} bone(s); skipped {skipped} existing": (
        "已添加 {added} 个骨骼；跳过 {skipped} 个已有骨骼"
    ),
    "Rules added {added}, updated {updated}, removed {removed} bones": (
        "规则已添加 {added} 个、更新 {updated} 个、移除 {removed} 个骨骼"
    ),
    "Added {count} explicit chain bone(s)": "已添加 {count} 个显式链骨骼",
    "{bone_name!r} has no L/R side suffix": "{bone_name!r} 没有 L/R 侧后缀",
    "Mirrored bone {bone_name!r} does not exist": (
        "镜像骨骼 {bone_name!r} 不存在"
    ),
    "Do not select both sides of the same mirrored pair": (
        "请勿同时选择同一镜像对的两侧"
    ),
    "Mirrored {count} configuration(s)": "已镜像 {count} 个配置",
    "Check at least one target bone": "请至少勾选一个目标骨骼",
    "Copied bone settings to {count} bone(s)": (
        "已将骨骼设置复制到 {count} 个骨骼"
    ),
    "Added {count} Rigify default color set(s)": (
        "已添加 {count} 个 Rigify 默认颜色集"
    ),
    "Create a bone collection configuration first": "请先创建骨骼集合配置",
    "No configured bones to add": "没有可添加的已配置骨骼",
    "Added {count} bone(s) to {collection}": (
        "已将 {count} 个骨骼添加到 {collection}"
    ),
    "Select one or more bones in the 3D View": (
        "请在三维视图中选择一个或多个骨骼"
    ),
    "Added {count} selected bone(s) to {collection}": (
        "已将 {count} 个选中骨骼添加到 {collection}"
    ),
    "Validation failed with {count} error(s)": "验证失败，共 {count} 个错误",
    "Configuration is valid": "配置有效",
    "Fix validation errors before exporting": "导出前请修复验证错误",
    "Import rejected with {count} error(s)": "导入被拒绝，共 {count} 个错误",
    "Fix validation errors before generating": "生成前请修复验证错误",
    "Rigify generation failed: {error}": "Rigify 生成失败：{error}",
    "Generated rig drives {mapped} source bones; {unmatched} unmatched": (
        "已生成的绑定驱动 {mapped} 个源骨骼；{unmatched} 个未匹配"
    ),
    "Select the source armature": "请选择源骨架",
    "Failed to remove Rigify drive: {error}": "移除 Rigify 驱动失败：{error}",
    "Removed {count} Re-Rigify constraints": (
        "已移除 {count} 个 Re-Rigify 约束"
    ),
    "{bone_count} bones / {chain_count} chains": (
        "{bone_count} 个骨骼 / {chain_count} 条链"
    ),
    "{bone_count} bones": "{bone_count} 个骨骼",
    "{count} Bones": "{count} 个骨骼",
    "{count} Collections": "{count} 个集合",
    "Driven by {rig_name}": "由 {rig_name} 驱动",
    "Row {row} / {order}": "行 {row} / {order}",
    "Parameter UI unavailable: {error}": "参数界面不可用：{error}",
    "No type": "无类型",
    "No bone": "无骨骼",
    "Unnamed": "未命名",
    "Empty": "空",
    "{path} must be {expected}": "{path} 必须是 {expected}",
    "{path}.eye_forward_axis is invalid": "{path}.eye_forward_axis 无效",
    "format must be {format_name!r}": "format 必须是 {format_name!r}",
    "unsupported schema_version: {version!r}": (
        "不支持的 schema_version：{version!r}"
    ),
    "{path} is empty": "{path} 为空",
    "{path} is invalid": "{path} 无效",
    "{path} row values must be non-negative": "{path} 的行值不能为负数",
    "{path} must contain three numbers": "{path} 必须包含三个数字",
    "{path} values must be between 0 and 1": (
        "{path} 的值必须介于 0 和 1 之间"
    ),
    "bone does not exist: {bone_name!r}": "骨骼不存在：{bone_name!r}",
    "{bone_name!r} has ambiguous child chain: {children}": (
        "{bone_name!r} 的子链不明确：{children}"
    ),
    "{kind} bone rule {pattern!r} matched no bones": (
        "{kind} 骨骼规则 {pattern!r} 未匹配任何骨骼"
    ),
    "chain bone rules require source bone topology": "链式骨骼规则需要源骨骼拓扑",
    "bone rule {pattern!r} Rigify type {rigify_type!r} does not support chain rules": (
        "骨骼规则 {pattern!r} 的 Rigify 类型 {rigify_type!r} 不支持链式规则"
    ),
    "bone rule {pattern!r} chain branches at {bone_name!r}": (
        "骨骼规则 {pattern!r} 的链在 {bone_name!r} 处分支"
    ),
    "bone rule {pattern!r} has disjoint edge {parent!r} -> {child!r}": (
        "骨骼规则 {pattern!r} 存在断开的边 {parent!r} -> {child!r}"
    ),
    "bone rule {pattern!r} chain at {bone_name!r} requires at least {minimum} bones": (
        "骨骼规则 {pattern!r} 在 {bone_name!r} 处的链至少需要 {minimum} 个骨骼"
    ),
    "chain bone rule topology has no reachable root for {bones!r}": (
        "链式骨骼规则拓扑无法为 {bones!r} 找到可达根节点"
    ),
    "{root!r} ({rigify_type}) requires an upper-arm, forearm/elbow, and hand/wrist chain": (
        "{root!r}（{rigify_type}）需要上臂、前臂/肘部和手/腕部链"
    ),
    "{root!r} ({rigify_type}) requires thigh, knee/shin, foot, and toe bones": (
        "{root!r}（{rigify_type}）需要大腿、膝/小腿、脚和脚趾骨骼"
    ),
    "{root!r} ({rigify_type}) requires a chain of at least 3 bones": (
        "{root!r}（{rigify_type}）需要至少 3 个骨骼的链"
    ),
    "{root!r} ({rigify_type}) requires a connected head child": (
        "{root!r}（{rigify_type}）需要已连接的头部子骨骼"
    ),
    "{kind} pattern {pattern!r} in collection {collection!r} matched no bones": (
        "集合 {collection!r} 中的 {kind} 模式 {pattern!r} 未匹配任何骨骼"
    ),
    "{owner} parameter {parameter!r} must be a list of collection names": (
        "{owner} 的参数 {parameter!r} 必须是集合名称列表"
    ),
    "{owner} parameter {parameter!r} references unknown managed collection: {reference!r}": (
        "{owner} 的参数 {parameter!r} 引用了未知的受管集合：{reference!r}"
    ),
    "color set name is empty": "颜色集名称为空",
    "duplicate color set: {name!r}": "颜色集重复：{name!r}",
    "duplicate bone rule id: {rule_id!r}": "骨骼规则 ID 重复：{rule_id!r}",
    "Rigify type is unavailable: {rigify_type!r}": (
        "Rigify 类型不可用：{rigify_type!r}"
    ),
    "duplicate bone configuration: {bone_name!r}": (
        "骨骼配置重复：{bone_name!r}"
    ),
    "bone {bone_name!r} explicit chain must start with the configured bone": (
        "骨骼 {bone_name!r} 的显式链必须从已配置骨骼开始"
    ),
    "bone {bone_name!r} explicit chain bone does not exist: {chain_bone!r}": (
        "骨骼 {bone_name!r} 的显式链骨骼不存在：{chain_bone!r}"
    ),
    "bone {bone_name!r} explicit chain contains duplicate bone: {chain_bone!r}": (
        "骨骼 {bone_name!r} 的显式链包含重复骨骼：{chain_bone!r}"
    ),
    "bone {bone_name!r} Rigify type does not support an explicit chain: {rigify_type!r}": (
        "骨骼 {bone_name!r} 的 Rigify 类型不支持显式链：{rigify_type!r}"
    ),
    "bone {bone_name!r} explicit chain requires at least {minimum} bones": (
        "骨骼 {bone_name!r} 的显式链至少需要 {minimum} 个骨骼"
    ),
    "duplicate collection: {name!r}": "集合重复：{name!r}",
    "collection {name!r} references unknown color set: {color_set!r}": (
        "集合 {name!r} 引用了未知颜色集：{color_set!r}"
    ),
    "root control references unknown color set: {color_set!r}": (
        "Root 控制器引用了未知颜色集：{color_set!r}"
    ),
    "duplicate row_order {order} in UI row {row}": (
        "界面行 {row} 中存在重复的 row_order {order}"
    ),
    "roll bone compatibility is only supported by limbs.arm": (
        "扭转骨兼容仅支持 limbs.arm"
    ),
    "roll bone does not exist: {bone_name!r}": "扭转骨不存在：{bone_name!r}",
    "roll bone {bone_name!r} must have a parent": (
        "扭转骨 {bone_name!r} 必须具有父级"
    ),
    "roll bone compatibility requires at least one roll bone": (
        "扭转骨兼容至少需要一个扭转骨"
    ),
    "{rigify_type!r} does not support forced chain connection": (
        "{rigify_type!r} 不支持强制链连接"
    ),
    "{root!r} ({rigify_type}) requires at least {minimum} connected bones": (
        "{root!r}（{rigify_type}）至少需要 {minimum} 个已连接骨骼"
    ),
    "invalid eye forward axis: {axis!r}": "无效的眼睛朝向轴：{axis!r}",
    "AUTO forward axis is ambiguous; choose ±X or ±Y": (
        "AUTO 朝向轴不明确；请选择 ±X 或 ±Y"
    ),
    "upper eyelid pattern must match at least 2 bones": (
        "上眼睑模式必须至少匹配 2 个骨骼"
    ),
    "lower eyelid pattern must match at least 2 bones": (
        "下眼睑模式必须至少匹配 2 个骨骼"
    ),
    "upper eyelid pattern {pattern!r} matched fewer than 2 bones": (
        "上眼睑模式 {pattern!r} 匹配的骨骼少于 2 个"
    ),
    "lower eyelid pattern {pattern!r} matched fewer than 2 bones": (
        "下眼睑模式 {pattern!r} 匹配的骨骼少于 2 个"
    ),
    "Bone {bone_name!r}: {error}": "骨骼 {bone_name!r}：{error}",
    "Bone {bone_name!r}: eyelid bone {eyelid!r} is already claimed by {owner!r}": (
        "骨骼 {bone_name!r}：眼睑骨 {eyelid!r} 已由 {owner!r} 占用"
    ),
    "roll target {target_name!r} was not generated": (
        "未生成扭转目标 {target_name!r}"
    ),
    "unknown or read-only Rigify parameter: {name!r}": (
        "未知或只读的 Rigify 参数：{name!r}"
    ),
    "unsupported collection parameter": "不支持的集合参数",
    "collection reference name must be a string": "集合引用名称必须是字符串",
    "bone collection {collection!r} does not exist": (
        "骨骼集合 {collection!r} 不存在"
    ),
    "invalid Rigify parameter {name!r}: {error}": (
        "Rigify 参数 {name!r} 无效：{error}"
    ),
    "Source and generated rig must be different armature objects": (
        "源骨架和已生成绑定必须是不同的骨架对象"
    ),
    "Rigify generation returned {result}": "Rigify 生成返回了 {result}",
    "Armature {armature!r} is not in the active view layer": (
        "骨架 {armature!r} 不在活动视图层中"
    ),
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

_ZH_HANS_OPERATOR = {
    "Add Bone Collection Reference": "添加骨骼集合引用",
    "Add Bone Matching Rule": "添加骨骼匹配规则",
    "Add Collection Configuration": "添加集合配置",
    "Add Color Set": "添加颜色集",
    "Add Rigify Default Color Sets": "添加 Rigify 默认颜色集",
    "Add Selected Bones": "添加选中骨骼",
    "Add Selected Bones to Active Collection": "将选中骨骼添加到活动集合",
    "Add Selected Bones to Explicit Chain": "将选中骨骼添加到显式链",
    "Add Selected Viewport Bones": "添加视图中选中的骨骼",
    "Copy Bone Settings to Checked": "将骨骼设置复制到勾选项",
    "Duplicate Collection Configuration": "复制集合配置",
    "Export Re-Rigify Configuration": "导出 Re-Rigify 配置",
    "Apply Built-in Preset": "应用内置预设",
    "Generate Rigify Rig": "生成 Rigify 绑定",
    "Import Re-Rigify Configuration": "导入 Re-Rigify 配置",
    "Insert or Remove UI Row": "插入或移除界面行",
    "Mirror Configuration to Opposite Side": "将配置镜像到另一侧",
    "Move Bone Configuration": "移动骨骼配置",
    "Move Bone Matching Rule": "移动骨骼匹配规则",
    "Move Collection Within UI Row": "在界面行内移动集合",
    "Move Collection in List": "在列表中移动集合",
    "Move Collection to UI Row": "将集合移动到界面行",
    "Move Explicit Chain Bone": "移动显式链骨骼",
    "Remove Bone Collection Reference": "移除骨骼集合引用",
    "Remove Bone Configuration": "移除骨骼配置",
    "Remove Bone Matching Rule": "移除骨骼匹配规则",
    "Remove Collection Configuration": "移除集合配置",
    "Remove Color Set": "移除颜色集",
    "Remove Explicit Chain Bone": "移除显式链骨骼",
    "Remove Rigify Drive": "移除 Rigify 驱动",
    "Select All Configured Bones": "选择所有已配置骨骼",
    "Select Collection": "选择集合",
    "Sync Bone Matching Rules": "同步骨骼匹配规则",
    "Validate Configuration": "验证配置",
}

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
