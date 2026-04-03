import type { PaperclipPluginManifestV1 } from "@paperclipai/plugin-sdk";

const manifest: PaperclipPluginManifestV1 = {
  id: "agent42.paperclip-plugin",
  apiVersion: 1,
  version: "1.2.0",
  displayName: "Agent42",
  description:
    "Gives Paperclip agents access to Agent42 memory recall, memory store, routing recommendations, effectiveness data, and MCP tool proxying",
  author: "Agent42",
  categories: ["automation"],
  capabilities: [
    "http.outbound",
    "agent.tools.register",
    "ui.detailTab.register",
    "ui.dashboardWidget.register",
    "jobs.schedule",
    "plugin.state.write",
    "plugin.state.read",
    "agents.invoke",
    "events.subscribe",
    "ui.page.register",
    "ui.sidebar.register",
  ],
  entrypoints: {
    worker: "./dist/worker-launcher.cjs",
    ui: "./dist/ui",
  },
  ui: {
    slots: [
      {
        type: "detailTab",
        id: "agent-effectiveness",
        displayName: "Effectiveness",
        exportName: "AgentEffectivenessTab",
        entityTypes: ["agent"],
      },
      {
        type: "dashboardWidget",
        id: "provider-health",
        displayName: "Agent42 Provider Health",
        exportName: "ProviderHealthWidget",
      },
      {
        type: "detailTab",
        id: "memory-browser",
        displayName: "Memory",
        exportName: "MemoryBrowserTab",
        entityTypes: ["run"],
      },
      {
        type: "dashboardWidget",
        id: "routing-decisions",
        displayName: "Agent42 Routing",
        exportName: "RoutingDecisionsWidget",
      },
      {
        type: "page",
        id: "workspace-terminal",
        displayName: "Terminal",
        exportName: "WorkspacePage",
      },
      {
        type: "page",
        id: "sandboxed-apps",
        displayName: "Apps",
        exportName: "AppsPage",
      },
      {
        type: "detailTab",
        id: "tools-skills",
        displayName: "Tools & Skills",
        exportName: "ToolsSkillsTab",
        entityTypes: ["project"],
      },
      {
        type: "settingsPage",
        id: "agent42-settings",
        displayName: "Agent42 Settings",
        exportName: "SettingsPage",
      },
      {
        type: "sidebar",
        id: "workspace-nav",
        displayName: "Agent42 Workspace",
        exportName: "WorkspaceNavEntry",
      },
    ],
  },
  jobs: [
    {
      jobKey: "extract-learnings",
      displayName: "Extract Learnings",
      description:
        "Hourly job that extracts structured learnings from Paperclip run transcripts",
      schedule: "0 * * * *",
    },
  ],
  instanceConfigSchema: {
    type: "object",
    properties: {
      agent42BaseUrl: {
        type: "string",
        description: "Agent42 sidecar base URL (e.g. http://localhost:8001)",
      },
      apiKey: {
        type: "string",
        description: "Bearer token for sidecar auth",
        format: "secret-ref",
      },
      timeoutMs: {
        type: "number",
        description: "Request timeout in ms (default 10000)",
        default: 10000,
      },
    },
    required: ["agent42BaseUrl", "apiKey"],
  },
  tools: [
    {
      name: "memory_recall",
      displayName: "Recall Memories",
      description: "Retrieve semantically relevant memories for the current task",
      parametersSchema: {
        type: "object",
        properties: {
          query: { type: "string", description: "What to search for in memory" },
          taskType: { type: "string", description: "Task category for relevance filtering" },
          topK: { type: "number", description: "Max memories to return (default 5)" },
          scoreThreshold: { type: "number", description: "Minimum similarity score (default 0.25)" },
        },
        required: ["query"],
      },
    },
    {
      name: "memory_store",
      displayName: "Store Memory",
      description: "Persist a learning or insight for future agent recall",
      parametersSchema: {
        type: "object",
        properties: {
          content: { type: "string", description: "Text content to store" },
          tags: { type: "array", items: { type: "string" }, description: "Optional tags for categorization" },
          section: { type: "string", description: "Memory section/category" },
        },
        required: ["content"],
      },
    },
    {
      name: "route_task",
      displayName: "Get Routing Recommendation",
      description: "Get optimal provider and model recommendation for a task type",
      parametersSchema: {
        type: "object",
        properties: {
          taskType: { type: "string", description: "Task type (engineer, researcher, writer, analyst)" },
          qualityTarget: { type: "string", description: "Optional quality target" },
        },
        required: ["taskType"],
      },
    },
    {
      name: "tool_effectiveness",
      displayName: "Get Tool Effectiveness",
      description: "Query top tools by success rate for a task type",
      parametersSchema: {
        type: "object",
        properties: {
          taskType: { type: "string", description: "Task type to query effectiveness for" },
        },
        required: ["taskType"],
      },
    },
    {
      name: "mcp_tool_proxy",
      displayName: "MCP Tool Proxy",
      description: "Invoke an Agent42 MCP tool through the sidecar proxy",
      parametersSchema: {
        type: "object",
        properties: {
          toolName: { type: "string", description: "Name of the MCP tool to invoke" },
          params: { type: "object", description: "Tool parameters", additionalProperties: true },
        },
        required: ["toolName"],
      },
    },
    {
      name: "team_execute",
      displayName: "Team Execute",
      description: "Orchestrate parallel fan-out or sequential wave sub-agent execution",
      parametersSchema: {
        type: "object",
        properties: {
          strategy: { type: "string", enum: ["fan-out", "wave"], description: "Execution strategy" },
          subAgentIds: { type: "array", items: { type: "string" }, description: "Agent IDs for fan-out" },
          waves: {
            type: "array",
            items: {
              type: "object",
              properties: { agentId: { type: "string" }, task: { type: "string" } },
              required: ["agentId", "task"],
            },
            description: "Wave definitions (required for wave)",
          },
          task: { type: "string", description: "Task description for all sub-agents" },
          context: { type: "object", description: "Additional context", additionalProperties: true },
        },
        required: ["strategy", "task"],
      },
    },
  ],
};

export default manifest;
