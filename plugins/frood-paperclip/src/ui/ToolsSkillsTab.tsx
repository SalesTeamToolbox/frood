import { usePluginData } from "@paperclipai/plugin-sdk/ui";
import type { PluginDetailTabProps } from "@paperclipai/plugin-sdk/ui";

interface ToolItem {
  name: string;
  display_name: string;
  description: string;
  enabled: boolean;
  source: string;
}

interface SkillItem {
  name: string;
  display_name: string;
  description: string;
  enabled: boolean;
  path: string;
}

interface ToolsSkillsData {
  tools: ToolItem[];
  skills: SkillItem[];
}

export function ToolsSkillsTab({ context }: PluginDetailTabProps) {
  const { data, loading, error } = usePluginData<ToolsSkillsData>("tools-skills", {
    companyId: context.companyId ?? undefined,
  });

  if (loading) return <p style={{ padding: "12px", fontFamily: "system-ui, sans-serif" }}>Loading tools & skills...</p>;
  if (error) return <p style={{ padding: "12px", color: "#ef4444", fontFamily: "system-ui, sans-serif" }}>Error: {error.message}</p>;
  if (!data) return <p style={{ padding: "12px", color: "#6b7280", fontFamily: "system-ui, sans-serif" }}>No tools or skills data available.</p>;

  const tools = data.tools ?? [];
  const skills = data.skills ?? [];

  return (
    <div style={{ padding: "12px", fontFamily: "system-ui, sans-serif" }}>
      <h3 style={{ margin: "0 0 12px", fontSize: "16px", fontWeight: 600 }}>Tools ({tools.length})</h3>
      {tools.length === 0 && <p style={{ color: "#6b7280", fontSize: "13px" }}>No tools registered.</p>}
      <div style={{ display: "flex", flexDirection: "column", gap: "6px", marginBottom: "20px" }}>
        {tools.map((t) => (
          <div key={t.name} style={{ padding: "8px 12px", borderRadius: "6px", border: "1px solid #e5e7eb", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <span style={{ fontWeight: 500, fontSize: "13px" }}>{t.display_name || t.name}</span>
              {t.description && <span style={{ fontSize: "12px", color: "#6b7280", marginLeft: "8px" }}>{t.description}</span>}
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <span style={{ fontSize: "11px", padding: "2px 6px", borderRadius: "4px", backgroundColor: "#f3f4f6", color: "#6b7280" }}>{t.source}</span>
              <span style={{ width: "8px", height: "8px", borderRadius: "50%", backgroundColor: t.enabled ? "#22c55e" : "#d1d5db", display: "inline-block" }} />
            </div>
          </div>
        ))}
      </div>

      <h3 style={{ margin: "0 0 12px", fontSize: "16px", fontWeight: 600 }}>Skills ({skills.length})</h3>
      {skills.length === 0 && <p style={{ color: "#6b7280", fontSize: "13px" }}>No skills loaded.</p>}
      <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
        {skills.map((s) => (
          <div key={s.name} style={{ padding: "8px 12px", borderRadius: "6px", border: "1px solid #e5e7eb", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <span style={{ fontWeight: 500, fontSize: "13px" }}>{s.display_name || s.name}</span>
              {s.description && <span style={{ fontSize: "12px", color: "#6b7280", marginLeft: "8px" }}>{s.description}</span>}
            </div>
            <span style={{ width: "8px", height: "8px", borderRadius: "50%", backgroundColor: s.enabled ? "#22c55e" : "#d1d5db", display: "inline-block" }} />
          </div>
        ))}
      </div>
    </div>
  );
}
