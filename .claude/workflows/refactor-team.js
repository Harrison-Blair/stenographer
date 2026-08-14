export const meta = {
  name: "refactor-team",
  description: "Run refactor teams in parallel — per team: one implementer, two adversarial reviewers (behavior-preservation and scope/quality lenses), and a bounded fix loop. Teams edit disjoint file sets; every agent is pinned to Opus 4.8.",
  whenToUse: "Invoked once per refactor phase with args = { phase, teams: [{ name, files, findings, techniques, brief }] }. Team file lists within one invocation MUST be disjoint — the caller guarantees no overlap.",
}

// refactor-team: parallel teams over disjoint file sets, working directly in
// the shared tree (no worktrees — disjointness is the isolation). Per team:
// implement → 2 adversarial reviews (parallel, distinct lenses) → fixer +
// re-review, at most MAX_FIX_ROUNDS rounds. Unresolved issues are reported,
// never silently dropped. All agents pinned to Opus 4.8 (user requirement).
const MODEL = "claude-opus-4-8"
const MAX_FIX_ROUNDS = 2

// Tolerate args arriving as a JSON-encoded string (observed with large payloads).
let parsedArgs = args
if (typeof parsedArgs === "string") {
  try { parsedArgs = JSON.parse(parsedArgs) } catch { parsedArgs = null }
}
const cfg = parsedArgs && typeof parsedArgs === "object" ? parsedArgs : {}
const PHASE = typeof cfg.phase === "string" ? cfg.phase : "refactor"
const TEAMS = Array.isArray(cfg.teams) ? cfg.teams : []
if (TEAMS.length === 0) {
  return { error: "No teams provided — pass args = { phase, teams: [{ name, files, findings, techniques, brief }] }" }
}

const CONVENTIONS =
  "## Repo conventions (binding)\n" +
  "- All Python tooling through the repo venv: `.venv/bin/pytest`, `.venv/bin/ruff`. NEVER the system python/pytest/ruff.\n" +
  "- Unit tests: `.venv/bin/pytest -m \"not integration\" <paths>`. Integration-marked tests are skipped without STENOGRAPHER_INTEGRATION=1 — do not set it.\n" +
  "- ruff: line length 100, target py312, rules E,F,I,B,UP,N,SIM,RUF. Run `.venv/bin/ruff check <touched files>` and `.venv/bin/ruff format <touched files>` before finishing.\n" +
  "- Every source file keeps its `SPDX-License-Identifier: GPL-3.0-or-later` header; a NEW source file must carry one.\n" +
  "- Surgical changes: every changed line must trace to this team's findings. Do not improve adjacent code, comments, or formatting. Match existing style.\n" +
  "- Simplicity first: no abstractions for single-use code, no speculative flexibility, no error handling for impossible scenarios.\n" +
  "- This is a BEHAVIOR-PRESERVING refactor. If you believe a behavior change is unavoidable, stop that part, leave the code as-is, and report it instead.\n"

const filesBlock = t =>
  "## File boundary (hard constraint)\n" +
  "You may create/modify/delete ONLY these files — other teams are editing other files concurrently, so touching anything else corrupts their work:\n" +
  t.files.map(f => "  - " + f).join("\n") + "\n"

const IMPL_SCHEMA = {
  type: "object", required: ["changes", "testsRun"],
  properties: {
    changes: { type: "array", items: { type: "string" }, description: "one entry per meaningful change: file — what was done and which technique/Mechanics step it follows" },
    testsRun: { type: "string", description: "exact test/lint commands run and their outcomes" },
    testEvidence: { type: "string", description: "for each NEW or PORTED test: evidence it failed when the behavior was broken (what was stubbed, the observed red, then green after restore)" },
    deferred: { type: "array", items: { type: "string" }, description: "anything in the findings deliberately NOT done, with the reason (e.g. would change behavior, out of file boundary)" },
  },
}
const REVIEW_SCHEMA = {
  type: "object", required: ["verdict", "issues"],
  properties: {
    verdict: { enum: ["approve", "revise"] },
    issues: { type: "array", items: {
      type: "object", required: ["file", "severity", "description"],
      properties: {
        file: { type: "string" },
        line: { type: "number" },
        severity: { enum: ["major", "minor"] },
        description: { type: "string", description: "the concrete problem, with quoted code/diff evidence" },
      },
    }},
  },
}

const IMPLEMENT_PROMPT = t =>
  "## Refactor implementer — team " + t.name + " (" + PHASE + ")\n\n" +
  CONVENTIONS + "\n" + filesBlock(t) + "\n" +
  "## Your findings\n" +
  "These smell-audit findings are your entire scope:\n" + t.findings + "\n\n" +
  "## Method\n" +
  "1. Read each finding's entry in docs/code-smells.md (its Signs and Fix gist).\n" +
  "2. Read the numbered **Mechanics** for the named technique(s) in docs/refactoring-techniques.md: " + t.techniques + ". Follow the Mechanics order — they exist to keep each step safe; run the scoped tests between risky steps.\n" +
  "3. Apply the refactor within the file boundary only.\n" +
  (t.brief ? "\n## Team-specific brief\n" + t.brief + "\n" : "") +
  "\n## Test discipline\n" +
  "- Run the scoped unit tests for your files before AND after (they must pass both times): `.venv/bin/pytest -m \"not integration\" <your test files>`.\n" +
  "- A new or ported test only counts if you have SEEN it fail: temporarily break/stub the behavior it covers, confirm red, restore, confirm green. Record this in testEvidence.\n" +
  "- Finish with `.venv/bin/ruff check` and `.venv/bin/ruff format` on every touched file.\n\n" +
  "Structured output only."

const R1_PROMPT = (t, implReport) =>
  "## Adversarial reviewer R1 — behavior preservation — team " + t.name + " (" + PHASE + ")\n\n" +
  CONVENTIONS + "\n" + filesBlock(t) + "\n" +
  "An implementer just refactored these files for the smell-audit findings below. Your job is to REFUTE the work: try to prove the diff changes observable behavior, drops an invariant/guard/error-path, or deviates from the cited technique's Mechanics in a way that matters.\n\n" +
  "## Findings being fixed\n" + t.findings + "\n\n" +
  "## Implementer's report\n" + implReport + "\n\n" +
  "## Method\n" +
  "- Inspect the scoped diff: `git diff -- " + t.files.join(" ") + "` and `git status --short -- " + t.files.join(" ") + "` (for added/deleted files, also `git diff --stat`).\n" +
  "- For every removed or moved block, name the invariant it enforced and find where the new code re-establishes it. Missing re-establishment with a realistic trigger = major issue.\n" +
  "- Re-run the scoped unit tests yourself; do not trust the report.\n" +
  "- Check the Mechanics of " + t.techniques + " in docs/refactoring-techniques.md were honored where it affects safety.\n\n" +
  "Verdict `revise` only for major issues (a real behavior change, lost guard, broken test, or unsafe deviation) — quote the code/diff for every claim. Minor nits go in issues with severity minor but do not force revise. If you cannot demonstrate a problem, approve.\n\nStructured output only."

const R2_PROMPT = (t, implReport) =>
  "## Adversarial reviewer R2 — scope, simplicity, test validity — team " + t.name + " (" + PHASE + ")\n\n" +
  CONVENTIONS + "\n" + filesBlock(t) + "\n" +
  "An implementer just refactored these files for the smell-audit findings below. Your job is to REFUTE the work on quality grounds:\n" +
  "- **Scope creep**: any changed line that does not trace to the findings (drive-by edits, reformatting, 'improvements'). Files touched outside the boundary are automatically major.\n" +
  "- **Over-abstraction**: helpers/classes/parameters beyond what the finding requires; speculative flexibility; a senior engineer saying 'this is overcomplicated'.\n" +
  "- **Under-delivery**: parts of a finding silently skipped without being listed in the report's deferred list.\n" +
  "- **Test validity**: the report must contain break-then-red-then-green evidence for every new/ported test; tests that merely mirror the implementation, or deleted tests whose coverage was not replaced or consciously retired, are issues.\n\n" +
  "## Findings being fixed\n" + t.findings + "\n\n" +
  "## Implementer's report\n" + implReport + "\n\n" +
  "Inspect `git diff -- " + t.files.join(" ") + "` and `git status --short -- " + t.files.join(" ") + "`. Cross-check against the findings below and the Mechanics of " + t.techniques + ".\n\n" +
  "Verdict `revise` only for major issues, each with quoted evidence; minor nits stay minor and do not force revise. If the work is clean, approve.\n\nStructured output only."

const FIX_PROMPT = (t, issues) =>
  "## Refactor fixer — team " + t.name + " (" + PHASE + ")\n\n" +
  CONVENTIONS + "\n" + filesBlock(t) + "\n" +
  "Adversarial review of the current `git diff -- " + t.files.join(" ") + "` found issues that must be fixed (or, if a claim is factually wrong, rebutted with quoted evidence in your report — do not silently ignore any):\n\n" +
  issues.map((x, i) => "[" + i + "] (" + x.severity + ") " + x.file + (x.line ? ":" + x.line : "") + " — " + x.description).join("\n") + "\n\n" +
  "Original findings for context:\n" + t.findings + "\n\n" +
  "Address every major issue. Re-run the scoped tests and ruff afterwards. Structured output only."

const summarizeImpl = r =>
  "Changes:\n" + (r.changes || []).map(c => "- " + c).join("\n") +
  "\nTests: " + (r.testsRun || "(none reported)") +
  (r.testEvidence ? "\nTest evidence: " + r.testEvidence : "") +
  ((r.deferred && r.deferred.length) ? "\nDeferred: " + r.deferred.join("; ") : "")

async function runTeam(t) {
  const ph = PHASE + ":" + t.name
  const impl = await agent(IMPLEMENT_PROMPT(t), { label: t.name + ":implement", phase: ph, model: MODEL, schema: IMPL_SCHEMA })
  if (!impl) return { team: t.name, error: "implementer returned no result", reviewRounds: 0, unresolved: [] }
  let report = summarizeImpl(impl)
  log(t.name + ": implemented — " + (impl.changes || []).length + " changes")

  let rounds = 0
  let unresolved = []
  let reviews = await parallel([
    () => agent(R1_PROMPT(t, report), { label: t.name + ":review-behavior", phase: ph, model: MODEL, schema: REVIEW_SCHEMA }),
    () => agent(R2_PROMPT(t, report), { label: t.name + ":review-quality", phase: ph, model: MODEL, schema: REVIEW_SCHEMA }),
  ])

  while (true) {
    const live = reviews.filter(Boolean)
    const majors = live.flatMap(r => r.issues || []).filter(i => i.severity === "major")
    const needRevise = live.some(r => r.verdict === "revise") && majors.length > 0
    unresolved = majors
    if (!needRevise) {
      const minors = live.flatMap(r => r.issues || []).filter(i => i.severity === "minor")
      return { team: t.name, changes: impl.changes, testsRun: impl.testsRun, testEvidence: impl.testEvidence, deferred: impl.deferred, reviewRounds: rounds, unresolved: [], minorNotes: minors, finalReport: report }
    }
    if (rounds >= MAX_FIX_ROUNDS) {
      log(t.name + ": max fix rounds reached with " + majors.length + " unresolved major issue(s)")
      return { team: t.name, changes: impl.changes, testsRun: impl.testsRun, reviewRounds: rounds, unresolved: majors, finalReport: report }
    }
    rounds++
    log(t.name + ": fix round " + rounds + " (" + majors.length + " major issues)")
    const fix = await agent(FIX_PROMPT(t, majors), { label: t.name + ":fix-" + rounds, phase: ph, model: MODEL, schema: IMPL_SCHEMA })
    if (fix) report = report + "\n\n--- Fix round " + rounds + " ---\n" + summarizeImpl(fix)
    // Re-review with the behavior lens (the stricter safety gate) judging the
    // updated diff against the outstanding issues.
    const recheck = await agent(
      R1_PROMPT(t, report) + "\n\nThis is re-review round " + rounds + ". The previously reported major issues were:\n" +
      majors.map((x, i) => "[" + i + "] " + x.file + " — " + x.description).join("\n") +
      "\nVerify each is resolved (or convincingly rebutted in the report) and re-check the full scoped diff.",
      { label: t.name + ":re-review-" + rounds, phase: ph, model: MODEL, schema: REVIEW_SCHEMA }
    )
    reviews = [recheck]
  }
}

const results = await parallel(TEAMS.map(t => () => runTeam(t)))
return { phase: PHASE, teams: results.filter(Boolean) }
