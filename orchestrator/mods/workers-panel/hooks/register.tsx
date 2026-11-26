import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { WorkersPanelText } from '../types'

// /workers opens a side pane showing `workers-view.mjs` (plain text) refreshed every 15 s. One child per refresh,
// 12 s timeout (workers-view keeps itself inside 9 s), never overlapping (busy flag). poll() never rejects: any
// failure, $.ui.panes() included, is caught and shown in the pane. Same {{ORCH_REPO}} / {{HOME}} node fallback as
// dispatch-status.
const VIEW = '{{ORCH_REPO}}/bin/workers-view.mjs'
const NODES = ['node', '{{HOME}}/.local/share/mise/shims/node']
const PERIOD_MS = 15_000
const PANE = 'workers'

const view = atom({ plugin: 'workers-panel', key: 'view' } as const, { text: 'loading…', at: 0 } as WorkersPanelText, {
  shape: 'view-1',
})

export const register: Register = on => {
  // One timer per session, started by the first /workers; polling skips while the pane is not placed.
  let timer = false
  let node = 0
  let busy = false

  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'workers', description: 'Show the live headless workers in a pane' })
    return next(e)
  })

  on('command.run', { command: 'workers' }, async $ => {
    await $.ui.open({ id: PANE, title: 'Workers' })

    const poll = async () => {
      if (busy) return
      busy = true
      try {
        const up = (await $.ui.panes()).some(p => p.id === PANE && p.isPlaced)
        if (!up) return
        let text: string
        try {
          const { exitCode, stdout } = await $.process.run([NODES[node] ?? 'node', VIEW], { timeoutMs: 12_000 })
          text = exitCode === 0 ? stdout.trim() || 'no output' : `workers-view: exit ${exitCode}`
        } catch (err) {
          // `node` not on the app's PATH: try the mise shim once, next poll.
          if (node + 1 < NODES.length) node++
          text = `workers-view: ${String(err).slice(0, 120)}`
        }
        await update($, view, () => ({ text, at: Date.now() }))
      } catch (err) {
        // panes() or update() failed: show it if we can, and never let the rejection escape the timer.
        const text = `workers-panel: ${String(err).slice(0, 120)}`
        try {
          await update($, view, () => ({ text, at: Date.now() }))
        } catch {
          // nothing left to report to; the next poll tries again
        }
      } finally {
        busy = false
      }
    }

    if (!timer) {
      timer = true
      $.clock.every(PERIOD_MS, poll)
    }
    void poll()
    return { text: 'Workers pane opened.' }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const { text } = await read($, view)
    return (
      <Box flexDirection="column">
        {text.split('\n').map(line => (
          <Text dimColor={line.startsWith('held:') || line.startsWith('pace:')}>{line}</Text>
        ))}
      </Box>
    )
  })
}
