import { defineAgent } from "eve";

// Model routes through the Vercel AI Gateway (AI_GATEWAY_API_KEY in .env.local).
// eve 0.24.5 can't fetch live gateway context-window metadata in local dev, so we
// set it explicitly to satisfy the compaction compiler (Gemini 2.5 Flash = 1M window).
export default defineAgent({
  model: "google/gemini-2.5-flash",
  modelContextWindowTokens: 1_000_000,
});
