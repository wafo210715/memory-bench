# probes —— 一次性调查脚本

与 `scripts/` 下的常驻工具（`smoke_test.py` 被 tests/ 依赖、`archive_run.sh` 是运维）
区分开：这里放的是**为回答某个具体问题而写的探针**，价值在于结论可复现，
不在于长期维护。

每个脚本的文件头必须写清：回答了什么问题、结论落在哪个 commit 或文档里。

| 脚本 | 回答的问题 | 结论 |
|---|---|---|
| `probe_f8_real.py` | A-MEM 的沿链扩展（论文 Fig.2）在真实数据上到底触发不触发？ | native 0/30，fixed 30/30（邻居占满 25% 配额）。见 commit「A-MEM 第 4 层」 |
| `verify_amem_fixed.py` | native / fixed 两臂在 MCP 契约层面的行为差异 | F9 上下文注入 5/5、embedding-3 生效、evolution 失败率对照。同上 |
