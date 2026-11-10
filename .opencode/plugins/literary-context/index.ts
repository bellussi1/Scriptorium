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

function cacheKey(root: string): string {
  return [ACTIVE, BUDGETS, LEDGER]
    .map((relative) => {
      const path = join(root, relative)
      return existsSync(path) ? String(statSync(path).mtimeMs) : "0"
    })
    .join(":")
}

function statusLine(root: string): string {
  const agent = readJson(root, AGENT)
  const runner = readJson(root, RUNNER)
  const online = agent.heartbeat
    ? Date.now() - Date.parse(String(agent.heartbeat)) < 120_000
    : Boolean(agent.online)
  const running = Boolean(runner.running)
  const title = running ? `, ${String(runner.title || "book")} active` : ", runner idle"
  return `agent ${online ? "online" : "offline"}, ${running ? "runner active" : "runner idle"}${title}`
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
          `Queue next: ${nextLine(root)}.`,
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
          "Return the live TraducaoLLM queue state: agent heartbeat, runner, next pending book and recent queue-run log lines.",
        input: { type: "object", properties: {}, additionalProperties: false },
        execute: async () => {
          const agent = readJson(root, AGENT)
          const runner = readJson(root, RUNNER)
          const payload = {
            agent,
            runner,
            next: nextLine(root),
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
