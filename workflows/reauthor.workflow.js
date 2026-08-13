export const meta = {
  name: 'reauthor',
  description:
    'Greenfield reauthor per docs/reauthor.md: per milestone an Opus 4.8 planner, up to 3 implementer+2-adversarial-reviewer teams over disjoint files, then a sweep gate (ruff, pytest, editable install, CLI smoke) with a bounded fix loop and a scoped commit',
  whenToUse:
    'Execute build-order milestones from docs/reauthor.md §8. Default run is M0–M5; M6 (old-code deletion) runs only via args {milestones:["M6"]} after real-dictation sign-off. Pass args {milestones:["M0"]} to run a single milestone.',
  phases: [
    { title: 'M0 plan' },
    { title: 'M0 implement' },
    { title: 'M0 sweep' },
    { title: 'M1 plan' },
    { title: 'M1 implement' },
    { title: 'M1 sweep' },
    { title: 'M2 plan' },
    { title: 'M2 implement' },
    { title: 'M2 sweep' },
    { title: 'M3 plan' },
    { title: 'M3 implement' },
    { title: 'M3 sweep' },
    { title: 'M4 plan' },
    { title: 'M4 implement' },
    { title: 'M4 sweep' },
    { title: 'M5 plan' },
    { title: 'M5 implement' },
    { title: 'M5 sweep' },
    { title: 'M6 plan' },
    { title: 'M6 implement' },
    { title: 'M6 sweep' },
  ],
}
// SPDX-License-Identifier: GPL-3.0-or-later
// Orchestrates the clean-room rewrite defined in docs/reauthor.md, one milestone at a time:
// plan -> disjoint parallel teams (implementer + 2 adversarial reviewers + bounded fix loop)
// -> sweep gate (lint/tests/install/CLI, bounded fix loop, scoped commit). Red sweep aborts
// the remaining milestones. Patterns lifted from workflows/gui-reauthor.workflow.js and
// .claude/workflows/refactor-team.js.

const MODEL = 'claude-opus-4-8'
const SPEC = 'docs/reauthor.md'
const SMELLS = 'docs/code-smells.md'
const ALL = ['M0', 'M1', 'M2', 'M3', 'M4', 'M5', 'M6']
const DEFAULT_RUN = ['M0', 'M1', 'M2', 'M3', 'M4', 'M5']
const MAX_TEAM_FIX_ROUNDS = 2
const MAX_SWEEP_FIX_ROUNDS = 2

const MILESTONE_SCOPE = {
  M0: 'Scaffold. New package skeleton beside the old one (implementer choice: src/stenographer_v2/ during transition or a branch-level swap — document the choice), pyproject with py3.12 floor and deps (faster-whisper, sounddevice, soundfile, evdev, huggingface_hub), ruff + pytest config for the new code. Verify: venv installs, empty CLI runs.',
  M1: 'Model + batch path. config.py, model.py, format.py, cli.py transcribe + model download. Verify: transcribe on a known WAV matches the old tool; hotwords honored.',
  M2: 'Capture. audio.py with RMS gate and sample-rate fallback. Verify: record a clip via a temporary CLI hook, inspect the WAV; quiet-mic gate test at low RMS.',
  M3: 'Worker. worker.py child process: one job at a time, idle kill, restart. Verify: smoke test transcribes through the child, kill it mid-idle, transcribe again.',
  M4: 'Delivery. deliver.py (wl-copy both selections + uinput Shift+Insert + release guard) and feedback.py. Verify: smoke paste into a focused terminal on Hyprland AND GNOME Wayland; clipboard readable via wl-paste.',
  M5: 'Daemon. hotkey.py, daemon.py, single-instance lock, signals, cues wired, notify.py; systemd unit in packaging/. Verify: real dictation end-to-end on both compositor families — the acceptance test.',
  M6: 'Doctor + deletion. doctor.py, devices; smoke suite complete; README rewritten; DELETE the old package, old tests, update-era workflows, and the GUI-reauthor workflow files; reconcile CLAUDE.md. Verify: full smoke suite green; fresh-venv install from scratch works. Runs ONLY after real-dictation sign-off.',
}

// ---------- schemas ----------

const PLAN_SCHEMA = {
  type: 'object',
  required: ['overview', 'file_structure', 'data_structures', 'shared_constraints', 'commit_scope', 'work_packages'],
  properties: {
    overview: { type: 'string' },
    file_structure: {
      type: 'string',
      description: 'planned directory/file layout this milestone creates or touches, one-line purpose each',
    },
    data_structures: {
      type: 'string',
      description: 'the important data structures/types/contracts for this milestone: names, fields, invariants',
    },
    shared_constraints: {
      type: 'string',
      description: 'constraints binding every work package: spec §4 inventory items in play, py3.12 floor, style, line budget',
    },
    commit_scope: {
      type: 'array',
      items: { type: 'string' },
      description: 'git pathspecs making up this milestone commit — the sweep stages nothing outside them',
    },
    work_packages: {
      type: 'array',
      minItems: 1,
      maxItems: 3,
      items: {
        type: 'object',
        required: ['name', 'files', 'instructions', 'tests_to_create', 'acceptance_criteria', 'functional_criteria'],
        properties: {
          name: { type: 'string' },
          files: {
            type: 'array',
            items: { type: 'string' },
            description: 'every file this package may create/modify — MUST be disjoint from the other packages',
          },
          instructions: { type: 'string' },
          tests_to_create: { type: 'array', items: { type: 'string' } },
          acceptance_criteria: { type: 'array', items: { type: 'string' } },
          functional_criteria: { type: 'array', items: { type: 'string' } },
        },
      },
    },
  },
}

const IMPL_SCHEMA = {
  type: 'object',
  required: ['changes', 'testsRun'],
  properties: {
    changes: {
      type: 'array',
      items: { type: 'string' },
      description: 'one entry per meaningful change: file — what was done and which criterion it serves',
    },
    testsRun: { type: 'string', description: 'exact test/lint commands run and their outcomes' },
    testEvidence: {
      type: 'string',
      description: 'for each NEW pure-logic test: evidence it failed when the behavior was broken (what was stubbed, the observed red, then green after restore)',
    },
    deferred: {
      type: 'array',
      items: { type: 'string' },
      description: 'anything in the instructions deliberately NOT done, with the reason',
    },
  },
}

const REVIEW_SCHEMA = {
  type: 'object',
  required: ['verdict', 'issues'],
  properties: {
    verdict: { enum: ['approve', 'revise'] },
    issues: {
      type: 'array',
      items: {
        type: 'object',
        required: ['file', 'severity', 'description'],
        properties: {
          file: { type: 'string' },
          line: { type: 'number' },
          severity: { enum: ['major', 'minor'] },
          description: { type: 'string', description: 'the concrete problem, with quoted code/diff evidence' },
        },
      },
    },
  },
}

const SWEEP_SCHEMA = {
  type: 'object',
  required: ['ruff_ok', 'format_ok', 'tests_ok', 'install_ok', 'cli_ok', 'committed', 'details'],
  properties: {
    ruff_ok: { type: 'boolean' },
    format_ok: { type: 'boolean' },
    tests_ok: { type: 'boolean' },
    install_ok: { type: 'boolean' },
    cli_ok: { type: 'boolean' },
    committed: { type: 'boolean' },
    commit: { type: 'string', description: 'commit hash and subject line, if committed' },
    details: { type: 'string', description: 'command outputs summary; FULL failure output if anything is red' },
  },
}

// ---------- prompt builders ----------

function common(m) {
  return (
    'You are working in the stenographer repo (current directory = repo root, branch dev). ' +
    'FIRST read ' + SPEC + ' IN FULL — it is the single source of truth for this rewrite; its §2 decisions are settled, do not relitigate them. Also read the repo CLAUDE.md. ' +
    'All Python tooling runs through the repo venv (.venv/bin/pip, .venv/bin/ruff, .venv/bin/pytest) — NEVER system python/pip/ruff/pytest. ' +
    'Binding rules: the old package src/stenographer/ and its tests/ are a READ-ONLY behavioral reference until M6 — never modify them; ' +
    'SPDX-License-Identifier: GPL-3.0-or-later header on every new source file; do NOT touch src/stenographer/_version.py; do not push. ' +
    'Testing policy (spec §6, binding): unit tests cover pure logic only; NO mocked-subprocess theater — a test that mocks subprocess/UInput/wl-copy and asserts "we would have called it" must not be written; ' +
    'mock-only testability is a design smell, restructure the component instead; integration-marked tests are skipped without STENOGRAPHER_INTEGRATION=1 (do not set it); ' +
    'a new pure-logic test only counts once it has been SEEN to fail against broken/stubbed behavior. ' +
    'Known version conflict, resolved in the spec\'s favor: the spec (§2.13) sets a py3.12 floor for the NEW package while CLAUDE.md/ruff target py3.14 for the old one — all new code must be 3.12-compatible. ' +
    'This task is milestone ' + m + ' of the spec §8 build order: ' + MILESTONE_SCOPE[m] + ' '
  )
}

function filesBlock(p) {
  return (
    '\n## File boundary (hard constraint)\n' +
    'You may create/modify ONLY these files — other teams are editing other files concurrently, so touching anything else corrupts their work:\n' +
    p.files.map((f) => '  - ' + f).join('\n') +
    '\n'
  )
}

function plannerPrompt(m, retryNote) {
  return (
    common(m) +
    'You are the milestone PLANNER — you produce the implementation directions the build team will execute; you write no implementation code and modify no files. ' +
    'Study the spec: §5 target architecture (module map with line budgets, config schema, worker contract, utterance lifecycle), §4 behavioral knowledge inventory (extract every item binding this milestone), §6 testing policy, and §8 this milestone\'s scope and Verify clause. ' +
    'Read the relevant OLD modules under src/stenographer/ as the behavioral reference for what the new code must do (reference only — this is clean-room, not a port). ' +
    'Deliver: (1) the planned directory/file structure for this milestone; (2) the important data structures and contracts (names, fields, invariants); ' +
    '(3) the tests to be created — pure-logic unit tests per §6, with integration-marked smoke tests named separately where the milestone\'s Verify clause calls for them; ' +
    '(4) per work package: concrete instructions, acceptance criteria (verifiable, mapped to the Verify clause), and functional criteria; ' +
    '(5) a split into 1–3 work packages with STRICTLY DISJOINT file sets — list every file each package may create or modify; prefer fewer coherent packages over a forced 3-way split (small milestones may be one package); ' +
    '(6) commit_scope: the exact git pathspecs that form this milestone\'s commit (new-package paths, its tests, pyproject if touched) — the tree carries unrelated dirt, so the sweep may stage nothing outside them. ' +
    (retryNote || '')
  )
}

function implPrompt(m, plan, p) {
  return (
    common(m) +
    'You are the IMPLEMENTER for work package "' + p.name + '".\n' +
    '## Milestone plan\nOverview: ' + plan.overview + '\nFile structure: ' + plan.file_structure + '\n' +
    'Data structures/contracts: ' + plan.data_structures + '\nShared constraints: ' + plan.shared_constraints + '\n' +
    filesBlock(p) +
    '\n## Your instructions\n' + p.instructions + '\n' +
    '\n## Tests to create\n' + p.tests_to_create.map((t) => '  - ' + t).join('\n') + '\n' +
    '\n## Acceptance criteria (all must hold)\n' + p.acceptance_criteria.map((c) => '  - ' + c).join('\n') + '\n' +
    '\n## Functional criteria\n' + p.functional_criteria.map((c) => '  - ' + c).join('\n') + '\n' +
    '\nHard rules: the smallest implementation that meets the criteria; no features, abstractions, or configurability beyond the plan and the spec; ' +
    'respect the spec §5 line budget for your modules; reuse and match existing style where the plan builds on prior milestones. ' +
    'If an instruction is ambiguous or wrong, pick the smallest reasonable interpretation and record it in deferred/changes rather than expanding scope. ' +
    'Before returning: run .venv/bin/ruff check and .venv/bin/ruff format on every touched file, and the scoped unit tests (.venv/bin/pytest -m "not integration" <your test files>) — fix what they surface. Do NOT commit.'
  )
}

function r1Prompt(m, plan, p, history) {
  return (
    common(m) +
    'You are ADVERSARIAL REVIEWER R1 — correctness and spec adherence — for work package "' + p.name + '". ' +
    'The implementer left UNCOMMITTED changes: inspect them with git status/git diff scoped to the package files, and read the new files in full. ' +
    filesBlock(p) +
    '\n## Acceptance criteria\n' + p.acceptance_criteria.map((c) => '  - ' + c).join('\n') +
    '\n## Functional criteria\n' + p.functional_criteria.map((c) => '  - ' + c).join('\n') +
    '\n## Implementer report\n' + history + '\n' +
    '\nActively try to REFUTE the implementation — assume it is wrong and hunt for evidence: acceptance/functional criteria that do not actually hold, ' +
    'violations of the spec §4 behavioral knowledge inventory relevant to these files (e.g. copy-confirmed-before-paste, release guard, RMS gate semantics, callback discipline, local-cache-only model loading), ' +
    'real bugs (races, error paths, resource leaks, lost invariants), and contract mismatches against the milestone plan\'s data structures. ' +
    'Re-run the scoped unit tests yourself; do not trust the report. Do not fix anything; do not modify files. ' +
    'Verdict "revise" only for major issues (a criterion that fails, a real bug, a spec violation) — quote code/diff evidence for every claim. ' +
    'Minor nits get severity minor and do not force revise. If you cannot demonstrate a problem, approve.'
  )
}

function r2Prompt(m, plan, p, history) {
  return (
    common(m) +
    'You are ADVERSARIAL REVIEWER R2 — code smells, scope, and test validity — for work package "' + p.name + '". ' +
    'The implementer left UNCOMMITTED changes: inspect them with git status/git diff scoped to the package files, and read the new files in full. ' +
    filesBlock(p) +
    '\n## Implementer report\n' + history + '\n' +
    '\nYour review guide is ' + SMELLS + ' — read it FIRST. Match the new code against each entry\'s Signs, cite the entry anchor (e.g. code-smells.md#long-method) for every smell finding, and honor each entry\'s Ignore-when clause. ' +
    'Beyond smells, refute on: scope creep (changed lines that do not trace to the package instructions; files touched outside the boundary are automatically major); ' +
    'over-abstraction (helpers/classes/parameters beyond what the criteria require, speculative flexibility — the spec has a hard line budget); ' +
    'under-delivery (instructions silently skipped without appearing in the report\'s deferred list); ' +
    'and test validity per spec §6 (mocked-subprocess theater is automatically major; new pure-logic tests need break-then-red-then-green evidence in the report; tautological tests are issues). ' +
    'Do not fix anything; do not modify files. Verdict "revise" only for major issues, each with quoted evidence; minor nits stay minor. If the work is clean, approve.'
  )
}

function teamFixPrompt(m, plan, p, majors) {
  return (
    common(m) +
    'You are the FIXER for work package "' + p.name + '". Adversarial review of the uncommitted changes found these major issues:\n' +
    majors.map((x, i) => '[' + i + '] ' + x.file + (x.line ? ':' + x.line : '') + ' — ' + x.description).join('\n') +
    filesBlock(p) +
    '\nAddress each with the smallest correct change, staying inside the file boundary, the package instructions, and the spec. ' +
    'If a claim is factually wrong, do not change code for it — rebut it with quoted evidence in your report; never silently ignore a finding. ' +
    'Re-run .venv/bin/ruff check, .venv/bin/ruff format, and the scoped unit tests before returning. Do NOT commit.'
  )
}

function sweepPrompt(m, plan, attempt) {
  return (
    common(m) +
    'You are the SWEEP GATE (verification attempt ' + attempt + '). The milestone\'s work sits UNCOMMITTED in the tree. Run exactly, in order: ' +
    '(1) .venv/bin/ruff check .  (2) .venv/bin/ruff format --check .  (3) .venv/bin/pytest -m "not integration"  ' +
    '(4) a fresh editable install: .venv/bin/pip install -e ".[dev]" must succeed  ' +
    '(5) CLI smoke: the new package\'s console entry point (see the milestone plan and pyproject) with --help and --version, both exiting 0. ' +
    'If ALL five are green: commit ONLY these pathspecs — git add -- ' + plan.commit_scope.join(' ') + ' — as ONE conventional commit (subject like "feat: ... (reauthor ' + m + ')"). ' +
    'The tree carries unrelated dirt: NEVER use git add -A or git commit -a; stage only the listed pathspecs and leave everything else untouched. ' +
    'The commit message must NOT contain any Co-Authored-By or other attribution trailers. Do not push. ' +
    'If anything is red: do NOT commit, fix NOTHING yourself, and report the full failing output in details.'
  )
}

function sweepFixPrompt(m, plan, details) {
  return (
    common(m) +
    'You are the SWEEP FIXER. The milestone\'s uncommitted work failed the sweep gate. Failing output:\n' + details + '\n' +
    'Fix the failures with the smallest correct changes, staying inside the milestone commit scope (' + plan.commit_scope.join(' ') + ') and the spec. ' +
    'Re-run the failed commands yourself until green: .venv/bin/ruff check . ; .venv/bin/ruff format --check . ; .venv/bin/pytest -m "not integration" ; .venv/bin/pip install -e ".[dev]" ; the CLI --help/--version smoke. ' +
    'Do NOT commit — a fresh sweep re-verifies after you.'
  )
}

// ---------- helpers ----------

function summarizeImpl(impl) {
  return (
    'Changes:\n' + impl.changes.map((c) => '  - ' + c).join('\n') +
    '\nTests run: ' + impl.testsRun +
    (impl.testEvidence ? '\nTest evidence: ' + impl.testEvidence : '') +
    (impl.deferred && impl.deferred.length ? '\nDeferred: ' + impl.deferred.join('; ') : '')
  )
}

function packageOverlaps(pkgs) {
  const seen = new Map()
  const out = []
  for (const p of pkgs) {
    for (const f of p.files) {
      if (seen.has(f) && seen.get(f) !== p.name) out.push(f + ' (' + seen.get(f) + ' vs ' + p.name + ')')
      seen.set(f, p.name)
    }
  }
  return out
}

async function runTeam(m, plan, p) {
  const ph = m + ' implement'
  const impl = await agent(implPrompt(m, plan, p), {
    label: m + ':' + p.name + ':implement', phase: ph, model: MODEL, schema: IMPL_SCHEMA,
  })
  if (!impl) return { package: p.name, error: 'implementer returned no result', rounds: 0, unresolved: [] }
  let history = summarizeImpl(impl)

  let reviews = await parallel([
    () => agent(r1Prompt(m, plan, p, history), {
      label: m + ':' + p.name + ':review-correctness', phase: ph, model: MODEL, schema: REVIEW_SCHEMA,
    }),
    () => agent(r2Prompt(m, plan, p, history), {
      label: m + ':' + p.name + ':review-smells', phase: ph, model: MODEL, schema: REVIEW_SCHEMA,
    }),
  ])

  let rounds = 0
  while (true) {
    const live = reviews.filter(Boolean)
    const majors = live.flatMap((r) => r.issues || []).filter((i) => i.severity === 'major')
    const minors = live.flatMap((r) => r.issues || []).filter((i) => i.severity === 'minor')
    const needRevise = live.some((r) => r.verdict === 'revise') && majors.length > 0
    if (!needRevise) return { package: p.name, implementation: impl, rounds, unresolved: [], minor_notes: minors }
    if (rounds >= MAX_TEAM_FIX_ROUNDS) {
      log(m + ':' + p.name + ': max fix rounds reached with ' + majors.length + ' unresolved major issue(s)')
      return { package: p.name, implementation: impl, rounds, unresolved: majors, minor_notes: minors }
    }
    rounds++
    const fix = await agent(teamFixPrompt(m, plan, p, majors), {
      label: m + ':' + p.name + ':fix-' + rounds, phase: ph, model: MODEL, schema: IMPL_SCHEMA,
    })
    if (fix) history = history + '\n\n--- Fix round ' + rounds + ' ---\n' + summarizeImpl(fix)
    // Re-review with the correctness lens only — the stricter safety gate.
    const recheck = await agent(
      r1Prompt(m, plan, p, history) +
        '\n\nThis is re-review round ' + rounds + '. The previously reported major issues were:\n' +
        majors.map((x, i) => '[' + i + '] ' + x.file + ' — ' + x.description).join('\n') +
        '\nVerify each is resolved (or convincingly rebutted in the report) and re-check the full scoped diff.',
      { label: m + ':' + p.name + ':re-review-' + rounds, phase: ph, model: MODEL, schema: REVIEW_SCHEMA }
    )
    reviews = [recheck]
  }
}

// ---------- args ----------

let parsedArgs = args
if (typeof parsedArgs === 'string') {
  try { parsedArgs = JSON.parse(parsedArgs) } catch { parsedArgs = null }
}
const cfg = parsedArgs && typeof parsedArgs === 'object' ? parsedArgs : {}
const requested = Array.isArray(cfg.milestones) ? cfg.milestones : DEFAULT_RUN
const milestones = ALL.filter((m) => requested.includes(m))
if (milestones.length === 0) {
  throw new Error('args.milestones matched none of ' + ALL.join(', '))
}
if (milestones.includes('M6')) {
  log('M6 requested — it deletes the old package and requires prior real-dictation sign-off (spec §8). Proceeding on the caller\'s authority.')
}

// ---------- milestone loop ----------

const report = []
let aborted = false

for (const m of milestones) {
  phase(m + ' plan')
  log(m + ': planning — ' + MILESTONE_SCOPE[m])
  let plan = await agent(plannerPrompt(m), { label: 'plan:' + m, phase: m + ' plan', model: MODEL, schema: PLAN_SCHEMA })
  if (!plan) { report.push({ milestone: m, status: 'planner failed or was skipped' }); aborted = true; break }
  let overlap = packageOverlaps(plan.work_packages)
  if (overlap.length) {
    log(m + ': work-package file sets overlap (' + overlap.join(', ') + ') — re-planning once')
    plan = await agent(
      plannerPrompt(m, 'PREVIOUS ATTEMPT REJECTED: work-package file sets overlapped on: ' + overlap.join(', ') + '. Produce strictly disjoint file sets (merge packages if needed).'),
      { label: 'plan:' + m + ':retry', phase: m + ' plan', model: MODEL, schema: PLAN_SCHEMA }
    )
    overlap = plan ? packageOverlaps(plan.work_packages) : ['planner failed']
    if (!plan || overlap.length) {
      report.push({ milestone: m, status: 'planner could not produce disjoint work packages: ' + overlap.join(', ') })
      aborted = true
      break
    }
  }
  log(m + ': ' + plan.work_packages.length + ' work package(s): ' + plan.work_packages.map((p) => p.name).join(', '))

  phase(m + ' implement')
  const teams = await parallel(plan.work_packages.map((p) => () => runTeam(m, plan, p)))
  const liveTeams = teams.filter(Boolean)
  const failedTeams = plan.work_packages.length - liveTeams.filter((t) => !t.error).length
  if (failedTeams > 0) {
    report.push({ milestone: m, plan, teams: liveTeams, status: failedTeams + ' work package(s) failed to implement' })
    aborted = true
    break
  }
  const unresolved = liveTeams.flatMap((t) => t.unresolved || [])
  if (unresolved.length) {
    log(m + ': ' + unresolved.length + ' unresolved major review finding(s) survive the fix loop — the sweep still gates')
  }

  phase(m + ' sweep')
  let attempt = 1
  let sweep = await agent(sweepPrompt(m, plan, attempt), { label: 'sweep:' + m, phase: m + ' sweep', model: MODEL, schema: SWEEP_SCHEMA })
  const sweepGreen = (s) => !!(s && s.ruff_ok && s.format_ok && s.tests_ok && s.install_ok && s.cli_ok && s.committed)
  while (!sweepGreen(sweep) && attempt <= MAX_SWEEP_FIX_ROUNDS) {
    const details = sweep ? sweep.details : 'sweep agent returned no result'
    log(m + ': sweep attempt ' + attempt + ' is RED — spawning fixer')
    await agent(sweepFixPrompt(m, plan, details), { label: 'sweep-fix:' + m + ':' + attempt, phase: m + ' sweep', model: MODEL, schema: IMPL_SCHEMA })
    attempt++
    sweep = await agent(sweepPrompt(m, plan, attempt), { label: 'sweep:' + m + ':r' + attempt, phase: m + ' sweep', model: MODEL, schema: SWEEP_SCHEMA })
  }

  const green = sweepGreen(sweep)
  report.push({ milestone: m, plan, teams: liveTeams, unresolved_review_findings: unresolved, sweep, green })
  if (!green) {
    log(m + ': sweep is RED after ' + attempt + ' attempt(s) — aborting remaining milestones')
    aborted = true
    break
  }
  log(m + ' complete and committed' + (sweep.commit ? ': ' + sweep.commit : ''))
}

return {
  milestones_run: report.map((r) => r.milestone),
  aborted,
  report,
  reminder:
    'Manual verification is NOT automated (spec §8): after M4, smoke-paste on both Hyprland and a GNOME Wayland session; ' +
    'M5\'s acceptance test is real dictation end-to-end on both compositor families; ' +
    'M6 (old-code deletion) runs only after that sign-off, via args {milestones:["M6"]}. ' +
    'Real-dictation validation precedes any dev -> main merge (spec §6.4).',
}
