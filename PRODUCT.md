# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

One operator: the project owner, working alone on a local machine. They run the translation queue, review each finished book, and approve it or send it back. No other audience is confirmed.

## Product Purpose

Scriptorium runs literary translation of English novels into Brazilian Portuguese through a local model, one book at a time, with automatic checks at each stage. The queue interface shows what is running and what waits for a human decision. Success means the operator always knows the real state of the queue and can act on a book without reading logs.

## Positioning

Not a general translation tool. Each book passes deterministic gates (EPUB validation, glossary coverage, forbidden renderings, language markers) before a human review, and the review is an explicit approval step.

## Operating Context

- Runs on one Windows 11 PC with a local GPU, Docker, and Ollama. Nothing is hosted.
- The queue runs in the background for hours. The operator checks it between other tasks, often after a long wait.
- Finished books are reviewed in the queue interface, then exported to Kindle.

## Capabilities and Constraints

- The interface is desktop only. No mobile layout is required.
- One book runs at a time. The interface must never suggest that two books are running in parallel.
- Every user-facing string is translatable. Each key exists in both `pt-BR` and `en`, and labels update when the language switches without a reload (see `CLAUDE.md`, frontend i18n rules).
- The stack already exists: Flask, Jinja templates, and vanilla JavaScript in `src/web/`. No framework change is planned.

## Product Principles

- Show the real state of the queue before any action. A paused, failed, or waiting book is never shown as running.
- One book at a time. Starting, pausing, and resuming are explicit operator actions.
- Approval is a deliberate decision. A review step is never completed as a side effect of another action.
