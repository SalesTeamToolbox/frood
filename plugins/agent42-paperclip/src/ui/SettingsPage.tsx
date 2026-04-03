import { usePluginData, usePluginAction } from "@paperclipai/plugin-sdk/ui";
import type { PluginSettingsPageProps } from "@paperclipai/plugin-sdk/ui";
import { useState, useCallback } from "react";

interface SettingsKeyEntry {
  name: string;
  masked_value: string;
  is_set: boolean;
}

interface SettingsData {
  keys: SettingsKeyEntry[];
}

export function SettingsPage({ context }: PluginSettingsPageProps) {
  const { data, loading, error, refresh } = usePluginData<SettingsData>("agent42-settings", {
    companyId: context.companyId ?? undefined,
  });
  const updateSettings = usePluginAction("update-agent42-settings");
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [saving, setSaving] = useState(false);

  const handleSave = useCallback(async () => {
    if (!editingKey) return;
    setSaving(true);
    try {
      await updateSettings({ key_name: editingKey, value: editValue });
      setEditingKey(null);
      setEditValue("");
      refresh();
    } catch { /* handled by SDK */ }
    setSaving(false);
  }, [editingKey, editValue, updateSettings, refresh]);

  if (loading) return <div style={{ padding: "16px", fontFamily: "system-ui, sans-serif" }}>Loading settings...</div>;
  if (error) return <div style={{ padding: "16px", color: "#ef4444", fontFamily: "system-ui, sans-serif" }}>Error: {error.message}</div>;

  const keys = data?.keys ?? [];

  return (
    <div style={{ padding: "16px", fontFamily: "system-ui, sans-serif", maxWidth: "600px" }}>
      <h2 style={{ margin: "0 0 8px", fontSize: "18px", fontWeight: 600 }}>Agent42 Settings</h2>
      <p style={{ margin: "0 0 16px", fontSize: "13px", color: "#6b7280" }}>
        Manage API keys and configuration for the Agent42 sidecar. Changes take effect immediately.
      </p>

      <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
        {keys.map((k) => (
          <div key={k.name} style={{ padding: "10px 12px", borderRadius: "6px", border: "1px solid #e5e7eb" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <span style={{ fontWeight: 500, fontSize: "13px", fontFamily: "monospace" }}>{k.name}</span>
                <span style={{ marginLeft: "8px", fontSize: "12px", color: k.is_set ? "#22c55e" : "#d1d5db" }}>
                  {k.is_set ? "Set" : "Not set"}
                </span>
              </div>
              {editingKey !== k.name && (
                <button
                  onClick={() => { setEditingKey(k.name); setEditValue(""); }}
                  style={{ padding: "2px 8px", borderRadius: "4px", border: "1px solid #d1d5db", background: "white", cursor: "pointer", fontSize: "12px" }}
                >Edit</button>
              )}
            </div>
            {k.masked_value && editingKey !== k.name && (
              <div style={{ fontSize: "12px", color: "#9ca3af", fontFamily: "monospace", marginTop: "4px" }}>{k.masked_value}</div>
            )}
            {editingKey === k.name && (
              <div style={{ marginTop: "8px", display: "flex", gap: "6px" }}>
                <input
                  type="password"
                  value={editValue}
                  onChange={(e) => setEditValue(e.target.value)}
                  placeholder="Enter new value..."
                  style={{ flex: 1, padding: "4px 8px", borderRadius: "4px", border: "1px solid #d1d5db", fontSize: "13px", fontFamily: "monospace" }}
                />
                <button
                  onClick={handleSave}
                  disabled={saving}
                  style={{ padding: "4px 10px", borderRadius: "4px", border: "none", background: "#3b82f6", color: "white", cursor: "pointer", fontSize: "12px", opacity: saving ? 0.5 : 1 }}
                >Save</button>
                <button
                  onClick={() => { setEditingKey(null); setEditValue(""); }}
                  style={{ padding: "4px 10px", borderRadius: "4px", border: "1px solid #d1d5db", background: "white", cursor: "pointer", fontSize: "12px" }}
                >Cancel</button>
              </div>
            )}
          </div>
        ))}
      </div>

      {keys.length === 0 && (
        <p style={{ color: "#6b7280", fontSize: "13px" }}>No configurable settings available.</p>
      )}
    </div>
  );
}
