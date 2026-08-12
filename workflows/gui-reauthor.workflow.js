export const meta = {
  name: 'gui-reauthor',
  description: 'GUI reauthor milestones: Opus 4.8 implementer + two adversarial reviewer pairs + bounded fix loop + green-gate commit',
  whenToUse: 'Execute milestones M1-M5 of workflows/gui-reauthor-plan.md. Pass args {milestones: ["M1"]} to run one milestone (recommended); omit args to run all five sequentially.',
}
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Orchestration (owner-specified): per milestone, one implementer, then two pairs of
// adversarial reviewers in parallel (pair A: behavior & contracts; pair B: quality &
// footprint), then a bounded fix loop (max 2 rounds, re-reviewing only the aspects that
// raised must-fix findings), then a gate agent that verifies ruff + pytest and commits.
// A red gate aborts remaining milestones. Everything the agents implement is specified in
// workflows/gui-reauthor-plan.md — this script carries orchestration only.

const MODEL = 'claude-opus-4-8'
const PLAN = 'workflows/gui-reauthor-plan.md'
const ALL_MILESTONES = ['M1', 'M2', 'M3', 'M4', 'M5']

const MILESTONE_SCOPE = {
  M1: 'Renderer (pure addition): pillow dep, src/stenographer/visualizer/render.py, DejaVuSans asset, renderer/wrap/conversion tests. Discard the stale uncommitted GTK size-request fix first if present (git checkout -- src/stenographer/visualizer/overlay_app.py tests/test_visualizer.py).',
  M2: 'Wayland backend + helper rewrite + GTK removal: vendored protocols/ + regen script, backend_wayland.py, overlay_app.py rewrite, overlay_client.py probe/env changes, delete GTK code and GTK-only tests, pyproject swap PyGObject -> pywayland + python-xlib, CI apt package swap in the same milestone.',
  M3: 'X11 backend: backend_x11.py, selector registers it second, chunking/selection tests.',
  M4: 'Doctor + injection fallback: src/stenographer/wayland.py, capabilities gate + degrade_capability, delivery outcome + per-utterance clipboard-fallback notification wiring, doctor lines + probe_backend, associated tests.',
  M5: 'Packaging + docs: PyInstaller spec, packaging/install.sh, README/BUILD/CLAUDE/AGENTS updates, GTK-reference grep sweep, bundle-size check.',
}

const REVIEW_ASPECTS = [
  {
    key: 'A1-behavior',
    focus:
      'Protocol and behavior preservation. Verify against the plan invariants: the daemon<->helper spawn contract (frozen "_visualizer" argv, source -m entry), READY/ERROR handshake, the exact JSON-lines wire format (configure/state/levels/preview/preview_clear/quit, EOF=quit), writer coalescing and degrade semantics, indicator/session invariants (daemon never assumes the overlay exists; preview text never reaches notify-send), config keys unchanged, and visual parity with the documented look (geometry, colors, alphas, bar math, auto-hide timings, generation guard). Flag ANY divergence not explicitly sanctioned by the plan (sanctioned: italic drop, cue-semantics change).',
  },
  {
    key: 'A2-correctness',
    focus:
      'Correctness and robustness. Hunt for real bugs: races and deadlocks (the writer thread must never block; session lock is held across indicator calls), select()-loop fd handling (partial stdin lines, wayland flush-before-select discipline, X11 pending events), error paths and resource leaks (fds, mmaps, subprocesses), frozen-vs-source divergence, and every item in the plan "Known risks" list (vendored import rewrite, premultiplied alpha, PutImage chunking vs the 262140-byte request cap, layer-shell configure/ack ordering, hide-via-transparent-buffer).',
  },
  {
    key: 'B1-minimality',
    focus:
      'Diff minimality and reuse. Run git diff and interrogate every hunk: does it trace directly to this milestone in the plan? Flag drive-by refactors, reformatting of untouched code, speculative flexibility/configurability, abstractions with a single caller that existing code already covers, and missed reuse of existing helpers (_trim_preview, the coalescing writer, notification _enqueue pattern, errors.py helpers). Also flag the opposite: places where the implementer duplicated logic instead of the plan-sanctioned refactor.',
  },
  {
    key: 'B2-tests-packaging',
    focus:
      'Tests, packaging, and docs. Verify new behavioral tests fail when the behavior is broken (check the implementer demonstrated fail-then-pass, or re-derive it by temporarily breaking the code yourself in a scratch worktree if cheap); check test assertions are meaningful, not tautological mocks. Check pyproject/PyInstaller-spec/CI/docs consistency for this milestone: dependency hygiene, hiddenimports, SPDX headers on new files, ruff clean, no stale GTK/PyGObject references left in files this milestone claims to have cleaned.',
  },
]

const IMPL_SCHEMA = {
  type: 'object',
  required: ['summary', 'files_touched', 'tests_added', 'deviations', 'fail_then_pass_evidence'],
  properties: {
    summary: { type: 'string' },
    files_touched: { type: 'array', items: { type: 'string' } },
    tests_added: { type: 'array', items: { type: 'string' } },
    deviations: {
      type: 'array',
      items: { type: 'string' },
      description: 'Every place the implementation deviates from the plan, with the reason',
    },
    fail_then_pass_evidence: {
      type: 'string',
      description: 'How new behavioral tests were shown to fail against broken/stubbed code before passing',
    },
  },
}

const FINDINGS_SCHEMA = {
  type: 'object',
  required: ['findings'],
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['title', 'file', 'detail', 'must_fix'],
        properties: {
          title: { type: 'string' },
          file: { type: 'string' },
          detail: { type: 'string', description: 'Concrete failure scenario or violation, with evidence' },
          must_fix: { type: 'boolean', description: 'true only for confirmed defects/violations, not taste' },
        },
      },
    },
  },
}

const FIX_SCHEMA = {
  type: 'object',
  required: ['summary', 'fixed', 'rejected'],
  properties: {
    summary: { type: 'string' },
    fixed: { type: 'array', items: { type: 'string' } },
    rejected: {
      type: 'array',
      items: { type: 'string' },
      description: 'Findings NOT acted on, each with the concrete justification',
    },
  },
}

const GATE_SCHEMA = {
  type: 'object',
  required: ['ruff_ok', 'format_ok', 'tests_ok', 'committed', 'details'],
  properties: {
    ruff_ok: { type: 'boolean' },
    format_ok: { type: 'boolean' },
    tests_ok: { type: 'boolean' },
    committed: { type: 'boolean' },
    commit: { type: 'string', description: 'Commit hash and subject line, if committed' },
    details: { type: 'string', description: 'Command outputs summary; full failure output if anything is red' },
  },
}

function common(m) {
  return (
    'You are working in the stenographer repo (current directory = repo root, branch dev). ' +
    'FIRST read ' + PLAN + ' in full — it is the single source of truth; also read the repo CLAUDE.md. ' +
    'All tooling runs through the repo venv (.venv/bin/ruff, .venv/bin/pytest, .venv/bin/pip) — NEVER system python/pip. ' +
    'If .venv is missing, create it per CLAUDE.md (python3 -m venv .venv && .venv/bin/pip install -e ".[dev,build]"). ' +
    'This task is milestone ' + m + ': ' + MILESTONE_SCOPE[m] + ' '
  )
}

function implPrompt(m) {
  return (
    common(m) +
    'Implement this milestone exactly as specified in the plan (its design sections name the files, APIs, and constants). ' +
    'Hard rules: keep the diff as small as possible — every changed line must trace to this milestone; reuse existing code and follow existing style; ' +
    'no features, abstractions, or configurability beyond the plan; SPDX header on every new source file; do NOT touch src/stenographer/_version.py; do NOT commit — a gate agent commits after review. ' +
    'If the milestone changes dependencies, reinstall the venv editable install afterwards. ' +
    'Repo test policy: every new behavioral test must be demonstrated to FAIL against broken/stubbed code before it passes — record how you did this. ' +
    'Before returning, run .venv/bin/ruff check ., .venv/bin/ruff format --check ., and .venv/bin/pytest -m "not integration" and fix what they surface. ' +
    'If the plan is ambiguous or wrong somewhere, pick the smallest reasonable interpretation and record it as a deviation rather than expanding scope.'
  )
}

function reviewPrompt(m, aspect, implSummary) {
  return (
    common(m) +
    'You are an ADVERSARIAL reviewer. The implementer left the milestone as UNCOMMITTED changes: inspect them with git status and git diff (plus git diff --stat), and read the new files. ' +
    'Implementer report (JSON): ' + JSON.stringify(implSummary) + ' ' +
    'Your single review aspect — confine yourself to it: ' + aspect.focus + ' ' +
    'Actively try to REFUTE the implementation: assume it is wrong and look for the evidence. Do not fix anything; do not modify files. ' +
    'Report findings with concrete evidence (file, what breaks, how). Set must_fix=true only for confirmed defects or plan violations; style preferences and speculation are must_fix=false. ' +
    'An empty findings list is a valid result if you genuinely could not break it.'
  )
}

function fixPrompt(m, findings) {
  return (
    common(m) +
    'You are the fixer. Adversarial review of the uncommitted milestone produced these confirmed findings (JSON): ' +
    JSON.stringify(findings) +
    ' Address each with the smallest correct change, staying inside the milestone scope and the plan. ' +
    'If a finding is actually wrong, do not change code for it — reject it with concrete justification. ' +
    'Do not commit. Re-run .venv/bin/ruff check ., .venv/bin/ruff format --check ., and .venv/bin/pytest -m "not integration" before returning.'
  )
}

function gatePrompt(m) {
  return (
    common(m) +
    'You are the milestone gate. Run exactly: .venv/bin/ruff check . ; .venv/bin/ruff format --check . ; .venv/bin/pytest -m "not integration". ' +
    'If ALL are green: commit ALL uncommitted milestone changes on dev as ONE commit with a conventional-commit message describing the milestone (e.g. "feat: ..." or "refactor: ..."). ' +
    'IMPORTANT: the commit message must NOT contain any Co-Authored-By trailer or other attribution trailers. Do not push. ' +
    'If anything is red: do NOT commit; report the failing output in details. Fix nothing yourself.'
  )
}

const requested = args && args.milestones ? args.milestones : ALL_MILESTONES
const milestones = ALL_MILESTONES.filter((m) => requested.includes(m))
if (milestones.length === 0) {
  throw new Error('args.milestones matched none of ' + ALL_MILESTONES.join(', '))
}

const report = []
let aborted = false

for (const m of milestones) {
  phase(m + ' implement')
  log(m + ': implementing — ' + MILESTONE_SCOPE[m])
  const impl = await agent(implPrompt(m), {
    label: 'impl:' + m,
    phase: m + ' implement',
    model: MODEL,
    schema: IMPL_SCHEMA,
  })
  if (!impl) {
    report.push({ milestone: m, status: 'implementer failed or was skipped' })
    aborted = true
    break
  }

  phase(m + ' review')
  let aspects = REVIEW_ASPECTS
  let mustFix = []
  const allFindings = []
  const fixRounds = []
  for (let round = 0; round <= 2; round++) {
    const reviews = await parallel(
      aspects.map((a) => () =>
        agent(reviewPrompt(m, a, impl), {
          label: 'review:' + m + ':' + a.key + (round ? ':r' + round : ''),
          phase: m + ' review',
          model: MODEL,
          schema: FINDINGS_SCHEMA,
        }).then((r) => ({ aspect: a.key, findings: r ? r.findings : [] }))
      )
    )
    const tagged = reviews
      .filter(Boolean)
      .flatMap((r) => r.findings.map((f) => ({ ...f, aspect: r.aspect, round })))
    allFindings.push(...tagged)
    mustFix = tagged.filter((f) => f.must_fix)
    log(m + ' review round ' + round + ': ' + tagged.length + ' findings, ' + mustFix.length + ' must-fix')
    if (mustFix.length === 0 || round === 2) break

    const fix = await agent(fixPrompt(m, mustFix), {
      label: 'fix:' + m + ':r' + (round + 1),
      phase: m + ' review',
      model: MODEL,
      schema: FIX_SCHEMA,
    })
    fixRounds.push(fix)
    const affectedKeys = new Set(mustFix.map((f) => f.aspect))
    aspects = REVIEW_ASPECTS.filter((a) => affectedKeys.has(a.key))
  }

  phase(m + ' gate')
  const gate = await agent(gatePrompt(m), {
    label: 'gate:' + m,
    phase: m + ' gate',
    model: MODEL,
    schema: GATE_SCHEMA,
  })
  const green = !!(gate && gate.ruff_ok && gate.format_ok && gate.tests_ok && gate.committed)
  report.push({
    milestone: m,
    implementation: impl,
    findings: allFindings,
    fix_rounds: fixRounds,
    unresolved_must_fix: mustFix,
    gate,
    green,
  })
  if (!green) {
    log(m + ' gate is RED — aborting remaining milestones')
    aborted = true
    break
  }
  log(m + ' complete and committed')
}

return {
  milestones_run: report.map((r) => r.milestone),
  aborted,
  report,
  reminder:
    'Manual integration checks from the plan Verification section are NOT automated: run them on Arch/Hyprland after M2/M3 and on Ubuntu/GNOME after M3/M4 before continuing.',
}
