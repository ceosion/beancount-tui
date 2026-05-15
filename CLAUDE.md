# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

This repository is freshly initialized — no commits, no source files, no build config. The sections below are stubs based only on the repo name. Once an initial scaffold is committed, re-run `/init` to replace this file with a real command + architecture summary.

## Intended project

A terminal user interface (TUI) for [Beancount](https://beancount.github.io/), the plain-text double-entry accounting system. The exact scope (read-only ledger browser vs. full editor, query/reporting features, etc.) has not been decided yet — confirm with the user before assuming.

## Commands

Not yet defined. The language, runtime, and toolchain have not been chosen, so there are no build, lint, test, or run commands to document. Add them here once the scaffold lands.

## Architecture

No architecture exists yet. Once code is present, this section should describe:

- How the TUI layer is structured (framework, screen/component model, event loop).
- How Beancount data is loaded and queried (direct use of the `beancount` Python library vs. shelling out to `bean-query` vs. a custom parser).
- The boundary between read-only views and any mutating operations on the ledger file.
