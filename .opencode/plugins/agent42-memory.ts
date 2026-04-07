/**
 * Agent42 Memory Plugin for OpenCode
 *
 * Automatically surfaces relevant memories from Agent42's memory system
 * when the user submits a prompt. Works the same way as the Claude Code
 * memory-recall.py hook — associative recall triggered by prompt content.
 *
 * Uses the Agent42 MCP server's memory tool for search, falling back to
 * direct MEMORY.md/HISTORY.md keyword search when MCP is unavailable.
 */

import { readFileSync, existsSync } from "fs";
import { join } from "path";

const MIN_PROMPT_LEN = 10;
const MAX_MEMORIES = 3;
const MIN_KEYWORD_MATCHES = 2;

const CONTINUATION_SIGNALS = [
  "i restarted",
  "it worked",
  "still failing",
  "the error is",
  "back now",
  "ran the test",
  "tried that",
  "same issue",
  "as we discussed",
  "like you said",
  "as you suggested",
  "that fixed",
  "didn't work",
  "now it says",
  "after restarting",
  "i tried",
  "got this error",
  "here's the output",
  "the result is",
  "it broke",
  "it's broken",
  "same error",
  "still broken",
  "where were we",
  "picking up",
  "continuing",
  "let's continue",
  "resume",
  "back to",
  "following up",
  "as planned",
  "next step",
];

const STOP_WORDS = new Set([
  "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
  "have", "has", "had", "do", "does", "did", "will", "would", "could",
  "should", "may", "might", "can", "shall", "must", "need", "let",
  "lets", "please", "want", "like", "just", "make", "get", "use",
  "this", "that", "these", "those", "its", "me", "my", "we", "our",
  "you", "your", "they", "them", "their", "him", "her", "and", "or",
  "but", "if", "then", "else", "when", "where", "how", "what", "which",
  "who", "not", "no", "so", "too", "very", "also", "about", "to",
  "for", "with", "from", "at", "by", "on", "in", "of", "up", "out",
  "off", "over", "into", "onto", "all", "any", "each", "every", "some",
  "many", "much", "more", "now", "here", "there", "yes", "ok", "okay",
  "sure", "right", "well", "done",
]);

function extractKeywords(text: string): string[] {
  const words = text.toLowerCase().match(/[a-zA-Z_][a-zA-Z0-9_]*/g) || [];
  const keywords = [...new Set(words.filter(w => w.length >= 3 && !STOP_WORDS.has(w)))];
  return keywords;
}

function hasContinuationSignal(promptLower: string): boolean {
  return CONTINUATION_SIGNALS.some(signal => promptLower.includes(signal));
}

function searchMemorySections(content: string, keywords: string[]): Array<{text: string, score: number}> {
  const results: Array<{text: string, score: number}> = [];
  const sections = content.split(/^## /m);

  for (const section of sections) {
    if (!section.trim()) continue;
    const lines = section.trim().split("\n");
    const title = lines[0].trim();
    const body = lines.slice(1).join("\n").trim();
    const fullText = `${title} ${body}`.toLowerCase();

    const matches = keywords.filter(kw => fullText.includes(kw)).length;
    if (matches >= MIN_KEYWORD_MATCHES) {
      const score = Math.min(matches / Math.max(keywords.length, 1), 1.0) * 0.7;
      const display = body.length > 250 ? body.slice(0, 250) + "..." : body;
      results.push({ text: `[Memory: ${title}] ${display}`, score });
    }
  }
  return results;
}

function searchHistoryEntries(content: string, keywords: string[]): Array<{text: string, score: number}> {
  const results: Array<{text: string, score: number}> = [];
  const entries = content.includes("\n---\n") ? content.split("\n---\n") : content.split("\n\n");

  // Only search last 100 entries
  for (const entry of entries.slice(-100)) {
    const trimmed = entry.trim();
    if (!trimmed || trimmed.length < 20) continue;

    const textLower = trimmed.toLowerCase();
    const matches = keywords.filter(kw => textLower.includes(kw)).length;
    if (matches >= MIN_KEYWORD_MATCHES) {
      const score = Math.min(matches / Math.max(keywords.length, 1), 1.0) * 0.6;
      const display = trimmed.length > 200 ? trimmed.slice(0, 200) + "..." : trimmed;
      results.push({ text: `[History] ${display}`, score });
    }
  }
  return results;
}

export default async (ctx: any) => {
  const memoryDir = join(ctx.directory, ".agent42", "memory");

  return {
    "message.updated": async (input: any, output: any) => {
      // Only trigger on user messages
      const msg = input?.properties?.message;
      if (!msg || msg.role !== "user") return;

      const prompt = typeof msg.content === "string"
        ? msg.content
        : Array.isArray(msg.content)
          ? msg.content.map((c: any) => c.text || "").join(" ")
          : "";

      if (!prompt || prompt.trim().startsWith("/")) return;

      const promptLower = prompt.trim().toLowerCase();
      const isContinuation = hasContinuationSignal(promptLower);

      if (prompt.trim().length < MIN_PROMPT_LEN && !isContinuation) return;

      const keywords = extractKeywords(prompt);
      if (!keywords.length) return;

      // Try MCP search first via the Agent42 MCP server
      try {
        const result = await ctx.client.mcp.call("agent42", "agent42_memory", {
          action: "search",
          content: prompt,
        });
        if (result?.content) {
          const text = typeof result.content === "string"
            ? result.content
            : result.content.map((c: any) => c.text || "").join("\n");
          if (text && text.trim() && !text.includes("No results")) {
            output.parts = output.parts || [];
            output.parts.push({
              type: "text",
              text: `\n[agent42-memory] Recalled via MCP:\n${text.slice(0, 2000)}\n`,
            });
            return;
          }
        }
      } catch {
        // MCP unavailable — fall through to keyword search
      }

      // Fallback: keyword search on local files
      let memories: Array<{text: string, score: number}> = [];

      const memoryFile = join(memoryDir, "MEMORY.md");
      if (existsSync(memoryFile)) {
        try {
          const content = readFileSync(memoryFile, "utf-8");
          memories.push(...searchMemorySections(content, keywords));
        } catch {}
      }

      if (memories.length === 0) {
        const historyFile = join(memoryDir, "HISTORY.md");
        if (existsSync(historyFile)) {
          try {
            const content = readFileSync(historyFile, "utf-8");
            memories.push(...searchHistoryEntries(content, keywords));
          } catch {}
        }
      }

      // Deduplicate, rank, limit
      const seen = new Set<string>();
      memories = memories
        .filter(m => {
          const key = m.text.slice(0, 80).toLowerCase();
          if (seen.has(key)) return false;
          seen.add(key);
          return true;
        })
        .sort((a, b) => b.score - a.score)
        .slice(0, MAX_MEMORIES);

      if (memories.length === 0) return;

      const lines = [`[agent42-memory] Recall: ${memories.length} memories surfaced via keyword`];
      for (const m of memories) {
        lines.push(`  - [${Math.round(m.score * 100)}%] ${m.text}`);
      }

      output.parts = output.parts || [];
      output.parts.push({
        type: "text",
        text: "\n" + lines.join("\n") + "\n",
      });
    },
  };
};
