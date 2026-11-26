import type { Register } from 'claude-code'

// Polls Frood's `dispatch.mjs status --line --session <this session>` every 10 s and shows it as this plugin's
// status entry (the footer in the desktop app, under the prompt in the terminal). Only tickets this session holds
// are shown (board assignment, or a stream named after the ticket that this session holds); empty → no entry.
// Runs in the session's cwd, so the board is the repo this session works in; no board → empty → no entry.
const DISPATCH = '{{ORCH_REPO}}/bin/dispatch.mjs'
const NODES = ['node', '{{HOME}}/.local/share/mise/shims/node']
const PERIOD_MS = 10_000

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const result = await next(e)
    const session = await $.session.id()
    let node = 0
    let shown: string | undefined
    let busy = false

    const show = (text: string | undefined) => {
      if (text === shown) return
      shown = text
      $.ui.status(text)
    }

    const poll = async () => {
      if (busy) return
      busy = true
      try {
        const { exitCode, stdout } = await $.process.run(
          [NODES[node] ?? 'node', DISPATCH, 'status', '--line', '--session', session],
          { timeoutMs: 5_000 },
        )
        show(exitCode === 0 ? stdout.trim() || undefined : `⇉ dispatch-status: exit ${exitCode}`)
      } catch (err) {
        // `node` not on the app's PATH: fall back to the mise shim once.
        if (node + 1 < NODES.length) node++
        else show(`⇉ dispatch-status: ${String(err).slice(0, 80)}`)
      } finally {
        busy = false
      }
    }

    void poll()
    $.clock.every(PERIOD_MS, poll)
    return result
  })
}
