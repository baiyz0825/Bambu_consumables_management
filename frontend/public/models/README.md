# 真实模型放置目录

把 A1 的 GLB 模型放成 **`a1.glb`**（与本文件同级），数字孪生会自动切换为真实模型。

```
frontend/public/models/a1.glb
```

## 推荐来源

| 来源 | 说明 | 获取 |
|---|---|---|
| **Sketchfab — 3D printer \| Bambu Lab A1**（@scb3d） | 112.9k 三角面，基于 MakerWorld 770920 CAD 制作；面数适中，Web 直接可用 | 登录后 Download → glTF |
| MakerWorld 770920 | 精确 STEP（±0.2mm） | 需 Bambu 账号，下载后自行转 GLB |
| GrabCAD A1 Combo + AMS | 26 个文件，含 AMS | 需 GrabCAD 账号 |

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
