import { usePluginData, usePluginAction } from "@paperclipai/plugin-sdk/ui";
import type { PluginSettingsPageProps } from "@paperclipai/plugin-sdk/ui";
import { useState, useCallback } from "react";
import type { SettingsKeyEntry, MemoryStatsResponse, StorageStatusResponse } from "../types";

// -- Static help text lookup per D-09 --
const KEY_HELP: Record<string, string> = {
  OPENROUTER_API_KEY: "OpenRouter aggregates 100+ models. Get key at openrouter.ai/keys",
  OPENAI_API_KEY: "OpenAI GPT models. Get key at platform.openai.com/api-keys",
  ANTHROPIC_API_KEY: "Anthropic Claude models. Get key at console.anthropic.com/settings/keys",
  SYNTHETIC_API_KEY: "Synthetic.new Anthropic-compatible API. Get key at synthetic.new/dashboard",
  DEEPSEEK_API_KEY: "DeepSeek models. Get key at platform.deepseek.com",
  GEMINI_API_KEY: "Google Gemini models. Get key at aistudio.google.com/apikey",
  CEREBRAS_API_KEY: "Cerebras fast inference. Get key at cloud.cerebras.ai",
  REPLICATE_API_TOKEN: "Replicate media generation. Get token at replicate.com/account/api-tokens",
  LUMA_API_KEY: "Luma AI video generation. Get key at lumalabs.ai",
  BRAVE_API_KEY: "Brave Search API. Get key at api.search.brave.com",
  GITHUB_TOKEN: "GitHub API access. Create at github.com/settings/tokens",
};

// -- Tab definitions per D-02 (Paperclip mode) --
const TABS = [
  { id: "apikeys", label: "API Keys" },
  { id: "security", label: "Security" },
  { id: "orchestrator", label: "Orchestrator" },
  { id: "storage", label: "Storage & Paths" },
  { id: "memory", label: "Memory & Learning" },
  { id: "rewards", label: "Rewards" },
] as const;

type TabId = (typeof TABS)[number]["id"];

// -- Shared card style --
const cardStyle: React.CSSProperties = {
  padding: "10px 12px",
  borderRadius: "6px",
  border: "1px solid #e5e7eb",
};

// -- Source badge --
function SourceBadge({ source }: { source: "admin" | "env" | "none" }) {
  if (source === "none") return null;
  const bg = source === "admin" ? "#dbeafe" : "#f3f4f6";
  const color = source === "admin" ? "#1e40af" : "#374151";
  return (
    <span style={{
      display: "inline-block", padding: "1px 6px", borderRadius: "4px",
      fontSize: "11px", fontWeight: 500, background: bg, color, marginLeft: "6px",
    }}>
      {source}
    </span>
  );
}

// -- ApiKeysTab --
function ApiKeysTab({ context }: { context: any }) {
  const { data, loading, error, refresh } = usePluginData<{ keys: SettingsKeyEntry[] }>("agent42-settings", {
    companyId: context.companyId ?? undefined,
  });
  const updateSettings = usePluginAction("update-agent42-settings");
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [visibleKeys, setVisibleKeys] = useState<Set<string>>(new Set());

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

  const handleClear = useCallback(async (name: string) => {
    setSaving(true);
    try {
      await updateSettings({ key_name: name, value: "" });
      refresh();
    } catch { /* handled by SDK */ }
    setSaving(false);
  }, [updateSettings, refresh]);

  const toggleVisibility = useCallback((name: string) => {
    setVisibleKeys((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }, []);

  if (loading) return <div style={{ padding: "8px", color: "#6b7280", fontSize: "13px" }}>Loading settings...</div>;
  if (error) return <div style={{ padding: "8px", color: "#ef4444", fontSize: "13px" }}>Error: {error.message}</div>;

  const keys = data?.keys ?? [];

  return (
    <div>
      <h3 style={{ fontSize: "15px", fontWeight: 600, margin: "0 0 12px" }}>API Keys</h3>
      <p style={{ fontSize: "13px", color: "#6b7280", margin: "0 0 12px" }}>
        Manage API keys for LLM providers and services. Keys are stored securely on the Agent42 sidecar.
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
        {keys.map((k) => (
          <div key={k.name} style={cardStyle}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <div>
                <span style={{ fontWeight: 500, fontSize: "13px", fontFamily: "monospace" }}>{k.name}</span>
                <SourceBadge source={k.source} />
                <span style={{ marginLeft: "8px", fontSize: "12px", color: k.is_set ? "#22c55e" : "#d1d5db" }}>
                  {k.is_set ? "Set" : "Not set"}
                </span>
                {KEY_HELP[k.name] && (
                  <div style={{ fontSize: "12px", color: "#9ca3af", marginTop: "2px" }}>{KEY_HELP[k.name]}</div>
                )}
              </div>
              {editingKey !== k.name && (
                <div style={{ display: "flex", gap: "4px", flexShrink: 0 }}>
                  {k.is_set && (
                    <button
                      onClick={() => toggleVisibility(k.name)}
                      style={{ padding: "2px 8px", borderRadius: "4px", border: "1px solid #d1d5db", background: "white", cursor: "pointer", fontSize: "12px" }}
                    >{visibleKeys.has(k.name) ? "Hide" : "Show"}</button>
                  )}
                  <button
                    onClick={() => { setEditingKey(k.name); setEditValue(""); }}
                    style={{ padding: "2px 8px", borderRadius: "4px", border: "1px solid #d1d5db", background: "white", cursor: "pointer", fontSize: "12px" }}
                  >Edit</button>
                  {k.is_set && k.source === "admin" && (
                    <button
                      onClick={() => handleClear(k.name)}
                      disabled={saving}
                      style={{ padding: "2px 8px", borderRadius: "4px", border: "1px solid #fca5a5", background: "#fef2f2", color: "#dc2626", cursor: "pointer", fontSize: "12px", opacity: saving ? 0.5 : 1 }}
                    >Clear</button>
                  )}
                </div>
              )}
            </div>
            {k.masked_value && editingKey !== k.name && visibleKeys.has(k.name) && (
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
        {keys.length === 0 && (
          <p style={{ color: "#6b7280", fontSize: "13px" }}>No configurable settings available.</p>
        )}
      </div>
    </div>
  );
}

// -- SecurityTab -- per D-05, no password section in Paperclip mode
function SecurityTab() {
  return (
    <div>
      <h3 style={{ fontSize: "15px", fontWeight: 600, margin: "0 0 12px" }}>Security</h3>
      <div style={{ padding: "12px", borderRadius: "6px", background: "#f0f9ff", border: "1px solid #bae6fd", marginBottom: "16px" }}>
        <p style={{ margin: 0, fontSize: "13px", color: "#0369a1" }}>
          Authentication is managed by Paperclip. Password and JWT settings are not applicable in this mode.
        </p>
      </div>
      <p style={{ fontSize: "13px", color: "#6b7280" }}>
        Sandbox, CORS, and rate limit settings are controlled via environment variables on the Agent42 sidecar.
        Contact your Agent42 administrator to adjust these settings.
      </p>
    </div>
  );
}

// -- OrchestratorTab --
function OrchestratorTab() {
  return (
    <div>
      <h3 style={{ fontSize: "15px", fontWeight: 600, margin: "0 0 12px" }}>Orchestrator</h3>
      <div style={{ padding: "12px", borderRadius: "6px", background: "#f9fafb", border: "1px solid #e5e7eb", marginBottom: "16px" }}>
        <p style={{ margin: 0, fontSize: "13px", color: "#6b7280" }}>
          Orchestrator settings are managed via Agent42 environment configuration.
          These include MAX_CONCURRENT_AGENTS, MAX_DAILY_API_SPEND_USD, and MODEL_ROUTING_POLICY.
        </p>
      </div>
      <p style={{ fontSize: "13px", color: "#6b7280" }}>
        To adjust orchestrator settings, update the <code style={{ fontFamily: "monospace", background: "#f3f4f6", padding: "1px 4px", borderRadius: "3px" }}>.env</code> file
        on the Agent42 sidecar and restart the service.
      </p>
    </div>
  );
}

// -- StorageTab --
function StorageTab() {
  return (
    <div>
      <h3 style={{ fontSize: "15px", fontWeight: 600, margin: "0 0 12px" }}>Storage & Paths</h3>
      <div style={{ padding: "12px", borderRadius: "6px", background: "#f9fafb", border: "1px solid #e5e7eb", marginBottom: "16px" }}>
        <p style={{ margin: 0, fontSize: "13px", color: "#6b7280" }}>
          Storage paths are configured via Agent42 environment variables.
          These include MEMORY_DIR, SESSIONS_DIR, OUTPUTS_DIR, and TEMPLATES_DIR.
        </p>
      </div>
      <p style={{ fontSize: "13px", color: "#6b7280" }}>
        To view detailed storage backend status (Qdrant, Redis, CC sync), use the standalone Agent42 dashboard.
      </p>
    </div>
  );
}

// -- MemoryTab -- per D-11 through D-16
function MemoryTab({ context: _context }: { context: any }) {
  const { data: memStats, loading: memLoading, refresh: refreshStats } = usePluginData<MemoryStatsResponse>("memory-stats", {});
  const { data: storageStatus, loading: storageLoading } = usePluginData<StorageStatusResponse>("storage-status", {});
  const purgeMemory = usePluginAction("purge-memory");
  const updateSettings = usePluginAction("update-agent42-settings");
  const [confirmPurge, setConfirmPurge] = useState<string | null>(null);
  const [purgeInput, setPurgeInput] = useState("");
  const [purging, setPurging] = useState(false);
  const [togglingLearning, setTogglingLearning] = useState(false);

  const handlePurge = useCallback(async () => {
    if (!confirmPurge || purgeInput !== "PURGE") return;
    setPurging(true);
    try {
      await purgeMemory({ collection: confirmPurge });
      setConfirmPurge(null);
      setPurgeInput("");
      refreshStats();
    } catch { /* handled by SDK */ }
    setPurging(false);
  }, [confirmPurge, purgeInput, purgeMemory, refreshStats]);

  const handleToggleLearning = useCallback(async (enabled: boolean) => {
    setTogglingLearning(true);
    try {
      await updateSettings({ key_name: "LEARNING_ENABLED", value: enabled ? "true" : "false" });
    } catch { /* handled by SDK */ }
    setTogglingLearning(false);
  }, [updateSettings]);

  const statCardStyle: React.CSSProperties = {
    padding: "16px",
    borderRadius: "8px",
    border: "1px solid #e5e7eb",
    textAlign: "center",
  };

  return (
    <div>
      <h3 style={{ fontSize: "15px", fontWeight: 600, margin: "0 0 12px" }}>Memory & Learning</h3>

      {/* Memory stats cards (D-13) */}
      <h4 style={{ fontSize: "13px", fontWeight: 600, margin: "0 0 8px", color: "#374151" }}>Memory Statistics (24h)</h4>
      {memLoading ? (
        <p style={{ fontSize: "13px", color: "#9ca3af", marginBottom: "16px" }}>Loading memory stats...</p>
      ) : memStats ? (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "12px", marginBottom: "20px" }}>
          <div style={statCardStyle}>
            <div style={{ fontSize: "1.5rem", fontWeight: 700, color: "#111827" }}>{memStats.recall_count}</div>
            <div style={{ fontSize: "12px", color: "#6b7280", marginTop: "4px" }}>Recalls (24h)</div>
          </div>
          <div style={statCardStyle}>
            <div style={{ fontSize: "1.5rem", fontWeight: 700, color: "#111827" }}>{memStats.learn_count}</div>
            <div style={{ fontSize: "12px", color: "#6b7280", marginTop: "4px" }}>Learnings (24h)</div>
          </div>
          <div style={statCardStyle}>
            <div style={{ fontSize: "1.5rem", fontWeight: 700, color: "#111827" }}>{memStats.error_count}</div>
            <div style={{ fontSize: "12px", color: "#6b7280", marginTop: "4px" }}>Errors (24h)</div>
          </div>
          <div style={statCardStyle}>
            <div style={{ fontSize: "1.5rem", fontWeight: 700, color: "#111827" }}>{Math.round(memStats.avg_latency_ms)} ms</div>
            <div style={{ fontSize: "12px", color: "#6b7280", marginTop: "4px" }}>Avg Latency</div>
          </div>
        </div>
      ) : (
        <p style={{ fontSize: "13px", color: "#9ca3af", marginBottom: "16px" }}>Memory stats unavailable.</p>
      )}

      {/* Learning toggle (D-14) */}
      <div style={{ marginBottom: "20px" }}>
        <h4 style={{ fontSize: "13px", fontWeight: 600, margin: "0 0 8px", color: "#374151" }}>Learning Extraction</h4>
        <div style={cardStyle}>
          <label style={{ display: "flex", alignItems: "center", gap: "8px", cursor: togglingLearning ? "not-allowed" : "pointer" }}>
            <input
              type="checkbox"
              checked={storageStatus?.learning_enabled ?? true}
              onChange={(e) => handleToggleLearning(e.target.checked)}
              disabled={togglingLearning || storageLoading}
              style={{ width: "16px", height: "16px" }}
            />
            <span style={{ fontSize: "13px" }}>Enable automatic learning extraction from agent runs</span>
          </label>
          <p style={{ fontSize: "12px", color: "#9ca3af", margin: "6px 0 0" }}>
            When enabled, Agent42 extracts learnings from completed agent runs and stores them in the knowledge base for future recall.
          </p>
        </div>
      </div>

      {/* Storage status (D-12) */}
      {storageStatus && (
        <div style={{ marginBottom: "20px" }}>
          <h4 style={{ fontSize: "13px", fontWeight: 600, margin: "0 0 8px", color: "#374151" }}>Storage Backend</h4>
          <div style={cardStyle}>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              <span style={{ padding: "4px 8px", borderRadius: "4px", fontSize: "12px", background: "#dbeafe", color: "#1e40af" }}>
                Mode: {storageStatus.mode}
              </span>
              <span style={{
                padding: "4px 8px", borderRadius: "4px", fontSize: "12px",
                background: storageStatus.qdrant_available ? "#dcfce7" : "#fef2f2",
                color: storageStatus.qdrant_available ? "#166534" : "#991b1b",
              }}>
                Qdrant: {storageStatus.qdrant_available ? "available" : "unavailable"}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Purge controls (D-15) */}
      <div style={{ marginBottom: "20px" }}>
        <h4 style={{ fontSize: "13px", fontWeight: 600, margin: "0 0 4px", color: "#dc2626" }}>Danger Zone</h4>
        <p style={{ fontSize: "12px", color: "#9ca3af", margin: "0 0 8px" }}>
          Purge operations are irreversible. All entries in the selected collection will be permanently deleted.
        </p>
        {confirmPurge ? (
          <div style={{ ...cardStyle, border: "1px solid #fca5a5", background: "#fef2f2" }}>
            <p style={{ fontSize: "13px", color: "#dc2626", margin: "0 0 8px" }}>
              This will permanently delete ALL entries in the <strong>{confirmPurge}</strong> collection. This action is irreversible.
            </p>
            <p style={{ fontSize: "13px", margin: "0 0 8px" }}>Type <strong>PURGE</strong> to confirm:</p>
            <div style={{ display: "flex", gap: "6px" }}>
              <input
                type="text"
                value={purgeInput}
                onChange={(e) => setPurgeInput(e.target.value)}
                placeholder="Type PURGE to confirm"
                style={{ flex: 1, padding: "4px 8px", borderRadius: "4px", border: "1px solid #fca5a5", fontSize: "13px" }}
              />
              <button
                onClick={handlePurge}
                disabled={purgeInput !== "PURGE" || purging}
                style={{
                  padding: "4px 10px", borderRadius: "4px", border: "none",
                  background: purgeInput === "PURGE" ? "#dc2626" : "#d1d5db",
                  color: "white", cursor: purgeInput === "PURGE" ? "pointer" : "not-allowed",
                  fontSize: "12px", opacity: purging ? 0.5 : 1,
                }}
              >{purging ? "Purging..." : "Confirm Purge"}</button>
              <button
                onClick={() => { setConfirmPurge(null); setPurgeInput(""); }}
                style={{ padding: "4px 10px", borderRadius: "4px", border: "1px solid #d1d5db", background: "white", cursor: "pointer", fontSize: "12px" }}
              >Cancel</button>
            </div>
          </div>
        ) : (
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            {["memory", "knowledge", "history"].map((col) => (
              <button
                key={col}
                onClick={() => { setConfirmPurge(col); setPurgeInput(""); }}
                style={{ padding: "6px 12px", borderRadius: "4px", border: "1px solid #fca5a5", background: "#fef2f2", color: "#dc2626", cursor: "pointer", fontSize: "13px" }}
              >Purge {col.charAt(0).toUpperCase() + col.slice(1)}</button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// -- RewardsTab -- per D-04, minimal read-only
function RewardsTab() {
  return (
    <div>
      <h3 style={{ fontSize: "15px", fontWeight: 600, margin: "0 0 12px" }}>Rewards</h3>
      <div style={{ padding: "12px", borderRadius: "6px", background: "#f9fafb", border: "1px solid #e5e7eb", marginBottom: "16px" }}>
        <p style={{ margin: 0, fontSize: "13px", color: "#6b7280" }}>
          Rewards and tier configuration is managed via the Agent42 platform. Use the standalone Agent42 dashboard
          to view tier distribution and enable or disable the rewards system.
        </p>
      </div>
    </div>
  );
}

// -- Main SettingsPage component --
export function SettingsPage({ context }: PluginSettingsPageProps) {
  const [activeTab, setActiveTab] = useState<TabId>("apikeys");

  return (
    <div style={{ padding: "16px", fontFamily: "system-ui, sans-serif", maxWidth: "800px" }}>
      <h2 style={{ margin: "0 0 8px", fontSize: "18px", fontWeight: 600 }}>Agent42 Settings</h2>
      <p style={{ margin: "0 0 16px", fontSize: "13px", color: "#6b7280" }}>
        Manage Agent42 sidecar configuration. Changes take effect immediately.
      </p>

      {/* Tab navigation */}
      <div style={{ display: "flex", gap: "4px", borderBottom: "1px solid #e5e7eb", marginBottom: "16px", flexWrap: "wrap" }}>
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            style={{
              padding: "8px 16px", border: "none", background: "none", cursor: "pointer",
              fontSize: "13px", fontWeight: activeTab === tab.id ? 600 : 400,
              color: activeTab === tab.id ? "#3b82f6" : "#6b7280",
              borderBottom: activeTab === tab.id ? "2px solid #3b82f6" : "2px solid transparent",
            }}
          >{tab.label}</button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === "apikeys" && <ApiKeysTab context={context} />}
      {activeTab === "security" && <SecurityTab />}
      {activeTab === "orchestrator" && <OrchestratorTab />}
      {activeTab === "storage" && <StorageTab />}
      {activeTab === "memory" && <MemoryTab context={context} />}
      {activeTab === "rewards" && <RewardsTab />}
    </div>
  );
}
