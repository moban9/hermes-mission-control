# The Mission Control dashboard

![Mission Control dashboard](dashboard.png)

One page that answers three questions in two seconds: **is anything on fire, is
anything waiting on me, is spend on track.** The UI is the fixed Appendix A
prototype; the data is real (see the README for the two data paths).

## Panels, top to bottom

### KPI row
Five cards across the top.
- **Active subagents** — working now / total (e.g. 2/17).
- **Tasks completed** — from the kanban board.
- **Success rate** — completed vs failed.
- **Tokens per second** — live throughput.
- **Spend today** — today's cost against the daily budget ($10). Turns from green
  to red when it is near or over.

### Agent network
The SVG map: **Hermes** in the centre, the 17 subagents on an orbit. Each node is
coloured by state and shows the agent's name + task progress %. Links to working
agents animate (a dashed flow toward the node); idle/offline agents are still. This
is the fastest "who is doing what right now" read.

### Task pipeline
Four count tiles (Queued / Running / Done / Failed) and a per-agent list of the
current task: the task id, the title, the agent badge, and a progress bar.

### Subagents
One card per agent: a left accent bar in the state colour, the name + state badge,
the role, a one-line "now" (the current action), a progress bar, and a footer with
the task id, token count, and a **Pause / Resume** button. Pausing an agent is an
operator action and takes effect immediately.

### Live event stream
The filtered log of what is happening, newest at the bottom: timestamp, agent,
message. Filter chips (All / Info / Warn / Error). Warn rows amber, error rows red.
Capped at 80 rows; auto-scrolls unless you have scrolled up.

### Throughput
A sparkline of tokens per second over time, plus average latency, context window
used, spend today, and budget left.

### Tool calls
A bar per tool over the last 5 minutes — which tools the fleet is leaning on
(`terminal`, `read_file`, `write_file`, `patch`, …).

### Alerts
Derived alarms: `stuck_agent` (no progress for 90 s while engaged),
`agent_offline` (owns a running task but silent > 30 s), `error_burst` (3+ task
failures in 5 min), `budget_risk` (today's cost over the budget). Each row shows a
severity dot, the message, the agent + time, and a **Dismiss** button. When empty it
reads "No alerts. All agents look healthy."

### Approval queue
Risky actions that are **blocked** waiting for a human. Each row: a risk dot (green
low / amber medium / red high), a plain sentence ("Runner wants to deploy build
2.4.1 to production"), the risk + time, and **Deny / Approve**. The agent shows as
`waiting` while a request is pending. Requests also go out to **Discord** so you can
act from a phone. With no source pending it shows an honest empty state.

How it works: a tool call fires Hermes' `pre_tool_call` hook; if the tool is on the
approval list the agent is blocked and a row appears here; Approve lets the tool run,
Deny stops it. This is a real block, not a flag.

### Context and memory
Per-agent chips select an agent. Shows the context window: the share used, a stacked
bar (system / task / tool results / history / memory), and the token counts. Below
that, the agent's **remembered facts**, read from its real memory file. A **Compact
context** button trims an agent's history.

### Cost forecast
A cost line with a dashed projection to end of day and a dashed red budget line.
Below: burn rate per hour, projected spend by end of day, and the daily budget. The
badge reads "On track" or "Over budget risk".

### Replay
A heat strip of every agent's state over time, with a slider to scrub back. Chips
show each agent's state, task, and progress at the selected moment, plus a summary
line (done, spend, tokens/s, pending approvals). A "Viewing history" banner appears
while scrubbing; **Back to live** returns.

## States and signals
- **Connection badge:** `Live` (stream open), `Reconnecting` (amber, with the age of
  the last event).
- **Loading:** skeleton blocks in the panel shapes.
- **Empty:** a friendly sentence per panel ("No pending requests…"),
  never fake data.
- **No active run:** a full-page empty state.
- **Stale:** if the stream drops, numbers grey out and show "Last update N s ago".

## What is real vs estimated
- **Real:** agents, sessions, tasks, event stream, tool calls, throughput, cost,
  alerts, replay, the memory facts, usage tokens, tool durations.
- **Estimated (labelled):** per-task progress %, and the context *split* — the hooks
  give the total and the counts, not the per-section breakdown. No number is
  invented to look precise.

## Design rules (binding)
Dark + light themes from the token table, the six state colours (running cyan,
thinking violet, waiting amber, error red, paused grey, offline grey), motion only
for live data, `prefers-reduced-motion` respected, mobile-first responsive layout,
keyboard reachable, WCAG AA contrast. The `?demo=1` query runs the original
simulation for design work only.
