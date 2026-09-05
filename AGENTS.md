# memory-bench 项目地图

## 目标与入口

- 在统一 MCP 契约下比较 agent 记忆系统；主入口是 `main.py`，server 注册与解释器配置在 `servers.yaml`。
- 评测循环位于 `bench/`，系统封装位于 `servers/<arm>/`，契约与 envelope 公共实现位于 `servers/common/`。
- 总体使用与当前阶段见 [[README]]；部署和多 venv 边界见 [[DEPLOY]]；实验设计见 [[docs/bench-design]]；接口契约见 [[docs/interface-spec]]。

## 常用命令

```bash
python main.py arms
python main.py smoke <arm>
python main.py run --arms mem0,graphiti,rag_baseline --run-id <id> --n 3 --top-k 20 --concurrency 10
pytest
```

- Python 要求 `>=3.12`；主依赖与 pytest 配置见 `pyproject.toml`。
- A-Mem、Mandol 使用独立 venv；具体解释器和依赖边界以 `servers.yaml` 与 `DEPLOY.md` 为准。
- 正式跑分前必须让目标 arm 的 smoke 契约门禁 8/8 通过。

## Methodology 文档

- 跨系统图规范与 canonical module 词汇：[[servers/METHODOLOGY-FLOW-SPEC]]。
- 14 个目标系统：`letta`、`mem0`、`graphiti`、`memos`、`amem`、`mandol`、`mragent`、`atommem`、`graphmemix`、`plugmem`、`memharness`、`transmem`、`livemem`、`memorydecoder`。
- 每个系统的 `servers/<name>/methodology-flow.md` 以 Mermaid 保存精确拓扑和证据，以 `assets/<name>-*-flow.png` 作为生成式可视层。
- A-Mem 与 Mandol 仅有 code 图；其余系统均有 paper/code 双图。
- `paper-architecture.md` / `code-architecture.md` 与 `verification.md` 冲突时，以 verification 的逐条证据为准。A-Mem、Mandol 的封装行为以各自 `ARCHITECTURE.md` 与 server 源码为准。

## 修改边界

- `runs/` 是实验产物；不要为文档任务修改或清理其中的进度、日志和统计文件。
- 不提交 `.env`、本地 venv、`.state/` 或大型 answer/evidence 原文。
- 修改 arm 行为时同时检查 `servers.yaml`、`servers/common/` 契约和 `tests/test_contract.py`；修改 methodology 图时同步检查 PNG 引用、Mermaid 真源和中央 canonical 词汇。

<!-- proma:knowledge-maintenance:start -->
## 协作知识演进（Proma 维护）

- 只把已通过 README、manifest、源码、测试配置或本轮验证报告确认的架构、命令和边界写入本文件。
- 项目事实变化时做最小更新；长调研与逐条证据留在项目文档，不复制到本项目地图或个人协作记忆。
- 新增 methodology module 时先在系统文档的“新登记 module”记录，裁决后回填 `servers/METHODOLOGY-FLOW-SPEC.md`。
<!-- proma:knowledge-maintenance:end -->
