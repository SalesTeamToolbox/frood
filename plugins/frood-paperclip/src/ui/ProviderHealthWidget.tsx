import { usePluginData } from "@paperclipai/plugin-sdk/ui";
import type { PluginWidgetProps } from "@paperclipai/plugin-sdk/ui";

interface ProviderDetail {
  name: string;
  configured: boolean;
  connected: boolean;
  model_count: number;
  last_check: number;
}

interface HealthData {
  status: string;
  memory: { available: boolean; [key: string]: unknown };
  providers: { available: boolean; configured?: Record<string, boolean>; [key: string]: unknown };
  providers_detail?: ProviderDetail[];
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

      {data.providers_detail && data.providers_detail.length > 0 ? (
        <div style={{ marginTop: "12px" }}>
          <div style={{ fontSize: "12px", fontWeight: 500, marginBottom: "4px", color: "#6b7280" }}>Providers</div>
          <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
            {data.providers_detail.map((p) => (
              <div key={p.name} style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                padding: "6px 10px", borderRadius: "6px",
                backgroundColor: p.configured ? "#f0fdf4" : "#fef2f2",
                border: `1px solid ${p.configured ? "#bbf7d0" : "#fecaca"}`,
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                  <span style={{
                    width: "8px", height: "8px", borderRadius: "50%", display: "inline-block",
                    backgroundColor: p.connected ? "#22c55e" : p.configured ? "#f59e0b" : "#ef4444",
                  }} />
                  <span style={{ fontSize: "13px", fontWeight: 500 }}>{p.name}</span>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  {p.model_count > 0 && (
                    <span style={{ fontSize: "11px", color: "#6b7280" }}>{p.model_count} models</span>
                  )}
                  <span style={{
                    fontSize: "11px", padding: "1px 6px", borderRadius: "3px",
                    backgroundColor: p.configured ? "#dcfce7" : "#fee2e2",
                    color: p.configured ? "#166534" : "#991b1b",
                  }}>
                    {p.connected ? "connected" : p.configured ? "configured" : "not configured"}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : Object.keys(configured).length > 0 ? (
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
      ) : null}
    </div>
  );
}
