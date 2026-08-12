# 任务：用 Blender MCP 为当前打开工程的源骨架配置 Re-Rigify

## 环境

- Blender 已打开目标 `.blend`，MCP 已连接。
- 源骨架是 **现有角色 armature**（非 metarig）；不要原地改成 Rigify metarig。
- 通过 `bl_ext.vscode_development.re_rigify.re_rigify`（或当前已加载的 re_rigify 模块）读写配置。
- 优先用：
  - `armature_to_payload(arm.data)`
  - `payload_to_armature(arm.data, payload)`
  - `validate_active(bpy.context)`
- 修改代码后若 addon 已加载，对相关模块 `importlib.reload`。
- **不要保存 `.blend`**，留给用户。
- 源 mesh 绑定不要破坏；本次只改 re_rigify 配置（及必要时插件代码）。

## 先勘察

1. 找到活动/主 armature（通常是选中的 ARMATURE）。
2. 列出全部骨骼名、parent 层级、现有 bone collections。
3. 导出当前 `re_rigify` payload：bones / collections / color_sets / bone_rules / validation_message。
4. 识别左右侧命名：`.L/.R`、`_L/_R`、日文 MMD（肩/腕/ひじ/手首/足/ひざ/足首/つま先 等）。
5. 识别角色结构：root/center、spine、head、arm、leg、fingers、heel/Extra（`limbs.leg` 生成需要）。

## 配置目标（必须满足）

### A. Bone 配置（manual bones）

为主要控制链写 re_rigify bone 行（保留用户已有合理 type，只修明显错误）：

| 部位 | 典型 rigify_type | 备注 |
|------|------------------|------|
| 肩 | `basic.super_copy` | 左右；**`super_copy_widget_type = "shoulder"`**（不要用默认 circle） |
| 上臂根 | `limbs.arm` | 显式链：上臂→肘/小臂→腕/手（≥3） |
| 大腿根 | `limbs.leg` | 显式链：大腿→膝→脚→脚趾；**若场景有 heel/Extra 必须作为第 5 项**（Rigify 生成强制要 heel） |
| 手指根 | `limbs.super_finger` | 每指完整链；`force_connect_chain=True`（仅 finger/tentacle/tail 支持） |
| 脊柱根 | `spines.basic_spine` | 显式链 ≥3；配 **Torso FK** + Torso Tweak；MMD 三骨链常用 `pivot_pos=1` |
| 脖子根 | `spines.super_head` | 显式链：颈→头 |

规则：

- 显式链 `chain_bones[0]` 必须等于配置骨名。
- `limbs.leg`：
  - 主链 4 根全连接：大腿→膝→脚→脚趾。
  - **Rigify 官方 `limbs.leg` 生成时强制要求 heel**（`Heel bone not found`）。Re-Rigify 校验可以不写 heel，但 **Generate 会失败**。
  - heel 发现规则（Rigify）：**脚骨（链第 3 根）的未连接、无子级子骨**。
  - 若源骨架里 heel/Extra 挂在脚趾下（MMD 常见），必须把 `Extra.L/R` 写进显式链第 5 项，让拓扑把它 **改挂到脚下且 use_connect=False**；从链里删掉 Extra 后 Generate 必炸。
  - 真没有独立 heel 骨时，不要用 `limbs.leg`，或先加一根脚底 marker 再配。
- `force_connect_chain` 只能给支持类型（`limbs.super_finger` / `limbs.simple_tentacle` / `spines.basic_tail`）。arm/leg/spine/head **不要**开 force_connect。
- 日文名骨架：arm/leg 优先写显式链，不要依赖英文关键词推断。
- 清空无效空链 `["","",""]`。
- 肩部 `basic.super_copy` 必须设 `super_copy_widget_type: "shoulder"`。
- `spines.basic_spine`：
  - `make_fk_controls: true`
  - `fk_coll_refs` → `Torso FK`，`tweak_coll_refs` → `Torso Tweak`
  - 短链（3 骨，如 腰/上半身/上半身2）设 `pivot_pos: 1`（hips 取自第 1 骨、chest 取自第 2 骨）
- Rigify 的 `hips` 控件会 **沿 -Y 翻转**（`align_bone_to_axis(..., flip=True)`），这是官方设计，不是配置写反；不要为“纠正方向”去翻源骨。

### B. 骨骼集合（collections）——命名与归属

按肢体 + 左右 + 控制类别建立集合。手臂示例（其他肢体同理）：

- IK/主控：`Arm.L` / `Arm.R`
- FK：`Arm FK.L` / `Arm FK.R`
- Tweak：`Arm Tweak.L` / `Arm Tweak.R`

腿：`Leg.L` / `Leg.R` / `Leg FK.*` / `Leg Tweak.*`  
躯干/头：`Root`、`Torso`、`Torso FK`、`Torso Tweak`、`Head`、`Head Tweak`  
手指：`Fingers.L` / `Fingers.R`（主控）+ `Fingers Tweak.L` / `Fingers Tweak.R`（**必配**）

IK 集合 rules：把该侧 IK 相关源骨 exact/glob 进去。  
例：`Arm.L` ← 肩.L、腕.L、ひじ.L、手首.L（按实际骨名）。  
FK/Tweak 集合通常 **rules 为空**，靠 bone 参数里的 coll_refs 在生成时填充。

### C. 额外集合引用（FK / Tweak）

对需要分层的 limb/spine 写入 parameters：

- `limbs.arm`：
  - `fk_coll_refs: ["Arm FK.L"]` / R
  - `tweak_coll_refs: ["Arm Tweak.L"]` / R
  - `fk_layers_extra: true`，`tweak_layers_extra: true`
- `limbs.leg`：同理 `Leg FK.*` / `Leg Tweak.*`
- `limbs.super_finger`（每指根骨）：
  - `tweak_coll_refs: ["Fingers Tweak.L"]` / R
  - `tweak_layers_extra: true`
  - Rigify `super_finger` 通过 `ControlLayersOption.TWEAK` 吃 tweak 集合；不要漏配
- `spines.basic_spine`：
  - `fk_coll_refs: ["Torso FK"]`，`fk_layers_extra: true`
  - `tweak_coll_refs: ["Torso Tweak"]`，`tweak_layers_extra: true`
  - `make_fk_controls: true`，短链 `pivot_pos: 1`
- `spines.super_head`：`tweak_coll_refs` → `Head Tweak`

引用名必须与 collections 里 name **完全一致**。

### D. 颜色

使用 Rigify 默认色板（没有就写入）：`Root`、`IK`、`Special`、`Tweak`、`FK`、`Extra`。

建议：

- Root → Root
- Arm/Leg 主 IK 集合 → IK
- FK 集合 → FK
- Tweak 集合 → Tweak
- Torso/Head 主控 → Special
- Fingers 主控 → Extra；Fingers Tweak → Tweak
- `root_color_set = "Root"`

### E. 生成后可见性（Visible After Generation）

**默认只启用 IK/主控类**，FK/Tweak 关闭：

- visible=true：`Root`、`Torso`、`Head`、`Arm.L/R`、`Leg.L/R`、`Fingers.L/R`（及同类主控）
- visible=false：所有 `* FK*`、`* Tweak*`（含 `Torso FK`、`Fingers Tweak.*`）

### F. 绑定界面 UI 排布（ui_row / row_order）——关键

按 **控制类别分行**，不要把同一肢体的 IK+FK+Tweak 塞同一行；左右同类别共行。

推荐行号（中间空行用“无 collection 占用该 row”实现）：

```
1:  Root, Torso, Torso FK, Torso Tweak, Head, Head Tweak
2:  <empty>
3:  Arm.L, Arm.R                 # IK 一行
4:  Arm FK.L, Arm FK.R           # FK 一行
5:  Arm Tweak.L, Arm Tweak.R     # Tweak 一行
6:  <empty>                      # Arm / Leg 分区
7:  Leg.L, Leg.R
8:  Leg FK.L, Leg FK.R
9:  Leg Tweak.L, Leg Tweak.R
10: <empty>
11: Fingers.L, Fingers.R         # 手指主控一行
12: Fingers Tweak.L, Fingers Tweak.R
```

要求：

- **上下分区**：Root 区 / Arm 区 / Leg 区 / Fingers 区，区间空行隔离。
- **同类一行**：`Arm.L, Arm.R` 同行；`Arm FK.L, Arm FK.R` 另一行。
- 同一 row 内 `row_order` 从 0 递增，L 在 R 前。
- 不要把 6 个按钮横塞同一行。
- `ui_title` 可用短名（如 `FK`/`Tweak`/`Arm.L`）；`name` 保持完整唯一名。

## 实施步骤

1. 勘察骨架与现有 payload。
2. 组装完整 schema v1 payload（format=`re-rigify`）。
3. `payload_to_armature` 一次写入（避免半残状态）。
4. `validate_active`；errors 必须清空。
5. 打印摘要：collections（row/order/color/visible）、bones（type/chain/fk/tweak/force/widget）、validation errors。
6. 若拓扑/显式链能力不足（如旧版不支持 leg chain），先最小修复插件代码 + 单测，reload 后再写配置。
7. 生成前检查 `source.re_rigify_generated_rig` / `<source>_rig`：若物体已不在任何 collection / 不在当前 view layer，视为已删除，清空指针并移除残留 datablock，再生成（避免 Rigify “不在视图层中, 所以无法选中”）。
8. 不保存 blend。

## 验收清单

- [ ] validate_active → 0 errors
- [ ] 无空 chain、无错误 force_connect
- [ ] 肩 `super_copy_widget_type == "shoulder"`
- [ ] `spines.basic_spine` 有 `Torso FK` + `Torso Tweak` coll_refs，`make_fk_controls=true`
- [ ] Arm/Leg/Finger 的 FK·Tweak coll_refs 指向真实集合
- [ ] 每个 `limbs.super_finger` 都有对应侧 `Fingers Tweak.*` 的 `tweak_coll_refs`
- [ ] 生成后仅 IK/主控 visible；FK/Tweak hidden（含 Torso FK / Fingers Tweak）
- [ ] UI：同类一行、Arm/Leg/Fingers 上下分区、区间有空行
- [ ] `limbs.leg`：有 heel/Extra 则链长 5 且第 5 项为 heel；Generate 不报 `Heel bone not found`
- [ ] 颜色集齐全且 collection.color_set 有效
- [ ] 删除旧生成骨架后可再次 Generate（无 view-layer 选中错误）

## 反例（禁止）

- 把 FK/Tweak 默认 visible=true
- `Arm.L, Arm FK.L, Arm Tweak.L, Arm.R, ...` 全塞一行
- 给 `limbs.arm`/`limbs.leg` 开 `force_connect_chain`
- 肩部 widget 仍用 `circle` / 空
- 配置了手指主控集合却不配 `Fingers Tweak.*` / 不写 `tweak_coll_refs`
- 因 Rigify `hips` 官方 -Y 翻转而错误改源骨骼方向
- 把 MMD `Extra` heel 从 `limbs.leg` 显式链删掉还指望 Generate 成功
- 只改 Blender 骨架 collection、不写 re_rigify collections/payload
- 生成并覆盖用户绑定前未校验
- 残留未 link 的 `<source>_rig` 仍当作 target 传给 Rigify

## 可选输出

完成后用简洁列表汇报：修了什么问题、集合布局、bone 链与 coll_refs、校验结果。
