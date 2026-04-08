import { usePluginData, usePluginAction } from "@paperclipai/plugin-sdk/ui";
import type { PluginPageProps } from "@paperclipai/plugin-sdk/ui";
import { useState } from "react";

interface AppItem {
  id: string;
  name: string;
  status: string;
  port: number | null;
  created_at: string;
}

interface AppsData {
  apps: AppItem[];
}

export function AppsPage({ context }: PluginPageProps) {
  const { data, loading, error, refresh } = usePluginData<AppsData>("apps-list", {
    companyId: context.companyId ?? undefined,
  });
  const startApp = usePluginAction("app-start");
  const stopApp = usePluginAction("app-stop");
  const [actionPending, setActionPending] = useState<string | null>(null);

  if (loading) return <div style={{ padding: "16px", fontFamily: "system-ui, sans-serif" }}>Loading apps...</div>;
  if (error) return <div style={{ padding: "16px", color: "#ef4444", fontFamily: "system-ui, sans-serif" }}>Error: {error.message}</div>;

  const apps = data?.apps ?? [];

  const handleAction = async (appId: string, action: "start" | "stop") => {
    setActionPending(appId);
    try {
      if (action === "start") await startApp({ appId });
      else await stopApp({ appId });
      refresh();
    } catch { /* handled by SDK */ }
    setActionPending(null);
  };

  const statusColor = (s: string) => {
    if (s === "running") return "#22c55e";
    if (s === "building") return "#f59e0b";
    if (s === "error") return "#ef4444";
    return "#6b7280";
  };

  return (
    <div style={{ padding: "16px", fontFamily: "system-ui, sans-serif" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
        <h2 style={{ margin: 0, fontSize: "18px", fontWeight: 600 }}>Sandboxed Apps</h2>
        <button onClick={refresh} style={{ padding: "4px 12px", borderRadius: "4px", border: "1px solid #d1d5db", background: "white", cursor: "pointer", fontSize: "12px" }}>Refresh</button>
      </div>
      {apps.length === 0 && (
        <p style={{ color: "#6b7280" }}>No apps found. Create apps through the Agent42 workspace.</p>
      )}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: "12px" }}>
        {apps.map((app) => (
          <div key={app.id} style={{ padding: "12px", borderRadius: "8px", border: "1px solid #e5e7eb", backgroundColor: "#fafafa" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
              <span style={{ fontWeight: 600, fontSize: "14px" }}>{app.name || app.id}</span>
              <span style={{ width: "8px", height: "8px", borderRadius: "50%", backgroundColor: statusColor(app.status), display: "inline-block" }} />
            </div>
            <div style={{ fontSize: "12px", color: "#6b7280", marginBottom: "8px" }}>
              Status: {app.status}{app.port ? ` | Port: ${app.port}` : ""}
            </div>
            <div style={{ display: "flex", gap: "6px" }}>
              {app.status !== "running" && (
                <button
                  onClick={() => handleAction(app.id, "start")}
                  disabled={actionPending === app.id}
                  style={{ padding: "4px 10px", borderRadius: "4px", border: "none", background: "#22c55e", color: "white", cursor: "pointer", fontSize: "12px", opacity: actionPending === app.id ? 0.5 : 1 }}
                >Start</button>
              )}
              {app.status === "running" && (
                <button
                  onClick={() => handleAction(app.id, "stop")}
                  disabled={actionPending === app.id}
                  style={{ padding: "4px 10px", borderRadius: "4px", border: "none", background: "#ef4444", color: "white", cursor: "pointer", fontSize: "12px", opacity: actionPending === app.id ? 0.5 : 1 }}
                >Stop</button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
