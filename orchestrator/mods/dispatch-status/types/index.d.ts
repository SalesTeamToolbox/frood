export type DispatchLine = string | null

declare module 'claude-code' {
  interface PluginState {
    'dispatch-status': { line: DispatchLine }
  }
}
