import { Plugin } from "@opencode/plugin"
import { execFileSync } from "node:child_process"
import { existsSync, readFileSync, statSync } from "node:fs"
import { join } from "node:path"

type Json = Record<string, unknown>

const BUDGETS = "data/budgets.json"
const LEDGER = "data/cost_ledger.jsonl"
const ACTIVE = "docs/ACTIVE_CONTEXT.md"
const AGENT = "data/literary_queue.agent.json"
const RUNNER = "data/literary_queue.runner.json"
const AUTO = "data/literary_queue.auto.json"
const HEALTH = "data/literary_queue.health.json"
const CONTROL = "data/literary_queue.control.json"

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

function slug(value: string): string {
  return (
    value
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "book"
  )
}

function tailLines(root: string, relative: string, limit = 12): string[] {
  const text = readText(root, relative)
  if (!text) return []
  return text
    .split(/\r?\n/)
    .filter((line) => line.trim())
    .slice(-limit)
    .map((line) => compact(line, 400))
}

function currentLogPath(root: string): string {
  const health = readJson(root, HEALTH)
  const auto = readJson(root, AUTO)
  const title = String(health.title || auto.title || "").trim()
  if (!title) return ""
  const candidate = `data/queue-runs/${slug(title)}.log`
  return existsSync(join(root, candidate)) ? candidate : ""
}

function cacheKey(root: string): string {
  return [ACTIVE, BUDGETS, LEDGER, AUTO, HEALTH, CONTROL]
    .map((relative) => {
      const path = join(root, relative)
      return existsSync(path) ? String(statSync(path).mtimeMs) : "0"
    })
    .join(":")
}

function statusLine(root: string): string {
  const auto = readJson(root, AUTO)
  const health = readJson(root, HEALTH)
  const agent = readJson(root, AGENT)
  const runner = readJson(root, RUNNER)

  const state = String(health.state || "")
  const active = ["preparing", "translating", "reviewing", "validating"].includes(state)
  const title = String(health.title || auto.title || "").trim()
  const progress =
    health.checkpoint_count != null && health.total_chunks != null
      ? `${String(health.checkpoint_count)}/${String(health.total_chunks)}`
      : ""
  const eta = health.eta_human ? `, ETA ${String(health.eta_human)}` : ""
  const healthFresh =
    Boolean(health.timestamp) && Date.now() - Date.parse(String(health.timestamp)) < 120_000
  const autoFresh =
    Boolean(auto.heartbeat) && Date.now() - Date.parse(String(auto.heartbeat)) < 300_000
  const supervisor = auto.phase
    ? `supervisor ${autoFresh ? "" : "stale "}${String(auto.phase)}${
        auto.title ? ` (${String(auto.title)})` : ""
      }`
    : ""

  if (active) {
    const runnerLine = `runner ${state}${title ? ` ${title}` : ""}${progress ? ` ${progress}` : ""}${eta}`
    return `${supervisor ? supervisor + "; " : ""}${runnerLine}${healthFresh ? "" : " (health stale)"}`
  }
  if (title) {
    return `${supervisor ? supervisor + "; " : ""}runner idle, last ${title}${
      healthFresh ? "" : " (health stale)"
    }`
  }
  if (supervisor) return `${supervisor}; runner idle`

  const online = agent.heartbeat
    ? Date.now() - Date.parse(String(agent.heartbeat)) < 120_000
    : Boolean(agent.online)
  const running = Boolean(runner.running)
  return `agent ${online ? "online" : "offline"}, ${running ? "runner active" : "runner idle"}`
}

function nextLine(root: string): string {
  try {
    const output = execFileSync(
      "python",
      ["-m", "src.literary.cli", "queue", "next"],
      { cwd: root, encoding: "utf8", timeout: 15_000 },
    )
    const book = JSON.parse(output) as Json
    if (!book || !book.id) return "no pending book"
    return `#${book.id} ${book.title} (${book.provider}/${book.model})`
  } catch {
    return "unavailable"
  }
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
    const note = String(budget.note || "")
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
    let cachedKey = ""
    let cachedBlock = ""
    let cachedAt = 0

    await ctx.session.hook("context", (event) => {
      const key = cacheKey(root)
      const now = Date.now()
      if (!cachedBlock || key !== cachedKey || now - cachedAt > 30_000) {
        const active = readText(root, ACTIVE)
        const decision = compact(section(active, "Decision"))
        const next = compact(section(active, "Next decision"))
        const budgets = budgetLines(root).join("; ")
        cachedBlock = [
          "<literary-context>",
          `Runtime: ${statusLine(root)}.`,
          `Next pending: ${nextLine(root)} (after the active book).`,
          decision ? `Decision: ${decision}` : "",
          next ? `Next: ${next}` : "",
          budgets ? `Budgets: ${budgets}.` : "",
          "Rules: one book/one chunk, mode=next, review gate, no cloud run without an explicit cap.",
          "</literary-context>",
        ]
          .filter(Boolean)
          .join("\n")
        cachedKey = key
        cachedAt = now
      }
      event.system.push({ type: "text", text: cachedBlock })
    })

    await ctx.tool.transform((editor) => {
      editor.add({
        name: "literary_status",
        description:
          "Return the live TraducaoLLM queue state: watchdog health, supervisor phase, current book, next pending book and the current queue-run log tail.",
        input: { type: "object", properties: {}, additionalProperties: false },
        execute: async () => {
          const health = readJson(root, HEALTH)
          const auto = readJson(root, AUTO)
          const control = readJson(root, CONTROL)
          const agent = readJson(root, AGENT)
          const runner = readJson(root, RUNNER)
          const current = {
            book_id: health.book_id ?? auto.book_id ?? null,
            title: health.title ?? auto.title ?? null,
            state: health.state ?? auto.phase ?? null,
            checkpoint_count: health.checkpoint_count ?? null,
            total_chunks: health.total_chunks ?? null,
            eta_human: health.eta_human ?? null,
            process_alive: health.process_alive ?? null,
            stalled: health.stalled ?? null,
            last_checkpoint_age_seconds: health.last_checkpoint_age_seconds ?? null,
            supervisor_phase: auto.phase ?? null,
            supervisor_message: auto.message ?? null,
          }
          const logPath = currentLogPath(root)
          const payload = {
            current,
            supervisor: auto,
            health,
            control,
            next: nextLine(root),
            log_path: logPath,
            log_tail: logPath ? tailLines(root, logPath, 12) : [],
            legacy: { agent, runner },
          }
          return {
            content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
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
