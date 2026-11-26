import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { WorkersPanelText } from '../types'

// /workers opens a side pane showing `workers-view.mjs` (plain text) refreshed every 15 s. One child per refresh,
// 10 s timeout, never overlapping (busy flag). Same {{ORCH_REPO}} / {{HOME}} node fallback as dispatch-status.
const VIEW = '{{ORCH_REPO}}/bin/workers-view.mjs'
const NODES = ['node', '{{HOME}}/.local/share/mise/shims/node']
const PERIOD_MS = 15_000
const PANE = 'workers'

const view = atom({ plugin: 'workers-panel', key: 'view' } as const, { text: 'loading…', at: 0 } as WorkersPanelText, {
  shape: 'view-1',
})

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'workers', description: 'Show the live headless workers in a pane' })
    let node = 0
    let busy = false

    const poll = async () => {
      if (busy) return
      busy = true
      let text: string
      try {
        const { exitCode, stdout } = await $.process.run([NODES[node] ?? 'node', VIEW], { timeoutMs: 12_000 })
        text = exitCode === 0 ? stdout.trim() || 'no output' : `workers-view: exit ${exitCode}`
      } catch (err) {
        // `node` not on the app's PATH: try the mise shim once, next poll.
        if (node + 1 < NODES.length) node++
        text = `workers-view: ${String(err).slice(0, 120)}`
      } finally {
        busy = false
      }
      await update($, view, () => ({ text, at: Date.now() }))
    }

    void poll()
    $.clock.every(PERIOD_MS, poll)
    return next(e)
  })

  on('command.run', { command: 'workers' }, async $ => {
    await $.ui.open({ id: PANE, title: 'Workers' })
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
