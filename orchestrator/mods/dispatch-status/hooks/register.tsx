import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

// Polls Frood's `dispatch.mjs status --line` (the session-indicator contract: one line ≤120 chars,
// empty when nothing is active) and shows it as a row above the prompt (the desktop app does not
// draw `$.ui.status`; the terminal does, so it is set too). Runs in the session's cwd: no board →
// empty → no row.
const DISPATCH = '{{ORCH_REPO}}/bin/dispatch.mjs'
const NODES = ['node', '{{HOME}}/.local/share/mise/shims/node']
const PERIOD_MS = 10_000

const line = atom({ plugin: 'dispatch-status', key: 'line' } as const, null)

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const result = await next(e)
    let node = 0
    let busy = false

    const show = async (text: string | null) => {
      if ((await read($, line)) === text) return
      await update($, line, () => text)
      $.ui.status(text ?? undefined)
    }

    const poll = async () => {
      if (busy) return
      busy = true
      try {
        const { exitCode, stdout } = await $.process.run(
          [NODES[node] ?? "node", DISPATCH, 'status', '--line'],
          { timeoutMs: 5_000 },
        )
        await show(exitCode === 0 ? stdout.trim() || null : `⇉ dispatch-status: exit ${exitCode}`)
      } catch (err) {
        // `node` not on the app's PATH: fall back to the absolute install once.
        if (node + 1 < NODES.length) node++
        else await show(`⇉ dispatch-status: ${String(err).slice(0, 80)}`)
      } finally {
        busy = false
      }
    }

    void poll()
    $.clock.every(PERIOD_MS, poll)
    return result
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const text = await read($, line)
    if (!text || e.props.hasSurvey) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    return (
      <Box>
        <Text dimColor>{text}</Text>
      </Box>
    )
  })
}
