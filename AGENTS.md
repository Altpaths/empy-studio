# Empy Studio Agent Contract

Read `EMPY.md` before acting.

## Required workflow

For a new project:

```text
Intake → Project Vault → Discovery → Audit → Requirement
→ targeted benchmark when needed
→ visual gate when needed
→ implementation
→ verification
→ synchronization
→ complete release
→ validated learning
```

For an existing Project Vault:

```text
Request → impact and scope → task graph → execution
→ verification → synchronization → release → learning
```

## Context budget

The primary agent may read the project identity, architecture map, active request, locked decisions, relevant contracts, and handoffs.

Worker agents receive only:

- their exact task;
- relevant files;
- read/write boundaries;
- acceptance criteria;
- dependency handoffs.

Do not send the complete chat history or repository to every worker.

## File ownership

Each file has one write owner per execution wave. Shared files are handled sequentially or by the Release Integrator.

## Approval

Present one complete bounded plan. After approval, continue all in-scope work without repeated confirmation.

Stop only for:

- missing secrets or credentials;
- destructive data changes;
- architecture or public-contract changes;
- critical security risk;
- unresolved file conflict;
- work outside the approved scope.

## Evidence

Mark statements as `FACT`, `INFERENCE`, `UNKNOWN`, or `BLOCKED`.

Never claim that a test passed unless it actually ran.

## Delivery

Default delivery is one complete synchronized project with:

- version;
- change log;
- tests run;
- tests not run;
- pending external checks;
- remaining risks;
- release artifact and checksum.
