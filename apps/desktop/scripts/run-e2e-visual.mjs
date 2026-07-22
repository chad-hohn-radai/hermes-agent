import { spawnSync } from 'node:child_process'

const env = { ...process.env }
const extraArgs = process.argv.slice(2)
const testPaths = extraArgs.filter(arg => !arg.startsWith('-'))
const playwrightArgs = [
  'test',
  ...(testPaths.length > 0 ? testPaths : ['e2e/']),
  '--reporter=list',
  ...extraArgs.filter(arg => arg.startsWith('-')),
]
let command = 'playwright'
let args = playwrightArgs

if (process.platform === 'darwin') {
  // macOS does not have a Cage-style headless Wayland compositor. Electron's
  // offscreen renderer keeps the test BrowserWindow off the user's desktop.
  env.HERMES_DESKTOP_E2E_HEADLESS = '1'
} else {
  command = 'cage'
  args = ['--', 'playwright', ...playwrightArgs]
  env.WLR_BACKENDS = 'headless'
  env.WLR_NO_HARDWARE_CURSORS = '1'
}

const result = spawnSync(command, args, { env, stdio: 'inherit' })

if (result.error) {
  throw result.error
}

process.exitCode = result.status ?? 1