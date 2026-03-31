import { usePluginData } from "@paperclipai/plugin-sdk/ui";
import type { PluginDetailTabProps } from "@paperclipai/plugin-sdk/ui";

// Inline types (avoid cross-import from worker types which are Node.js)
interface AgentProfile {
  agentId: string;
  tier: string;
  successRate: number;
  taskVolume: number;
  avgSpeedMs: number;
  compositeScore: number;
}

interface TaskTypeStat {
  taskType: string;
  successRate: number;
  count: number;
  avgDurationMs: number;
}

interface EffectivenessData {
  agentId: string;
  stats: TaskTypeStat[];
}

const tierColors: Record<string, string> = {
  bronze: "#cd7f32",
  silver: "#c0c0c0",
  gold: "#ffd700",
};

export function AgentEffectivenessTab({ context }: PluginDetailTabProps) {
  const agentId = context.entityId;

  const profile = usePluginData<AgentProfile>("agent-profile", { agentId });
  const effectiveness = usePluginData<EffectivenessData>("agent-effectiveness", { agentId });
  // Data keys match worker.ts ctx.data.register() calls from Plan 02:
  // - "agent-profile" for tier + overall stats
  // - "agent-effectiveness" for per-task-type breakdown

  if (profile.loading) return <p style={{ padding: "16px" }}>Loading effectiveness data...</p>;
  if (profile.error) return <p style={{ padding: "16px", color: "#ef4444" }}>Error: {profile.error.message}</p>;
  if (!profile.data) return <p style={{ padding: "16px", color: "#6b7280" }}>No effectiveness data for this agent.</p>;

  const d = profile.data;
  const tierColor = tierColors[d.tier] || "#6b7280";

  return (
    <div style={{ padding: "16px", fontFamily: "system-ui, sans-serif" }}>
      {/* Tier Badge + Summary */}
      <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "24px" }}>
        <span style={{
          display: "inline-block", padding: "4px 12px", borderRadius: "9999px",
          backgroundColor: tierColor, color: "#fff", fontWeight: 600,
          fontSize: "14px", textTransform: "uppercase",
        }}>
          {d.tier}
        </span>
        <span style={{ fontSize: "24px", fontWeight: 700 }}>
          {(d.successRate * 100).toFixed(1)}%
        </span>
        <span style={{ color: "#6b7280", fontSize: "14px" }}>success rate</span>
      </div>

      {/* Stats Grid */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "12px", marginBottom: "24px" }}>
        <div style={{ padding: "12px", border: "1px solid #e5e7eb", borderRadius: "8px" }}>
          <div style={{ fontSize: "12px", color: "#6b7280" }}>Tasks Completed</div>
          <div style={{ fontSize: "20px", fontWeight: 600 }}>{d.taskVolume}</div>
        </div>
        <div style={{ padding: "12px", border: "1px solid #e5e7eb", borderRadius: "8px" }}>
          <div style={{ fontSize: "12px", color: "#6b7280" }}>Avg Speed</div>
          <div style={{ fontSize: "20px", fontWeight: 600 }}>{d.avgSpeedMs.toFixed(0)}ms</div>
        </div>
        <div style={{ padding: "12px", border: "1px solid #e5e7eb", borderRadius: "8px" }}>
          <div style={{ fontSize: "12px", color: "#6b7280" }}>Composite Score</div>
          <div style={{ fontSize: "20px", fontWeight: 600 }}>{(d.compositeScore * 100).toFixed(0)}%</div>
        </div>
      </div>

      {/* Per-task-type breakdown from agent-effectiveness data handler */}
      {effectiveness.data && effectiveness.data.stats.length > 0 && (
        <div style={{ marginBottom: "24px" }}>
          <h3 style={{ fontSize: "16px", fontWeight: 600, marginBottom: "8px" }}>By Task Type</h3>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "14px" }}>
            <thead>
              <tr style={{ borderBottom: "2px solid #e5e7eb" }}>
                <th style={{ textAlign: "left", padding: "8px 4px" }}>Task Type</th>
                <th style={{ textAlign: "right", padding: "8px 4px" }}>Success Rate</th>
                <th style={{ textAlign: "right", padding: "8px 4px" }}>Count</th>
                <th style={{ textAlign: "right", padding: "8px 4px" }}>Avg Duration</th>
              </tr>
            </thead>
            <tbody>
              {effectiveness.data.stats.map((s, i) => (
                <tr key={i} style={{ borderBottom: "1px solid #f3f4f6" }}>
                  <td style={{ padding: "6px 4px" }}>{s.taskType}</td>
                  <td style={{ textAlign: "right", padding: "6px 4px" }}>
                    {(s.successRate * 100).toFixed(1)}%
                  </td>
                  <td style={{ textAlign: "right", padding: "6px 4px" }}>{s.count}</td>
                  <td style={{ textAlign: "right", padding: "6px 4px" }}>
                    {s.avgDurationMs.toFixed(0)}ms
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
