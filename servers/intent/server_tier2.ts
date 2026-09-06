// D 臂入口（B 档单列，active 类）：C 臂 + Tier2 LLM 精读逐字引用（top-5 session）。
// 检索期调用内部 LLM，不与被动臂混表；与其余两臂共享 state。
process.env.MEMBENCH_INTENT_MODE = "full";
process.env.MEMBENCH_INTENT_TIER2 = "on";
await import("./server.ts");
