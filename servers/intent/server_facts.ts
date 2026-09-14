// B 臂入口：同构建预算的「纯记忆库替身」（fact 粒度检索与证据，mem0 形态）。
// 与 intent_full/intent_tier2 共享同一份 state 与快照，入库只做一次。
process.env.MEMBENCH_INTENT_MODE = "facts";
await import("./server.ts");
