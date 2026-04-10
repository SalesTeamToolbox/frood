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
        "Frood Sidecar: ",
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
    data.providers_detail && data.providers_detail.length > 0 ? /* @__PURE__ */ jsxs2("div", { style: { marginTop: "12px" }, children: [
      /* @__PURE__ */ jsx2("div", { style: { fontSize: "12px", fontWeight: 500, marginBottom: "4px", color: "#6b7280" }, children: "Providers" }),
      /* @__PURE__ */ jsx2("div", { style: { display: "flex", flexDirection: "column", gap: "6px" }, children: data.providers_detail.map((p) => /* @__PURE__ */ jsxs2("div", { style: {
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "6px 10px",
        borderRadius: "6px",
        backgroundColor: p.configured ? "#f0fdf4" : "#fef2f2",
        border: `1px solid ${p.configured ? "#bbf7d0" : "#fecaca"}`
      }, children: [
        /* @__PURE__ */ jsxs2("div", { style: { display: "flex", alignItems: "center", gap: "6px" }, children: [
          /* @__PURE__ */ jsx2("span", { style: {
            width: "8px",
            height: "8px",
            borderRadius: "50%",
            display: "inline-block",
            backgroundColor: p.connected ? "#22c55e" : p.configured ? "#f59e0b" : "#ef4444"
          } }),
          /* @__PURE__ */ jsx2("span", { style: { fontSize: "13px", fontWeight: 500 }, children: p.name })
        ] }),
        /* @__PURE__ */ jsxs2("div", { style: { display: "flex", alignItems: "center", gap: "8px" }, children: [
          p.model_count > 0 && /* @__PURE__ */ jsxs2("span", { style: { fontSize: "11px", color: "#6b7280" }, children: [
            p.model_count,
            " models"
          ] }),
          /* @__PURE__ */ jsx2("span", { style: {
            fontSize: "11px",
            padding: "1px 6px",
            borderRadius: "3px",
            backgroundColor: p.configured ? "#dcfce7" : "#fee2e2",
            color: p.configured ? "#166534" : "#991b1b"
          }, children: p.connected ? "connected" : p.configured ? "configured" : "not configured" })
        ] })
      ] }, p.name)) })
    ] }) : Object.keys(configured).length > 0 ? /* @__PURE__ */ jsxs2("div", { style: { marginTop: "12px" }, children: [
      /* @__PURE__ */ jsx2("div", { style: { fontSize: "12px", fontWeight: 500, marginBottom: "4px", color: "#6b7280" }, children: "Providers" }),
      /* @__PURE__ */ jsx2("div", { style: { display: "flex", flexWrap: "wrap", gap: "6px" }, children: Object.entries(configured).map(([name, active]) => /* @__PURE__ */ jsx2("span", { style: {
        padding: "2px 8px",
        borderRadius: "4px",
        fontSize: "12px",
        backgroundColor: active ? "#dcfce7" : "#fee2e2",
        color: active ? "#166534" : "#991b1b"
      }, children: name }, name)) })
    ] }) : null
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

// src/ui/WorkspacePage.tsx
import { usePluginStream, usePluginAction } from "@paperclipai/plugin-sdk/ui";
import { useState, useEffect, useRef, useCallback } from "react";
import { jsx as jsx5, jsxs as jsxs5 } from "react/jsx-runtime";
function WorkspacePage({ context }) {
  const [sessionId, setSessionId] = useState(null);
  const [outputLines, setOutputLines] = useState([]);
  const [inputValue, setInputValue] = useState("");
  const outputRef = useRef(null);
  const startTerminal = usePluginAction("terminal-start");
  const sendInput = usePluginAction("terminal-input");
  const closeTerminal = usePluginAction("terminal-close");
  const { events, connected } = usePluginStream("terminal-output", {
    companyId: context.companyId ?? void 0
  });
  useEffect(() => {
    if (events.length > 0) {
      const latest = events[events.length - 1];
      if (latest?.text) {
        setOutputLines((prev) => [...prev, latest.text]);
      }
    }
  }, [events]);
  useEffect(() => {
    if (outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight;
    }
  }, [outputLines]);
  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const result = await startTerminal({});
        if (mounted && result?.ok && result.sessionId) {
          setSessionId(result.sessionId);
        }
      } catch {
        if (mounted) setOutputLines(["[Failed to start terminal session]"]);
      }
    })();
    return () => {
      mounted = false;
      if (sessionId) {
        closeTerminal({ sessionId }).catch(() => {
        });
      }
    };
  }, []);
  const handleSend = useCallback(async () => {
    if (!sessionId || !inputValue.trim()) return;
    await sendInput({ sessionId, data: inputValue + "\n" });
    setOutputLines((prev) => [...prev, `$ ${inputValue}`]);
    setInputValue("");
  }, [sessionId, inputValue, sendInput]);
  const handleKeyDown = useCallback(
    (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend]
  );
  return /* @__PURE__ */ jsxs5("div", { style: { display: "flex", flexDirection: "column", height: "100%", fontFamily: "monospace", backgroundColor: "#1e1e1e", color: "#d4d4d4" }, children: [
    /* @__PURE__ */ jsxs5("div", { style: { padding: "8px 12px", borderBottom: "1px solid #333", display: "flex", justifyContent: "space-between", alignItems: "center" }, children: [
      /* @__PURE__ */ jsx5("span", { style: { fontWeight: 600, fontSize: "14px" }, children: "Frood Terminal" }),
      /* @__PURE__ */ jsx5("span", { style: { fontSize: "12px", color: connected ? "#22c55e" : "#ef4444" }, children: connected ? "Connected" : "Disconnected" })
    ] }),
    /* @__PURE__ */ jsxs5("div", { ref: outputRef, style: { flex: 1, overflow: "auto", padding: "8px 12px", fontSize: "13px", lineHeight: "1.5", whiteSpace: "pre-wrap" }, children: [
      outputLines.length === 0 && /* @__PURE__ */ jsx5("span", { style: { color: "#6b7280" }, children: sessionId ? "Terminal ready." : "Connecting..." }),
      outputLines.map((line, i) => /* @__PURE__ */ jsx5("div", { children: line }, i))
    ] }),
    /* @__PURE__ */ jsxs5("div", { style: { padding: "8px 12px", borderTop: "1px solid #333", display: "flex", gap: "8px" }, children: [
      /* @__PURE__ */ jsx5("span", { style: { color: "#22c55e" }, children: "$" }),
      /* @__PURE__ */ jsx5(
        "input",
        {
          type: "text",
          value: inputValue,
          onChange: (e) => setInputValue(e.target.value),
          onKeyDown: handleKeyDown,
          placeholder: "Type command...",
          style: { flex: 1, backgroundColor: "transparent", border: "none", color: "#d4d4d4", fontFamily: "monospace", fontSize: "13px", outline: "none" },
          disabled: !sessionId
        }
      )
    ] })
  ] });
}

// src/ui/AppsPage.tsx
import { usePluginData as usePluginData5, usePluginAction as usePluginAction2 } from "@paperclipai/plugin-sdk/ui";
import { useState as useState2 } from "react";
import { jsx as jsx6, jsxs as jsxs6 } from "react/jsx-runtime";
function AppsPage({ context }) {
  const { data, loading, error, refresh } = usePluginData5("apps-list", {
    companyId: context.companyId ?? void 0
  });
  const startApp = usePluginAction2("app-start");
  const stopApp = usePluginAction2("app-stop");
  const [actionPending, setActionPending] = useState2(null);
  if (loading) return /* @__PURE__ */ jsx6("div", { style: { padding: "16px", fontFamily: "system-ui, sans-serif" }, children: "Loading apps..." });
  if (error) return /* @__PURE__ */ jsxs6("div", { style: { padding: "16px", color: "#ef4444", fontFamily: "system-ui, sans-serif" }, children: [
    "Error: ",
    error.message
  ] });
  const apps = data?.apps ?? [];
  const handleAction = async (appId, action) => {
    setActionPending(appId);
    try {
      if (action === "start") await startApp({ appId });
      else await stopApp({ appId });
      refresh();
    } catch {
    }
    setActionPending(null);
  };
  const statusColor = (s) => {
    if (s === "running") return "#22c55e";
    if (s === "building") return "#f59e0b";
    if (s === "error") return "#ef4444";
    return "#6b7280";
  };
  return /* @__PURE__ */ jsxs6("div", { style: { padding: "16px", fontFamily: "system-ui, sans-serif" }, children: [
    /* @__PURE__ */ jsxs6("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }, children: [
      /* @__PURE__ */ jsx6("h2", { style: { margin: 0, fontSize: "18px", fontWeight: 600 }, children: "Sandboxed Apps" }),
      /* @__PURE__ */ jsx6("button", { onClick: refresh, style: { padding: "4px 12px", borderRadius: "4px", border: "1px solid #d1d5db", background: "white", cursor: "pointer", fontSize: "12px" }, children: "Refresh" })
    ] }),
    apps.length === 0 && /* @__PURE__ */ jsx6("p", { style: { color: "#6b7280" }, children: "No apps found. Create apps through the Frood workspace." }),
    /* @__PURE__ */ jsx6("div", { style: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: "12px" }, children: apps.map((app) => /* @__PURE__ */ jsxs6("div", { style: { padding: "12px", borderRadius: "8px", border: "1px solid #e5e7eb", backgroundColor: "#fafafa" }, children: [
      /* @__PURE__ */ jsxs6("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }, children: [
        /* @__PURE__ */ jsx6("span", { style: { fontWeight: 600, fontSize: "14px" }, children: app.name || app.id }),
        /* @__PURE__ */ jsx6("span", { style: { width: "8px", height: "8px", borderRadius: "50%", backgroundColor: statusColor(app.status), display: "inline-block" } })
      ] }),
      /* @__PURE__ */ jsxs6("div", { style: { fontSize: "12px", color: "#6b7280", marginBottom: "8px" }, children: [
        "Status: ",
        app.status,
        app.port ? ` | Port: ${app.port}` : ""
      ] }),
      /* @__PURE__ */ jsxs6("div", { style: { display: "flex", gap: "6px" }, children: [
        app.status !== "running" && /* @__PURE__ */ jsx6(
          "button",
          {
            onClick: () => handleAction(app.id, "start"),
            disabled: actionPending === app.id,
            style: { padding: "4px 10px", borderRadius: "4px", border: "none", background: "#22c55e", color: "white", cursor: "pointer", fontSize: "12px", opacity: actionPending === app.id ? 0.5 : 1 },
            children: "Start"
          }
        ),
        app.status === "running" && /* @__PURE__ */ jsx6(
          "button",
          {
            onClick: () => handleAction(app.id, "stop"),
            disabled: actionPending === app.id,
            style: { padding: "4px 10px", borderRadius: "4px", border: "none", background: "#ef4444", color: "white", cursor: "pointer", fontSize: "12px", opacity: actionPending === app.id ? 0.5 : 1 },
            children: "Stop"
          }
        )
      ] })
    ] }, app.id)) })
  ] });
}

// src/ui/ToolsSkillsTab.tsx
import { usePluginData as usePluginData6 } from "@paperclipai/plugin-sdk/ui";
import { jsx as jsx7, jsxs as jsxs7 } from "react/jsx-runtime";
function ToolsSkillsTab({ context }) {
  const { data, loading, error } = usePluginData6("tools-skills", {
    companyId: context.companyId ?? void 0
  });
  if (loading) return /* @__PURE__ */ jsx7("p", { style: { padding: "12px", fontFamily: "system-ui, sans-serif" }, children: "Loading tools & skills..." });
  if (error) return /* @__PURE__ */ jsxs7("p", { style: { padding: "12px", color: "#ef4444", fontFamily: "system-ui, sans-serif" }, children: [
    "Error: ",
    error.message
  ] });
  if (!data) return /* @__PURE__ */ jsx7("p", { style: { padding: "12px", color: "#6b7280", fontFamily: "system-ui, sans-serif" }, children: "No tools or skills data available." });
  const tools = data.tools ?? [];
  const skills = data.skills ?? [];
  return /* @__PURE__ */ jsxs7("div", { style: { padding: "12px", fontFamily: "system-ui, sans-serif" }, children: [
    /* @__PURE__ */ jsxs7("h3", { style: { margin: "0 0 12px", fontSize: "16px", fontWeight: 600 }, children: [
      "Tools (",
      tools.length,
      ")"
    ] }),
    tools.length === 0 && /* @__PURE__ */ jsx7("p", { style: { color: "#6b7280", fontSize: "13px" }, children: "No tools registered." }),
    /* @__PURE__ */ jsx7("div", { style: { display: "flex", flexDirection: "column", gap: "6px", marginBottom: "20px" }, children: tools.map((t) => /* @__PURE__ */ jsxs7("div", { style: { padding: "8px 12px", borderRadius: "6px", border: "1px solid #e5e7eb", display: "flex", justifyContent: "space-between", alignItems: "center" }, children: [
      /* @__PURE__ */ jsxs7("div", { children: [
        /* @__PURE__ */ jsx7("span", { style: { fontWeight: 500, fontSize: "13px" }, children: t.display_name || t.name }),
        t.description && /* @__PURE__ */ jsx7("span", { style: { fontSize: "12px", color: "#6b7280", marginLeft: "8px" }, children: t.description })
      ] }),
      /* @__PURE__ */ jsxs7("div", { style: { display: "flex", alignItems: "center", gap: "6px" }, children: [
        /* @__PURE__ */ jsx7("span", { style: { fontSize: "11px", padding: "2px 6px", borderRadius: "4px", backgroundColor: "#f3f4f6", color: "#6b7280" }, children: t.source }),
        /* @__PURE__ */ jsx7("span", { style: { width: "8px", height: "8px", borderRadius: "50%", backgroundColor: t.enabled ? "#22c55e" : "#d1d5db", display: "inline-block" } })
      ] })
    ] }, t.name)) }),
    /* @__PURE__ */ jsxs7("h3", { style: { margin: "0 0 12px", fontSize: "16px", fontWeight: 600 }, children: [
      "Skills (",
      skills.length,
      ")"
    ] }),
    skills.length === 0 && /* @__PURE__ */ jsx7("p", { style: { color: "#6b7280", fontSize: "13px" }, children: "No skills loaded." }),
    /* @__PURE__ */ jsx7("div", { style: { display: "flex", flexDirection: "column", gap: "6px" }, children: skills.map((s) => /* @__PURE__ */ jsxs7("div", { style: { padding: "8px 12px", borderRadius: "6px", border: "1px solid #e5e7eb", display: "flex", justifyContent: "space-between", alignItems: "center" }, children: [
      /* @__PURE__ */ jsxs7("div", { children: [
        /* @__PURE__ */ jsx7("span", { style: { fontWeight: 500, fontSize: "13px" }, children: s.display_name || s.name }),
        s.description && /* @__PURE__ */ jsx7("span", { style: { fontSize: "12px", color: "#6b7280", marginLeft: "8px" }, children: s.description })
      ] }),
      /* @__PURE__ */ jsx7("span", { style: { width: "8px", height: "8px", borderRadius: "50%", backgroundColor: s.enabled ? "#22c55e" : "#d1d5db", display: "inline-block" } })
    ] }, s.name)) })
  ] });
}

// src/ui/SettingsPage.tsx
import { usePluginData as usePluginData7, usePluginAction as usePluginAction3 } from "@paperclipai/plugin-sdk/ui";
import { useState as useState3, useCallback as useCallback2 } from "react";
import { jsx as jsx8, jsxs as jsxs8 } from "react/jsx-runtime";
var KEY_HELP = {
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
  GITHUB_TOKEN: "GitHub API access. Create at github.com/settings/tokens"
};
var TABS = [
  { id: "apikeys", label: "API Keys" },
  { id: "security", label: "Security" },
  { id: "orchestrator", label: "Orchestrator" },
  { id: "storage", label: "Storage & Paths" },
  { id: "memory", label: "Memory & Learning" },
  { id: "rewards", label: "Rewards" }
];
var cardStyle = {
  padding: "10px 12px",
  borderRadius: "6px",
  border: "1px solid #e5e7eb"
};
function SourceBadge({ source }) {
  if (source === "none") return null;
  const bg = source === "admin" ? "#dbeafe" : "#f3f4f6";
  const color = source === "admin" ? "#1e40af" : "#374151";
  return /* @__PURE__ */ jsx8("span", { style: {
    display: "inline-block",
    padding: "1px 6px",
    borderRadius: "4px",
    fontSize: "11px",
    fontWeight: 500,
    background: bg,
    color,
    marginLeft: "6px"
  }, children: source });
}
function ApiKeysTab({ context }) {
  const { data, loading, error, refresh } = usePluginData7("frood-settings", {
    companyId: context.companyId ?? void 0
  });
  const updateSettings = usePluginAction3("update-frood-settings");
  const [editingKey, setEditingKey] = useState3(null);
  const [editValue, setEditValue] = useState3("");
  const [saving, setSaving] = useState3(false);
  const [visibleKeys, setVisibleKeys] = useState3(/* @__PURE__ */ new Set());
  const handleSave = useCallback2(async () => {
    if (!editingKey) return;
    setSaving(true);
    try {
      await updateSettings({ key_name: editingKey, value: editValue });
      setEditingKey(null);
      setEditValue("");
      refresh();
    } catch {
    }
    setSaving(false);
  }, [editingKey, editValue, updateSettings, refresh]);
  const handleClear = useCallback2(async (name) => {
    setSaving(true);
    try {
      await updateSettings({ key_name: name, value: "" });
      refresh();
    } catch {
    }
    setSaving(false);
  }, [updateSettings, refresh]);
  const toggleVisibility = useCallback2((name) => {
    setVisibleKeys((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }, []);
  if (loading) return /* @__PURE__ */ jsx8("div", { style: { padding: "8px", color: "#6b7280", fontSize: "13px" }, children: "Loading settings..." });
  if (error) return /* @__PURE__ */ jsxs8("div", { style: { padding: "8px", color: "#ef4444", fontSize: "13px" }, children: [
    "Error: ",
    error.message
  ] });
  const keys = data?.keys ?? [];
  return /* @__PURE__ */ jsxs8("div", { children: [
    /* @__PURE__ */ jsx8("h3", { style: { fontSize: "15px", fontWeight: 600, margin: "0 0 12px" }, children: "API Keys" }),
    /* @__PURE__ */ jsx8("p", { style: { fontSize: "13px", color: "#6b7280", margin: "0 0 12px" }, children: "Manage API keys for LLM providers and services. Keys are stored securely on the Frood sidecar." }),
    /* @__PURE__ */ jsxs8("div", { style: { display: "flex", flexDirection: "column", gap: "8px" }, children: [
      keys.map((k) => /* @__PURE__ */ jsxs8("div", { style: cardStyle, children: [
        /* @__PURE__ */ jsxs8("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "flex-start" }, children: [
          /* @__PURE__ */ jsxs8("div", { children: [
            /* @__PURE__ */ jsx8("span", { style: { fontWeight: 500, fontSize: "13px", fontFamily: "monospace" }, children: k.name }),
            /* @__PURE__ */ jsx8(SourceBadge, { source: k.source }),
            /* @__PURE__ */ jsx8("span", { style: { marginLeft: "8px", fontSize: "12px", color: k.is_set ? "#22c55e" : "#d1d5db" }, children: k.is_set ? "Set" : "Not set" }),
            KEY_HELP[k.name] && /* @__PURE__ */ jsx8("div", { style: { fontSize: "12px", color: "#9ca3af", marginTop: "2px" }, children: KEY_HELP[k.name] })
          ] }),
          editingKey !== k.name && /* @__PURE__ */ jsxs8("div", { style: { display: "flex", gap: "4px", flexShrink: 0 }, children: [
            k.is_set && /* @__PURE__ */ jsx8(
              "button",
              {
                onClick: () => toggleVisibility(k.name),
                style: { padding: "2px 8px", borderRadius: "4px", border: "1px solid #d1d5db", background: "white", cursor: "pointer", fontSize: "12px" },
                children: visibleKeys.has(k.name) ? "Hide" : "Show"
              }
            ),
            /* @__PURE__ */ jsx8(
              "button",
              {
                onClick: () => {
                  setEditingKey(k.name);
                  setEditValue("");
                },
                style: { padding: "2px 8px", borderRadius: "4px", border: "1px solid #d1d5db", background: "white", cursor: "pointer", fontSize: "12px" },
                children: "Edit"
              }
            ),
            k.is_set && k.source === "admin" && /* @__PURE__ */ jsx8(
              "button",
              {
                onClick: () => handleClear(k.name),
                disabled: saving,
                style: { padding: "2px 8px", borderRadius: "4px", border: "1px solid #fca5a5", background: "#fef2f2", color: "#dc2626", cursor: "pointer", fontSize: "12px", opacity: saving ? 0.5 : 1 },
                children: "Clear"
              }
            )
          ] })
        ] }),
        k.masked_value && editingKey !== k.name && visibleKeys.has(k.name) && /* @__PURE__ */ jsx8("div", { style: { fontSize: "12px", color: "#9ca3af", fontFamily: "monospace", marginTop: "4px" }, children: k.masked_value }),
        editingKey === k.name && /* @__PURE__ */ jsxs8("div", { style: { marginTop: "8px", display: "flex", gap: "6px" }, children: [
          /* @__PURE__ */ jsx8(
            "input",
            {
              type: "password",
              value: editValue,
              onChange: (e) => setEditValue(e.target.value),
              placeholder: "Enter new value...",
              style: { flex: 1, padding: "4px 8px", borderRadius: "4px", border: "1px solid #d1d5db", fontSize: "13px", fontFamily: "monospace" }
            }
          ),
          /* @__PURE__ */ jsx8(
            "button",
            {
              onClick: handleSave,
              disabled: saving,
              style: { padding: "4px 10px", borderRadius: "4px", border: "none", background: "#3b82f6", color: "white", cursor: "pointer", fontSize: "12px", opacity: saving ? 0.5 : 1 },
              children: "Save"
            }
          ),
          /* @__PURE__ */ jsx8(
            "button",
            {
              onClick: () => {
                setEditingKey(null);
                setEditValue("");
              },
              style: { padding: "4px 10px", borderRadius: "4px", border: "1px solid #d1d5db", background: "white", cursor: "pointer", fontSize: "12px" },
              children: "Cancel"
            }
          )
        ] })
      ] }, k.name)),
      keys.length === 0 && /* @__PURE__ */ jsx8("p", { style: { color: "#6b7280", fontSize: "13px" }, children: "No configurable settings available." })
    ] })
  ] });
}
function SecurityTab() {
  return /* @__PURE__ */ jsxs8("div", { children: [
    /* @__PURE__ */ jsx8("h3", { style: { fontSize: "15px", fontWeight: 600, margin: "0 0 12px" }, children: "Security" }),
    /* @__PURE__ */ jsx8("div", { style: { padding: "12px", borderRadius: "6px", background: "#f0f9ff", border: "1px solid #bae6fd", marginBottom: "16px" }, children: /* @__PURE__ */ jsx8("p", { style: { margin: 0, fontSize: "13px", color: "#0369a1" }, children: "Authentication is managed by Paperclip. Password and JWT settings are not applicable in this mode." }) }),
    /* @__PURE__ */ jsx8("p", { style: { fontSize: "13px", color: "#6b7280" }, children: "Sandbox, CORS, and rate limit settings are controlled via environment variables on the Frood sidecar. Contact your Frood administrator to adjust these settings." })
  ] });
}
function OrchestratorTab() {
  return /* @__PURE__ */ jsxs8("div", { children: [
    /* @__PURE__ */ jsx8("h3", { style: { fontSize: "15px", fontWeight: 600, margin: "0 0 12px" }, children: "Orchestrator" }),
    /* @__PURE__ */ jsx8("div", { style: { padding: "12px", borderRadius: "6px", background: "#f9fafb", border: "1px solid #e5e7eb", marginBottom: "16px" }, children: /* @__PURE__ */ jsx8("p", { style: { margin: 0, fontSize: "13px", color: "#6b7280" }, children: "Orchestrator settings are managed via Frood environment configuration. These include MAX_CONCURRENT_AGENTS, MAX_DAILY_API_SPEND_USD, and MODEL_ROUTING_POLICY." }) }),
    /* @__PURE__ */ jsxs8("p", { style: { fontSize: "13px", color: "#6b7280" }, children: [
      "To adjust orchestrator settings, update the ",
      /* @__PURE__ */ jsx8("code", { style: { fontFamily: "monospace", background: "#f3f4f6", padding: "1px 4px", borderRadius: "3px" }, children: ".env" }),
      " file on the Frood sidecar and restart the service."
    ] })
  ] });
}
function StorageTab() {
  return /* @__PURE__ */ jsxs8("div", { children: [
    /* @__PURE__ */ jsx8("h3", { style: { fontSize: "15px", fontWeight: 600, margin: "0 0 12px" }, children: "Storage & Paths" }),
    /* @__PURE__ */ jsx8("div", { style: { padding: "12px", borderRadius: "6px", background: "#f9fafb", border: "1px solid #e5e7eb", marginBottom: "16px" }, children: /* @__PURE__ */ jsx8("p", { style: { margin: 0, fontSize: "13px", color: "#6b7280" }, children: "Storage paths are configured via Frood environment variables. These include MEMORY_DIR, SESSIONS_DIR, OUTPUTS_DIR, and TEMPLATES_DIR." }) }),
    /* @__PURE__ */ jsx8("p", { style: { fontSize: "13px", color: "#6b7280" }, children: "To view detailed storage backend status (Qdrant, Redis, CC sync), use the standalone Frood dashboard." })
  ] });
}
function MemoryTab({ context: _context }) {
  const { data: memStats, loading: memLoading, refresh: refreshStats } = usePluginData7("memory-stats", {});
  const { data: storageStatus, loading: storageLoading } = usePluginData7("storage-status", {});
  const purgeMemory = usePluginAction3("purge-memory");
  const updateSettings = usePluginAction3("update-frood-settings");
  const [confirmPurge, setConfirmPurge] = useState3(null);
  const [purgeInput, setPurgeInput] = useState3("");
  const [purging, setPurging] = useState3(false);
  const [togglingLearning, setTogglingLearning] = useState3(false);
  const handlePurge = useCallback2(async () => {
    if (!confirmPurge || purgeInput !== "PURGE") return;
    setPurging(true);
    try {
      await purgeMemory({ collection: confirmPurge });
      setConfirmPurge(null);
      setPurgeInput("");
      refreshStats();
    } catch {
    }
    setPurging(false);
  }, [confirmPurge, purgeInput, purgeMemory, refreshStats]);
  const handleToggleLearning = useCallback2(async (enabled) => {
    setTogglingLearning(true);
    try {
      await updateSettings({ key_name: "LEARNING_ENABLED", value: enabled ? "true" : "false" });
    } catch {
    }
    setTogglingLearning(false);
  }, [updateSettings]);
  const statCardStyle = {
    padding: "16px",
    borderRadius: "8px",
    border: "1px solid #e5e7eb",
    textAlign: "center"
  };
  return /* @__PURE__ */ jsxs8("div", { children: [
    /* @__PURE__ */ jsx8("h3", { style: { fontSize: "15px", fontWeight: 600, margin: "0 0 12px" }, children: "Memory & Learning" }),
    /* @__PURE__ */ jsx8("h4", { style: { fontSize: "13px", fontWeight: 600, margin: "0 0 8px", color: "#374151" }, children: "Memory Statistics (24h)" }),
    memLoading ? /* @__PURE__ */ jsx8("p", { style: { fontSize: "13px", color: "#9ca3af", marginBottom: "16px" }, children: "Loading memory stats..." }) : memStats ? /* @__PURE__ */ jsxs8("div", { style: { display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "12px", marginBottom: "20px" }, children: [
      /* @__PURE__ */ jsxs8("div", { style: statCardStyle, children: [
        /* @__PURE__ */ jsx8("div", { style: { fontSize: "1.5rem", fontWeight: 700, color: "#111827" }, children: memStats.recall_count }),
        /* @__PURE__ */ jsx8("div", { style: { fontSize: "12px", color: "#6b7280", marginTop: "4px" }, children: "Recalls (24h)" })
      ] }),
      /* @__PURE__ */ jsxs8("div", { style: statCardStyle, children: [
        /* @__PURE__ */ jsx8("div", { style: { fontSize: "1.5rem", fontWeight: 700, color: "#111827" }, children: memStats.learn_count }),
        /* @__PURE__ */ jsx8("div", { style: { fontSize: "12px", color: "#6b7280", marginTop: "4px" }, children: "Learnings (24h)" })
      ] }),
      /* @__PURE__ */ jsxs8("div", { style: statCardStyle, children: [
        /* @__PURE__ */ jsx8("div", { style: { fontSize: "1.5rem", fontWeight: 700, color: "#111827" }, children: memStats.error_count }),
        /* @__PURE__ */ jsx8("div", { style: { fontSize: "12px", color: "#6b7280", marginTop: "4px" }, children: "Errors (24h)" })
      ] }),
      /* @__PURE__ */ jsxs8("div", { style: statCardStyle, children: [
        /* @__PURE__ */ jsxs8("div", { style: { fontSize: "1.5rem", fontWeight: 700, color: "#111827" }, children: [
          Math.round(memStats.avg_latency_ms),
          " ms"
        ] }),
        /* @__PURE__ */ jsx8("div", { style: { fontSize: "12px", color: "#6b7280", marginTop: "4px" }, children: "Avg Latency" })
      ] })
    ] }) : /* @__PURE__ */ jsx8("p", { style: { fontSize: "13px", color: "#9ca3af", marginBottom: "16px" }, children: "Memory stats unavailable." }),
    /* @__PURE__ */ jsxs8("div", { style: { marginBottom: "20px" }, children: [
      /* @__PURE__ */ jsx8("h4", { style: { fontSize: "13px", fontWeight: 600, margin: "0 0 8px", color: "#374151" }, children: "Learning Extraction" }),
      /* @__PURE__ */ jsxs8("div", { style: cardStyle, children: [
        /* @__PURE__ */ jsxs8("label", { style: { display: "flex", alignItems: "center", gap: "8px", cursor: togglingLearning ? "not-allowed" : "pointer" }, children: [
          /* @__PURE__ */ jsx8(
            "input",
            {
              type: "checkbox",
              checked: storageStatus?.learning_enabled ?? true,
              onChange: (e) => handleToggleLearning(e.target.checked),
              disabled: togglingLearning || storageLoading,
              style: { width: "16px", height: "16px" }
            }
          ),
          /* @__PURE__ */ jsx8("span", { style: { fontSize: "13px" }, children: "Enable automatic learning extraction from agent runs" })
        ] }),
        /* @__PURE__ */ jsx8("p", { style: { fontSize: "12px", color: "#9ca3af", margin: "6px 0 0" }, children: "When enabled, Frood extracts learnings from completed agent runs and stores them in the knowledge base for future recall." })
      ] })
    ] }),
    storageStatus && /* @__PURE__ */ jsxs8("div", { style: { marginBottom: "20px" }, children: [
      /* @__PURE__ */ jsx8("h4", { style: { fontSize: "13px", fontWeight: 600, margin: "0 0 8px", color: "#374151" }, children: "Storage Backend" }),
      /* @__PURE__ */ jsx8("div", { style: cardStyle, children: /* @__PURE__ */ jsxs8("div", { style: { display: "flex", gap: "8px", flexWrap: "wrap" }, children: [
        /* @__PURE__ */ jsxs8("span", { style: { padding: "4px 8px", borderRadius: "4px", fontSize: "12px", background: "#dbeafe", color: "#1e40af" }, children: [
          "Mode: ",
          storageStatus.mode
        ] }),
        /* @__PURE__ */ jsxs8("span", { style: {
          padding: "4px 8px",
          borderRadius: "4px",
          fontSize: "12px",
          background: storageStatus.qdrant_available ? "#dcfce7" : "#fef2f2",
          color: storageStatus.qdrant_available ? "#166534" : "#991b1b"
        }, children: [
          "Qdrant: ",
          storageStatus.qdrant_available ? "available" : "unavailable"
        ] })
      ] }) })
    ] }),
    /* @__PURE__ */ jsxs8("div", { style: { marginBottom: "20px" }, children: [
      /* @__PURE__ */ jsx8("h4", { style: { fontSize: "13px", fontWeight: 600, margin: "0 0 4px", color: "#dc2626" }, children: "Danger Zone" }),
      /* @__PURE__ */ jsx8("p", { style: { fontSize: "12px", color: "#9ca3af", margin: "0 0 8px" }, children: "Purge operations are irreversible. All entries in the selected collection will be permanently deleted." }),
      confirmPurge ? /* @__PURE__ */ jsxs8("div", { style: { ...cardStyle, border: "1px solid #fca5a5", background: "#fef2f2" }, children: [
        /* @__PURE__ */ jsxs8("p", { style: { fontSize: "13px", color: "#dc2626", margin: "0 0 8px" }, children: [
          "This will permanently delete ALL entries in the ",
          /* @__PURE__ */ jsx8("strong", { children: confirmPurge }),
          " collection. This action is irreversible."
        ] }),
        /* @__PURE__ */ jsxs8("p", { style: { fontSize: "13px", margin: "0 0 8px" }, children: [
          "Type ",
          /* @__PURE__ */ jsx8("strong", { children: "PURGE" }),
          " to confirm:"
        ] }),
        /* @__PURE__ */ jsxs8("div", { style: { display: "flex", gap: "6px" }, children: [
          /* @__PURE__ */ jsx8(
            "input",
            {
              type: "text",
              value: purgeInput,
              onChange: (e) => setPurgeInput(e.target.value),
              placeholder: "Type PURGE to confirm",
              style: { flex: 1, padding: "4px 8px", borderRadius: "4px", border: "1px solid #fca5a5", fontSize: "13px" }
            }
          ),
          /* @__PURE__ */ jsx8(
            "button",
            {
              onClick: handlePurge,
              disabled: purgeInput !== "PURGE" || purging,
              style: {
                padding: "4px 10px",
                borderRadius: "4px",
                border: "none",
                background: purgeInput === "PURGE" ? "#dc2626" : "#d1d5db",
                color: "white",
                cursor: purgeInput === "PURGE" ? "pointer" : "not-allowed",
                fontSize: "12px",
                opacity: purging ? 0.5 : 1
              },
              children: purging ? "Purging..." : "Confirm Purge"
            }
          ),
          /* @__PURE__ */ jsx8(
            "button",
            {
              onClick: () => {
                setConfirmPurge(null);
                setPurgeInput("");
              },
              style: { padding: "4px 10px", borderRadius: "4px", border: "1px solid #d1d5db", background: "white", cursor: "pointer", fontSize: "12px" },
              children: "Cancel"
            }
          )
        ] })
      ] }) : /* @__PURE__ */ jsx8("div", { style: { display: "flex", gap: "8px", flexWrap: "wrap" }, children: ["memory", "knowledge", "history"].map((col) => /* @__PURE__ */ jsxs8(
        "button",
        {
          onClick: () => {
            setConfirmPurge(col);
            setPurgeInput("");
          },
          style: { padding: "6px 12px", borderRadius: "4px", border: "1px solid #fca5a5", background: "#fef2f2", color: "#dc2626", cursor: "pointer", fontSize: "13px" },
          children: [
            "Purge ",
            col.charAt(0).toUpperCase() + col.slice(1)
          ]
        },
        col
      )) })
    ] })
  ] });
}
function RewardsTab() {
  return /* @__PURE__ */ jsxs8("div", { children: [
    /* @__PURE__ */ jsx8("h3", { style: { fontSize: "15px", fontWeight: 600, margin: "0 0 12px" }, children: "Rewards" }),
    /* @__PURE__ */ jsx8("div", { style: { padding: "12px", borderRadius: "6px", background: "#f9fafb", border: "1px solid #e5e7eb", marginBottom: "16px" }, children: /* @__PURE__ */ jsx8("p", { style: { margin: 0, fontSize: "13px", color: "#6b7280" }, children: "Rewards and tier configuration is managed via the Frood platform. Use the standalone Frood dashboard to view tier distribution and enable or disable the rewards system." }) })
  ] });
}
function SettingsPage({ context }) {
  const [activeTab, setActiveTab] = useState3("apikeys");
  return /* @__PURE__ */ jsxs8("div", { style: { padding: "16px", fontFamily: "system-ui, sans-serif", maxWidth: "800px" }, children: [
    /* @__PURE__ */ jsx8("h2", { style: { margin: "0 0 8px", fontSize: "18px", fontWeight: 600 }, children: "Frood Settings" }),
    /* @__PURE__ */ jsx8("p", { style: { margin: "0 0 16px", fontSize: "13px", color: "#6b7280" }, children: "Manage Frood sidecar configuration. Changes take effect immediately." }),
    /* @__PURE__ */ jsx8("div", { style: { display: "flex", gap: "4px", borderBottom: "1px solid #e5e7eb", marginBottom: "16px", flexWrap: "wrap" }, children: TABS.map((tab) => /* @__PURE__ */ jsx8(
      "button",
      {
        onClick: () => setActiveTab(tab.id),
        style: {
          padding: "8px 16px",
          border: "none",
          background: "none",
          cursor: "pointer",
          fontSize: "13px",
          fontWeight: activeTab === tab.id ? 600 : 400,
          color: activeTab === tab.id ? "#3b82f6" : "#6b7280",
          borderBottom: activeTab === tab.id ? "2px solid #3b82f6" : "2px solid transparent"
        },
        children: tab.label
      },
      tab.id
    )) }),
    activeTab === "apikeys" && /* @__PURE__ */ jsx8(ApiKeysTab, { context }),
    activeTab === "security" && /* @__PURE__ */ jsx8(SecurityTab, {}),
    activeTab === "orchestrator" && /* @__PURE__ */ jsx8(OrchestratorTab, {}),
    activeTab === "storage" && /* @__PURE__ */ jsx8(StorageTab, {}),
    activeTab === "memory" && /* @__PURE__ */ jsx8(MemoryTab, { context }),
    activeTab === "rewards" && /* @__PURE__ */ jsx8(RewardsTab, {})
  ] });
}

// src/ui/WorkspaceNavEntry.tsx
import { jsx as jsx9, jsxs as jsxs9 } from "react/jsx-runtime";
function WorkspaceNavEntry({ context }) {
  return /* @__PURE__ */ jsxs9("div", { style: { padding: "8px 0", fontFamily: "system-ui, sans-serif" }, children: [
    /* @__PURE__ */ jsx9("div", { style: { fontSize: "11px", fontWeight: 600, color: "#9ca3af", textTransform: "uppercase", letterSpacing: "0.05em", padding: "4px 12px" }, children: "Frood" }),
    /* @__PURE__ */ jsxs9("div", { style: { display: "flex", flexDirection: "column", gap: "2px" }, children: [
      /* @__PURE__ */ jsx9("a", { href: `/plugins/frood.paperclip-plugin/workspace-terminal`, style: { padding: "6px 12px", fontSize: "13px", color: "#374151", textDecoration: "none", borderRadius: "4px", display: "block" }, children: "Terminal" }),
      /* @__PURE__ */ jsx9("a", { href: `/plugins/frood.paperclip-plugin/sandboxed-apps`, style: { padding: "6px 12px", fontSize: "13px", color: "#374151", textDecoration: "none", borderRadius: "4px", display: "block" }, children: "Apps" })
    ] })
  ] });
}
export {
  AgentEffectivenessTab,
  AppsPage,
  MemoryBrowserTab,
  ProviderHealthWidget,
  RoutingDecisionsWidget,
  SettingsPage,
  ToolsSkillsTab,
  WorkspaceNavEntry,
  WorkspacePage
};
//# sourceMappingURL=index.js.map
