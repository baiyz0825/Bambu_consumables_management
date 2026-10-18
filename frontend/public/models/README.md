# 真实模型放置目录

把 A1 的 GLB 模型放成 **`a1.glb`**（与本文件同级），数字孪生会自动切换为真实模型。

```
frontend/public/models/a1.glb
```

## 当前内置模型

仓库中的 `a1.glb` 来自 **Bambu A1 官方结构 CAD（STEP，25 个装配件）**，
用 `cascadio` 转换为 GLB。注意官方 CAD **不含 AMS Lite**——AMS 由
`components/printer/twin/ams-lite-model.js` 参数化几何叠加渲染（料盘颜色 /
换料 / HMS 联动与真实模型一致）。

若后续拿到比例正确的 AMS Lite 模型，用
`backend/scripts/merge_ams_model.py` 合并进 `a1.glb`
（自动处理米/毫米单位换算、节点变换保留），再删掉 twin-view.js 里的
`<AmsLiteModel />` 一行即可切换。

## 推荐来源

| 来源 | 说明 | 获取 |
|---|---|---|
| MakerWorld 770920 | 精确 STEP（±0.2mm），当前内置模型来源 | 需 Bambu 账号 |
| GrabCAD「Bambu Lab AMS Lite」 | AMS Lite 单独 CAD（STEP/IGES） | 需 GrabCAD 账号，页面有 CloudFront 反爬 |
| GrabCAD A1 Combo + AMS Module | 26 个文件，含 AMS | 需 GrabCAD 账号 |

> Meshy / Tripo 等 AI 生成的模型**不要用**：结构会错乱，且无法拆件驱动。

## 部件命名（决定能否联动）

加载器会按名称关键词把部件归类，命中则驱动其运动：

| 关键词（不区分大小写） | 归类 | 驱动 |
|---|---|---|
| `toolhead` / `extruder` / `hotend` / `nozzle` / `喷头` | 喷头 | 随层高升降 + 走 X |
| `gantry` / `x_axis` / `beam` / `rail` / `龙门` / `横梁` | 龙门 | 随层高升降 |
| `bed` / `heatbed` / `build_plate` / `热床` | 热床 | 前后移动（Y） |
| `ams` / `spool` / `filament` / `料盘` | AMS | 换料时轻微摆动 |
| `screen` / `display` / `触摸屏` | 屏幕 | 静态 |

其余部件视为机身，保持不动。

**即使完全不命名也能用**：模型会整体静态显示，只是不联动。所以先放进去看效果，再决定要不要在 Blender 里改名。

## 单位与朝向

- 加载器按「整机高度 ≈ 430mm」自动缩放，底部对齐床面，水平居中
- 不必手动调比例
- 朝向：假设 Z 轴向下为床面、Y 轴向上（Three.js 惯例）；若模型躺倒，需在 Blender 里先转正

## 许可提醒

Sketchfab 模型可能带 CC 署名要求。商用前请确认作者许可，并在界面或文档中保留署名。
