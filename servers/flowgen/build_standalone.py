#!/usr/bin/env python3
"""把 inspect-over-time.html 打包成自包含单文件（42 张 SVG 以 data URI 内联）。

用法：  python3 build_standalone.py
产出：  out/inspect-over-time-standalone.html

改图之后重跑即可。源页面 out/inspect-over-time.html 不动。
"""
import base64
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "out" / "inspect-over-time.html"
SVG_DIR = HERE / "out" / "svg"
DST = HERE / "out" / "inspect-over-time-standalone.html"

html = SRC.read_text(encoding="utf-8")

data = {}
for f in sorted(SVG_DIR.glob("*.svg")):
    key = f.name.replace("-flow.svg", "")          # 例：graphmemix-diff
    b64 = base64.b64encode(f.read_bytes()).decode("ascii")
    data[key] = f"data:image/svg+xml;base64,{b64}"

if len(data) != 42:
    raise SystemExit(f"期望 42 张，实际 {len(data)} 张——先检查 out/svg/")

# 1) 注入内联数据表（放在 TIMELINE 定义之前）
inject = "const SVG_DATA = " + json.dumps(data, ensure_ascii=False) + ";\n"
anchor = "// 时间轴：[系统, YYYY-MM, 论文名 · arXiv]"
if anchor not in html:
    raise SystemExit("找不到注入锚点，源文件结构可能变了")
html = html.replace(anchor, inject + anchor, 1)

# 2) 图片与「原图」链接改指内联数据
html = html.replace('src="svg/${id}-flow.svg"', 'src="${SVG_DATA[id]}"')
html = html.replace('href="svg/${id}-flow.svg"', 'href="${SVG_DATA[id]}"')

# 3) 标题与页脚说明改成分享版口径
html = html.replace(
    "<title>flowgen 目检 · 按时间 — 42 张</title>",
    "<title>memory-bench · 14 个记忆系统 methodology 流程图（按时间）</title>", 1)
html = re.sub(
    r"<b>进度不自动互通</b>.*?</（若用普通浏览器[^）]*）",
    "", html, flags=re.S)
html = html.replace(
    "勾选状态与 <code>inspect.html</code> <b>共用</b> localStorage（同一批 42 张、同一次目检），两边进度互通。",
    "本文件已内联全部 42 张图，可单独发送、离线打开。", 1)

DST.write_text(html, encoding="utf-8")
size = DST.stat().st_size / 1048576
print(f"已生成 {DST}")
print(f"内联 {len(data)} 张，单文件 {size:.2f} MB")
