// src/ui/AgentEffectivenessTab.tsx
import { usePluginData } from "@paperclipai/plugin-sdk/ui";
import { jsx, jsxs } from "react/jsx-runtime";
var tierColors = {
  bronze: "#cd7f32",
  silver: "#c0c0c0",
  gold: "#ffd700"
};
function AgentEffectivenessTab({ context }) {
  const agentId = context.entityId;
  const profile = usePluginData("agent-profile", { agentId });
  const effectiveness = usePluginData("agent-effectiveness", { agentId });
  if (profile.loading) return /* @__PURE__ */ jsx("p", { style: { padding: "16px" }, children: "Loading effectiveness data..." });
  if (profile.error) return /* @__PURE__ */ jsxs("p", { style: { padding: "16px", color: "#ef4444" }, children: [
    "Error: ",
    profile.error.message
  ] });
  if (!profile.data) return /* @__PURE__ */ jsx("p", { style: { padding: "16px", color: "#6b7280" }, children: "No effectiveness data for this agent." });
  const d = profile.data;
  const tierColor = tierColors[d.tier] || "#6b7280";
  return /* @__PURE__ */ jsxs("div", { style: { padding: "16px", fontFamily: "system-ui, sans-serif" }, children: [
    /* @__PURE__ */ jsxs("div", { style: { display: "flex", alignItems: "center", gap: "12px", marginBottom: "24px" }, children: [
      /* @__PURE__ */ jsx("span", { style: {
        display: "inline-block",
        padding: "4px 12px",
        borderRadius: "9999px",
        backgroundColor: tierColor,
        color: "#fff",
        fontWeight: 600,
        fontSize: "14px",
        textTransform: "uppercase"
      }, children: d.tier }),
      /* @__PURE__ */ jsxs("span", { style: { fontSize: "24px", fontWeight: 700 }, children: [
        (d.successRate * 100).toFixed(1),
        "%"
      ] }),
      /* @__PURE__ */ jsx("span", { style: { color: "#6b7280", fontSize: "14px" }, children: "success rate" })
    ] }),
    /* @__PURE__ */ jsxs("div", { style: { display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "12px", marginBottom: "24px" }, children: [
      /* @__PURE__ */ jsxs("div", { style: { padding: "12px", border: "1px solid #e5e7eb", borderRadius: "8px" }, children: [
        /* @__PURE__ */ jsx("div", { style: { fontSize: "12px", color: "#6b7280" }, children: "Tasks Completed" }),
        /* @__PURE__ */ jsx("div", { style: { fontSize: "20px", fontWeight: 600 }, children: d.taskVolume })
      ] }),
      /* @__PURE__ */ jsxs("div", { style: { padding: "12px", border: "1px solid #e5e7eb", borderRadius: "8px" }, children: [
        /* @__PURE__ */ jsx("div", { style: { fontSize: "12px", color: "#6b7280" }, children: "Avg Speed" }),
        /* @__PURE__ */ jsxs("div", { style: { fontSize: "20px", fontWeight: 600 }, children: [
          d.avgSpeedMs.toFixed(0),
          "ms"
        ] })
      ] }),
      /* @__PURE__ */ jsxs("div", { style: { padding: "12px", border: "1px solid #e5e7eb", borderRadius: "8px" }, children: [
        /* @__PURE__ */ jsx("div", { style: { fontSize: "12px", color: "#6b7280" }, children: "Composite Score" }),
        /* @__PURE__ */ jsxs("div", { style: { fontSize: "20px", fontWeight: 600 }, children: [
          (d.compositeScore * 100).toFixed(0),
          "%"
        ] })
      ] })
    ] }),
    effectiveness.data && effectiveness.data.stats.length > 0 && /* @__PURE__ */ jsxs("div", { style: { marginBottom: "24px" }, children: [
      /* @__PURE__ */ jsx("h3", { style: { fontSize: "16px", fontWeight: 600, marginBottom: "8px" }, children: "By Task Type" }),
      /* @__PURE__ */ jsxs("table", { style: { width: "100%", borderCollapse: "collapse", fontSize: "14px" }, children: [
        /* @__PURE__ */ jsx("thead", { children: /* @__PURE__ */ jsxs("tr", { style: { borderBottom: "2px solid #e5e7eb" }, children: [
          /* @__PURE__ */ jsx("th", { style: { textAlign: "left", padding: "8px 4px" }, children: "Task Type" }),
          /* @__PURE__ */ jsx("th", { style: { textAlign: "right", padding: "8px 4px" }, children: "Success Rate" }),
          /* @__PURE__ */ jsx("th", { style: { textAlign: "right", padding: "8px 4px" }, children: "Count" }),
          /* @__PURE__ */ jsx("th", { style: { textAlign: "right", padding: "8px 4px" }, children: "Avg Duration" })
        ] }) }),
        /* @__PURE__ */ jsx("tbody", { children: effectiveness.data.stats.map((s, i) => /* @__PURE__ */ jsxs("tr", { style: { borderBottom: "1px solid #f3f4f6" }, children: [
          /* @__PURE__ */ jsx("td", { style: { padding: "6px 4px" }, children: s.taskType }),
          /* @__PURE__ */ jsxs("td", { style: { textAlign: "right", padding: "6px 4px" }, children: [
            (s.successRate * 100).toFixed(1),
            "%"
          ] }),
          /* @__PURE__ */ jsx("td", { style: { textAlign: "right", padding: "6px 4px" }, children: s.count }),
          /* @__PURE__ */ jsxs("td", { style: { textAlign: "right", padding: "6px 4px" }, children: [
            s.avgDurationMs.toFixed(0),
            "ms"
          ] })
        ] }, i)) })
      ] })
    ] })
  ] });
}

// src/ui/ProviderHealthWidget.tsx
import { usePluginData as usePluginData2 } from "@paperclipai/plugin-sdk/ui";
import { jsx as jsx2, jsxs as jsxs2 } from "react/jsx-runtime";
function ProviderHealthWidget({ context }) {
  const { data, loading, error } = usePluginData2("provider-health", {
    companyId: context.companyId ?? void 0
  });
  if (loading) return /* @__PURE__ */ jsx2("p", { style: { padding: "12px" }, children: "Loading health..." });
  if (error) return /* @__PURE__ */ jsxs2("p", { style: { padding: "12px", color: "#ef4444" }, children: [
    "Error: ",
    error.message
  ] });
  if (!data) return /* @__PURE__ */ jsx2("p", { style: { padding: "12px", color: "#6b7280" }, children: "Health data unavailable." });
  const statusColor = data.status === "ok" ? "#22c55e" : "#f59e0b";
  const configured = data.providers?.configured ?? {};
  return /* @__PURE__ */ jsxs2("div", { style: { padding: "12px", fontFamily: "system-ui, sans-serif" }, children: [
    /* @__PURE__ */ jsxs2("div", { style: { display: "flex", alignItems: "center", gap: "8px", marginBottom: "12px" }, children: [
      /* @__PURE__ */ jsx2("span", { style: {
        width: "10px",
        height: "10px",
        borderRadius: "50%",
        backgroundColor: statusColor,
        display: "inline-block"
      } }),
      /* @__PURE__ */ jsxs2("span", { style: { fontWeight: 600 }, children: [
        "Agent42 Sidecar: ",
        data.status
      ] })
    ] }),
    /* @__PURE__ */ jsxs2("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" }, children: [
      /* @__PURE__ */ jsxs2("div", { style: {
        padding: "8px",
        borderRadius: "6px",
        backgroundColor: data.memory?.available ? "#f0fdf4" : "#fef2f2",
        border: `1px solid ${data.memory?.available ? "#bbf7d0" : "#fecaca"}`
      }, children: [
        /* @__PURE__ */ jsx2("span", { style: { fontSize: "12px", fontWeight: 500 }, children: "Memory" }),
        /* @__PURE__ */ jsx2("div", { style: { fontSize: "14px" }, children: data.memory?.available ? "Available" : "Unavailable" })
      ] }),
      /* @__PURE__ */ jsxs2("div", { style: {
        padding: "8px",
        borderRadius: "6px",
        backgroundColor: data.qdrant?.available ? "#f0fdf4" : "#fef2f2",
        border: `1px solid ${data.qdrant?.available ? "#bbf7d0" : "#fecaca"}`
      }, children: [
        /* @__PURE__ */ jsx2("span", { style: { fontSize: "12px", fontWeight: 500 }, children: "Qdrant" }),
        /* @__PURE__ */ jsx2("div", { style: { fontSize: "14px" }, children: data.qdrant?.available ? "Available" : "Unavailable" })
      ] })
    ] }),
    Object.keys(configured).length > 0 && /* @__PURE__ */ jsxs2("div", { style: { marginTop: "12px" }, children: [
      /* @__PURE__ */ jsx2("div", { style: { fontSize: "12px", fontWeight: 500, marginBottom: "4px", color: "#6b7280" }, children: "Providers" }),
      /* @__PURE__ */ jsx2("div", { style: { display: "flex", flexWrap: "wrap", gap: "6px" }, children: Object.entries(configured).map(([name, active]) => /* @__PURE__ */ jsx2("span", { style: {
        padding: "2px 8px",
        borderRadius: "4px",
        fontSize: "12px",
        backgroundColor: active ? "#dcfce7" : "#fee2e2",
        color: active ? "#166534" : "#991b1b"
      }, children: name }, name)) })
    ] })
  ] });
}

// src/ui/MemoryBrowserTab.tsx
import { usePluginData as usePluginData3 } from "@paperclipai/plugin-sdk/ui";
import { jsx as jsx3, jsxs as jsxs3 } from "react/jsx-runtime";
function MemoryBrowserTab({ context }) {
  const runId = context.entityId;
  const { data, loading, error } = usePluginData3("memory-run-trace", { runId });
  if (loading) return /* @__PURE__ */ jsx3("p", { style: { padding: "16px" }, children: "Loading memory trace..." });
  if (error) return /* @__PURE__ */ jsxs3("p", { style: { padding: "16px", color: "#ef4444" }, children: [
    "Error: ",
    error.message
  ] });
  if (!data) return /* @__PURE__ */ jsx3("p", { style: { padding: "16px", color: "#6b7280" }, children: "No memory data available." });
  return /* @__PURE__ */ jsxs3("div", { style: { padding: "16px", fontFamily: "system-ui, sans-serif" }, children: [
    /* @__PURE__ */ jsxs3("h3", { style: { fontSize: "16px", fontWeight: 600, marginBottom: "8px" }, children: [
      "Injected Memories (",
      data.injectedMemories.length,
      ")"
    ] }),
    data.injectedMemories.length === 0 ? /* @__PURE__ */ jsx3("p", { style: { color: "#6b7280", fontStyle: "italic", marginBottom: "24px" }, children: "No memories were recalled for this run." }) : /* @__PURE__ */ jsx3("div", { style: { marginBottom: "24px" }, children: data.injectedMemories.map((m, i) => /* @__PURE__ */ jsxs3("div", { style: {
      padding: "10px 12px",
      marginBottom: "6px",
      border: "1px solid #e5e7eb",
      borderRadius: "6px"
    }, children: [
      /* @__PURE__ */ jsx3("div", { style: { fontSize: "14px", marginBottom: "4px" }, children: m.text }),
      /* @__PURE__ */ jsxs3("div", { style: { display: "flex", gap: "8px", fontSize: "12px", color: "#6b7280" }, children: [
        /* @__PURE__ */ jsxs3("span", { style: {
          padding: "1px 6px",
          borderRadius: "4px",
          backgroundColor: "#eff6ff",
          color: "#1d4ed8"
        }, children: [
          (m.score * 100).toFixed(0),
          "% relevance"
        ] }),
        m.source && /* @__PURE__ */ jsx3("span", { style: {
          padding: "1px 6px",
          borderRadius: "4px",
          backgroundColor: "#f3f4f6"
        }, children: m.source })
      ] })
    ] }, i)) }),
    /* @__PURE__ */ jsxs3("h3", { style: { fontSize: "16px", fontWeight: 600, marginBottom: "8px" }, children: [
      "Extracted Learnings (",
      data.extractedLearnings.length,
      ")"
    ] }),
    data.extractedLearnings.length === 0 ? /* @__PURE__ */ jsx3("p", { style: { color: "#6b7280", fontStyle: "italic" }, children: "No learnings were extracted yet. Extraction runs hourly." }) : /* @__PURE__ */ jsx3("div", { children: data.extractedLearnings.map((l, i) => /* @__PURE__ */ jsxs3("div", { style: {
      padding: "10px 12px",
      marginBottom: "6px",
      border: "1px solid #e5e7eb",
      borderRadius: "6px"
    }, children: [
      /* @__PURE__ */ jsx3("div", { style: { fontSize: "14px", marginBottom: "4px" }, children: l.text }),
      l.tags.length > 0 && /* @__PURE__ */ jsx3("div", { style: { display: "flex", gap: "4px", flexWrap: "wrap" }, children: l.tags.map((tag, j) => /* @__PURE__ */ jsx3("span", { style: {
        padding: "1px 6px",
        borderRadius: "9999px",
        fontSize: "11px",
        backgroundColor: "#faf5ff",
        color: "#7c3aed",
        border: "1px solid #e9d5ff"
      }, children: tag }, j)) })
    ] }, i)) })
  ] });
}

// src/ui/RoutingDecisionsWidget.tsx
import { usePluginData as usePluginData4 } from "@paperclipai/plugin-sdk/ui";
import { jsx as jsx4, jsxs as jsxs4 } from "react/jsx-runtime";
function RoutingDecisionsWidget({ context: _context }) {
  const { data, loading, error } = usePluginData4("routing-decisions", {
    hours: 24
  });
  if (loading) return /* @__PURE__ */ jsx4("p", { style: { padding: "12px" }, children: "Loading routing data..." });
  if (error) return /* @__PURE__ */ jsxs4("p", { style: { padding: "12px", color: "#ef4444" }, children: [
    "Error: ",
    error.message
  ] });
  if (!data || data.entries.length === 0) {
    return /* @__PURE__ */ jsx4("p", { style: { padding: "12px", color: "#6b7280" }, children: "No routing data in the last 24 hours." });
  }
  const byProvider = {};
  for (const entry of data.entries) {
    const key = entry.provider || "unknown";
    if (!byProvider[key]) byProvider[key] = { tokens: 0, cost: 0 };
    byProvider[key].tokens += entry.inputTokens + entry.outputTokens;
    byProvider[key].cost += entry.costUsd;
  }
  const totalTokens = Object.values(byProvider).reduce((s, v) => s + v.tokens, 0);
  const colors = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899"];
  return /* @__PURE__ */ jsxs4("div", { style: { padding: "12px", fontFamily: "system-ui, sans-serif" }, children: [
    /* @__PURE__ */ jsxs4("div", { style: { display: "flex", justifyContent: "space-between", marginBottom: "12px" }, children: [
      /* @__PURE__ */ jsx4("span", { style: { fontWeight: 600 }, children: "Last 24h" }),
      /* @__PURE__ */ jsxs4("span", { style: { fontSize: "14px", color: "#6b7280" }, children: [
        "$",
        data.totalCostUsd.toFixed(4),
        " total"
      ] })
    ] }),
    totalTokens > 0 && /* @__PURE__ */ jsx4("div", { style: { display: "flex", height: "8px", borderRadius: "4px", overflow: "hidden", marginBottom: "12px" }, children: Object.entries(byProvider).map(([name, vals], i) => {
      const pct = vals.tokens / totalTokens * 100;
      return /* @__PURE__ */ jsx4("div", { style: {
        width: `${pct}%`,
        backgroundColor: colors[i % colors.length],
        minWidth: pct > 0 ? "2px" : "0"
      }, title: `${name}: ${pct.toFixed(1)}%` }, name);
    }) }),
    /* @__PURE__ */ jsx4("div", { children: Object.entries(byProvider).map(([name, vals], i) => /* @__PURE__ */ jsxs4("div", { style: {
      display: "flex",
      justifyContent: "space-between",
      alignItems: "center",
      padding: "4px 0",
      borderBottom: "1px solid #f3f4f6"
    }, children: [
      /* @__PURE__ */ jsxs4("div", { style: { display: "flex", alignItems: "center", gap: "6px" }, children: [
        /* @__PURE__ */ jsx4("span", { style: {
          width: "8px",
          height: "8px",
          borderRadius: "50%",
          backgroundColor: colors[i % colors.length],
          display: "inline-block"
        } }),
        /* @__PURE__ */ jsx4("span", { style: { fontSize: "13px" }, children: name })
      ] }),
      /* @__PURE__ */ jsxs4("div", { style: { fontSize: "12px", color: "#6b7280" }, children: [
        (vals.tokens / 1e3).toFixed(1),
        "k tokens / $",
        vals.cost.toFixed(4)
      ] })
    ] }, name)) })
  ] });
}
export {
  AgentEffectivenessTab,
  MemoryBrowserTab,
  ProviderHealthWidget,
  RoutingDecisionsWidget
};
//# sourceMappingURL=index.js.map
