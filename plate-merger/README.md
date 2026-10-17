# plate-merger

拓竹 A1 自动换盘场景下的**多盘 3MF 合盘工具**：把 N 个已切片盘子合并为一个
可无人值守连续打印的 `.gcode.3mf`。

## 定位

本包是**纯算法库**，不依赖 FastAPI、不直接访问打印机，可独立以 CLI 使用，
也可被 `backend/` 作为「生产」模块的能力调用。

技术依据见仓库外的技术方案文档：

- 合盘流程与元数据重写：`自动换盘完整技术方案.html` §4、§5、§10
- 换盘码参数与管理：§10.4
- 耗材全局重映射：§5.2
- 输出校验：§10.4 校验规则

## 目录结构

```
plate_merger/
├── errors.py       异常体系（稳定错误码，禁止静默兜底）
├── models.py       跨模块不可变领域模型
├── io3mf.py        3MF（OPC/ZIP）读写、大写 MD5
├── gcode.py        G-code 三段块解析（HEADER/CONFIG/EXECUTABLE）
├── sliceinfo.py    slice_info / plate_N.json / filament_sequence 解析
├── swapcode.py     换盘码：参数 → G-code + 校验 + 时长估算
├── presets.py      保守 / 均衡 / 快速三档预设
├── filament.py     全局色表与跨盘槽位重映射
├── splitter.py     中间盘 start/end 剥离策略
├── merger.py       拼接与换盘码注入
├── metadata.py     元数据重写（单 plate / rels / 缩略图）
├── verifier.py     输出校验器
├── pipeline.py     流水线编排
└── cli.py          命令行入口
```

## 设计原则

1. **零第三方运行时依赖**：仅用标准库（`zipfile` / `xml.etree` / `json` / `hashlib`）。
2. **失败即报错**：锚点缺失、格式不符一律抛异常，不产出「看似正常」的半成品。
3. **按 key 解析**：元数据一律按字段名取值，不依赖行号或元素顺序。
4. **不可变数据**：阶段之间只传递 `frozen=True` 的 dataclass。
5. **可复现**：3MF 写入使用固定时间戳，相同输入产生相同字节。

## 开发

```bash
# 运行测试（无需安装依赖）
python3 -m pytest

# 以可编辑模式安装（供 backend 引用）
pip install -e ".[dev]"
```

## 版本约定

- Python >= 3.10
- 输出扩展名固定 `.gcode.3mf`
- 生成的 `plate_1.gcode.md5` 使用**大写**
