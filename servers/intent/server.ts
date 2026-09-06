/**
 * intent：意图系统 Robust Baseline v1（memory-bench 六工具契约）—— 2026-09-07
 * 设计文档：./BASELINE-DESIGN.md（策略：全机制 + 全开关；LoCoMo 出粗结论；消融留归因）
 *
 * 构建期（每 session：2 次 LLM + 1 次 embedding 批调用）：
 *   A2-1 蒸馏     英文四段式意图摘要 + 5-10 条自包含事实（三人称/代词消解/绝对日期）
 *   A2-2 自检     第二次 LLM 对照 transcript 修补（graphiti 论文有代码无——全领域空白）    [selfcheck]
 *   A3-1 修订     version/status/history 非破坏归档（同 session 重灌不覆盖）              常开
 *   A3-2 效用     utility.json 记 retrieval_count/last_used——只记账不反馈（保检索确定性）  常开
 *   A4-1 双索引   facts+摘要 embedding（embedding-3 同口径）+ 关键词 token 集             常算
 *   A4-2 意图链   摘要向量 cos≥0.60 挂链，存 sessionId 指针（绕开 amem 位置索引坑）        [chains]
 *
 * 查询期（每 query：1 次 embedding，零文本 LLM——A 档被动面）：
 *   B1 线索       tokenize + query embedding（失败重试 ×3 → 降级纯关键词并记 note）
 *   B2 召回       五路排名 facts-kw/facts-dense/summary-kw/summary-dense/raw-kw → RRF(60)  [dense]
 *   B3 扩展       链邻居 0.5 折扣进候选，全局 +5 上限                                      [expand]
 *   B4 去冗定选   MMR λ=0.7（摘要向量相似度），候选池 2×top_k                              [mmr]
 *   B6 交付       时间升序组装（score 定入选、时间定顺序）+ 意图概要 + 命中事实 + 原文摘录
 *                 + turn_range + 事实时间戳
 *
 * 三臂入口（state/快照共享）：
 *   intent_full  = baseline（本文件直跑，全开）
 *   intent_facts = 纯事实库替身（MODE=facts，意图层归因用，消融期跑）
 *   intent_tier2 = agent 形态（TIER2=on，检索期 LLM 精读，B 档单列）
 * 消融开关：MEMBENCH_INTENT_ABLATE=selfcheck,dense,chains,expand,mmr（逗号分隔，默认全开）
 *
 * env: MEMBENCH_LLM_API_KEY / MEMBENCH_LLM_BASE_URL / MEMBENCH_LLM_MODEL
 *      （embedding 走智谱普通通道：MEMBENCH_EMBED_* 可覆盖，缺省从 LLM_* 推导并去 /coding）
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

// embedding 走智谱普通通道（coding 通道无 embedding 权限——rag_baseline 同约定）
const EMBED_BASE = (process.env.MEMBENCH_EMBED_BASE_URL || LLM_BASE.replace("/coding", "")).replace(/\/$/, "");
const EMBED_KEY = process.env.MEMBENCH_EMBED_API_KEY || LLM_KEY;
const EMBED_MODEL = process.env.MEMBENCH_EMBED_MODEL || "embedding-3";

// ===== 臂开关 =====
const MODE = (process.env.MEMBENCH_INTENT_MODE || "full") as "full" | "facts";
const TIER2 = process.env.MEMBENCH_INTENT_TIER2 === "on";
const OFF = new Set((process.env.MEMBENCH_INTENT_ABLATE || "").split(",").map((s) => s.trim()).filter(Boolean));
const on = (k: string) => !OFF.has(k);

const RRF_K = 60;
const CHAIN_MIN_COS = 0.60;
const EXPAND_DISCOUNT = 0.5;
const EXPAND_CAP = 5;
const MMR_LAMBDA = 0.7;
const TIER2_READ_TOP = 5;

let lastResetAt: string | null = null;
let llmCalls = 0;
let internalTokens = 0;   // 文本 LLM token（蒸馏+自检+Tier2）
let embedCalls = 0;
let embedTokens = 0;

// ===== 基础工具 =====

function json(data: unknown) {
  return { content: [{ type: "text" as const, text: JSON.stringify(data) }] };
}

function scopeDir(scopeId: string) {
  return join(STATE_DIR, "scopes", scopeId);
}

function readJson<T>(p: string, fallback: T): T {
  if (!existsSync(p)) return fallback;
  try { return JSON.parse(readFileSync(p, "utf-8")); } catch { return fallback; }
}

function writeJson(p: string, data: unknown) {
  mkdirSync(join(p, ".."), { recursive: true });
  writeFileSync(p, JSON.stringify(data));
}

function readScopes(): { scope_ids: string[]; sessions: string[]; n_units: number } {
  return readJson(join(STATE_DIR, "scopes.json"), { scope_ids: [], sessions: [], n_units: 0 });
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
  facts: string[];
  version: number;          // A3 非破坏修订
  status: "active";
  history: Array<{ version: number; settledAt: string; abstract: IntentEntry["abstract"]; facts: string[]; status: "superseded" }>;
}

function readIntents(scopeId: string): IntentEntry[] {
  const arr = readJson<any[]>(join(scopeDir(scopeId), "session-intent.json"), []);
  return (Array.isArray(arr) ? arr : []).map((e: any) => ({
    ...e,
    keywords: Array.isArray(e.keywords) ? e.keywords : [],
    facts: Array.isArray(e.facts) ? e.facts : [],
    version: e.version || 1,
    status: "active" as const,
    history: Array.isArray(e.history) ? e.history : [],
  }));
}

// ===== sidecar：向量 / 意图链 / 效用（快照随 scopes 目录整体走）=====

type VecMap = Record<string, { summary: number[]; facts: number[][] }>;
type ChainMap = Record<string, { prev: string | null; chainId: string }>;
type UtilMap = Record<string, { retrievals: number; last_used: string | null }>;

const vecCache = new Map<string, VecMap>();

function loadVectors(scopeId: string): VecMap {
  if (vecCache.has(scopeId)) return vecCache.get(scopeId)!;
  const v = readJson<VecMap>(join(scopeDir(scopeId), "vectors.json"), {});
  vecCache.set(scopeId, v);
  return v;
}
function saveVectors(scopeId: string, v: VecMap) {
  writeJson(join(scopeDir(scopeId), "vectors.json"), v);
  vecCache.set(scopeId, v);
}
function loadChains(scopeId: string): ChainMap {
  return readJson<ChainMap>(join(scopeDir(scopeId), "chains.json"), {});
}
function saveChains(scopeId: string, c: ChainMap) {
  writeJson(join(scopeDir(scopeId), "chains.json"), c);
}
function loadUtility(scopeId: string): UtilMap {
  return readJson<UtilMap>(join(scopeDir(scopeId), "utility.json"), {});
}
function saveUtility(scopeId: string, u: UtilMap) {
  writeJson(join(scopeDir(scopeId), "utility.json"), u);
}
function invalidateCaches() {
  vecCache.clear();
}

// ===== embedding（与 rag_baseline/mem0/graphiti/amem_fixed 同口径）=====

async function embed(texts: string[]): Promise<number[][]> {
  let lastErr: unknown = null;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const res = await fetch(`${EMBED_BASE}/embeddings`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${EMBED_KEY}` },
        body: JSON.stringify({ model: EMBED_MODEL, input: texts }),
      });
      embedCalls += 1;
      if (!res.ok) throw new Error(`embeddings HTTP ${res.status}`);
      const data: any = await res.json();
      embedTokens += data?.usage?.total_tokens || 0;
      const out = (data?.data || []).map((d: any) => d.embedding as number[]);
      if (out.length !== texts.length) throw new Error(`embeddings 返回数不符: ${out.length}/${texts.length}`);
      return out;
    } catch (err) {
      lastErr = err;
      await new Promise((r) => setTimeout(r, 1000 * (attempt + 1) * (attempt + 1)));
    }
  }
  throw new Error(`embedding 三次重试耗尽: ${String(lastErr).slice(0, 120)}`);
}

function cosine(a: number[], b: number[]): number {
  if (!a?.length || !b?.length || a.length !== b.length) return 0;
  let dot = 0, na = 0, nb = 0;
  for (let i = 0; i < a.length; i++) { dot += a[i] * b[i]; na += a[i] * a[i]; nb += b[i] * b[i]; }
  if (!na || !nb) return 0;
  return dot / (Math.sqrt(na) * Math.sqrt(nb));
}

// ===== A2 蒸馏 + 自检 =====

function transcriptOf(turns: Array<{ role?: string; content?: string }>): string {
  return turns.map((t) => `${t.role || "user"}: ${t.content || ""}`).join("\n");
}

const SCHEMA_HINT = `{"title":"one-line title","scenario":"setting in one sentence","intent":"what the speakers want, one sentence","method":"how it unfolds, one sentence","conclusion":"outcome, one sentence","keywords":["6-10 keywords"],"facts":["5-10 statements"]}`;

async function llmJson(prompt: string): Promise<any> {
  const body: Record<string, unknown> = {
    model: LLM_MODEL,
    messages: [{ role: "user", content: prompt }],
    temperature: 0,
  };
  if (process.env.MEMBENCH_THINKING !== "enabled") body.reasoning_effort = "low";  // P5 修复保留
  const res = await fetch(`${LLM_BASE}/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${LLM_KEY}` },
    body: JSON.stringify(body),
  });
  llmCalls += 1;
  if (!res.ok) throw new Error(`LLM HTTP ${res.status}（不静默降级，P7 修复）`);
  const data: any = await res.json();
  internalTokens += data?.usage?.total_tokens || 0;
  const raw = data?.choices?.[0]?.message?.content ?? "{}";
  const cleaned = raw.replace(/```json|```/g, "").trim();
  try { return JSON.parse(cleaned); } catch { return null; }
}

function entryFromParsed(sessionId: string, parsed: any, turns: Array<{ role?: string; content?: string; timestamp?: string }>, now: string): IntentEntry {
  const facts = (Array.isArray(parsed?.facts) ? parsed.facts : [])
    .filter((f: unknown) => typeof f === "string" && (f as string).trim().length > 0)
    .map((f: string) => f.trim())
    .slice(0, 10);
  return {
    sessionId,
    title: parsed?.title || (turns[0]?.content || "").slice(0, 40),
    startedAt: turns[0]?.timestamp || now,
    settledAt: now,
    abstract: {
      scenario: parsed?.scenario || "n/a",
      intent: parsed?.intent || "n/a",
      method: parsed?.method || "n/a",
      conclusion: parsed?.conclusion || "n/a",
    },
    keywords: Array.isArray(parsed?.keywords) ? parsed.keywords.slice(0, 12) : [],
    facts,
    version: 1,
    status: "active",
    history: [],
  };
}

async function distill(sessionId: string, turns: Array<{ role?: string; content?: string; timestamp?: string }>): Promise<IntentEntry> {
  const now = new Date().toISOString();
  if (!LLM_KEY) {
    // 无 LLM 配置降级：保证契约可跑通，质量打折在 notes 声明
    const first = (turns[0]?.content || "").slice(0, 60);
    return { sessionId, title: first, startedAt: turns[0]?.timestamp || now, settledAt: now,
      abstract: { scenario: "n/a", intent: first, method: "n/a", conclusion: "n/a" },
      keywords: Array.from(new Set((turns.map((t) => t.content || "").join(" ").match(/[\u4e00-\u9fff]{2}|[a-zA-Z]{3,}/g) || []).slice(0, 12))),
      facts: [], version: 1, status: "active", history: [] };
  }
  const transcript = transcriptOf(turns);
  // facts 规则压缩自 mem0 核心四条 + mandol L0 自包含改写 + atommem 第三人称规则；
  // 绝对日期依据 loader 注入的 [YYYY-MM-DD] turn 前缀（bench-design §3.2）
  const prompt = `Analyze the conversation transcript and output ONLY a JSON object (no other text):
${SCHEMA_HINT}

Rules for "facts" (the most important field):
- Each fact is ONE self-contained sentence a stranger could understand with no context.
- Third person only; use explicit names, never pronouns (no he/she/they/it as subjects).
- Resolve relative time ("yesterday", "last month", "next week") into absolute dates using the [YYYY-MM-DD] prefixes on the turns; write dates as YYYY-MM-DD. Never invent a year.
- Copy names, numbers, places, dates exactly as written in the text.
- Prefer facts that answer who / what / when / where.
- English only.

Transcript:
${transcript}`;
  const parsed = await llmJson(prompt);
  let entry = entryFromParsed(sessionId, parsed, turns, now);

  // A2-2 自检（graphiti 论文写了、全领域代码没实现的一步）：对照 transcript 修补
  if (on("selfcheck")) {
    const checkPrompt = `Below is a conversation transcript and a draft JSON analysis of it. Verify the draft against the transcript and fix errors:
- wrong or invented dates (dates must come from the [YYYY-MM-DD] turn prefixes; never invent a year),
- wrong or missing names; pronouns used as sentence subjects,
- facts that are not self-contained or contradict the transcript,
- missing high-value who/what/when/where facts (add up to 2).
Keep the exact same JSON schema. Output ONLY the corrected JSON.

Transcript:
${transcript}

Draft:
${JSON.stringify({ title: entry.title, scenario: entry.abstract.scenario, intent: entry.abstract.intent, method: entry.abstract.method, conclusion: entry.abstract.conclusion, keywords: entry.keywords, facts: entry.facts })}`;
    try {
      const checked = await llmJson(checkPrompt);
      if (checked && Array.isArray(checked.facts) && checked.facts.length) {
        entry = entryFromParsed(sessionId, checked, turns, now);
      }
    } catch {
      // 自检失败保留初稿（不因增强步骤丢主产物）
    }
  }
  return entry;
}

// ===== 打分原语 =====

function tokenize(text: string): Set<string> {
  // 中文滑窗 bigram（重叠）+ 英文小写词（≥3 字符）；与 mock server 语义对齐
  const cnRuns = text.match(/[\u4e00-\u9fff]+/g) || [];
  const cn: string[] = [];
  for (const run of cnRuns) {
    for (let i = 0; i + 1 < run.length; i++) cn.push(run.slice(i, i + 2));
  }
  const en = (text.match(/[a-zA-Z]{3,}/g) || []).map((w) => w.toLowerCase());
  return new Set([...cn, ...en]);
}

function overlapScore(text: string, qTokens: Set<string>): number {
  if (!qTokens.size || !text) return 0;
  const t = tokenize(text);
  let hit = 0;
  for (const q of qTokens) if (t.has(q)) hit += 1;
  return hit / qTokens.size;
}

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

function summaryHay(e: IntentEntry): string {
  return [e.title, e.abstract.scenario, e.abstract.intent, e.abstract.method, e.abstract.conclusion, ...e.keywords].join(" ");
}

function bestFactScore(e: IntentEntry, qTokens: Set<string>): number {
  let best = 0;
  for (const f of e.facts) {
    const s = overlapScore(f, qTokens);
    if (s > best) best = s;
  }
  return best;
}

function rawScore(scopeId: string, sessionId: string, qTokens: Set<string>): number {
  let best = 0;
  for (const turn of loadTurns(scopeId, sessionId)) {
    const s = overlapScore(turn.content || "", qTokens);
    if (s > best) best = s;
  }
  return best;
}

// ===== 原文摘录（证据出口；turn_range 落地）=====

function pickExcerpt(scopeId: string, sessionId: string, qTokens: Set<string>, budget: number):
  { text: string; range: [number, number] | null } {
  const turns = loadTurns(scopeId, sessionId);
  if (!turns.length) return { text: "", range: null };
  const scored = turns.map((t, i) => {
    const toks = tokenize(t.content || "");
    let hit = 0;
    for (const q of qTokens) if (toks.has(q)) hit += 1;
    return { i, hit, c: (t.content || "").trim() };
  });
  const ranked = scored.filter((s) => s.hit > 0).sort((a, b) => b.hit - a.hit || a.i - b.i);
  const chosen = ranked.length ? ranked.slice(0, 3) : [scored[0]];
  const parts: string[] = [];
  const usedIdx: number[] = [];
  let used = 0;
  for (const c of chosen) {
    const frag = c.c.length > 170 ? c.c.slice(0, 169) + "…" : c.c;
    if (used + frag.length + 3 > budget) break;
    parts.push(frag);
    usedIdx.push(c.i);
    used += frag.length + 3;
  }
  const range: [number, number] | null = usedIdx.length
    ? [Math.min(...usedIdx), Math.max(...usedIdx)]
    : null;
  return { text: parts.join(" / "), range };
}

// ===== envelope 渲染 =====

// facts 臂（消融期用）：mem0 形态——一条事实 = 一个 memory
function renderEnvelopeFact(e: IntentEntry, idx: number, fact: string, score: number) {
  const text = fact.length > 600 ? fact.slice(0, 599) + "…" : fact;
  return {
    memory_id: `${e.sessionId}#f${idx}`,
    text,
    source: { session_id: e.sessionId, turn_range: null },
    timestamp: e.startedAt,
    score: Number(score.toFixed(4)),
    raw_format: "intent_fact",
  };
}

// baseline：session 粒度——意图概要 + 命中事实 + 原文摘录；timestamp 用事实时间
function renderEnvelopeFull(e: IntentEntry, score: number, scopeId: string, qTokens: Set<string>,
  tier2Quotes?: string[]) {
  const day = (e.startedAt || "").slice(0, 10);
  const head = `- ${day} · ${e.title} (session:${e.sessionId})`;
  const gist = `intent: ${e.abstract.intent}; conclusion: ${e.abstract.conclusion}`.slice(0, 140);
  const matched = e.facts
    .map((f) => ({ f, s: overlapScore(f, qTokens) }))
    .filter((x) => x.s > 0)
    .sort((a, b) => b.s - a.s)
    .slice(0, 2)
    .map((x) => (x.f.length > 118 ? x.f.slice(0, 117) + "…" : x.f));
  const factLine = matched.length ? `facts: ${matched.join(" | ")}` : "";
  const fixed = head.length + gist.length + factLine.length + 30;
  const budget = Math.max(600 - fixed, 80);
  let excerpt = "";
  let range: [number, number] | null = null;
  if (tier2Quotes && tier2Quotes.length) {
    const parts: string[] = [];
    let used = 0;
    for (const q of tier2Quotes) {
      const frag = q.length > 240 ? q.slice(0, 239) + "…" : q;
      if (used + frag.length + 3 > budget) break;
      parts.push(frag);
      used += frag.length + 3;
    }
    excerpt = parts.join(" / ");
  }
  if (!excerpt) {
    const p = pickExcerpt(scopeId, e.sessionId, qTokens, budget);
    excerpt = p.text;
    range = p.range;
  }
  let text = [head, `  ${gist}`, factLine ? `  ${factLine}` : "", excerpt ? `  src: ${excerpt}` : ""]
    .filter(Boolean).join("\n");
  if (text.length > 600) text = text.slice(0, 599) + "…";
  return {
    memory_id: e.sessionId,
    text,
    source: { session_id: e.sessionId, turn_range: tier2Quotes && tier2Quotes.length ? null : range },
    timestamp: e.startedAt,
    score: Number(score.toFixed(4)),
    raw_format: tier2Quotes && tier2Quotes.length ? "intent_session+tier2" : "intent_session+excerpt",
  };
}

// ===== Tier 2 精读（intent_tier2 臂专属，active 类，B 档单列）=====

async function deepRead(query: string, entries: IntentEntry[], scopeId: string): Promise<Map<string, string[]>> {
  const out = new Map<string, string[]>();
  if (!LLM_KEY || !entries.length) return out;
  const blocks: string[] = [];
  for (const e of entries) {
    const turns = loadTurns(scopeId, e.sessionId);
    const text = turns.map((t) => t.content || "").join("\n").slice(0, 6000);
    if (text.trim()) blocks.push(`### ${e.sessionId}\n${text}`);
  }
  if (!blocks.length) return out;
  const prompt = `Given a question and several session transcripts, extract evidence fragments directly relevant to the question. Quote verbatim (keep dates, numbers, names exactly; do not paraphrase). Output 0-2 quotes per session; skip sessions with nothing relevant. Output ONLY JSON: {"evidence":[{"session":"<session_id>","quote":"<verbatim quote>"}]}; if none: {"evidence":[]}.

Question: ${query}

Transcripts:
${blocks.join("\n\n")}`;
  const parsed = await llmJson(prompt);
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

const server = new Server({ name: "intent", version: "0.3.0" }, { capabilities: { tools: {} } });

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    { name: "add_conversation", description: "写 session JSONL + 蒸馏意图摘要与自包含事实 + 自检 + 向量/意图链/效用 sidecar",
      inputSchema: { type: "object", properties: {
        session_id: { type: "string" }, turns: { type: "array" }, scope: { type: "object" },
        metadata: { type: "object" } }, required: ["session_id", "turns", "scope"] } },
    { name: "retrieve", description: `检索（mode=${MODE}${TIER2 ? "+tier2" : ""}${OFF.size ? " ablate=" + [...OFF].join("/") : ""}）`,
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

      const notes: string[] = [];
      let entry = await distill(a.session_id, a.turns || []);

      // A3-1 非破坏修订：同 session 重灌归档旧版（不覆盖销毁——mandol 重灌事故的反面）
      const intents = readIntents(scopeId);
      const prev = intents.find((e) => e.sessionId === a.session_id);
      if (prev) {
        entry.version = (prev.version || 1) + 1;
        entry.history = [
          ...(prev.history || []).slice(-2),
          { version: prev.version || 1, settledAt: prev.settledAt, abstract: prev.abstract, facts: prev.facts, status: "superseded" as const },
        ];
        notes.push(`REVISED: v${prev.version || 1}→v${entry.version}（旧版已归档非覆盖）`);
      }
      const nextIntents = intents.filter((e) => e.sessionId !== a.session_id);
      nextIntents.push(entry);
      writeJson(join(scopeDir(scopeId), "session-intent.json"), nextIntents);

      // A4-1 向量 sidecar（facts + 摘要一次批调用；失败不阻断——关键词通道仍可用，但要留痕）
      try {
        const vecs = await embed([summaryHay(entry), ...entry.facts]);
        const vmap = loadVectors(scopeId);
        vmap[a.session_id] = { summary: vecs[0], facts: vecs.slice(1) };
        saveVectors(scopeId, vmap);
      } catch (err) {
        notes.push(`EMBED_FAIL: ${String(err).slice(0, 80)}`);
      }

      // A4-2 意图链：与库内最相似 session 的摘要向量比对（存 sessionId 指针，非位置索引）
      if (on("chains")) {
        const vmap = loadVectors(scopeId);
        const mine = vmap[a.session_id]?.summary;
        if (mine) {
          const chains = loadChains(scopeId);
          let bestId: string | null = null;
          let bestCos = 0;
          for (const [sid, v] of Object.entries(vmap)) {
            if (sid === a.session_id || !v.summary) continue;
            const c = cosine(mine, v.summary);
            if (c > bestCos) { bestCos = c; bestId = sid; }
          }
          if (bestId && bestCos >= CHAIN_MIN_COS) {
            chains[a.session_id] = { prev: bestId, chainId: chains[bestId]?.chainId || bestId };
            notes.push(`CHAINED: →${bestId} cos=${bestCos.toFixed(3)}`);
          } else {
            chains[a.session_id] = { prev: null, chainId: a.session_id };
          }
          saveChains(scopeId, chains);
        }
      }

      // A3-2 效用记账初始化
      const util = loadUtility(scopeId);
      util[a.session_id] = util[a.session_id] || { retrievals: 0, last_used: null };
      saveUtility(scopeId, util);

      writeScopes(scopeId, a.session_id, (a.turns || []).length);
      return json({ accepted_turns: (a.turns || []).length,
        native_notes: [`蒸馏${on("selfcheck") ? "+自检" : ""}完成：${entry.facts.length} 条事实，耗时 ${Date.now() - t0}ms（LLM: ${LLM_MODEL}${LLM_KEY ? "" : "，未配置降级为关键词模式"}）`, ...notes].join("; ") });
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
      const topK = a.top_k || 20;
      const entries = readIntents(scopeId);
      let results: any[] = [];

      if (MODE === "facts") {
        // 消融臂：全 scope 事实池按重叠度排序，fact 粒度返回（mem0 形态）
        const pool: Array<{ e: IntentEntry; i: number; f: string; s: number }> = [];
        for (const e of entries) {
          e.facts.forEach((f, i) => {
            const s = overlapScore(f, qTokens);
            if (s > 0) pool.push({ e, i, f, s });
          });
        }
        pool.sort((x, y) => y.s - x.s || ((x.e.startedAt || "") < (y.e.startedAt || "") ? -1 : 1));
        results = pool.slice(0, topK).map((x) => renderEnvelopeFact(x.e, x.i, x.f, x.s));
      } else {
        const vmap = loadVectors(scopeId);
        const byId = new Map(entries.map((e) => [e.sessionId, e] as const));

        // B1 线索：query embedding（重试在 embed() 内；仍失败则降级纯关键词并留痕）
        let qVec: number[] | null = null;
        if (on("dense")) {
          try { qVec = (await embed([a.query || ""]))[0]; }
          catch (err) { parts.push(`DENSE_FALLBACK: ${String(err).slice(0, 80)}`); }
        }

        // B2 五路排名 → RRF
        const rankings: Array<Array<{ id: string; s: number }>> = [];
        const factsKw: Array<{ id: string; s: number }> = [];
        const sumKw: Array<{ id: string; s: number }> = [];
        const rawKw: Array<{ id: string; s: number }> = [];
        const factsDe: Array<{ id: string; s: number }> = [];
        const sumDe: Array<{ id: string; s: number }> = [];
        for (const e of entries) {
          const sFk = bestFactScore(e, qTokens);
          const sSk = overlapScore(summaryHay(e), qTokens);
          const sRk = rawScore(scopeId, e.sessionId, qTokens);
          if (sFk > 0) factsKw.push({ id: e.sessionId, s: sFk });
          if (sSk > 0) sumKw.push({ id: e.sessionId, s: sSk });
          if (sRk > 0) rawKw.push({ id: e.sessionId, s: sRk });
          const v = vmap[e.sessionId];
          if (qVec && v) {
            let fd = 0;
            for (const fv of v.facts) { const c = cosine(qVec, fv); if (c > fd) fd = c; }
            if (fd > 0) factsDe.push({ id: e.sessionId, s: fd });
            const sd = v.summary ? cosine(qVec, v.summary) : 0;
            if (sd > 0) sumDe.push({ id: e.sessionId, s: sd });
          }
        }
        rankings.push(factsKw, sumKw, rawKw);
        if (qVec) rankings.push(factsDe, sumDe);
        const rrf = new Map<string, number>();
        for (const list of rankings) {
          list.sort((x, y) => y.s - x.s || (x.id < y.id ? -1 : 1));
          list.forEach((x, rank) => rrf.set(x.id, (rrf.get(x.id) || 0) + 1 / (RRF_K + rank + 1)));
        }

        // B3 链扩展：入选者的链邻居折扣进候选
        if (on("chains") && on("expand") && rrf.size) {
          const chains = loadChains(scopeId);
          const seeds = [...rrf.entries()].sort((x, y) => y[1] - x[1]).slice(0, topK);
          let added = 0;
          for (const [sid, s] of seeds) {
            if (added >= EXPAND_CAP) break;
            const neighbors: string[] = [];
            const prev = chains[sid]?.prev;
            if (prev) neighbors.push(prev);
            for (const [oid, c] of Object.entries(chains)) if (c.prev === sid) neighbors.push(oid);
            for (const nb of neighbors) {
              if (added >= EXPAND_CAP) break;
              if (!rrf.has(nb) && byId.has(nb)) {
                rrf.set(nb, s * EXPAND_DISCOUNT);
                added += 1;
              }
            }
          }
          if (added) parts.push(`EXPANDED: +${added}`);
        }

        // B4 MMR 去冗定选（候选池 2×topK；相似度用摘要向量，缺向量按 0）
        let selectedIds: Array<{ id: string; s: number }> =
          [...rrf.entries()].map(([id, s]) => ({ id, s })).sort((x, y) => y.s - x.s || (x.id < y.id ? -1 : 1));
        if (on("mmr") && selectedIds.length > topK) {
          const pool = selectedIds.slice(0, 2 * topK);
          const maxS = pool[0]?.s || 1;
          const chosen: Array<{ id: string; s: number }> = [];
          const rest = [...pool];
          while (chosen.length < topK && rest.length) {
            let bestIdx = 0;
            let bestVal = -Infinity;
            for (let i = 0; i < rest.length; i++) {
              const cand = rest[i];
              let maxSim = 0;
              const cv = vmap[cand.id]?.summary;
              if (cv) {
                for (const c of chosen) {
                  const sv = vmap[c.id]?.summary;
                  if (sv) { const sim = cosine(cv, sv); if (sim > maxSim) maxSim = sim; }
                }
              }
              const val = MMR_LAMBDA * (cand.s / maxS) - (1 - MMR_LAMBDA) * maxSim;
              if (val > bestVal) { bestVal = val; bestIdx = i; }
            }
            chosen.push(rest.splice(bestIdx, 1)[0]);
          }
          selectedIds = chosen;
        } else {
          selectedIds = selectedIds.slice(0, topK);
        }

        // Tier2（intent_tier2 臂）：对 RRF 序前 5 精读
        let tier2 = new Map<string, string[]>();
        if (TIER2 && selectedIds.length) {
          try {
            const top = selectedIds.slice(0, TIER2_READ_TOP)
              .map((x) => byId.get(x.id))
              .filter((e): e is IntentEntry => Boolean(e));
            tier2 = await deepRead(a.query || "", top, scopeId);
          } catch (err) {
            parts.push(`TIER2_FALLBACK: ${String(err).slice(0, 100)}`);
          }
        }

        // A3-2 效用记账（只记录不反馈——检索确定性优先）
        {
          const util = loadUtility(scopeId);
          const now = new Date().toISOString();
          for (const x of selectedIds) {
            const u = util[x.id] || { retrievals: 0, last_used: null };
            u.retrievals += 1;
            u.last_used = now;
            util[x.id] = u;
          }
          saveUtility(scopeId, util);
        }

        // B6 时间线组装：score 定入选，时间定顺序（旧在前新在后）
        const ordered = selectedIds
          .map((x) => ({ e: byId.get(x.id)!, s: x.s }))
          .filter((x) => Boolean(x.e))
          .sort((x, y) => ((x.e.startedAt || "") < (y.e.startedAt || "") ? -1 : 1));
        results = ordered.map((x) => renderEnvelopeFull(x.e, x.s, scopeId, qTokens, tier2.get(x.e.sessionId)));
      }

      parts.push(`MODE: ${MODE}${TIER2 ? "+tier2" : ""}${OFF.size ? " ablate=" + [...OFF].join("/") : ""}`);
      return json({ results, query_used: a.query, query_mode: a.query_mode || "fixed",
        latency_ms: Date.now() - t0, native_notes: parts.join("; ") });
    }

    if (name === "reset") {
      rmSync(join(STATE_DIR, "scopes"), { recursive: true, force: true });
      rmSync(join(STATE_DIR, "scopes.json"), { force: true });
      invalidateCaches();
      lastResetAt = new Date().toISOString();
      return json({ ok: true, cleared: { system: "intent" } });
    }
    if (name === "stats") {
      const s = readScopes();
      return json({ n_memories: s.n_units, n_sessions: s.sessions.length,
        mode: `${MODE}${TIER2 ? "+tier2" : ""}`, ablate: [...OFF],
        tokens_used: { ingest: null, retrieve: 0, internal_llm: internalTokens, embed: embedTokens },
        llm_calls: llmCalls, embed_calls: embedCalls,
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
      invalidateCaches();
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
