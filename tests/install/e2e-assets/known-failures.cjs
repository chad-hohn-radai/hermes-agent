const fs = require('node:fs')
const path = require('node:path')
const { execFileSync } = require('node:child_process')
const rules = require('./known-failures.json')

// This file lives inside the checkout under test, and CI fetches it with
// fetch-depth: 0, so it always has full history to answer ancestry
// questions about itself.
function repoRootFor(startDir) {
  try {
    return execFileSync('git', ['-C', startDir, 'rev-parse', '--show-toplevel'], { encoding: 'utf8' }).trim()
  } catch {
    return null
  }
}

// True only for a STRICT ancestor: an unfixable rule bounded by the commit
// that fixed it must never match the fix commit itself, or every release
// from the fix onward would silently inherit a limitation it no longer has.
function isStrictAncestor(commit, ancestor, repoRoot) {
  if (!repoRoot || !commit || !ancestor || commit === ancestor) return false
  try {
    execFileSync('git', ['-C', repoRoot, 'merge-base', '--is-ancestor', commit, ancestor], { stdio: 'ignore' })
    return true
  } catch {
    return false
  }
}

// A rule matches a starting commit either by exact SHA (explicit, verified
// evidence — see KNOWN_FAILURES.md) or by ancestry: any commit strictly
// before `rule.before` carries the same unfixed code, so pick-release-
// tags.sh sampling a new "oldest" tag between two documented releases does
// not need a matcher update to stay covered.
function commitMatchesRule(rule, commit, repoRoot) {
  if (Array.isArray(rule.commits) && rule.commits.includes(commit)) return true
  if (rule.before && isStrictAncestor(commit, rule.before, repoRoot)) return true
  return false
}

function matchKnownFailure({ platform, phase, commit, installMethod, updateMethod, error, logs, repoRoot }) {
  if (platform !== 'windows' || phase !== 'update' || !/^[0-9a-f]{40}$/.test(commit || '')) return null
  return rules.find(rule =>
    commitMatchesRule(rule, commit, repoRoot) &&
    rule.cases.some(([install, update]) => install === installMethod && update === updateMethod) &&
    rule.errors.some(pattern => new RegExp(pattern).test(error || '')) &&
    rule.signatures.every(pattern => new RegExp(pattern, 'i').test(logs[rule.log] || '')),
  ) || null
}

function readOptional(file) {
  try { return fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '') } catch (error) {
    if (error.code === 'ENOENT') return ''
    throw error
  }
}

function classifyWorkRoot(root, installMethod, updateMethod, error) {
  const state = JSON.parse(fs.readFileSync(path.join(root, 'shas.json'), 'utf8').replace(/^\uFEFF/, ''))
  const rule = matchKnownFailure({
    platform: 'windows', phase: 'update', commit: state.old, installMethod, updateMethod, error,
    logs: {
      update: readOptional(path.join(root, 'logs', 'update.log')),
      desktop: readOptional(path.join(root, 'hermes-home', 'logs', 'desktop.log')),
    },
    repoRoot: repoRootFor(__dirname),
  })
  if (!rule) return null
  return {
    id: rule.id, title: rule.title, explanation: rule.explanation, evidence: rule.evidence,
    commit: state.old, target: state.current, installRef: state.old_ref,
    installMethod, updateMethod, error,
  }
}

module.exports = { matchKnownFailure, classifyWorkRoot, rules }

if (require.main === module) {
  const [root, install, update, error] = process.argv.slice(2)
  try {
    const receipt = classifyWorkRoot(root, install, update, error)
    if (!receipt) process.exitCode = 1
    else {
      fs.writeFileSync(path.join(root, 'known-failure.json'), JSON.stringify(receipt, null, 2) + '\n')
      console.log(JSON.stringify(receipt))
    }
  } catch (error) {
    console.error(`known-failure classification failed: ${error.message}`)
    process.exitCode = 2
  }
}
