import type { PluginSidebarProps } from "@paperclipai/plugin-sdk/ui";

export function WorkspaceNavEntry({ context }: PluginSidebarProps) {
  return (
    <div style={{ padding: "8px 0", fontFamily: "system-ui, sans-serif" }}>
      <div style={{ fontSize: "11px", fontWeight: 600, color: "#9ca3af", textTransform: "uppercase", letterSpacing: "0.05em", padding: "4px 12px" }}>
        Agent42
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
        <a href={`/plugins/agent42.paperclip-plugin/workspace-terminal`} style={{ padding: "6px 12px", fontSize: "13px", color: "#374151", textDecoration: "none", borderRadius: "4px", display: "block" }}>
          Terminal
        </a>
        <a href={`/plugins/agent42.paperclip-plugin/sandboxed-apps`} style={{ padding: "6px 12px", fontSize: "13px", color: "#374151", textDecoration: "none", borderRadius: "4px", display: "block" }}>
          Apps
        </a>
      </div>
    </div>
  );
}
