import { usePluginData } from "@paperclipai/plugin-sdk/ui";
import type { PluginDetailTabProps } from "@paperclipai/plugin-sdk/ui";

interface TraceItem {
  text: string;
  score: number;
  source: string;
  tags: string[];
}

interface RunTrace {
  runId: string;
  injectedMemories: TraceItem[];
  extractedLearnings: TraceItem[];
}

export function MemoryBrowserTab({ context }: PluginDetailTabProps) {
  const runId = context.entityId;
  const { data, loading, error } = usePluginData<RunTrace>("memory-run-trace", { runId });

  if (loading) return <p style={{ padding: "16px" }}>Loading memory trace...</p>;
  if (error) return <p style={{ padding: "16px", color: "#ef4444" }}>Error: {error.message}</p>;
  if (!data) return <p style={{ padding: "16px", color: "#6b7280" }}>No memory data available.</p>;

  return (
    <div style={{ padding: "16px", fontFamily: "system-ui, sans-serif" }}>
      {/* Injected Memories Section (D-24) */}
      <h3 style={{ fontSize: "16px", fontWeight: 600, marginBottom: "8px" }}>
        Injected Memories ({data.injectedMemories.length})
      </h3>
      {data.injectedMemories.length === 0 ? (
        <p style={{ color: "#6b7280", fontStyle: "italic", marginBottom: "24px" }}>
          No memories were recalled for this run.
        </p>
      ) : (
        <div style={{ marginBottom: "24px" }}>
          {data.injectedMemories.map((m, i) => (
            <div key={i} style={{
              padding: "10px 12px", marginBottom: "6px",
              border: "1px solid #e5e7eb", borderRadius: "6px",
            }}>
              <div style={{ fontSize: "14px", marginBottom: "4px" }}>{m.text}</div>
              <div style={{ display: "flex", gap: "8px", fontSize: "12px", color: "#6b7280" }}>
                <span style={{
                  padding: "1px 6px", borderRadius: "4px",
                  backgroundColor: "#eff6ff", color: "#1d4ed8",
                }}>
                  {(m.score * 100).toFixed(0)}% relevance
                </span>
                {m.source && (
                  <span style={{
                    padding: "1px 6px", borderRadius: "4px",
                    backgroundColor: "#f3f4f6",
                  }}>
                    {m.source}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Extracted Learnings Section (D-24) */}
      <h3 style={{ fontSize: "16px", fontWeight: 600, marginBottom: "8px" }}>
        Extracted Learnings ({data.extractedLearnings.length})
      </h3>
      {data.extractedLearnings.length === 0 ? (
        <p style={{ color: "#6b7280", fontStyle: "italic" }}>
          No learnings were extracted yet. Extraction runs hourly.
        </p>
      ) : (
        <div>
          {data.extractedLearnings.map((l, i) => (
            <div key={i} style={{
              padding: "10px 12px", marginBottom: "6px",
              border: "1px solid #e5e7eb", borderRadius: "6px",
            }}>
              <div style={{ fontSize: "14px", marginBottom: "4px" }}>{l.text}</div>
              {l.tags.length > 0 && (
                <div style={{ display: "flex", gap: "4px", flexWrap: "wrap" }}>
                  {l.tags.map((tag, j) => (
                    <span key={j} style={{
                      padding: "1px 6px", borderRadius: "9999px", fontSize: "11px",
                      backgroundColor: "#faf5ff", color: "#7c3aed", border: "1px solid #e9d5ff",
                    }}>
                      {tag}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
