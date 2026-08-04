# Empy Studio Product Architecture Boundaries

## Status

Ticket 2 of `EMPY_PRODUCT_MASTER_PLAN.html`.

## Purpose

This document fixes the product boundaries before desktop implementation.

## Core

`empy_studio.core` contains provider-independent contracts and product rules.

Core may contain:

- project and task contracts;
- planner and orchestration rules;
- workspace interfaces;
- verification contracts;
- token-budget rules;
- driver protocols.

Core must not import:

- `empy_studio.desktop`;
- provider-specific drivers;
- desktop UI frameworks.

## Desktop

`empy_studio.desktop` is the product-facing application boundary.

Desktop may import Core contracts. Provider implementations must be supplied
through dependency injection. Desktop must not create hard dependencies on
Codex, Claude, Gemini, or another provider.

## Drivers

`empy_studio.drivers` contains provider-specific adapters.

Each driver implements the stable Core contract and owns:

- provider availability checks;
- command/API invocation;
- execution lifecycle;
- provider-specific error mapping;
- cancellation when supported.

Drivers must not own product workflow, workspace persistence, or desktop UI.

## Existing code

Ticket 2 does not move or rewrite the existing runtime modules. Existing modules
remain in place until a later roadmap ticket needs them. New product-facing work
must use these boundaries immediately.

## Enforcement

`empy_studio.architecture_guard` scans imports and blocks these violations:

1. Core importing Desktop.
2. Core importing Drivers.
3. Desktop importing a concrete provider driver.

## Definition of Done

- Core has no provider dependency.
- Desktop uses only internal application contracts.
- AI providers have one stable driver boundary.
- Automated tests enforce the boundary.
