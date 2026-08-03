# Empy Studio Operating Principles

Empy Studio exists to make AI-assisted software development easier, cheaper, safer, and more repeatable.

It is not a replacement for a coding agent. It gives coding agents a small, durable operating context so that projects do not restart from zero, unrelated files are not changed, and completed work returns as one synchronized release.

## Core rules

1. **Reduce context before adding intelligence**  
   Agents receive only the project map, active request, relevant files, contracts, and prior handoffs.

2. **Product outcome before code volume**  
   A task is successful only when it improves the intended product outcome.

3. **One project baseline**  
   The Project Vault is the source of truth for the current codebase, decisions, active work, and releases.

4. **One write owner per file per execution wave**  
   Parallel work must not create hidden conflicts.

5. **One approval for one bounded scope**  
   After the complete plan is approved, in-scope tasks continue without repetitive confirmations.

6. **Visual work requires a visual gate**  
   Significant interface work must lock direction, hierarchy, typography, palette, and main flows before production coding.

7. **Claims require evidence**  
   A test is marked passed only when it actually ran. Environment-dependent checks remain pending.

8. **Deliver a synchronized project**  
   The default output is a complete release, not scattered patches.

9. **Learn only from validated outcomes**  
   Project-specific preferences stay in the project. Reusable patterns require evidence.

10. **Stay lightweight**  
    A feature belongs in the core only when it reduces token use, repeated work, risk, or delivery friction across projects.

## Non-goals

Empy Studio does not:

- provide its own language model;
- hide destructive changes;
- claim fully autonomous production deployment;
- replace human product judgment;
- require a specific coding-agent provider.
