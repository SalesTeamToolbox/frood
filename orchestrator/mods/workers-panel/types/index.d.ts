export type WorkersPanelText = { text: string; at: number }

declare module 'claude-code' {
  interface PluginState {
    'workers-panel': { view: Shaped<WorkersPanelText> }
  }
}
