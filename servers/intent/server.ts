/**
 * intent：意图系统适配层（memory-bench 六工具契约）
 *
 * 把 intent-recall-mcp 的核心机制（session 意图摘要 + 意图驱动检索）接上 benchmark 契约：
 * - add_conversation: 写 session JSONL + LLM 生成意图摘要（结构对齐 SessionIntentMetadata——ingest 时
 *   LLM 加工与 mem0 抽取等价，公平），摘要进 session-intent.json（Tier 1 数据源）
 * - retrieve: Tier 1 语义——意图摘要关键词检索，返回 session 级 envelope（turn_range 恒 null，
 *   session 粒度是本系统原生属性，spec 已声明）。Tier 2 精读（recall_timeline）属 agent 用法，
 *   留给 Phase 2 free-call 臂
 * - scope 隔离：每 scope 一个目录树
 *
 * env: MEMBENCH_LLM_API_KEY / MEMBENCH_LLM_BASE_URL / MEMBENCH_LLM_MODEL（smoke_test 转发）
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import {
  existsSync, mkdirSync, readFileSync, writeFileSync, readdirSync, rmSync, cpSync,
} from "fs";
import { join } from "path";

const REPO_ROOT = join(import.meta.dir, "..", "..");
const STATE_DIR = process.env.MEMBENCH_STATE_DIR || join(REPO_ROOT, ".state", "intent");
const SNAP_ROOT = join(STATE_DIR, "..", "__snapshots__", "intent");

const LLM_KEY = process.env.MEMBENCH_LLM_API_KEY || "";
const LLM_BASE = (process.env.MEMBENCH_LLM_BASE_URL || "").replace(/\/$/, "");
const LLM_MODEL = process.env.MEMBENCH_LLM_MODEL || "glm-5.3";

let lastResetAt: string | null = null;
let llmCalls = 0;
let internalTokens = 0;  // 内部 LLM token 账（Tier 2 精读 + 摘要生成），stats.internal_llm

// ===== 工具函数 =====

function json(data: unknown) {
  return { content: [{ type: "text" as const, text: JSON.stringify(data) }] };
}

function scopeDir(scopeId: string) {
  return join(STATE_DIR, "scopes", scopeId);
}

function readScopes(): { scope_ids: string[]; sessions: string[]; n_units: number } {
  const p = join(STATE_DIR, "scopes.json");
  if (existsSync(p)) return JSON.parse(readFileSync(p, "utf-8"));
  return { scope_ids: [], sessions: [], n_units: 0 };
}

function writeScopes(scopeId: string | null, sessionId: string | null, nTurns: number) {
  const s = readScopes();
  if (scopeId && !s.scope_ids.includes(scopeId)) s.scope_ids.push(scopeId);
  if (sessionId && !s.sessions.includes(sessionId)) s.sessions.push(sessionId);
  s.n_units += nTurns;
  mkdirSync(STATE_DIR, { recursive: true });
  writeFileSync(join(STATE_DIR, "scopes.json"), JSON.stringify(s));
}

interface IntentEntry {
  sessionId: string;
  title: string;
  startedAt: string;
  settledAt: string;
  abstract: { scenario: string; intent: string; method: string; conclusion: string };
  keywords: string[];
}

function readIntents(scopeId: string): IntentEntry[] {
  const p = join(scopeDir(scopeId), "session-intent.json");
  if (!existsSync(p)) return [];
  return JSON.parse(readFileSync(p, "utf-8"));
}

// ===== LLM 摘要生成（ingest 加工，与 mem0 抽取同性质）=====

async function summarize(sessionId: string, turns: Array<{ role?: string; content?: string }>): Promise<IntentEntry> {
  const transcript = turns.map((t) => `${t.role || "user"}: ${t.content || ""}`).join("\n");
  const now = new Date().toISOString();
  if (!LLM_KEY) {
    // 无 LLM 配置时降级：首句做 intent，分词做 keywords（保证可跑通，质量打折并在 notes 声明）
    const first = (turns[0]?.content || "").slice(0, 60);
    return { sessionId, title: first, startedAt: now, settledAt: now,
      abstract: { scenario: "n/a", intent: first, method: "n/a", conclusion: "n/a" },
      keywords: Array.from(new Set((turns.map((t) => t.content || "").join(" ").match(/[\u4e00-\u9fff]{2}|[a-zA-Z]{3,}/g) || []).slice(0, 12))) };
  }
  const prompt = `分析以下对话，生成 JSON（不要其他文字）：{"title":"一句话标题","scenario":"场景","intent":"用户意图","method":"方法/过程","conclusion":"结论","keywords":["关键词",...6-10个]}\n\n${transcript}`;
  const body: Record<string, unknown> = {
    model: LLM_MODEL,
    messages: [{ role: "user", content: prompt }],
    temperature: 0,
  };
  // 智谱顶层字段：reasoning_effort 钉住（P5 修复：原两分支皆空的死代码）
  if (process.env.MEMBENCH_THINKING !== "enabled") {
    body.reasoning_effort = "low";
  }
  const res = await fetch(`${LLM_BASE}/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${LLM_KEY}` },
    body: JSON.stringify(body),
  });
  llmCalls += 1;
  if (!res.ok) {
    throw new Error(`意图摘要 LLM 调用失败: HTTP ${res.status}（不静默降级，P7 修复）`);
  }
  const data: any = await res.json();
  internalTokens += data?.usage?.total_tokens || 0;
  const raw = data?.choices?.[0]?.message?.content ?? "{}";
  const cleaned = raw.replace(/```json|```/g, "").trim();
  let parsed: any = {};
  try { parsed = JSON.parse(cleaned); } catch { parsed = {}; }
  return {
    sessionId,
    title: parsed.title || (turns[0]?.content || "").slice(0, 40),
    startedAt: turns[0]?.timestamp || now,
    settledAt: now,
    abstract: {
      scenario: parsed.scenario || "n/a",
      intent: parsed.intent || "n/a",
      method: parsed.method || "n/a",
      conclusion: parsed.conclusion || "n/a",
    },
    keywords: Array.isArray(parsed.keywords) ? parsed.keywords.slice(0, 12) : [],
  };
}

// ===== Tier 1 检索：双通道打分（A+，2026-08-21）=====
// 通道 1（原生）：query 与意图摘要的关键词匹配——intent 系统的设计主信号（中文个人会话验证过）
// 通道 2（A+ 适配）：query 与 session 原文 turn 的关键词匹配——修复英文语料下中文摘要的天然错配
// （LoCoMo 英文 query vs 中文摘要 tokenize 几乎零重叠，session 召回 0.429 卡死下游；
//   与 rag_baseline 纯原文检索相比，双通道叠故意图摘要信号才是可归因的对比：
//   intent(摘要+原文) > rag_baseline(纯原文) ⇔ 意图层有正贡献）
// 取两通道 max：任一命中即可召回，排序分取更强信号。

function loadTurns(scopeId: string, sessionId: string): Array<{ content?: string }> {
  const p = join(scopeDir(scopeId), "sessions", `${sessionId}.jsonl`);
  if (!existsSync(p)) return [];
  try {
    const t = JSON.parse(readFileSync(p, "utf-8"));
    return Array.isArray(t) ? t : [];
  } catch {
    return [];
  }
}

function scoreEntry(entry: IntentEntry, qTokens: Set<string>, scopeId: string): number {
  if (!qTokens.size) return 0;
  // 通道 1：意图摘要
  const hay = [entry.title, entry.abstract.scenario, entry.abstract.intent, entry.abstract.method, entry.abstract.conclusion, ...entry.keywords].join(" ");
  const t = tokenize(hay);
  let hit = 0;
  for (const q of qTokens) if (t.has(q)) hit += 1;
  const summaryScore = hit / qTokens.size;
  // 通道 2：原文 turn 最优命中
  let turnScore = 0;
  for (const turn of loadTurns(scopeId, entry.sessionId)) {
    const toks = tokenize(turn.content || "");
    let h = 0;
    for (const q of qTokens) if (toks.has(q)) h += 1;
    if (h / qTokens.size > turnScore) turnScore = h / qTokens.size;
  }
  return Math.max(summaryScore, turnScore);
}

// ===== 方案 A（2026-08-21 shakeout 修复）：envelope 附 query 命中的 session 原文摘录 =====
// 诊断：纯意图摘要无事实细节（LoCoMo 多为日期/人名/数字题），avg evidence 671 字符撑不起答题。
// 修复：从 sessions/<id>.jsonl 原文里选 query 命中的 top-3 turn（无命中退化为首 turn），
// 在 600 字符总预算内截断。turn 原文含 loader 加的 [日期] 前缀——事实题答案就在里面。

function tokenize(text: string): Set<string> {
  // 中文滑窗 bigram（重叠，与 mock server 的 Python 实现语义对齐）：
  // JS match(/[\u4e00-\u9fff]{2}/g) 是非重叠匹配——"帕丁森"只会切出"帕丁"丢"丁森"（2026-08-21
  // 深夜诊断：smoke 抖动 + 中文匹配能力残缺的根源），必须逐 run 滑窗
  const cnRuns = text.match(/[\u4e00-\u9fff]+/g) || [];
  const cn: string[] = [];
  for (const run of cnRuns) {
    for (let i = 0; i + 1 < run.length; i++) cn.push(run.slice(i, i + 2));
  }
  const en = (text.match(/[a-zA-Z]{3,}/g) || []).map((w) => w.toLowerCase());
  return new Set([...cn, ...en]);
}

function pickExcerpt(scopeId: string, sessionId: string, qTokens: Set<string>, budget: number): string {
  const p = join(scopeDir(scopeId), "sessions", `${sessionId}.jsonl`);
  if (!existsSync(p)) return "";
  const turns = loadTurns(scopeId, sessionId);
  if (!turns.length) return "";
  const scored = turns.map((t, i) => {
    const toks = tokenize(t.content || "");
    let hit = 0;
    for (const q of qTokens) if (toks.has(q)) hit += 1;
    return { i, hit, c: (t.content || "").trim() };
  });
  const ranked = scored.filter((s) => s.hit > 0).sort((a, b) => b.hit - a.hit || a.i - b.i);
  const chosen = ranked.length ? ranked.slice(0, 3) : [scored[0]];
  const parts: string[] = [];
  let used = 0;
  for (const c of chosen) {
    const frag = c.c.length > 170 ? c.c.slice(0, 169) + "…" : c.c;
    if (used + frag.length + 3 > budget) break;
    parts.push(frag);
    used += frag.length + 3;
  }
  return parts.join(" / ");
}

function renderEnvelope(entry: IntentEntry, score: number, scopeId: string, qTokens: Set<string>,
  tier2Quotes?: string[]) {
  // timestamp 语义修复（方案 A 诊断 3）：用对话发生时间 startedAt（turns[0].timestamp），
  // 不再用 ingest 时刻 settledAt——temporal 题依赖它
  const head = `- ${entry.startedAt} · [${entry.title}]（session:${entry.sessionId}）`;
  const gist = `意图: ${entry.abstract.intent}；结论: ${entry.abstract.conclusion}`.slice(0, 120);
  const budget = 600 - head.length - gist.length - 20;  // 20 = 换行+标点开销
  // 证据优先级：Tier 2 精读逐字引用（B）> query 命中 turn 机械摘录（A）
  let excerpt = "";
  if (tier2Quotes && tier2Quotes.length) {
    const parts: string[] = [];
    let used = 0;
    for (const q of tier2Quotes) {
      const frag = q.length > 240 ? q.slice(0, 239) + "…" : q;
      if (used + frag.length + 3 > Math.max(budget, 0)) break;
      parts.push(frag);
      used += frag.length + 3;
    }
    excerpt = parts.join(" / ");
  }
  if (!excerpt) excerpt = pickExcerpt(scopeId, entry.sessionId, qTokens, Math.max(budget, 0));
  let text = excerpt ? `${head}\n  ${gist}\n  原文: ${excerpt}` : `${head}\n  ${gist}`;
  if (text.length > 600) text = text.slice(0, 599) + "…";
  return {
    memory_id: entry.sessionId,
    text,
    source: { session_id: entry.sessionId, turn_range: null },
    timestamp: entry.startedAt,
    score: Number(score.toFixed(4)),
    raw_format: tier2Quotes && tier2Quotes.length ? "intent_session+tier2" : "intent_session+excerpt",
  };
}

// ===== Tier 2 精读（B，2026-08-21）：top-k session 原文一次 LLM 调用提炼逐字证据 =====
// intent-recall-mcp 完整形态 = search（Tier 1）+ read_session_detail（Tier 2 LLM 精读原文）。
// 适配层此前只接了 Tier 1；B 把精读接进 retrieve：Tier 1 筛候选 → LLM 读原文逐字引用 →
// 替代机械摘录。内部 LLM = 智谱 glm-5.3 temp=0（spec §7 统一），token 记 internal_llm。
// 失败降级为 A+ 行为（机械摘录），native_notes 记 TIER2_FALLBACK——不静默丢证据。

async function deepRead(query: string, entries: IntentEntry[], scopeId: string): Promise<Map<string, string[]>> {
  const out = new Map<string, string[]>();
  if (!LLM_KEY || !entries.length) return out;
  const blocks: string[] = [];
  for (const e of entries) {
    const turns = loadTurns(scopeId, e.sessionId);
    const text = turns.map((t) => t.content || "").join("\n").slice(0, 6000);  // 单 session 原文上限，防 prompt 爆
    if (text.trim()) blocks.push(`### ${e.sessionId}\n${text}`);
  }
  if (!blocks.length) return out;
  const prompt = `给定问题和若干段会话原文。从原文中提取与问题直接相关的证据片段，逐字引用（保留日期、数字、人名等细节，不要改写）。每个 session 输出 0-2 条证据；无相关内容则跳过该 session。只输出 JSON：{"evidence":[{"session":"<session_id>","quote":"<逐字引用>"}]}，没有证据则 {"evidence":[]}。

问题: ${query}

会话原文:
${blocks.join("\n\n")}`;
  const body: Record<string, unknown> = {
    model: LLM_MODEL,
    messages: [{ role: "user", content: prompt }],
    temperature: 0,
  };
  if (process.env.MEMBENCH_THINKING !== "enabled") body.reasoning_effort = "low";
  const res = await fetch(`${LLM_BASE}/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${LLM_KEY}` },
    body: JSON.stringify(body),
  });
  llmCalls += 1;
  if (!res.ok) throw new Error(`Tier2 LLM HTTP ${res.status}`);
  const data: any = await res.json();
  internalTokens += data?.usage?.total_tokens || 0;
  const raw = data?.choices?.[0]?.message?.content ?? "{}";
  const cleaned = raw.replace(/```json|```/g, "").trim();
  let parsed: any = {};
  try { parsed = JSON.parse(cleaned); } catch { return out; }
  if (Array.isArray(parsed?.evidence)) {
    for (const item of parsed.evidence) {
      if (item?.session && typeof item.quote === "string" && item.quote.trim()) {
        const list = out.get(item.session) || [];
        if (list.length < 2) list.push(item.quote.trim());
        out.set(item.session, list);
      }
    }
  }
  return out;
}

// ===== MCP Server =====

const server = new Server({ name: "intent", version: "0.1.0" }, { capabilities: { tools: {} } });

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    { name: "add_conversation", description: "写 session JSONL + LLM 生成意图摘要（Tier 1 数据源）",
      inputSchema: { type: "object", properties: {
        session_id: { type: "string" }, turns: { type: "array" }, scope: { type: "object" },
        metadata: { type: "object" } }, required: ["session_id", "turns", "scope"] } },
    { name: "retrieve", description: "Tier 1 意图摘要检索（session 粒度）",
      inputSchema: { type: "object", properties: {
        query: { type: "string" }, query_mode: { type: "string" }, top_k: { type: "number" },
        filter: { type: "object" } }, required: ["query"] } },
    { name: "reset", description: "清空全部状态", inputSchema: { type: "object", properties: {} } },
    { name: "stats", description: "状态报告", inputSchema: { type: "object", properties: {} } },
    { name: "snapshot", description: "目录快照", inputSchema: { type: "object", properties: { tag: { type: "string" } }, required: ["tag"] } },
    { name: "restore", description: "从快照恢复", inputSchema: { type: "object", properties: { tag: { type: "string" } }, required: ["tag"] } },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (req) => {
  const { name, arguments: args } = req.params;
  const a = (args || {}) as any;
  try {
    if (name === "add_conversation") {
      const t0 = Date.now();
      const scopeId = a.scope?.id || "default";
      const dir = join(scopeDir(scopeId), "sessions");
      mkdirSync(dir, { recursive: true });
      writeFileSync(join(dir, `${a.session_id}.jsonl`), JSON.stringify(a.turns));
      const entry = await summarize(a.session_id, a.turns || []);
      const intents = readIntents(scopeId).filter((e) => e.sessionId !== a.session_id);
      intents.push(entry);
      writeFileSync(join(scopeDir(scopeId), "session-intent.json"), JSON.stringify(intents));
      writeScopes(scopeId, a.session_id, (a.turns || []).length);
      return json({ accepted_turns: (a.turns || []).length,
        native_notes: `意图摘要生成完成，耗时 ${Date.now() - t0}ms（LLM: ${LLM_MODEL}${LLM_KEY ? "" : "，未配置降级为关键词模式"}）` });
    }
    if (name === "retrieve") {
      const t0 = Date.now();
      const scopes = readScopes();
      const parts: string[] = [];
      let scopeId = a.filter?.scope_id;
      if (!scopeId) {
        if (scopes.scope_ids.length > 1) parts.push("MULTI_SCOPE: 未指定 filter.scope_id，仅检索首个 scope");
        scopeId = scopes.scope_ids[0] || "default";
      }
      if (a.filter && Object.keys(a.filter).some((k) => k !== "scope_id")) parts.push("FILTER_IGNORED: 仅支持 scope_id");
      const qTokens = tokenize(a.query || "");
      const ranked = readIntents(scopeId)
        .map((e) => ({ e, s: scoreEntry(e, qTokens, scopeId) }))
        .filter((x) => x.s > 0)
        .sort((x, y) => y.s - x.s)
        .slice(0, a.top_k || 5);
      // Tier 2 精读（B）：失败降级 A+ 机械摘录，不静默丢证据
      let tier2 = new Map<string, string[]>();
      if (ranked.length) {
        try {
          tier2 = await deepRead(a.query || "", ranked.map((x) => x.e), scopeId);
        } catch (err) {
          parts.push(`TIER2_FALLBACK: ${String(err).slice(0, 100)}`);
        }
      }
      return json({ results: ranked.map((x) => renderEnvelope(x.e, x.s, scopeId, qTokens, tier2.get(x.e.sessionId))),
        query_used: a.query, query_mode: a.query_mode || "fixed",
        latency_ms: Date.now() - t0, native_notes: parts.join("; ") });
    }
    if (name === "reset") {
      rmSync(join(STATE_DIR, "scopes"), { recursive: true, force: true });
      rmSync(join(STATE_DIR, "scopes.json"), { force: true });
      lastResetAt = new Date().toISOString();
      return json({ ok: true, cleared: { system: "intent" } });
    }
    if (name === "stats") {
      const s = readScopes();
      return json({ n_memories: s.n_units, n_sessions: s.sessions.length,
        tokens_used: { ingest: null, retrieve: 0, internal_llm: internalTokens }, llm_calls: llmCalls,
        last_reset_at: lastResetAt, snapshots: listSnaps() });
    }
    if (name === "snapshot") {
      const dst = join(SNAP_ROOT, a.tag);
      rmSync(dst, { recursive: true, force: true });
      mkdirSync(dst, { recursive: true });
      cpSync(join(STATE_DIR, "scopes"), join(dst, "scopes"), { recursive: true });
      if (existsSync(join(STATE_DIR, "scopes.json"))) cpSync(join(STATE_DIR, "scopes.json"), join(dst, "scopes.json"));
      return json({ ok: true, tag: a.tag });
    }
    if (name === "restore") {
      const src = join(SNAP_ROOT, a.tag);
      if (!existsSync(join(src, "scopes"))) return json({ ok: false, error: "SNAPSHOT_NOT_FOUND", tag: a.tag });
      rmSync(join(STATE_DIR, "scopes"), { recursive: true, force: true });
      cpSync(join(src, "scopes"), join(STATE_DIR, "scopes"), { recursive: true });
      if (existsSync(join(src, "scopes.json"))) cpSync(join(src, "scopes.json"), join(STATE_DIR, "scopes.json"));
      return json({ ok: true, tag: a.tag });
    }
    return json({ error: `unknown tool: ${name}` });
  } catch (err) {
    return json({ error: String(err) });
  }
});

function listSnaps(): string[] {
  if (!existsSync(SNAP_ROOT)) return [];
  return readdirSync(SNAP_ROOT).sort();
}

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
}
main();
