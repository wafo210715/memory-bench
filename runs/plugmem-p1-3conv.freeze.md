# plugmem-p1-3conv 冻结存档

> [!warning] v1 已作废，本文件现为 v2 口径
> v1（2026-09-12 23:30 冻结，指纹 `cab00198060314fe`）于 09-13 03:38 启动、04:29 因账户限流
> 在灌入阶段中断（灌到 conv-26 第 11 段），零产出。同日对抗审查又判定那批灌入本来就不可用
> （C1：动作侧话语抽不出命题）。代码已按审查修复 1 条 CRITICAL + 5 条 MAJOR + 5 条 MINOR，
> 指纹重算为 `e144cbef27476d35`。修复清单见 `servers/plugmem/arm-reproduction.md` §6。

冻结时间：v1 2026-09-12 23:30 ｜ v2 2026-09-13 14:20 GMT+8
基线 commit：`e60e189`（工作区有未提交改动，故以下用文件指纹而非 commit 固定被测代码）
上游 PlugMem 钉住版本：`3b2ce75`（只读引入，不改上游仓库）

## 被测代码指纹（sha256 前 16 位）

见同目录 `plugmem-p1-3conv.freeze.txt`。冻结后到 run 结束期间这些文件不得修改；
如需修改，另开 v2 run-id，不混用修改前后的结果。

## 臂与配置

| 臂 | 角色 | 关键配置 |
|---|---|---|
| plugmem | 主臂 | 三图（情景/语义/程序）+ 记忆类型 LLM 三选一；跳数上限 2（论文默认）；推理压缩模块默认关 |

- 对话：conv-26、conv-30、conv-49（与 atommem-p1-3conv、memharness-p1-3conv 同题集，可横比）
- n=3、top_k=20、Phase B 并发 16、temp=0、thinking=low
- 嵌入：embedding-3（2048 维，与其余臂一致）
- 内部 LLM：glm-5.3，temp=0，thinking 三态映射同 mem0

## 已声明的偏离项（逐条理由见 servers/plugmem/arm-reproduction.md）

1. 嵌入模型偏离论文与上游的 NV-Embed-v2，与仓库其他臂同口径；代价是上游四个硬编码相似度阈值的尺度漂移，由 `stats().threshold_probes` 观测。已实测：轨迹切段触发率 72%，切得比论文设想碎。
2. 三处按论文补齐上游退化的能力：处方质量分打分、意图 embedding 语义判重（含同批内互判）、多跳检索控制器。
3. 一处按契约默认关：推理压缩模块（harness 已统一承担证据渲染，开它会让本臂证据粒度与其余臂不可比）。
4. 检索预算接契约 top_k；上游写死的路由参数（标签 k=1/0.8、意图 k=1/0.1、切段 0.75、情景池 30、会话票数 3）保持不动。
5. 情景模式下情景节点最多占 top_k 的一半、命题侧不足时不回填——这是防退化措施，实测不加会让不同问题拿到相同证据集。因此本臂返回条数常低于 top_k，用 `MODE_LIMITED` 上报，跨臂比较时须声明证据体量差异。
6. 本臂默认属 active retrieval 面（多跳停止判断读记忆内容），成本与延迟表不与零 LLM 检索臂并列。

## 门禁状态

- 对抗审查：已完成（2026-09-13，fable 5.1），报告 `servers/plugmem/review-2026-09-13.md`；CRITICAL 已清零
- pytest 无新增红
- 契约 smoke：**修复后尚未重跑**（14:05 一次尝试被 429 打断，当时 graphmemix v2 在跑）。
  由闸门任务在配额空闲后重跑，8/8 才允许启动

## 启动方式

由定时任务「plugmem 3conv 跑分闸门」在配额空闲后依次执行：清空旧状态 → 重跑 smoke → 8/8 才启动：

```bash
cd /Users/guanhongli/Documents/repo/memory-bench
nohup .venv/bin/python -m bench.runner --arms plugmem --convs conv-26,conv-30,conv-49 \
  --run-id plugmem-p1-3conv --n 3 --top-k 20 --concurrency 16 \
  > runs/plugmem-p1-3conv.log 2>&1 &
```
