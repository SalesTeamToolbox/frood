export function registerTools(ctx, client) {
    // -- memory_recall (PLUG-02, D-12) --
    ctx.tools.register("memory_recall", {
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
    }, async (params, runCtx) => {
        try {
            const p = params;
            const result = await client.memoryRecall({
                query: p.query,
                agentId: runCtx.agentId,
                companyId: runCtx.companyId,
                top_k: p.topK ?? 5,
                score_threshold: p.scoreThreshold ?? 0.25,
            });
            const simplified = result.memories.map((m) => ({
                text: m.text,
                score: m.score,
                source: m.source,
            }));
            return {
                content: JSON.stringify({ memories: simplified }),
                data: { memories: simplified },
            };
        }
        catch (e) {
            return { error: `memory_recall failed: ${String(e)}` };
        }
    });
    // -- memory_store (PLUG-03, D-13) --
    ctx.tools.register("memory_store", {
        displayName: "Store Memory",
        description: "Persist a learning or insight for future agent recall",
        parametersSchema: {
            type: "object",
            properties: {
                content: { type: "string", description: "Text content to store" },
                tags: { type: "array", items: { type: "string" }, description: "Optional tags" },
                section: { type: "string", description: "Memory section/category" },
            },
            required: ["content"],
        },
    }, async (params, runCtx) => {
        try {
            const p = params;
            const result = await client.memoryStore({
                text: p.content, // D-13: map content -> text for sidecar
                agentId: runCtx.agentId,
                companyId: runCtx.companyId,
                tags: p.tags ?? [],
                section: p.section ?? "",
            });
            return {
                content: JSON.stringify({ stored: result.stored, pointId: result.point_id }),
                data: { stored: result.stored, pointId: result.point_id },
            };
        }
        catch (e) {
            return { error: `memory_store failed: ${String(e)}` };
        }
    });
    // -- route_task (PLUG-04, D-14) --
    ctx.tools.register("route_task", {
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
    }, async (params, runCtx) => {
        try {
            const p = params;
            const result = await client.routeTask({
                taskType: p.taskType,
                agentId: runCtx.agentId,
                qualityTarget: p.qualityTarget ?? "",
            });
            return {
                content: `Route to ${result.provider}/${result.model} (tier: ${result.tier})`,
                data: {
                    provider: result.provider,
                    model: result.model,
                    tier: result.tier,
                    taskCategory: result.taskCategory,
                },
            };
        }
        catch (e) {
            return { error: `route_task failed: ${String(e)}` };
        }
    });
    // -- tool_effectiveness (PLUG-05, D-15) --
    ctx.tools.register("tool_effectiveness", {
        displayName: "Get Tool Effectiveness",
        description: "Query top tools by success rate for a task type",
        parametersSchema: {
            type: "object",
            properties: {
                taskType: { type: "string", description: "Task type to query effectiveness for" },
            },
            required: ["taskType"],
        },
    }, async (params, runCtx) => {
        try {
            const p = params;
            const result = await client.toolEffectiveness({
                taskType: p.taskType,
                agentId: runCtx.agentId,
            });
            return {
                content: JSON.stringify({ tools: result.tools }),
                data: { tools: result.tools },
            };
        }
        catch (e) {
            return { error: `tool_effectiveness failed: ${String(e)}` };
        }
    });
    // -- mcp_tool_proxy (PLUG-06, D-08) --
    ctx.tools.register("mcp_tool_proxy", {
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
    }, async (params, _runCtx) => {
        try {
            const p = params;
            const result = await client.mcpTool({
                toolName: p.toolName,
                params: p.params ?? {},
            });
            if (result.error) {
                return { error: `mcp_tool_proxy: ${result.error}` };
            }
            return {
                content: typeof result.result === "string" ? result.result : JSON.stringify(result.result),
                data: { result: result.result },
            };
        }
        catch (e) {
            return { error: `mcp_tool_proxy failed: ${String(e)}` };
        }
    });
    // -- team_execute (ADV-02, ADV-03, D-04, D-05, D-08) --
    ctx.tools.register("team_execute", {
        displayName: "Team Execute",
        description: "Orchestrate parallel fan-out or sequential wave sub-agent execution",
        parametersSchema: {
            type: "object",
            properties: {
                strategy: { type: "string", enum: ["fan-out", "wave"], description: "Execution strategy" },
                subAgentIds: { type: "array", items: { type: "string" }, description: "Agent IDs for fan-out" },
                waves: { type: "array", items: { type: "object" }, description: "Wave definitions [{agentId, task}]" },
                task: { type: "string", description: "Task description for sub-agents" },
                context: { type: "object", description: "Additional context", additionalProperties: true },
            },
            required: ["strategy", "task"],
        },
    }, async (params, runCtx) => {
        try {
            const p = params;
            const strategy = p.strategy;
            const task = p.task;
            if (strategy === "fan-out") {
                // Fan-out: parallel sub-agent invocation (D-05, D-06)
                const subAgentIds = p.subAgentIds ?? [];
                if (subAgentIds.length === 0) {
                    return { error: "fan-out requires at least one subAgentId" };
                }
                const invocations = await Promise.all(subAgentIds.map((id) => ctx.agents.invoke(id, runCtx.companyId, {
                    prompt: task,
                    reason: "fan-out",
                })));
                const subResults = invocations.map((inv, i) => ({
                    agentId: subAgentIds[i],
                    runId: inv.runId,
                    status: "invoked",
                    output: "",
                    costUsd: 0,
                }));
                return {
                    content: JSON.stringify({ strategy: "fan-out", subResults }),
                    data: { strategy: "fan-out", subResults },
                };
            }
            else if (strategy === "wave") {
                // Wave: sequential invocation with crash recovery (D-08, D-09, D-10)
                const waveDefs = p.waves ?? [];
                if (waveDefs.length === 0) {
                    return { error: "wave requires at least one wave definition" };
                }
                // Read saved progress for crash recovery (D-09)
                let startWave = 0;
                let waveOutputs = [];
                try {
                    const saved = await ctx.state.get({
                        scopeKind: "run",
                        scopeId: runCtx.runId,
                        stateKey: "wave-progress",
                    });
                    if (saved) {
                        startWave = saved.completedWaves;
                        waveOutputs = saved.waveOutputs;
                    }
                }
                catch {
                    // First run — no saved state
                }
                // Execute waves sequentially (D-08)
                for (let i = startWave; i < waveDefs.length; i++) {
                    const wavePrompt = i === 0
                        ? `${task}\n\nWave ${i + 1}: ${waveDefs[i].task}`
                        : `${task}\n\nWave ${i + 1}: ${waveDefs[i].task}\n\nContext from previous wave:\n${JSON.stringify(waveOutputs[i - 1])}`;
                    const result = await ctx.agents.invoke(waveDefs[i].agentId, runCtx.companyId, {
                        prompt: wavePrompt,
                        reason: `wave-${i + 1}`,
                    });
                    waveOutputs.push({
                        wave: i + 1,
                        agentId: waveDefs[i].agentId,
                        runId: result.runId,
                        status: "invoked",
                        output: "",
                    });
                    // Persist wave progress for crash recovery (D-09)
                    await ctx.state.set({ scopeKind: "run", scopeId: runCtx.runId, stateKey: "wave-progress" }, { completedWaves: i + 1, waveOutputs });
                }
                return {
                    content: JSON.stringify({ strategy: "wave", waveOutputs }),
                    data: { strategy: "wave", waveOutputs },
                };
            }
            else {
                return { error: `Unknown strategy: ${strategy}. Use "fan-out" or "wave".` };
            }
        }
        catch (e) {
            return { error: `team_execute failed: ${String(e)}` };
        }
    });
}
