# LogGuard Frontend — Claude Code Build Prompt

Paste this prompt into Claude Code at the start of your frontend session. It contains the complete design system, every page specification, every state, and all the integration details you need.

---

## Context

You are building the frontend for **LogGuard**, an AI-powered log anomaly detection system. The backend is already running at `http://localhost:8000` (FastAPI + WebSocket). The frontend is a single-page React app served at `http://localhost:5173`.

This is the user's solo academic project (Phase 1 Review 3 evaluation). They are doing both the backend and frontend. Your job is to build a polished, production-grade dashboard that makes the project look impressive in a live demo.

The backend exposes a documented REST + WebSocket API at `http://localhost:8000`. The OpenAPI spec is at `http://localhost:8000/openapi.json`. Generate the typed client from that — never hand-write request types.

---

## Stack — locked

- **React 18** + **Vite** + **TypeScript**
- **TailwindCSS** (with custom theme — see Design Tokens below)
- **shadcn/ui** for primitives (Button, Card, Dialog, Table, Badge, Tabs, Tooltip, Sheet)
- **Recharts** for charts (stacked bars, donuts, line)
- **react-router-dom** v6 for routing
- **@tanstack/react-query** for server state
- **date-fns** for time formatting
- **lucide-react** for icons
- **openapi-typescript** to generate the API client from `openapi.json`

Install these in the order above. Don't add other dependencies without asking.

---

## Design system — the absolute rules

### Brand identity

The product is called **LogGuard**. Subtitle: "AI-powered log anomaly detection."

The logo is a **hexagon mark** with internal lines (variant A — the energetic one). Inline SVG, never an image file:

```tsx
// src/components/Logo.tsx
export function Logo({ size = 24 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-label="LogGuard">
      <path d="M16 4 L26 10 L26 22 L16 28 L6 22 L6 10 Z"
            fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M16 4 L16 16 L26 22"
            fill="none" stroke="currentColor" strokeWidth="1.5" opacity="0.5" />
      <path d="M16 16 L6 22 M16 16 L26 10 M16 16 L16 28"
            fill="none" stroke="currentColor" strokeWidth="1" opacity="0.3" />
      <circle cx="16" cy="16" r="2" fill="var(--anomaly)" />
    </svg>
  );
}
```

The hexagon stroke uses `currentColor` so it inherits the text color (iris purple in normal use). The center dot is always the coral anomaly accent.

### Color tokens

These are the **only** colors in the product. Define them as CSS variables in `src/index.css`. Tailwind picks them up via the theme config.

```css
:root {
  /* Brand */
  --iris: #a78bfa;
  --iris-deep: #7c3aed;
  --anomaly: #fb7185;
  --anomaly-deep: #be123c;

  /* Severity (dark mode) */
  --severity-critical: #fb7185;
  --severity-warning: #fbbf24;
  --severity-info: #67e8f9;
  --severity-success: #34d399;

  /* Surfaces — dark mode (default) */
  --bg-page: #0a0a0a;
  --bg-sidebar: #050505;
  --bg-card: #16161a;
  --bg-hover: #1f1f23;
  --border-subtle: #1f1f1f;
  --border-default: #2a2a2e;

  /* Text — dark mode */
  --text-primary: #ffffff;
  --text-secondary: #c0c0c8;
  --text-tertiary: #7a7a85;
  --text-muted: #555;
}

[data-theme="light"] {
  /* Brand stays similar but slightly deeper for contrast */
  --iris: #7c3aed;
  --iris-deep: #5b21b6;
  --anomaly: #be123c;
  --anomaly-deep: #9f1239;

  /* Severity (light mode) */
  --severity-critical: #be123c;
  --severity-warning: #d97706;
  --severity-info: #0891b2;
  --severity-success: #059669;

  /* Surfaces — light mode */
  --bg-page: #fafaf7;
  --bg-sidebar: #f5f5f0;
  --bg-card: #ffffff;
  --bg-hover: #f0eee5;
  --border-subtle: #e8e6dd;
  --border-default: #d8d6cd;

  /* Text — light mode */
  --text-primary: #1a1a1a;
  --text-secondary: #444444;
  --text-tertiary: #888780;
  --text-muted: #aaaaaa;
}
```

**Tailwind config** (`tailwind.config.ts`):

```ts
export default {
  darkMode: ['class', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        iris: 'var(--iris)',
        'iris-deep': 'var(--iris-deep)',
        anomaly: 'var(--anomaly)',
        'anomaly-deep': 'var(--anomaly-deep)',
        critical: 'var(--severity-critical)',
        warning: 'var(--severity-warning)',
        info: 'var(--severity-info)',
        success: 'var(--severity-success)',
        page: 'var(--bg-page)',
        sidebar: 'var(--bg-sidebar)',
        card: 'var(--bg-card)',
        hover: 'var(--bg-hover)',
        'border-subtle': 'var(--border-subtle)',
        'border-default': 'var(--border-default)',
      },
      textColor: {
        primary: 'var(--text-primary)',
        secondary: 'var(--text-secondary)',
        tertiary: 'var(--text-tertiary)',
        muted: 'var(--text-muted)',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        display: ['Inter Display', 'Inter', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
    },
  },
};
```

**Severity color rule:** Critical = coral, Warning = amber, Info = cyan. **Never use red/orange/blue.** This is the unique part of the product's visual language. Apply this everywhere a severity appears: KPI numbers, badges, table rows, timeline bar stacks, drift gauge zones.

### Typography

- **Inter** for all body and UI text (`font-sans`)
- **Inter Display** for headings and large KPI numbers (`font-display`)
- **JetBrains Mono** for any technical data: anomaly IDs, scores, timestamps, log lines, template strings, hostnames (`font-mono`)

Load all three from Google Fonts in `index.html`.

**Weights: only 400 and 500.** Never 600 or 700 — they look heavy.

**Sizes:**
- Page title: 22px / 500 / -0.01em letter-spacing
- Section heading: 13px / 500 + uppercase eyebrow label 11px / tracking-wider
- KPI big number: 32px / 500 / -0.02em
- Body: 13–14px / 400 / 1.6 line-height
- Small / metadata: 11–12px / 400
- **Sentence case everywhere.** Never Title Case. Eyebrow labels are the only exception (they're uppercase with letter-spacing).

### Spacing & layout

- **Sidebar:** fixed 220px wide on the left, full height
- **Page padding:** 22px top, 26px sides
- **Section spacing:** 28px between major sections
- **Card padding:** 22px
- **Border radius:** 8px on most things, 10px on cards, 999px on pills/badges
- **Borders:** `0.5px solid var(--border-subtle)` — thin, never 1px+
- **Hairline dividers between KPIs:** 0.5px vertical lines, no card walls

### Visual rules — enforce these everywhere

1. **No card walls between KPIs.** Use thin vertical dividers (`w-px bg-border-subtle`). Cards only wrap discrete objects.
2. **Eyebrow labels** introduce every section: small (11px), uppercase, tracking-wider, text-tertiary, with 14px margin below.
3. **Hairline horizontal dividers** between feed items (`border-t-[0.5px] border-border-subtle`). No row backgrounds.
4. **No gradients, drop shadows, blurs, glows.** Flat surfaces only.
5. **Mono font for ALL numbers in data context** — scores, IDs, timestamps, percentages. Never sans for these.
6. **Tabular numerics** on any column of numbers: `font-variant-numeric: tabular-nums`.
7. **Rounded pills only for severity badges and counts.** Everything else is `rounded-md` or `rounded-lg`.
8. **Empty states never use a spinner — use a skeleton or a real empty message.**
9. **Active nav item** has `bg-card` background; inactive items are transparent.
10. **Severity color only appears on the severity-bearing element** (the score number, the badge, the left rail strip on a feed row). Don't tint entire rows.

---

## Folder structure

```
frontend/
├── public/
│   └── favicon.svg          # the hexagon mark
├── src/
│   ├── api/
│   │   ├── client.ts         # fetch wrapper using generated types
│   │   ├── generated.ts      # from `npx openapi-typescript ...`
│   │   ├── mock.ts           # canned data for dev
│   │   ├── queries.ts        # react-query hooks
│   │   └── websocket.ts      # WebSocket connection hook
│   ├── components/
│   │   ├── Logo.tsx
│   │   ├── Sidebar.tsx
│   │   ├── Layout.tsx        # shell with sidebar + main
│   │   ├── ThemeToggle.tsx
│   │   ├── SeverityBadge.tsx
│   │   ├── SeverityPill.tsx
│   │   ├── KpiBar.tsx        # horizontal KPIs with hairline dividers
│   │   ├── KpiCell.tsx       # one KPI: eyebrow + big number + sub-label
│   │   ├── TimelineChart.tsx
│   │   ├── SeverityDonut.tsx
│   │   ├── AnomalyFeedRow.tsx
│   │   ├── AnomalyTable.tsx
│   │   ├── AttentionLines.tsx
│   │   ├── ScorePanel.tsx
│   │   ├── ExplanationCard.tsx
│   │   ├── DriftGauge.tsx
│   │   ├── ServiceCard.tsx
│   │   ├── EyebrowLabel.tsx
│   │   ├── Skeleton.tsx
│   │   ├── EmptyState.tsx
│   │   ├── ErrorState.tsx
│   │   ├── Toast.tsx
│   │   └── ui/               # shadcn components
│   ├── hooks/
│   │   ├── useTheme.ts
│   │   ├── useLiveAnomalies.ts
│   │   ├── useToast.ts
│   │   └── useReducedMotion.ts
│   ├── pages/
│   │   ├── Dashboard.tsx     # /
│   │   ├── AnomalyList.tsx   # /anomalies
│   │   ├── AnomalyDetail.tsx # /anomalies/:id
│   │   ├── System.tsx        # /system
│   │   ├── Feedback.tsx      # /feedback
│   │   ├── Training.tsx      # /training
│   │   ├── Incidents.tsx     # /incidents
│   │   └── Settings.tsx      # /settings
│   ├── lib/
│   │   ├── format.ts         # formatRelativeTime, formatScore, formatNumber
│   │   ├── severity.ts       # severityToColor, severityToLabel
│   │   └── cn.ts             # className merge helper
│   ├── types.ts              # re-exports from generated.ts
│   ├── App.tsx               # router
│   ├── main.tsx
│   └── index.css             # tokens + tailwind base
├── tailwind.config.ts
├── vite.config.ts
├── tsconfig.json
└── package.json
```

**Naming:** `PascalCase.tsx` for components and pages; `camelCase.ts` for hooks and utils.

---

## Routes

```tsx
// src/App.tsx
<Routes>
  <Route element={<Layout />}>
    <Route path="/" element={<Dashboard />} />
    <Route path="/anomalies" element={<AnomalyList />} />
    <Route path="/anomalies/:id" element={<AnomalyDetail />} />
    <Route path="/system" element={<System />} />
    <Route path="/feedback" element={<Feedback />} />
    <Route path="/training" element={<Training />} />
    <Route path="/incidents" element={<Incidents />} />
    <Route path="/settings" element={<Settings />} />
  </Route>
</Routes>
```

---

## Sidebar

Fixed 220px wide. Logo at top, nav links in the middle, live status pill at the bottom.

Each nav link:
- 8px padding vertical, 10px horizontal
- 14px lucide icon + 12px label
- Active: `bg-card` background, `text-primary`, iris-colored icon
- Inactive: transparent background, `text-secondary`, gray icon
- Hover: `bg-hover`

If a route has live counts (e.g. critical anomalies on `/anomalies`), show a small pill on the right of that row:
```tsx
<span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-anomaly/10 text-anomaly">3</span>
```

Nav items in order:
1. Dashboard (LayoutDashboard icon)
2. Anomalies (AlignLeft icon) — with critical count badge if > 0
3. System (Activity icon)
4. Feedback (MessageSquare icon)
5. Training (Cpu icon)
6. Incidents (FileText icon)
7. Settings (Settings icon)

Bottom of sidebar:
- Hairline divider above
- Live status pill: small green dot + "connected" + "12/s" event rate
- The dot should pulse subtly via CSS animation when the WebSocket is alive
- If the WebSocket is disconnected: red dot + "reconnecting…"

Theme toggle button in the bottom-right of the sidebar (sun/moon icon).

---

## API integration

### Generate the typed client first

After creating the project skeleton, run:

```bash
npx openapi-typescript http://localhost:8000/openapi.json -o src/api/generated.ts
```

Add a `generate-types` script to `package.json` so this is repeatable.

### Anomaly object shape

This is the canonical object the backend returns everywhere:

```ts
type Severity = 'critical' | 'warning' | 'info';
type ExplanationStatus = 'pending' | 'ready' | 'failed';

interface Anomaly {
  id: string;                            // anom_<iso>_<4hex>
  detected_at: string;                   // ISO 8601 UTC
  severity: Severity;
  source: string;                        // hostname
  ensemble_score: number;                // 0..1
  confidence: number;                    // 0..1
  failure_probability: number;           // 0..1
  predicted_failure_window_min: number | null;
  log_template: string;                  // Drain3 template
  sequence_preview: string[];            // 20 lines
  top_contributing_lines: { line: string; attention: number }[];
  explanation_status: ExplanationStatus;
  cluster_id: string;
  cluster_size: number;
}
```

Use the generated types from `openapi.json` — this shape is the reference.

### Endpoints

```ts
GET    /api/v1/health
GET    /api/v1/anomalies?limit=&since=&severity=&cursor=
GET    /api/v1/anomalies/{id}
GET    /api/v1/anomalies/{id}/explanation
GET    /api/v1/metrics/summary
GET    /api/v1/metrics/timeline?window=1h|24h|7d
GET    /api/v1/system/drift
POST   /api/v1/anomalies/{id}/feedback   { feedback: 'true_positive' | 'false_positive' }
WS     /api/v1/ws/anomalies               // server pushes Anomaly objects
```

### react-query hooks

Define one hook per endpoint in `src/api/queries.ts`:

```ts
export const useAnomalies = (params: ListParams) =>
  useQuery({ queryKey: ['anomalies', params], queryFn: () => api.listAnomalies(params) });

export const useAnomaly = (id: string) =>
  useQuery({ queryKey: ['anomaly', id], queryFn: () => api.getAnomaly(id) });

export const useExplanation = (id: string) =>
  useQuery({
    queryKey: ['explanation', id],
    queryFn: () => api.getExplanation(id),
    refetchInterval: (data) => data?.status === 'pending' ? 2000 : false,
  });

export const useMetricsSummary = () =>
  useQuery({ queryKey: ['summary'], queryFn: api.getMetricsSummary, refetchInterval: 5000 });

// ...etc
```

### WebSocket

`useLiveAnomalies` connects to `ws://localhost:8000/api/v1/ws/anomalies` and:
- Reconnects with exponential backoff on disconnect (1s, 2s, 4s, 8s, max 30s)
- Exposes `connectionStatus: 'connecting' | 'connected' | 'disconnected'`
- Exposes `eventRate: number` (rolling 10-second average events/sec)
- On each `{ type: 'anomaly', data: Anomaly }`: invalidates the `['anomalies']` query, prepends to a local in-memory feed (capped at 50), shows a toast if `severity === 'critical'`
- On each `{ type: 'explanation_ready', data: { anomaly_id } }`: invalidates `['explanation', anomaly_id]`

### Mock layer

Build `src/api/mock.ts` with 15 hardcoded Anomaly objects covering all severities and states. A `VITE_USE_MOCK=true` env var swaps the real client for the mock. The user will build pages against this first, then flip the flag once the backend is ready. Keep the mock in sync with the real shape — type errors should catch any drift.

---

## Page specifications

For every page below, include these states:

- **Loading:** skeleton placeholders matching the final layout. Never spinners.
- **Empty:** specific message (e.g. "No anomalies in the last hour — system is healthy"). Use the EmptyState component.
- **Error:** error message + "Retry" button. Use the ErrorState component.

### Page 1 — Dashboard (`/`)

Header strip:
- Eyebrow label: "Anomaly intelligence"
- Page title: "Live dashboard"
- Right side: "Updated Xs ago · ● Live" (live indicator green when connected)
- Hairline divider below

KPI bar (KpiBar component, four cells separated by hairline vertical dividers):
1. **Past 24 hours** — `total_24h` big number, "↑ 12" trend below in success color, "total anomalies" label
2. **Critical** — `critical_24h` big number in `critical` color, "X unack" sub-label
3. **Confidence** — `avg_confidence` (mono font), "model average" sub-label
4. **Drift** — `drift_score` (mono font, success color if < 0.25, warning if < 0.4, critical if ≥ 0.4), "healthy" / "drifting" / "retrain needed" sub-label

Activity over time:
- Section header: "Activity over time" + window toggle (1h / 24h / 7d) on the right
- Recharts stacked bar chart, full width
- Stack order: critical (top) → warning → info (bottom)
- Bar width: ~14px with 4px gap
- Y-axis hidden, X-axis hidden (clean editorial look)
- Hover tooltip: shows time bucket + per-severity counts

Recent activity:
- Section header: "Recent activity" + "view all →" link to `/anomalies`
- 5 most recent anomalies, each in an AnomalyFeedRow:
  - Left: 3px-wide × 32px-tall colored rail (severity color)
  - Middle: log template (truncated, 13px), source + relative time + cluster size in mono 11px tertiary text
  - Right: ensemble_score in severity color, mono, tabular-nums
- Hairline divider between rows
- Whole row clickable, navigates to `/anomalies/:id`

### Page 2 — Anomaly list (`/anomalies`)

Header:
- Eyebrow: "All anomalies"
- Title: "Anomaly history"

Filter bar (above table):
- Severity multi-select (chips: critical / warning / info, click to toggle)
- Source dropdown (deduped from results)
- Time range picker (last hour / 24h / 7d / custom)
- Search input (filters on `log_template` substring, client-side on current page)
- Cluster collapse toggle (default on — collapses cluster_size > 1 into one row)

Table (AnomalyTable):
- Columns: Time, Severity, Source, Template (truncated), Confidence, Cluster size, ⋯
- Time column: relative time + absolute on hover
- Severity column: SeverityPill component
- Source: mono font
- Template: ellipsis at column width
- Confidence and Cluster size: mono, tabular-nums, right-aligned
- Each row clickable, navigates to detail
- Cluster rows show "View N grouped" expand button
- Server-side pagination via `next_cursor` — load more button at bottom, not infinite scroll
- Sticky header that stays put on scroll

### Page 3 — Anomaly detail (`/anomalies/:id`)

Breadcrumb: "Anomalies / anom_…" (mono font for the ID)

Header:
- Severity badge + "Detected X ago" + "N grouped" metadata row
- Page title: derived from the anomaly's log template (humanised, max ~50 chars)
- Mono source name below
- Right side: two outline buttons — "true positive" (success colored check) and "false positive" (anomaly colored x)
- Buttons POST to `/api/v1/anomalies/{id}/feedback`, show loading spinner inline, success toast on completion
- Hairline divider below

ScorePanel (KpiBar reused, four cells):
1. **Ensemble score** — mono, big
2. **Confidence** — mono, big
3. **Failure probability** — mono, big
4. **Predicted in** — mono, big, anomaly color (critical-tinted), shows "12m" or "—" if null

ExplanationCard:
- Section heading: small hexagon icon (iris colored) + "Root cause analysis" + "LLaMA 3 · N incidents retrieved" in tertiary text
- If `explanation_status === 'pending'`: skeleton placeholder + "LLaMA is analysing this anomaly…"
- If `'ready'`: render `root_cause` as 14px paragraph, then a tertiary eyebrow label "Recommended fix" then `recommended_fix` as a numbered ordered list (13px, 1.8 line-height)
- If `'failed'`: error state inline
- Inline mono code spans for any `<code>` tags or things that look like config keys

AttentionLines:
- Section heading: "Top contributing log lines" + "attention weighted" in tertiary
- For each item in `top_contributing_lines`:
  - Mono font, 11px
  - Background: `rgba(251, 113, 133, attention)` — i.e. coral with attention as alpha (hottest line is most opaque)
  - Each row: log line on the left, attention score on the right (mono, tabular)
  - Padding 9px 14px, border-radius 4px, 4px margin between rows
- For accessibility, also output the score in tertiary text — color isn't enough.

Sequence preview (collapsible, default closed):
- Heading: "Full sequence (20 events)"
- Click to expand
- Pre-formatted block of all 20 lines from `sequence_preview`, mono font, line-numbered
- High-attention lines from `top_contributing_lines` are highlighted in the same coral-shaded style

### Page 4 — System (`/system`)

Header:
- Eyebrow: "Model & infrastructure"
- Title: "System health"
- Right: "Updated just now"
- Hairline divider

Drift status card (full-width):
- Big mono number (drift_score) with severity color (success / warning / critical based on thresholds)
- Status pill next to it: "Healthy" / "Drifting" / "Retrain needed"
- Sub-text: "PSI between training and live embeddings. Last retrain X ago on Y dataset."
- On the right: a horizontal gauge SVG showing the value's position in the 0..1 range with green / amber / coral zones at 0–0.25 / 0.25–0.4 / 0.4–1.0

Services grid (2 columns):
- Each service in a card: name (left), green dot + status (right), mono technical detail line below
- Services: FastAPI backend, RAG worker, Redis streams, Ollama / LLaMA 3, Postgres
- Status: online / degraded / offline (success / warning / critical colors)

Active models table (no card wrapper, just a card-styled list):
- For each model (Transformer, AutoEncoder, Confidence MLP):
  - Left: model name (white, 13/500) + filename and config in mono tertiary
  - Right: F1, Precision, Recall — three mono numbers with tiny uppercase eyebrow labels above each
- Hairline divider between rows

### Page 5 — Feedback (`/feedback`)

Header:
- Eyebrow: "Engineer feedback"
- Title: "Feedback history"

Stats strip (small KpiBar):
- Total feedback count
- True positives count (success color)
- False positives count (anomaly color)
- TP rate (mono percentage)

Table:
- Columns: Time, Anomaly, Severity, Verdict, Reviewer
- Verdict column: `true_positive` (green check + "true") or `false_positive` (coral x + "false")
- Click row → navigate to `/anomalies/:id`

### Page 6 — Training (`/training`)

Header:
- Eyebrow: "Model training"
- Title: "Training runs"

A timeline / list of training runs:
- Each run in a card: date, dataset (HDFS / BGL), F1 / precision / recall (mono), duration, "completed" pill
- Latest run is highlighted (`bg-card` with iris-colored left rail)
- Click to expand and show full hyperparameters + per-epoch loss chart (Recharts line)

### Page 7 — Incidents (`/incidents`)

The seeded FAISS-indexed past incidents (from `incidents.jsonl`). Demonstrates the RAG retrieval source.

Header:
- Eyebrow: "Incident knowledge base"
- Title: "Indexed incidents"
- Sub-line: "X incidents available for retrieval"

Search bar (filter by template substring).

Card grid (2 columns):
- Each incident: incident ID (mono), template (mono), root cause text (sans, 13px), recommended fix (small text)
- Resolved date in mono tertiary

### Page 8 — Settings (`/settings`)

Tabs: General, Alerting, Data sources

**General tab:**
- Theme toggle (light / dark / system)
- Reduced motion preference
- Default time range for anomaly list

**Alerting tab:**
- For each channel (PagerDuty, Slack, email):
  - Toggle switch for enabled
  - Severity threshold (critical only / warning + critical / all)
  - Webhook URL or recipient field (masked, "••••••••" until shown)
  - Test button

**Data sources tab:**
- Read-only display of configured log sources (read from `/api/v1/system/drift` or a similar endpoint extended to expose this)

---

## Components — implementation notes

### KpiBar (used on Dashboard, Anomaly Detail, Feedback)

```tsx
<div className="flex gap-7 mb-7">
  <KpiCell ... />
  <div className="w-px bg-border-subtle" />
  <KpiCell ... />
  <div className="w-px bg-border-subtle" />
  ...
</div>
```

### KpiCell

```tsx
<div className="flex-1">
  <EyebrowLabel>Past 24 hours</EyebrowLabel>
  <div className="flex items-baseline gap-2.5">
    <span className="font-display text-[32px] font-medium tracking-[-0.02em]">142</span>
    <span className="text-xs text-success">↑ 12</span>
  </div>
  <div className="text-[11px] text-tertiary mt-1">total anomalies</div>
</div>
```

### EyebrowLabel

```tsx
<div className="text-[11px] text-tertiary uppercase tracking-[0.08em] mb-3">
  {children}
</div>
```

### SeverityPill

Compact pill for inline use. Background is severity color at 12% alpha, text is severity color full strength.

```tsx
<span className={cn(
  "inline-flex items-center px-3 py-1 rounded-md text-[11px] font-medium tracking-wider uppercase",
  severity === 'critical' && "bg-critical/10 text-critical",
  severity === 'warning' && "bg-warning/10 text-warning",
  severity === 'info' && "bg-info/10 text-info"
)}>
  {severity}
</span>
```

### TimelineChart (Recharts)

```tsx
<BarChart data={buckets}>
  <Bar dataKey="info" stackId="a" fill="var(--severity-info)" radius={[1,1,0,0]} />
  <Bar dataKey="warning" stackId="a" fill="var(--severity-warning)" radius={[1,1,0,0]} />
  <Bar dataKey="critical" stackId="a" fill="var(--severity-critical)" radius={[1,1,0,0]} />
  <Tooltip ... />
</BarChart>
```

X and Y axes hidden. Tooltip has dark card background, mono font for numbers.

### AttentionLines

The opacity scaling is **linear** in `attention` value, not square root. The user wants the dramatic effect. Test colors look right when the highest attention is around 0.31 (so max alpha will be around 0.55–0.6).

```tsx
{lines.map(({ line, attention }) => (
  <div
    style={{ background: `rgba(251, 113, 133, ${Math.min(attention * 1.8, 0.6)})` }}
    className="font-mono text-[11px] px-3.5 py-2 rounded mb-1 flex justify-between"
  >
    <span>{line}</span>
    <span className="opacity-80 tabular-nums">{attention.toFixed(2)}</span>
  </div>
))}
```

### Toast

Bottom-right, slides in from the right, auto-dismisses after 5 seconds. Stack vertically if multiple. Critical toasts have an anomaly-colored left rail.

### Skeleton

Pulses subtly between `bg-card` and `bg-hover`. Match the shape of what's loading — a KPI skeleton has a small rectangle for the eyebrow, a tall rectangle for the number, a small rectangle for the sub-label.

---

## Live elements (the "alive" feel)

These are non-negotiable polish items:

1. **Pulsing dot** on the sidebar's "connected" status — CSS keyframe animation, 2-second pulse cycle
2. **New anomaly fade-in** — when a new anomaly arrives via WebSocket, it slides into the top of the feed with a 300ms fade + 8px slide-down animation
3. **KPI tick animation** — when `total_24h` increments via a poll/refresh, briefly flash the number iris color (200ms transition) so the user notices
4. **Critical toast** — bottom-right toast with hexagon icon + "Critical anomaly: <template>" + 5-second auto-dismiss + dismiss button

**Reduced motion:** all four respect `prefers-reduced-motion` via the `useReducedMotion` hook. If reduced motion is on, no animations — items just appear.

---

## Theme toggle

Bottom of sidebar, sun/moon icon. On click:
1. Toggles `data-theme="dark"` ↔ `data-theme="light"` on `<html>`
2. Persists choice to `localStorage` under `loguard-theme`
3. On first load, reads `localStorage`; if missing, defaults to dark
4. CSS variables handle the rest — no component-level branching needed

---

## What "done" looks like

When the user runs `npm run dev`:

1. Dashboard loads at `/`, sidebar shows on the left, theme toggle works
2. KPI cards show real data from `/api/v1/metrics/summary`
3. Timeline chart shows real data, window toggle changes the data
4. Live anomaly feed connects to the WebSocket and shows the green pulsing dot
5. Clicking an anomaly navigates to `/anomalies/:id`, which shows score panel + LLaMA explanation + attention heatmap
6. The explanation status correctly flips from skeleton to ready when the RAG worker finishes
7. Marking true/false positive POSTs back and shows a success toast
8. Critical anomaly arrives → bottom-right toast appears
9. All 8 routes navigate cleanly, every page has loading + empty + error states
10. Both light and dark themes look polished, the toggle persists across reloads
11. No console errors or warnings
12. `npm run build` produces a clean production bundle

---

## Build order — strict

Don't skip ahead. Each step depends on the previous.

1. **Skeleton:** Vite + React + TS + Tailwind + the design tokens in `index.css`. `npm run dev` works, page is blank but fonts load and the dark page-bg is visible.
2. **Layout shell:** Sidebar component + Layout wrapper + theme toggle + light/dark working. Empty pages for all 8 routes.
3. **Mock API + types:** generate types from `openapi.json` if backend exists, else use the inline types from this prompt. Build `src/api/mock.ts` with 15 anomalies. `VITE_USE_MOCK=true` flag.
4. **Dashboard:** KpiBar + TimelineChart + Recent activity feed. All against mock.
5. **Anomaly Detail:** ScorePanel + ExplanationCard + AttentionLines. Most important page — spend time on attention heatmap polish.
6. **Anomaly List:** Table + filters + cluster collapse.
7. **System:** Drift gauge + service cards + models table.
8. **Other pages:** Feedback, Training, Incidents, Settings. These are simpler.
9. **WebSocket:** real connection, reconnect logic, toast on critical.
10. **Polish:** all loading skeletons, empty states, error states. Reduced-motion handling. Final pass on spacing.
11. **Switch to real API:** flip `VITE_USE_MOCK=false`. Fix anything that breaks.

---

## Don'ts — repeating because they matter

- Don't invent endpoints. If you need data the backend doesn't expose, ask the user — don't fake it server-side.
- Don't reshape the anomaly object on the frontend. Use it as-is.
- Don't store anomalies in localStorage. Backend owns the state.
- Don't use red/orange/blue for severity. Coral / amber / cyan only.
- Don't use 600 or 700 font weights. 400 and 500 only.
- Don't use Title Case in UI labels. Sentence case only.
- Don't use spinners as loading state. Skeletons or empty messages.
- Don't add decorative gradients or shadows. Flat surfaces, hairline borders, color via the severity ramp.
- Don't put cards inside cards (no nested boxes). Editorial layout uses dividers.
- Don't deviate from the spacing scale (gap-7 / 28px between sections, gap-2.5 / 10px inside cells, etc.).

---

## Final note

When in doubt, the source of truth is:
1. The Pydantic schemas auto-generated from the backend (`openapi.json`) — for data shape
2. This prompt — for visual / interaction decisions
3. The user — for anything not covered here

Default to asking before adding a dependency, changing a contract, or making a visual decision that conflicts with this prompt.

Build it.
