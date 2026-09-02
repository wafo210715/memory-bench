"""Mandol 三塔构建层（Phase 2）。

hierarchical  L0(逐 message 上下文改写) → L1(逐 session) → L2(逐 conv 聚合) → 载入图
episodic      事实抽取(逐 session) → DBSCAN 去重增强(逐簇) → 载入
kg            实体抽取(逐 session) → 实体去重(逐簇) → 关系生成(逐 session + 跨 session) → 载入

复现口径：prompt 逐字复用官方 dataset_maker（见 prompts.py），编排/持久化/LLM client 用本项目自己的。
"""
