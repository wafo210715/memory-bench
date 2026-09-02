#!/usr/bin/env python
"""从 Mandol 官方 dataset_maker 提取 prompt 常量，生成 servers/mandol/towers/prompts.py。

为什么用 AST 提取而不是手抄：这些 prompt 单个 2.3k–4.3k 字符，抄错一个字符就会
静默改变 LLM 抽取行为，而且没有任何断言能发现。AST 提取保证逐字忠实、可复现。

真源：dataset_maker/ 下的 8 个 step 脚本（论文复现路径）。
注意 src/mandol/auto_builder/hierarchical_prompts.py 里有一份内容等价的副本，
但那是**运行时 auto_builder 路径**，模板语法为 string.Template（${x}）；
复现路径用的是 dataset_maker 版（str.format 风格 {x}）。二者已做规范化比对，
除 {{ / { 转义差异外完全一致。

用法：
    MANDOL_REPO=~/Documents/repo/Mandol .venv/bin/python scripts/gen_mandol_prompts.py
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MANDOL = Path(os.environ.get("MANDOL_REPO", Path.home() / "Documents/repo/Mandol")).expanduser()
DM = MANDOL / "benchmark_locomo/dataset_maker"
OUT = REPO / "servers/mandol/towers/prompts.py"

# (输出常量名, 相对 dataset_maker 的路径, 源变量名, 所在函数名)
#   func=None            → 模块级常量
#   var=None + func="f"  → 函数 f 的 return 字符串常量
SPECS = [
    ("CONTEXTUAL_RETRIEVAL_PROMPT",
     "locomo_hierarchical_content_maker/step1_generate_l0_graph.py",
     "CONTEXTUAL_RETRIEVAL_PROMPT", None),
    ("L1_EXTRACTION_PROMPT_TEMPLATE",
     "locomo_hierarchical_content_maker/step2_extract_l1.py",
     "L1_EXTRACTION_PROMPT_TEMPLATE", None),
    ("L2_AGGREGATION_PROMPT_TEMPLATE",
     "locomo_hierarchical_content_maker/step3_aggregate_l2.py",
     "L2_AGGREGATION_PROMPT_TEMPLATE", None),
    ("EPISODIC_EXTRACTION_PROMPT",
     "locomo_episodic_memory/step1_extract_episodic_facts.py",
     "EPISODIC_EXTRACTION_PROMPT", None),
    ("LLM_DEDUP_PROMPT",
     "locomo_episodic_memory/step2_deduplicate_and_enhance.py",
     "LLM_DEDUP_PROMPT", None),
    ("ENTITY_EXTRACTION_PROMPT",
     "locomo_graph_maker/step1_locomo_entity_extractor.py",
     "entity_extraction", "_prepare_entity_extraction_prompts"),
    ("ENTITY_TYPES_DESCRIPTION",
     "locomo_graph_maker/step1_locomo_entity_extractor.py",
     None, "_get_entity_types_description"),
    ("ENTITY_DEDUPLICATION_PROMPT",
     "locomo_graph_maker/step1_locomo_entity_extractor.py",
     "entity_deduplication", "_prepare_entity_extraction_prompts"),
    ("RELATION_EXTRACTION_PROMPT",
     "locomo_graph_maker/step2_locomo_relation_generator.py",
     "relation_extraction", "_prepare_relation_extraction_prompts"),
    ("CROSS_SESSION_RELATION_PROMPT",
     "locomo_graph_maker/step2_locomo_relation_generator.py",
     "cross_session_relation_extraction", "_prepare_relation_extraction_prompts"),
]


def _find(tree: ast.AST, var: str | None, func: str | None):
    """取 prompt 字符串常量，返回 (值, 行号)。

    三种形态：模块级赋值 / 函数内局部赋值 / 函数 return 字面量。
    """
    scopes = [tree] if func is None else [
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func
    ]
    for scope in scopes:
        for node in ast.walk(scope):
            if var is None:
                if isinstance(node, ast.Return) and isinstance(node.value, ast.Constant) \
                        and isinstance(node.value.value, str):
                    return node.value.value, node.lineno
                continue
            if not isinstance(node, ast.Assign):
                continue
            if not (isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
                continue
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == var:
                    return node.value.value, node.lineno
    return None, None


def main() -> int:
    if not DM.is_dir():
        print(f"✗ 找不到 dataset_maker: {DM}\n  用 MANDOL_REPO=<路径> 指定", file=sys.stderr)
        return 1

    out = [
        '"""Mandol 官方 prompt 常量（自动生成，请勿手改）。',
        "",
        f"生成器：scripts/gen_mandol_prompts.py",
        f"真源：{DM.relative_to(MANDOL)}（论文复现路径）",
        "",
        "重新生成：MANDOL_REPO=<Mandol仓库> .venv/bin/python scripts/gen_mandol_prompts.py",
        '"""',
        "",
        "# ruff: noqa: E501",
        "",
    ]
    found = 0
    for name, rel, var, func in SPECS:
        path = DM / rel
        if not path.exists():
            print(f"  ✗ 缺文件 {rel}", file=sys.stderr)
            continue
        val, lineno = _find(ast.parse(path.read_text()), var, func)
        if val is None:
            print(f"  ✗ 未找到 {var} @ {rel}" + (f" (in {func})" if func else ""), file=sys.stderr)
            continue
        if func and var is None:
            loc = f"{rel}:{lineno} [{func}() 的 return]"
        elif func:
            loc = f"{rel}:{lineno} [{func}() 局部变量]"
        else:
            loc = f"{rel}:{lineno}"
        out.append(f"# 源：{loc}  原名：{var or func + '() return'}  {len(val)} 字符")
        out.append(f"{name} = {val!r}")
        out.append("")
        found += 1
        print(f"  ✓ {name:32s} ← {loc}  ({len(val)} 字符)")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(out))
    print(f"\n写入 {OUT.relative_to(REPO)}：{found}/{len(SPECS)} 个常量")
    return 0 if found == len(SPECS) else 1


if __name__ == "__main__":
    sys.exit(main())
