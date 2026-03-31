import { usePluginData } from "@paperclipai/plugin-sdk/ui";
import type { PluginWidgetProps } from "@paperclipai/plugin-sdk/ui";

interface HealthData {
  status: string;
  memory: { available: boolean; [key: string]: unknown };
  providers: { available: boolean; configured?: Record<string, boolean>; [key: string]: unknown };
  qdrant: { available: boolean; [key: string]: unknown };
}

export function ProviderHealthWidget({ context }: PluginWidgetProps) {
  const { data, loading, error } = usePluginData<HealthData>("provider-health", {
    companyId: context.companyId ?? undefined,
  });

  if (loading) return <p style={{ padding: "12px" }}>Loading health...</p>;
  if (error) return <p style={{ padding: "12px", color: "#ef4444" }}>Error: {error.message}</p>;
  if (!data) return <p style={{ padding: "12px", color: "#6b7280" }}>Health data unavailable.</p>;

  const statusColor = data.status === "ok" ? "#22c55e" : "#f59e0b";
  const configured = data.providers?.configured ?? {};

  return (
    <div style={{ padding: "12px", fontFamily: "system-ui, sans-serif" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "12px" }}>
        <span style={{
          width: "10px", height: "10px", borderRadius: "50%",
          backgroundColor: statusColor, display: "inline-block",
        }} />
        <span style={{ fontWeight: 600 }}>Agent42 Sidecar: {data.status}</span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" }}>
        <div style={{
          padding: "8px", borderRadius: "6px",
          backgroundColor: data.memory?.available ? "#f0fdf4" : "#fef2f2",
          border: `1px solid ${data.memory?.available ? "#bbf7d0" : "#fecaca"}`,
        }}>
          <span style={{ fontSize: "12px", fontWeight: 500 }}>Memory</span>
          <div style={{ fontSize: "14px" }}>{data.memory?.available ? "Available" : "Unavailable"}</div>
        </div>
        <div style={{
          padding: "8px", borderRadius: "6px",
          backgroundColor: data.qdrant?.available ? "#f0fdf4" : "#fef2f2",
          border: `1px solid ${data.qdrant?.available ? "#bbf7d0" : "#fecaca"}`,
        }}>
          <span style={{ fontSize: "12px", fontWeight: 500 }}>Qdrant</span>
          <div style={{ fontSize: "14px" }}>{data.qdrant?.available ? "Available" : "Unavailable"}</div>
        </div>
      </div>

      {Object.keys(configured).length > 0 && (
        <div style={{ marginTop: "12px" }}>
          <div style={{ fontSize: "12px", fontWeight: 500, marginBottom: "4px", color: "#6b7280" }}>Providers</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
            {Object.entries(configured).map(([name, active]) => (
              <span key={name} style={{
                padding: "2px 8px", borderRadius: "4px", fontSize: "12px",
                backgroundColor: active ? "#dcfce7" : "#fee2e2",
                color: active ? "#166534" : "#991b1b",
              }}>
                {name}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
