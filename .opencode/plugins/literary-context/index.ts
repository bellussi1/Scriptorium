import { Plugin } from "@opencode/plugin"
import { execFileSync } from "node:child_process"
import { readFileSync } from "node:fs"
import { join } from "node:path"

type Json = Record<string, unknown>

const BUDGETS = "data/budgets.json"
const LEDGER = "data/cost_ledger.jsonl"
const ACTIVE = "docs/ACTIVE_CONTEXT.md"
const QUEUE_DB = process.env.LITERARY_QUEUE_DB || "data/literary_queue.db"
const STATUS_SCHEMA = "literary-queue.status"
const STATUS_VERSION = "1.0"
const STATUS_TIMEOUT_MS = 5000

let lastStatus: Json | null = null
let lastStatusAt = 0

function readJson(root: string, relative: string): Json {
  try {
    return JSON.parse(readFileSync(join(root, relative), "utf8")) as Json
  } catch {
    return {}
  }
}

function readText(root: string, relative: string): string {
  try {
    return readFileSync(join(root, relative), "utf8")
  } catch {
    return ""
  }
}

function section(text: string, heading: string): string {
  const match = new RegExp(`^## ${heading}\\s*$`, "m").exec(text)
  if (!match) return ""
  const rest = text.slice(match.index + match[0].length).trimStart()
  const next = rest.search(/^## /m)
  return (next >= 0 ? rest.slice(0, next) : rest).trim()
}

function compact(value: string, limit = 320): string {
  const oneLine = value.replace(/\s+/g, " ").trim()
  return oneLine.length > limit ? oneLine.slice(0, limit - 1) + "…" : oneLine
}

function statusCommand(dbPath: string): string[] {
  return [
    "-m",
    "src.literary.cli",
    "queue",
    "status",
    "--json",
    "--db",
    dbPath,
  ]
}

function runtimeLine(snapshot: Json): string {
  const status = (snapshot.status || {}) as Json
  if (!snapshot.available) return String(snapshot.runtime || "status indisponível")
  if (!Boolean(status.running)) return "idle — no active book"
  const book = (status.book || {}) as Json
  const progress = (status.progress || {}) as Json
  const chunks = Number(progress.chunks || 0)
  const total = Number(progress.total || 0)
  const percent = Number(progress.percent || 0)
  const heartbeat =
    status.heartbeat_age_s !== null && status.heartbeat_age_s !== undefined
      ? ` · heartbeat ${String(status.heartbeat_age_s)}s`
      : ""
  const stale = Boolean(status.stale) ? " · stale" : ""
  const progressText = total
    ? ` ${chunks}/${total} (${percent}%)`
    : ""
  return `running — #${String(book.id)} ${String(book.title)} (${String(
    book.state,
  )})${progressText}${heartbeat}${stale}`
}

function nextLine(snapshot: Json): string {
  if (!snapshot.available) return "indisponível"
  const status = (snapshot.status || {}) as Json
  const next = (status.next_pending || null) as Json | null
  if (!next) return "none"
  const suffix = Boolean(status.running) ? " (after the running book)" : ""
  return `#${String(next.id)} ${String(next.title)}${suffix}`
}

function blockersLine(snapshot: Json): string {
  if (!snapshot.available) return "indisponível"
  const status = (snapshot.status || {}) as Json
  const blockers = Array.isArray(status.blockers) ? status.blockers : []
  if (!blockers.length) return "none"
  return blockers
    .map((raw) => {
      if (!raw || typeof raw !== "object") return String(raw)
      const item = raw as Json
      const kind = String(item.kind || "blocker")
      if (item.book_id !== undefined && item.book_id !== null) {
        return `${kind} #${String(item.book_id)} ${String(item.title || "")}`.trim()
      }
      if (item.age_s !== undefined && item.age_s !== null) {
        return `${kind} (${String(item.age_s)}s)`
      }
      return kind
    })
    .join("; ")
}

function dbLine(snapshot: Json): string {
  if (!snapshot.available) return "indisponível"
  const status = (snapshot.status || {}) as Json
  const db = (status.db || {}) as Json
  return `${String(db.integrity || "?")}/${String(db.journal_mode || "?")}`
}

function readStatus(root: string, dbPath: string = QUEUE_DB): Json {
  try {
    const output = execFileSync("python", statusCommand(dbPath), {
      cwd: root,
      encoding: "utf8",
      timeout: STATUS_TIMEOUT_MS,
      windowsHide: true,
      maxBuffer: 1_000_000,
    })
    const status = JSON.parse(output) as Json
    if (
      status.schema !== STATUS_SCHEMA ||
      status.schema_version !== STATUS_VERSION
    ) {
      throw new Error(
        `unexpected status schema ${String(status.schema)}/${String(
          status.schema_version,
        )}`,
      )
    }
    lastStatus = status
    lastStatusAt = Date.now()
    return {
      available: true,
      source: "python -m src.literary.cli queue status --json",
      db: dbPath,
      age_s: 0,
      status,
      runtime: runtimeLine({ available: true, status }),
      next: nextLine({ available: true, status }),
      blockers: blockersLine({ available: true, status }),
      db_line: dbLine({ available: true, status }),
      snapshot_at: String(status.snapshot_at || ""),
    }
  } catch (error) {
    const age = lastStatusAt
      ? Math.max(0, Math.round((Date.now() - lastStatusAt) / 1000))
      : null
    const ageText =
      age === null ? "sem dado anterior" : `último dado há ${age}s`
    const runtime = `status indisponível (${ageText})`
    return {
      available: false,
      source: "python -m src.literary.cli queue status --json",
      db: dbPath,
      age_s: age,
      error: String(error),
      runtime,
      next: "indisponível",
      blockers: "indisponível",
      db_line: "indisponível",
      snapshot_at: lastStatus ? String(lastStatus.snapshot_at || "") : "",
      last_status: lastStatus,
    }
  }
}

function contextBlock(root: string): string {
  const snapshot = readStatus(root)
  const active = readText(root, ACTIVE)
  const decision = compact(section(active, "Decision"))
  const budgets = budgetLines(root).join("; ")
  return [
    "<literary-context>",
    `Runtime: ${String(snapshot.runtime)}.`,
    `Next pending: ${String(snapshot.next)}.`,
    `Blockers: ${String(snapshot.blockers)}.`,
    snapshot.available
      ? `DB: ${String(snapshot.db_line)} · snapshot: ${String(snapshot.snapshot_at)}.`
      : `Status error: ${compact(String(snapshot.error || "unknown"), 160)}.`,
    decision ? `Decision: ${decision}` : "",
    budgets ? `Budgets: ${budgets}.` : "",
    "Rules: one book/one chunk, mode=next, review gate, no cloud run without an explicit cap.",
    "</literary-context>",
  ]
    .filter(Boolean)
    .join("\n")
}

function budgetLines(root: string): string[] {
  const budgets = readJson(root, BUDGETS)
  const totals = new Map<string, number>()
  const text = readText(root, LEDGER)
  for (const line of text.split(/\r?\n/)) {
    if (!line.trim()) continue
    try {
      const row = JSON.parse(line) as Json
      const provider = String(row.provider || "unknown")
      totals.set(provider, (totals.get(provider) || 0) + Number(row.cost_usd || 0))
    } catch {
      // Ignore malformed ledger lines.
    }
  }
  return Object.entries(budgets).map(([provider, raw]) => {
    const budget = raw as Json
    const spent = totals.get(provider) || 0
    const currency = String(budget.currency || "USD")
    if (currency === "BRL") {
      const cap = Number(budget.cap || 0)
      const capUsd = Number(budget.cap_usd || 0)
      return `${provider}: cap R$ ${cap.toFixed(2)} (~US$ ${capUsd.toFixed(2)}); ledger total US$ ${spent.toFixed(2)} historical`
    }
    const balance = Number(budget.balance || 0)
    return `${provider}: available US$ ${balance.toFixed(2)}; ledger total US$ ${spent.toFixed(2)} historical`
  })
}

export default Plugin.define({
  id: "literary-context",
  async setup(ctx) {
    const root = ctx.location.directory

    await ctx.session.hook("context", (event) => {
      event.system.push({ type: "text", text: contextBlock(root) })
    })

    await ctx.tool.transform((editor) => {
      editor.add({
        name: "literary_status",
        description:
          "Return the canonical read-only queue status from `queue status --json`: running, book, job, progress, next pending, blockers, heartbeat, stale and DB. Optional `db` is a diagnostic override; the default is the live queue DB.",
        input: {
          type: "object",
          properties: {
            db: {
              type: "string",
              description: "Optional queue DB path for a diagnostic run.",
            },
          },
          additionalProperties: false,
        },
        execute: async (args) => {
          const requested =
            args && typeof args.db === "string" && args.db.trim()
              ? args.db.trim()
              : QUEUE_DB
          const snapshot = readStatus(root, requested)
          return {
            content: [
              { type: "text", text: JSON.stringify(snapshot, null, 2) },
            ],
          }
        },
      })

      editor.add({
        name: "literary_cost",
        description:
          "Return local cloud spend from data/cost_ledger.jsonl against the limits in data/budgets.json.",
        input: { type: "object", properties: {}, additionalProperties: false },
        execute: async () => {
          const budgets = readJson(root, BUDGETS)
          const totals = new Map<string, number>()
          const byModel = new Map<string, number>()
          const text = readText(root, LEDGER)
          for (const line of text.split(/\r?\n/)) {
            if (!line.trim()) continue
            try {
              const row = JSON.parse(line) as Json
              const provider = String(row.provider || "unknown")
              const model = String(row.model || "unknown")
              const cost = Number(row.cost_usd || 0)
              totals.set(provider, (totals.get(provider) || 0) + cost)
              byModel.set(model, (byModel.get(model) || 0) + cost)
            } catch {
              // Ignore malformed ledger lines.
            }
          }
          return {
            content: [
              {
                type: "text",
                text: JSON.stringify(
                  {
                    budgets,
                    spent_by_provider: Object.fromEntries(totals),
                    spent_by_model: Object.fromEntries(byModel),
                    ledger: LEDGER,
                  },
                  null,
                  2,
                ),
              },
            ],
          }
        },
      })
    })
  },
})
