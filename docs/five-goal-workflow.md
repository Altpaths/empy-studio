# The five product goals

Empy coordinates scoped changes in an isolated copy of an imported project.
Its project knowledge, tickets and verification evidence belong to the workspace.
Each newly extracted macOS installation starts with its own empty workspace.
Normal Finder launches open the project screen without restoring the last ticket.
User-imported projects persist within that installation for follow-up tickets.
Existing legacy workspaces are neither imported automatically nor deleted.
Explicit --workspace launches retain exact session resume; --clean starts a
separate empty trial on each launch. Guided planning always uses economy.

## Reuse without stale knowledge

The project index is local, deterministic work. Reusing an unchanged indexed
record avoids rebuilding its structural summary and repeating model analysis.
Content fingerprints must detect edits even if file size and modification time
are unchanged. This freshness check still reads local files; it is not a promise
that the filesystem will never be inspected again.

Only relevant bounded context is sent to a worker. A second ticket should use
the same project and workspace, rather than reimporting the project into a fresh
workspace. Changed code still needs fresh verification.

Failure memory extends this reuse boundary to confirmed failures. Planning, preflight, execution, and Verification failures are normalized into a project-scoped ledger. The same fingerprint is deduplicated across tickets and restarts, and only a bounded cause/action summary is shown. When the current target and project snapshot are unchanged, Empy blocks the duplicate provider run before it can spend tokens and tells the user what to correct. A changed target or corrective request creates a new opportunity to run. A ledger entry is resolved only by passing Verification with real evidence; a provider's claim of success is insufficient.

## Usage and specialist work

Each graph node has a role, owned paths, dependencies and a token ceiling.
Independent nodes may execute together; shared writes need explicit ownership.
The coordinator audits actual changes and runs verification before Review.
A first file edit alone does not prove a multi-step ticket has finished.

Local context estimates, planned ceilings and provider-reported usage are
different measurements. Cached input, fresh input and output must remain
distinguishable. Missing provider usage is unknown, not zero. Context reduction
in a provider-free benchmark does not establish a reduction in billed cost.

The Codex CLI guard is reactive: Empy stops when reported fresh usage exceeds
the allocated threshold. If the provider reports late or omits usage, this
cannot guarantee a hard billing cap. Workflow time limits and reservations
reduce repeated execution, but are not a provider-enforced spending limit.

The failure ledger is a local repetition guard, not a billing system. It removes
avoidable duplicate model calls and keeps prior causes available without sending
the old transcript back to the provider. It does not claim that provider usage
is zero or that a late usage report can be undone.

## Recovery and review

An automatic correction must stay within the original objective and owned
scope. Preserve useful scoped changes, record the failure and run verification
again after repair. The workflow needs attempt, elapsed-time and usage limits,
and must stop on cancellation, an external blocker or repeated lack of progress.
Restarting the application must not silently launch another paid provider run.

Review the verified changes before exporting. A rejected file can affect the
remaining result, so a passing verification of a different file set is not
sufficient evidence for the final delivery.

## DirectAdmin extraction

The project delivery is a change-only ZIP with paths relative to the imported
project root. It does not add a new project folder. If the ZIP contains
`public_html/index.php`, extract it in the parent of `public_html`. If the imported
root was already `public_html` and the ZIP contains `index.php`, extract it inside
that existing `public_html` directory. Inspect the manifest before extraction.

Verification concerns the baseline plus accepted changes, not an isolated delta
without its dependencies. Extraction alone cannot delete files, migrate a
database or change hosting configuration. Unsupported deletion is blocked;
do not present an ordinary ZIP extraction as a complete deployment of those
operations. Keep a hosting backup before replacing existing files.

## Evidence boundaries

The accompanying acceptance report records checks actually run for this
candidate. Unit tests and a deterministic fake-provider browser scenario check
local orchestration, recovery, persistence, review and archive behavior. They do
not certify live-provider cost, Apple signing/notarization, another CPU
architecture, or a live DirectAdmin deployment. Those require separate evidence.
