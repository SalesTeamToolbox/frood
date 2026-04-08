import { describe, it, expect } from "vitest";
import manifest from "../../dist/manifest.js";

describe("Phase 36: Manifest slot declarations", () => {
  const slots = manifest.ui?.slots ?? [];

  it("has exactly 9 UI slots (4 existing + 5 new)", () => {
    expect(slots.length).toBe(9);
  });

  it("has workspace-terminal page slot (PAPERCLIP-01)", () => {
    const slot = slots.find((s) => s.id === "workspace-terminal");
    expect(slot).toBeDefined();
    expect(slot!.type).toBe("page");
    expect(slot!.exportName).toBe("WorkspacePage");
  });

  it("has sandboxed-apps page slot (PAPERCLIP-02)", () => {
    const slot = slots.find((s) => s.id === "sandboxed-apps");
    expect(slot).toBeDefined();
    expect(slot!.type).toBe("page");
    expect(slot!.exportName).toBe("AppsPage");
  });

  it("has tools-skills detailTab slot (PAPERCLIP-03)", () => {
    const slot = slots.find((s) => s.id === "tools-skills");
    expect(slot).toBeDefined();
    expect(slot!.type).toBe("detailTab");
    expect(slot!.exportName).toBe("ToolsSkillsTab");
    expect((slot as any).entityTypes).toContain("project");
  });

  it("has agent42-settings settingsPage slot (PAPERCLIP-04)", () => {
    const slot = slots.find((s) => s.id === "agent42-settings");
    expect(slot).toBeDefined();
    expect(slot!.type).toBe("settingsPage");
    expect(slot!.exportName).toBe("SettingsPage");
  });

  it("has workspace-nav sidebar slot (PAPERCLIP-05)", () => {
    const slot = slots.find((s) => s.id === "workspace-nav");
    expect(slot).toBeDefined();
    expect(slot!.type).toBe("sidebar");
    expect(slot!.exportName).toBe("WorkspaceNavEntry");
  });

  it("preserves existing 4 slots", () => {
    const existingIds = [
      "agent-effectiveness",
      "provider-health",
      "memory-browser",
      "routing-decisions",
    ];
    for (const id of existingIds) {
      expect(slots.find((s) => s.id === id)).toBeDefined();
    }
  });

  it("workspace-terminal slot has correct displayName", () => {
    const slot = slots.find((s) => s.id === "workspace-terminal");
    expect(slot?.displayName).toBe("Terminal");
  });

  it("sandboxed-apps slot has correct displayName", () => {
    const slot = slots.find((s) => s.id === "sandboxed-apps");
    expect(slot?.displayName).toBe("Apps");
  });

  it("tools-skills slot has correct displayName", () => {
    const slot = slots.find((s) => s.id === "tools-skills");
    expect(slot?.displayName).toBe("Tools & Skills");
  });
});

describe("Phase 36: Manifest capabilities", () => {
  const caps = manifest.capabilities ?? [];

  it("includes ui.page.register capability", () => {
    expect(caps).toContain("ui.page.register");
  });

  it("includes ui.sidebar.register capability", () => {
    expect(caps).toContain("ui.sidebar.register");
  });

  it("preserves existing capabilities", () => {
    expect(caps).toContain("http.outbound");
    expect(caps).toContain("agent.tools.register");
    expect(caps).toContain("ui.detailTab.register");
    expect(caps).toContain("ui.dashboardWidget.register");
  });

  it("includes jobs.schedule capability", () => {
    expect(caps).toContain("jobs.schedule");
  });

  it("includes plugin.state.write capability", () => {
    expect(caps).toContain("plugin.state.write");
  });
});
