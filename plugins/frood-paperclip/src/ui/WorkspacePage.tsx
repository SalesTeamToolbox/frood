import { usePluginStream, usePluginAction } from "@paperclipai/plugin-sdk/ui";
import type { PluginPageProps } from "@paperclipai/plugin-sdk/ui";
import { useState, useEffect, useRef, useCallback } from "react";

interface TerminalEvent {
  sessionId: string;
  text: string;
  ts: number;
}

export function WorkspacePage({ context }: PluginPageProps) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [outputLines, setOutputLines] = useState<string[]>([]);
  const [inputValue, setInputValue] = useState("");
  const outputRef = useRef<HTMLDivElement>(null);

  const startTerminal = usePluginAction("terminal-start");
  const sendInput = usePluginAction("terminal-input");
  const closeTerminal = usePluginAction("terminal-close");

  const { events, connected } = usePluginStream<TerminalEvent>("terminal-output", {
    companyId: context.companyId ?? undefined,
  });

  // Process incoming terminal events
  useEffect(() => {
    if (events.length > 0) {
      const latest = events[events.length - 1];
      if (latest?.text) {
        setOutputLines((prev) => [...prev, latest.text]);
      }
    }
  }, [events]);

  // Auto-scroll terminal output
  useEffect(() => {
    if (outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight;
    }
  }, [outputLines]);

  // Start terminal session on mount
  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const result = await startTerminal({}) as { ok: boolean; sessionId: string };
        if (mounted && result?.ok && result.sessionId) {
          setSessionId(result.sessionId);
        }
      } catch {
        if (mounted) setOutputLines(["[Failed to start terminal session]"]);
      }
    })();
    // Cleanup on unmount per Pitfall 4
    return () => {
      mounted = false;
      if (sessionId) {
        closeTerminal({ sessionId }).catch(() => {});
      }
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSend = useCallback(async () => {
    if (!sessionId || !inputValue.trim()) return;
    await sendInput({ sessionId, data: inputValue + "\n" });
    setOutputLines((prev) => [...prev, `$ ${inputValue}`]);
    setInputValue("");
  }, [sessionId, inputValue, sendInput]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter") {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", fontFamily: "monospace", backgroundColor: "#1e1e1e", color: "#d4d4d4" }}>
      <div style={{ padding: "8px 12px", borderBottom: "1px solid #333", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontWeight: 600, fontSize: "14px" }}>Agent42 Terminal</span>
        <span style={{ fontSize: "12px", color: connected ? "#22c55e" : "#ef4444" }}>
          {connected ? "Connected" : "Disconnected"}
        </span>
      </div>
      <div ref={outputRef} style={{ flex: 1, overflow: "auto", padding: "8px 12px", fontSize: "13px", lineHeight: "1.5", whiteSpace: "pre-wrap" }}>
        {outputLines.length === 0 && (
          <span style={{ color: "#6b7280" }}>{sessionId ? "Terminal ready." : "Connecting..."}</span>
        )}
        {outputLines.map((line, i) => (
          <div key={i}>{line}</div>
        ))}
      </div>
      <div style={{ padding: "8px 12px", borderTop: "1px solid #333", display: "flex", gap: "8px" }}>
        <span style={{ color: "#22c55e" }}>$</span>
        <input
          type="text"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type command..."
          style={{ flex: 1, backgroundColor: "transparent", border: "none", color: "#d4d4d4", fontFamily: "monospace", fontSize: "13px", outline: "none" }}
          disabled={!sessionId}
        />
      </div>
    </div>
  );
}
