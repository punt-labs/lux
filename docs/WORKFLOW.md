# Development Workflow

All work in this repository runs as three nested loops. The outermost loop
owns the backlog: what is worth doing and in what order. The middle loop owns
one pull request: a single shippable, revertible change. The innermost loop
owns one mission: a single delegated piece of work inside that change.

```text
Level 1 — Backlog loop   one iteration = one work batch     (Linear)
  Level 2 — PR loop      one iteration = one pull request
    Level 3 — Mission    one iteration = one delegated mission
                         (design, code, test — a do-while)
```

Each level hands work down and receives finished results back. Escalation of
scope only goes up: a mission that uncovers a bigger problem grows its PR; a
PR that uncovers a new line of work files an issue for the backlog loop. Defects
move the other way — anything found while a PR is open is fixed in that PR,
never sent back to the backlog.

The pseudocode at each level gives the control flow; a small Z schema at each
level gives the doorway conditions — what must be true to enter an iteration
and what must be true to leave it. The state those schemas observe:

```text
LoopState
  signals       : ℙ SIGNAL  -- issues, alerts, messages not yet triaged
  open          : ℙ ISSUE    -- open issues: the single work funnel
  validated     : ℙ ISSUE    -- re-proven against current main
  claimed       : ℙ ISSUE    -- the current batch
  closed        : ℙ ISSUE    -- issues completed by a merged PR
  activeWorkers : ℙ WORKER  -- sub-agents editing the shared worktree
  testCount     : ℕ         -- tests collected by the suite
  ------------------------------------------------------------------
  validated ⊆ open
  claimed   ⊆ validated
  open ∩ closed = ∅         -- an issue is open or closed, never both
```

An issue's lifecycle is a walk through these sets: `open → validated → claimed
→ closed`. Steps that were performed ("the recap was sent") appear as named
predicates over declared terms, never as bare primed flags.

## Roles

The operator owns requirements and design direction, rules on genuine design
forks, and judges interaction feel at the demo of an `interactive(pr)`
change. Claude runs everything else:
the backlog, the missions, the review cycles, the demos, and the merges. Review of code is done by agents
— the local review agents before the PR, then Qodo and Bugbot on the PR. There
is no human review gate. The operator reads code in the IDE, but that inspection is
separate, feeds design discussion only, and nothing in these loops waits on
it.

## Level 1 — The backlog loop

The backlog loop keeps the Linear tracker true and decides what to work on
next. Linear is the single funnel: every piece of work, whatever its origin,
is an issue before it is anything else. One iteration selects and completes one
batch of work. The loop runs at session start and again whenever the current
batch is done.

```text
function backlog_loop():

    # 1. INTAKE — every signal becomes an issue or is disposed at the door
    for signal in [github_issues, dependabot_alerts, biff_messages,
                   operator_requests, new_scope_found_while_working]:
                   # a defect inside an open PR's unit is fixed in that PR,
                   # never filed — only genuinely NEW scope arrives here
        if duplicate(signal):  close_at_door(signal, link_existing_issue)
        elif invalid(signal):  close_at_door(signal, stated_reason)
        else:                  linear_create(signal, labels, link_back_to_source)

    # 2. VALIDATE — an issue must be true before it is workable
    for issue in candidates(linear_ready):
        confirm it is still real against current main
        confirm nothing merged or decided has superseded it
        confirm it is one rollback-coherent unit (split or merge if not)
        confirm its blocked-by links reflect reality
        otherwise: fix the issue, or close it with the reason

    # 3. ASSESS — automatic ordering; escalate only on a genuine fork
    order = sort(validated, by:
        security severity                  # open HIGH/CRITICAL first, always
        > broken user journeys             # bugs on paths users actually hit
        > active epic continuity           # finish what is started
        > debt that blocks throughput      # decomposition, testability
        > features)                        # v1 scope before v2
    if the ordering hits a fork the charter cannot resolve:
        ask the operator for a focus ruling
    else:
        proceed without asking

    # 4. SELECT AND EXECUTE
    batch = claim a realistic set from the top of the order
    for unit in rollback_coherent_units(batch):
        pr_loop(unit)                      # Level 2

    # 5. CLOSE OUT
    close GitHub issues resolved by the merged PRs, linking each PR
    send the batch recap via beadle-email  # covers what the per-merge recaps
                                           # do not: intake dispositions, issues
                                           # closed at validation, order changes
    return to intake — new signals have accrued while working
```

Entry and exit for one batch iteration:

```text
EnterBatch ≙ [ LoopState ]                -- no precondition: the backlog loop
                                          -- is a do-while(true); intake always
                                          -- has standing to run

ExitBatch ≙ [ Δ LoopState |
  intakeDisposed(signals)                 -- every signal observed at this
                                          --   iteration's intake became an issue
                                          --   or was closed at the door with a
                                          --   reason; new signals keep accruing,
                                          --   so the live queue is never empty
  ∧ claimed′ = ∅ ∧ claimed ⊆ closed′      -- the batch drained: every claimed
                                          --   issue closed by a merged PR
  ∧ resolvedIssuesClosed(mergedPRs)       -- GitHub issues answered with their PR
  ∧ batchRecapSent(claimed) ]
```

### Intake

Work arrives from five places: GitHub issues filed by users, Dependabot
security alerts, biff messages from agents in other repositories, requests
from the operator, and new lines of work we discover ourselves. That last
source carries a boundary: a defect found inside the unit of an open PR is
fixed in that PR and never becomes an issue; only genuinely new scope —
discovered outside any open PR, or clearly a separate rollback unit — enters
at intake. At intake,
each signal is either turned into an issue or closed at the door with a stated
reason — duplicate of an existing issue, or invalid. Nothing is left sitting
in an external queue: a GitHub issue gets a reply naming its Linear issue, and it is
closed when that issue closes.

Security alerts map severity to priority: a critical or high alert becomes a
P1 issue and goes to the front of the order. Security work does not wait in
the backlog.

Intake must not depend on remembering to look. A recurring poll (via the
`/loop` skill) or a session-start sweep checks the GitHub issue list and the
Dependabot alert list, so an alert filed overnight is an issue by the time the
first batch is selected.

### Validation

The codebase moves; issues rot. Before an issue is workable, confirm it is still
real: reproduce the bug or re-check the premise against current main, confirm
no merged PR or design decision has superseded it, confirm it describes one
rollback-coherent unit of work, and confirm its dependency links are correct.
A stale issue is closed with the reason. A bloated issue is split. Validation
covers the candidates for the coming batch, not the whole backlog every time.

### Assessment

Ordering is automatic in the steady state. The sort is:

1. **Security severity.** Open high or critical alerts outrank everything.
2. **Broken user journeys.** A bug on a path users actually hit beats new
   work.
3. **Active epic continuity.** An epic in flight keeps its claim until it is
   done. Interleaving epics is how a backlog churns without shipping.
4. **Debt that blocks throughput.** Decomposition and testability work that
   makes the next ten changes cheaper.
5. **Features.** v1 scope before v2; issues labeled `v2` wait.

The operator is asked for a focus ruling only when the ordering hits a
genuine fork the rules above cannot resolve: two epics competing to be the
active one, a strategic pivot, or a drift in the debt-versus-feature balance
that changes what shipping means. Direction belongs to the operator;
sequencing inside a settled direction does not require asking.

## Level 2 — The PR loop

One iteration of the PR loop produces one merged pull request. It is entered
when the backlog loop hands down a unit of work sized for throughput, and it
runs the missions (Level 3) needed to build that unit.

### Sizing: throughput, not purity

Nobody reads these diffs. Agents review them, and they squash-merge. So the
size of a PR is an economic decision, not a hygiene one:

- **The floor is transaction cost.** Every PR pays a roughly fixed overhead —
  branch, full-diff review rounds, the demo, CI, remote review cycles, the
  merge gate, the recap. A PR too small pays that overhead for too little
  value.
- **The ceiling is reviewer effectiveness.** The reviewers are agents, and
  past a certain diff size their quality drops: local review agents lose
  focus across a sprawling diff, and the remote reviewers degrade outright on
  very large ones. A PR too large buys throughput at the cost of review
  quality.
- **The typical right size** is several small issues batched together, or one
  coherent slice of a larger issue. An issue too large to slice into one PR is
  mis-filed: decompose it into an epic whose child issues fit the band.
- **Rollback coherence still binds.** Whatever merges must revert together
  sensibly. That is the one structural constraint. "Purity," "one concern per
  PR," and "keep the diff small" are not criteria — a docs fix, a debt
  paydown, or an adjacent bug fix riding along is welcome, and an improvement
  is never held back or split out for tidiness.

```text
function pr_loop(unit):

    # A. BUILD — missions, one at a time
    branch from main
    consult the decision log before any design or design proposal:
        grep '^## DES-' DESIGN.md for the topic; read every match in full
        cite the ADRs consulted in the contract, the design, and any
        proposal to the operator — no citation means the step was skipped
    if unit is architectural (new contract, new types, cross-cutting flow):
        design mission first, with no prescribed write-set
        leader reviews the design end-to-end
        substantive issues go to the operator as concrete decisions
        implementation waits for the operator's ratification
    for mission in unit:
        mission_loop(mission)             # Level 3
        # bug fixes are TDD: a failing test reproduces the defect first
        # coverage rises with every mission; z-spec gates concurrency work

    # B. FULL-DIFF VERIFICATION (local, before any PR exists)
    make check                            # full gate on the accumulated diff
    if local_review(full diff) is blocked: stop the unit until the
        operator rules                    # local_review: punt-kit pr-review.md

    # C. DEMO — the leader verifies the running system; the operator judges feel
    make restart                          # from outside a Lux terminal; ends its sessions
    write down the expected outcome, then drive the real entry point
    capture machine evidence with the introspection tools, on both tiers:
        Hub store (scene_inspect, scene_ls, event_ls, error_ls) and
        Display state (display_state_get)
    if rendering(pr): capture the pixels with lux display screenshot (or
        the display_screenshot MCP tool) and READ the PNG back: the leader
        confirms the widgets are drawn as the expected outcome says
    if interactive(pr): the operator drives the interaction and confirms
        its feel — the one thing a still frame cannot attest

    # D. SHIP
    mark the issue Done in Linear
    push; create the PR (description carries the verification playbook)
    if the PR changes a file that is not demo_exempt:
        comment "demo confirmed: <head sha> interaction: operator|none"
            # once step C passed on that head; the body pastes the make
            #   demo-class summary; "operator" only when interactive(pr) and
            #   the operator confirmed it
        # a later push that changes a non-exempt file repeats step C on the
        #   new head and posts a new "demo confirmed:" comment (demo_ok)
        # Qodo reviews once, on open (.pr_agent.toml); Bugbot reviews once,
        #   on its own, at open (Cursor dashboard: once per PR) — no
        #   "bugbot run" comment for round 1
    if the operator asked for Copilot: request one review, at open   # never
                                          #   by default, never on push
    schedule a background poll with /loop 3m  # never gh pr checks --watch,
                                              # never foreground sleep loops

# poll_tick, merge_gate, close_out, local_review, and every term they use
# (round, qodo_in, bugbot_in, pending, finding, answered, reviewed_head,
# delta_head, bugbot_open, escalation, ...) are specified once, in
# punt-kit/standards/pr-review.md, and model-checked in that repo's
# pr-review-model.tex / pr-review-model-bugbot.tex. Run them exactly as
# written there. This repo adds only the lux-specific deltas:
#   - required CI checks: lint, test, docs, integration, check-oo, check-coupling
#   - CI failure: gh run view --log-failed; fix in this PR
#   - local_review (pr-review.md) runs before the PR and before every fix push
#   - merge is explicit squash on a satisfied gate (ExitPR); never auto-merge
#   - close_out: branch delete in git.md §4 order, then the merge recap
#   - the demo gate is lux's form of pr-review.md's verification step
#     (verified_head / verified_ok); interaction feel is the human-judged part
#     lux names. Its terms are defined here, under lux's names:
#       interactive(pr) = the PR changes a file that reads input or decides
#                      what input does, as reported by make demo-class
#                      (tools/demo_class.py); the demo comment quotes its
#                      summary
#       rendering(pr) = the PR changes a file under src/punt_lux/display/,
#                      src/punt_lux/wire/model/elements/,
#                      src/punt_lux/wire/model/compositions/, or
#                      src/punt_lux/applets/ (which elements and layout are
#                      sent) — what the Display paints — as reported by
#                      make demo-class (tools/demo_class.py); the demo
#                      comment quotes its summary
#       demoed_head  = the commit named in the leader's latest
#                      "demo confirmed: <sha> interaction: operator|none" PR
#                      comment, newer than any "demo failed:" comment; posted
#                      once the demo passes on that commit: the leader drove
#                      the entry point and the introspection tools, read the
#                      screenshot back when rendering(pr), pasted the make
#                      demo-class summary, and the comment says
#                      "interaction: operator" only when the operator
#                      confirmed interaction feel on that commit
#       demo_exempt(f) = f is *.md, under docs/, tests/, or .github/ (except
#                      .github/workflows/), or a ratchet baseline or audit
#                      file; and is NOT under plugin/ — commands, skills,
#                      agents, and hooks there are behavior even when Markdown,
#                      because Claude Code executes them, and a workflow under
#                      .github/workflows/ is behavior that runs in CI
#       demo_confirmed(pr) = every file the PR changes is demo_exempt; or
#                      demoed_head exists and, when interactive(pr), its
#                      comment says "interaction: operator"
#       demo_ok(pr)  = every file the PR changes is demo_exempt, or
#                      demo_confirmed(pr) and demoed_head is the head or an
#                      ancestor of it and every file changed since it is
#                      demo_exempt
```

Entry and exit for one PR iteration. `merge_gate` in the pseudocode is the
pre-merge subset of these conditions; `ExitPR` describes the state after
close-out completes.

```text
EnterPR ≙ [ LoopState; unit : ℙ ISSUE |
  unit ⊆ claimed
  ∧ rollbackCoherent(unit)                -- reverts together sensibly
  ∧ inThroughputBand(unit)                -- above transaction cost,
                                          --   below reviewer degradation
  ∧ adrsConsulted(unit)                   -- the decision log was searched for
                                          --   the topic and the governing ADRs
                                          --   are cited
  ∧ (architectural(unit) ⇒ designRatified(unit)) ]  -- operator has ruled

ExitPR ≙ [ Δ LoopState; pr : PR |
  merged(pr)
  ∧ localReviewClean(pr)                  -- a local round that left nothing
                                          --   to fix, BEFORE the PR opened and
                                          --   before every fix push
  ∧ demoConfirmed(pr)                     -- vacuous when every changed file
                                          --   is demo_exempt; otherwise the
                                          --   demo passed BEFORE the PR opened
                                          --   and demoed_head is the head or
                                          --   an ancestor (demo_ok)
  ∧ ciGreen(head(pr))
  ∧ ¬ pending(pr)                         -- every requested review is in
  ∧ demoOk(pr)                            -- demo_ok held at the merge
  ∧ ¬ bugbotOpen(pr)                      -- no Bugbot run on any commit of
                                          --   the PR was open at merge
  ∧ bugbotRerunsPosted(pr)                -- each round with a failed run
                                          --   had its rerun(N)
  ∧ reviewedHead(pr) = head(pr)           -- merged code was reviewed, bot-
                                          --   authored PRs included
  ∧ (∀ f : findings(pr) • answered(f))    -- fixed on head, or reasoned
  ∧ round(pr) ≤ 2                         -- round 2 only after a High fix
  ∧ unresolvedThreads(pr) = ∅
  ∧ openEscalations(pr) = ∅               -- each closed by a recorded ruling
  ∧ issuesOf(pr) ⊆ closed′
  ∧ mergeRecapSent(pr) ]
```

### Local review before the PR

Full-diff local review is where issues die cheaply. A local round costs
seconds; a remote review cycle costs minutes to hours. `local_review`
(specified in punt-kit `standards/pr-review.md`)
runs `code-reviewer`, `silent-failure-hunter`, and `qodo review` on the unit's
first full diff and on every fix diff of 20 lines or more; a fix diff under 20
lines gets `qodo review` alone. `djb` joins any diff that touches credentials,
secrets, or caller text that reaches a file, a log line, or a header — in lux
that is `src/punt_lux/trust/`, the identity headers, and the cross-host
listener — whatever the diff's size. Local rounds repeat until a round leaves
nothing to fix: at most four fix rounds plus one review that verifies the last
fixes. Every fix diff goes through the same loop before it is pushed,
including fixes made for PR findings.

From the second round on, the review is scoped to what the diff changed:
regressions it introduces and Highs inside it. Without that boundary a
failure-focused reviewer walks outward into code the diff never touched and
the rounds do not converge. The three reviewers are not substitutes — in the
vox pilot each found defects the other two missed. `qodo review` is the
engine that later reviews the PR, so what it finds locally does not come back
as a PR round.

Every finding is fixed in this PR. A dismissal requires the exact finding, the
specific reason it does not apply, and the code reference. Opening a PR with
unresolved local findings is a procedural violation. Nothing is deferred to a
issue.

### Remote review: Qodo and Bugbot, at most two rounds

Remote review is automated-only and runs on already-clean code, so findings
should be few. The full specification is
[`punt-kit/standards/pr-review.md`](https://github.com/punt-labs/punt-kit/blob/main/standards/pr-review.md);
this section names what lux does with it.

Qodo is the primary remote reviewer (`.pr_agent.toml`). It reviews when the PR
opens and never on push. High findings post inline as threads, and the
`required_review_thread_resolution` ruleset rule makes each one block the
merge. Medium findings appear in the summary. Lows are dropped by
`comments_routing`. Bugbot reviews each PR once, on its own, when the PR opens
(Cursor dashboard setting); a push draws no Bugbot review. Its findings are
handled whenever they arrive.

Round 1 is the review at open. Round 2 — one `/agentic_review` plus one
`bugbot run` — happens only when round 1's fixes included a High, and it is
the last. A new High in round 2 goes to the operator.

Copilot is not a default reviewer. Repo rulesets carry no
`copilot_code_review` rule, so Copilot reviews only when requested: at most
one request per PR, at open, never on push. Its findings are findings like any
other.

This holds only when four settings are in place: `.pr_agent.toml` is on
`main` (Qodo reads it from the default branch); "Review every push" is
Disabled in the Qodo portal; Bugbot is set to review each PR once, at open;
and the ruleset has no `copilot_code_review` rule. If a push still starts a
Bugbot run, its findings are findings like any other.

### The demo gate

Run `make restart` from outside a Lux terminal: restarting `luxd-pty` ends
its sessions. For a demo that doesn't change PTY, use
`make reload && lux display restart` to keep those sessions open.

`make check` passing means the code compiles and the tests pass. It does not
mean the feature works. Before any PR opens, the feature is driven through
its real entry point — an MCP tool call, a CLI command, a click in the
running window — with the expected outcome written down first. Machine
evidence comes from the introspection tools on both tiers, because the Hub's
stored state and the Display's rendered state can diverge. When the change
touches what the Display paints (`rendering(pr)` above), the pixels are
evidence too: `lux display screenshot` (or the `display_screenshot` MCP tool)
writes the next painted frame to a PNG and the leader reads it back, checking
the widgets against the written expectation. A screenshot that disagrees with
the introspection snapshot is a defect, not noise.

The operator's judgement is reserved for what a still frame cannot show: the
feel of an interaction. When the change touches the code that decides what a
click, drag, key, focus change, or dialog does (`interactive(pr)` above), the
operator drives it and says whether it feels right, and the demo comment
records "interaction: operator"; otherwise no operator step exists and the
comment records "interaction: none". (The same principle in sibling repos:
vox's audio flights are confirmed by ear, step by step.) The demo is a demo,
not a diff, and the leader runs it end to end.

## Level 3 — The mission loop (design, code, test)

One iteration is one delegated mission: a single piece of design,
implementation, test, or review work executed by a specialist sub-agent under
an ethos mission contract. The next mission does not start until this loop
completes on the current one.

The mission loop is a do-while: the work runs at least once, and the
review-and-fix cycle repeats until a round comes back clean.

```text
function mission_loop(mission):
    contract = write_contract(mission)   # problem, invariants, quality bar —
                                         # never a write-set for design work
    dispatch(contract)                   # mission create + background spawn;
                                         # verify the worker is running
    do:
        worker designs / codes / tests   # tests lead; TDD for bug fixes
        worker commits locally           # each commit passes make check
        result   = worker submits
        findings = evaluator review      # distinct specialist
                 + leader verification   # run the change, review agents
                                         # on the mission diff
        if findings: reflect(findings)   # another round, same mission
    while findings remain
    close(mission)
```

Entry and exit for one mission iteration:

```text
EnterMission ≙ [ LoopState; m : MISSION |
  contracted(m)                           -- problem, invariants, quality bar
  ∧ workerRunning(m)                      -- dispatch is two operations; a
                                          --   contract alone is orphaned work
  ∧ activeWorkers = {workerOf(m)}         -- one worker at a time in a shared
                                          --   worktree
  ∧ (concurrencyClass(m) ⇒ modelChecked(m)) ]   -- z-spec before code

ExitMission ≙ [ Δ LoopState; m : MISSION |
  verdict(m) = accept                     -- from an evaluator ≠ worker
  ∧ findings(m) = ∅                       -- the do-while ran dry
  ∧ (∀ c : commitsOf(m) • checkGreen(c))  -- every commit passed make check
  ∧ testCount′ ≥ testCount                -- coverage never decreases
  ∧ missionClosed(m) ]
```

### Who does what

The leader runs the workflow; the specialists produce the work. The boundary
is strict in both directions.

**The leader owns the workflow.** The backlog, the mission contract,
dispatch, monitoring, the local review agents (they are the leader's tools,
run on each mission's diff and on the full diff), the demo, and every git and
GitHub operation: creating branches, pushing, opening the PR, driving remote
review, resolving threads, merging, and closing out. The leader does not
write production code.

**The worker owns the work.** The thinking and the code inside its mission —
the design decisions its contract leaves open, the tests, the
implementation, and local commits on the current branch. A worker never
creates branches, never pushes, never opens PRs, and never touches review
threads. Putting workflow operations into a worker's prompt is a contract
defect.

**The evaluator** — always a different specialist from the worker — reviews
the worker's result inside the mission before the leader accepts it.

**Remote review findings are the one delegation that is not a mission.**
When Qodo or Bugbot report on the PR, the leader reads each finding and
hands the mechanical fix to a bare agent, then pushes and resolves the thread
itself. The exception covers *mechanical* fixes only: a fix that changes a
design — new classes, moved responsibilities, a ratchet regression to resolve
— is a mission with an evaluator, whatever review raised it. A bare agent has
no evaluator, so nothing checks its work before its report reaches the
leader.

### The lifecycle

1. **Contract.** The leader writes the mission contract: the problem, the
   invariants, the quality bar, and the commit discipline — one commit per
   logical step, each passing `make check`, never more than thirty minutes of
   work uncommitted. A design mission's contract never prescribes a
   write-set; the specialist decides what to create, split, or extract. For
   protocol or data work the contract cites the OO rules with an example,
   because sub-agents revert to procedural habits when the prompt is not
   explicit. Every design contract lists the `DESIGN.md` entries that bound
   the work, and every design result states which ADRs it builds on or
   supersedes — a design that cites none on a topic the log covers is
   returned unread.

   Every implementation contract carries the **standing worker contract**
   below verbatim. The leader does not paraphrase it per round: rules
   rewritten from memory each time drift, and a worker reads a missing rule as
   permission.

   > **Goal.** Good SOLID object-oriented design, stated as responsibilities:
   > which object owns what, who depends on what. The OO and coupling ratchet
   > numbers are *signals* of that design, never targets. A change that moves
   > a number without improving responsibilities — a grab-bag class, a bundle
   > of collaborators handed out for callers to reach through, a second facade
   > forwarding to the first — is rejected even when the gate goes green.
   >
   > **Forbidden.** Writing `.oo-baseline.json`, `.oo-audit.jsonl`,
   > `.oo-coupling-baseline.json`, or `.oo-coupling-audit.jsonl` by any means
   > other than `make update-oo` / `make update-coupling`. Running
   > `--rebaseline-files` (a bless) at all — it is the leader's act alone,
   > under DES-096/097. Restoring any file from git (`git show REV:path >
   > path`, `checkout --`, `restore`, `reset`, `stash`), `rm`, `clean`, or
   > switching branches. Pushing, or touching a PR. Calling MCP tools.
   > Piping a gate through `head`, `tail`, or `grep`.
   >
   > **On any ratchet regression: stop.** Do not extract a class to move the
   > number, do not bless, do not commit. Report the design and the numbers
   > to the leader, who decides.
   >
   > **Evidence, not claims.** Run `make check` with output saved to a file
   > under `.tmp/`; cite the file and its final summary line. A commit is
   > made only after that file shows exit 0. The evaluator and the leader
   > re-run it; a report that disagrees with their run rejects the work.

   No contract sets a numeric target for a ratchet metric ("LCOM at or below
   X"). Stating the number as the goal is what produces the number-chasing
   the contract forbids.
2. **Dispatch is two operations.** Creating the mission writes the contract;
   a separate background agent spawn starts the worker. Verify the worker is
   actually running — a contract with no agent behind it is orphaned work.
3. **The worker executes.** Tests lead: a bug fix starts from a failing test
   that reproduces the defect, and the fix is done when it passes; a feature
   ships its tests with the code; coverage rises and the test count never
   goes down. Work in the concurrency or stateful-protocol class gets its
   z-spec model-check before implementation. Every commit passes
   `make check` — zero exceptions, zero suppressions.
4. **The leader monitors by the filesystem, never by git activity.** A
   worker editing files is working, even with zero commits — analysis and
   reading are invisible. Progress is judged by whether the working tree is
   changing and advancing. An empty commit log is never a reason to
   intervene, commit by proxy, or stop the agent. A genuine stall — no file
   changes over a long window and no response to a status message — is the
   only cause for taking over. Monitoring is silent: concrete facts or
   action, no narration of the wait.
5. **Result and evaluation.** The worker submits its result; the evaluator
   reviews it; reflect-and-advance rounds continue until the evaluator
   accepts.
6. **The leader verifies and closes.** Check the result against the
   contract: `make test` against the source, then `make restart` to install it,
   and exercise the installed change through its real entry point with expected output
   written first — one invalid input, one missing dependency, one boundary.
   Run the applicable local review agents on the mission diff and fix every
   finding; a dismissal requires the exact finding, the specific reason it
   does not apply, and the code reference. If the result raises a design
   question, it goes to the operator as a concrete decision — with a
   recommendation — before any dependent mission dispatches. Then close the
   mission.

   **Never accept a worker's report on its own word.** For every worker
   commit, the leader runs `make check` itself and audits the ratchet files
   against `main`:

   ```bash
   git diff main...HEAD -- .oo-audit.jsonl .oo-coupling-audit.jsonl
   git log -p main..HEAD -- .oo-audit.jsonl .oo-coupling-audit.jsonl
   git diff main...HEAD -- .oo-baseline.json .oo-coupling-baseline.json
   ```

   The commit is untampered only if all three hold:

   1. **Append-only.** The audit logs gain lines only at the end — no `-`
      line or changed line in any commit. A deleted or rewritten entry is a
      rewritten history.
   2. **Every appended line passed.** Each new audit line reads
      `"verdict":"pass"`, or `"verdict":"rebaseline-files"` for a leader's
      bless. A `"fail"` line means the ratchet failed and the commit landed
      anyway. A refused update writes a `"fail"` line with empty deltas. That
      line is acceptable in two cases only. First, a refusal of a touched
      file that a later `"rebaseline-files"` line in the same commit blesses.
      Second, a refusal of files the commit did not touch, whose regression
      is already on `main`, provided `make check` passes at that commit. The
      second case is debt, not a pass: the refused files are fixed in the
      same PR, so `main` stops writing such lines. Workers find regressions
      with `make check` and run the update targets only once it is clean or
      blessed.
   3. **Baselines match the audit.** Every metric that moved in a baseline
      file appears as a delta in an appended audit line (`deltas`, or
      `improved` for bulk-bless improvements). A baseline change no
      audit line accounts for was not written by the tool.

   Any failure rejects the commit: the worker's result is returned, not
   repaired by the leader, and the report is treated as untrustworthy.

## Invariants

1. **Linear is the single funnel.** Every piece of work is an issue before it
   is anything else; external queues (issues, alerts) drain into it at
   intake.
2. **A satisfied merge gate means merge now.** The gate is the only path to a
   merge, and nothing waits once it passes. Merge is always explicit — never
   auto-merge, never an admin override.
3. **Do or do not.** A finding is fixed in this PR or dismissed with a
   reason, the moment it arrives. It is never deferred to an issue or a
   follow-up PR. A thread is resolved only once it is answered per
   `answered(f)`, one by one, never in bulk.
4. **A push restarts CI, not review.** Local rounds run until clean (at most
   four fix rounds plus a verifying review) before the PR opens and before
   every fix push. PR rounds are at most two, and the second only after a
   High fix.
5. **Defects flow inward, scope flows outward.** A defect found while a PR is
   open is fixed in that PR. Only genuinely new lines of work become issues.
6. **The operator gates interaction feel and direction, never diffs,
   sequencing, or pixels.** The leader reads the screenshot back; the
   operator is called in only for an `interactive(pr)` change, and the demo
   comment records it.
7. **Close-out is inside the loop.** The recap email, branch hygiene, and
   starting the next unit are steps of the loop, not afterthoughts.
