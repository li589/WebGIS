/**
 * Resolve Env/Python312 (Windows/Linux) then run a Python script.
 * Usage: node scripts/run-repo-python.mjs <script> [args...]
 */
import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(__dirname, '../../..')

function resolvePython() {
  if (process.env.CGDA_PYTHON && existsSync(process.env.CGDA_PYTHON)) {
    return process.env.CGDA_PYTHON
  }
  const candidates = [
    path.join(repoRoot, 'Env', 'Python312', 'python.exe'),
    path.join(repoRoot, 'Env', 'Python312', 'bin', 'python'),
    path.join(repoRoot, 'Env', 'Python312', 'bin', 'python3'),
  ]
  for (const c of candidates) {
    if (existsSync(c)) return c
  }
  return process.platform === 'win32' ? 'python' : 'python3'
}

const args = process.argv.slice(2)
if (args.length === 0) {
  console.error('Usage: node scripts/run-repo-python.mjs <script> [args...]')
  process.exit(2)
}

const py = resolvePython()
const scriptArg = args[0]
const resolvedScript = path.isAbsolute(scriptArg)
  ? scriptArg
  : path.resolve(process.cwd(), scriptArg)
const pyArgs = [resolvedScript, ...args.slice(1)]
const result = spawnSync(py, pyArgs, { stdio: 'inherit', cwd: repoRoot })
process.exit(result.status ?? 1)
