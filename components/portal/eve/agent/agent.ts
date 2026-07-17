import { defineAgent } from "eve";

// Model routes through the Vercel AI Gateway (AI_GATEWAY_API_KEY in .env.local).
// eve 0.24.5 can't fetch live gateway context-window metadata in local dev, so we
// set it explicitly to satisfy the compaction compiler (Claude Sonnet = 200k window).
export default defineAgent({
  model: "anthropic/claude-sonnet-4.5",
  modelContextWindowTokens: 200_000,
});
