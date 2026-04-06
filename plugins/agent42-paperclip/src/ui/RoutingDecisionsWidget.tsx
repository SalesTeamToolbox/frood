import { usePluginData } from "@paperclipai/plugin-sdk/ui";
import type { PluginWidgetProps } from "@paperclipai/plugin-sdk/ui";

interface SpendEntry {
  provider: string;
  model: string;
  inputTokens: number;
  outputTokens: number;
  costUsd: number;
  hourBucket: string;
}

interface SpendData {
  agentId: string;
  hours: number;
  entries: SpendEntry[];
  totalCostUsd: number;
}

export function RoutingDecisionsWidget({ context: _context }: PluginWidgetProps) {
  // Widget-level: no specific agentId, show company-wide spend
  const { data, loading, error } = usePluginData<SpendData>("routing-decisions", {
    hours: 24,
  });

  if (loading) return <p style={{ padding: "12px" }}>Loading routing data...</p>;
  if (error) return <p style={{ padding: "12px", color: "#ef4444" }}>Error: {error.message}</p>;
  if (!data || data.entries.length === 0) {
    return <p style={{ padding: "12px", color: "#6b7280" }}>No routing data in the last 24 hours.</p>;
  }

  // Aggregate by provider for distribution view
  const byProvider: Record<string, { tokens: number; cost: number }> = {};
  for (const entry of data.entries) {
    const key = entry.provider || "unknown";
    if (!byProvider[key]) byProvider[key] = { tokens: 0, cost: 0 };
    byProvider[key].tokens += entry.inputTokens + entry.outputTokens;
    byProvider[key].cost += entry.costUsd;
  }

  const totalTokens = Object.values(byProvider).reduce((s, v) => s + v.tokens, 0);

  // Color palette for providers
  const colors = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899"];

  return (
    <div style={{ padding: "12px", fontFamily: "system-ui, sans-serif" }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "12px" }}>
        <span style={{ fontWeight: 600 }}>Last 24h</span>
        <span style={{ fontSize: "14px", color: "#6b7280" }}>
          ${data.totalCostUsd.toFixed(4)} total
        </span>
      </div>

      {/* Stacked bar showing token distribution */}
      {totalTokens > 0 && (
        <div style={{ display: "flex", height: "8px", borderRadius: "4px", overflow: "hidden", marginBottom: "12px" }}>
          {Object.entries(byProvider).map(([name, vals], i) => {
            const pct = (vals.tokens / totalTokens) * 100;
            return (
              <div key={name} style={{
                width: `${pct}%`, backgroundColor: colors[i % colors.length],
                minWidth: pct > 0 ? "2px" : "0",
              }} title={`${name}: ${pct.toFixed(1)}%`} />
            );
          })}
        </div>
      )}

      {/* Provider breakdown */}
      <div>
        {Object.entries(byProvider).map(([name, vals], i) => (
          <div key={name} style={{
            display: "flex", justifyContent: "space-between", alignItems: "center",
            padding: "4px 0", borderBottom: "1px solid #f3f4f6",
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <span style={{
                width: "8px", height: "8px", borderRadius: "50%",
                backgroundColor: colors[i % colors.length], display: "inline-block",
              }} />
              <span style={{ fontSize: "13px" }}>{name}</span>
            </div>
            <div style={{ fontSize: "12px", color: "#6b7280" }}>
              {(vals.tokens / 1000).toFixed(1)}k tokens / ${vals.cost.toFixed(4)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
