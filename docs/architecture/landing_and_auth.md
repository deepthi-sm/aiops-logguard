# LogGuard — Landing Page, Auth, and Firebase Build Prompt

Master prompt for Claude Code to build the marketing landing page, authentication flow, Firebase integration, and severity color update — all at once. This document is the single source of truth for these features.

---

## Context

You are building three connected things on top of the existing LogGuard frontend (which already has 8 dashboard pages, a sidebar, and the design system from `docs/architecture/frontend_design.md`):

1. **A marketing landing page** at `/` (public, scrollable, with subtle scroll-triggered animations)
2. **Auth pages** — sign-up at `/signup` and sign-in at `/login`
3. **Real Firebase Authentication** wiring the auth pages to actual user accounts
4. **A severity color update** across the entire existing codebase

The user has already created the Firebase project and enabled email/password authentication. They will provide the `firebaseConfig` values via `.env`. Your job is to wire up the SDK and protect routes.

Build all four pieces at once. Don't pause for incremental checkpoints — but do confirm at the end that everything compiles and builds cleanly.

---

## Stack additions

Add these to the existing frontend:

- **firebase** (latest v10+) — for Authentication
- **framer-motion** — for scroll-triggered animations
- **react-intersection-observer** — for triggering animations when sections enter the viewport
- **react-countup** — for the count-up number animations on the Results section
- **react-router-dom** — already installed, but you'll be adding new routes and a protected-route wrapper

Install all at once:

```bash
npm install firebase framer-motion react-intersection-observer react-countup
```

---

## Part 1 — Severity color update (do this FIRST, it touches existing code)

The current severity ramp (coral / amber / cyan) is being replaced. Specifically:

| Severity | Old (dark mode) | New (dark mode) | Old (light mode) | New (light mode) |
|---|---|---|---|---|
| Critical | `#fb7185` coral | `#fb7185` coral (unchanged) | `#be123c` rose | `#be123c` rose (unchanged) |
| Warning | `#fbbf24` amber | `#fdba74` peach | `#d97706` deep amber | `#d97706` deep amber (unchanged) |
| Info | `#67e8f9` cyan | `#93c5fd` sky | `#0891b2` cyan | `#0891b2` cyan (unchanged) |

**Critical stays the same. Warning becomes peach. Info becomes sky.** Light mode keeps its existing palette since those darker shades already work.

### What to change

Open `src/index.css` (or wherever the design tokens live) and update only the severity tokens for dark mode:

```css
:root {
  /* ...existing brand colors stay... */
  --severity-critical: #fb7185;  /* unchanged */
  --severity-warning: #fdba74;   /* was #fbbf24 — peach now */
  --severity-info: #93c5fd;      /* was #67e8f9 — sky now */
  --severity-success: #34d399;   /* unchanged */
}
```

Light mode block stays untouched (the existing values were already strong).

### What you do NOT need to change

If the codebase uses Tailwind classes that point at the CSS variables (`bg-warning`, `text-info`, etc.), they automatically pick up the new values. **Do not search-and-replace component code.** Just update the tokens.

If any component has a hardcoded hex value like `#fbbf24` or `#67e8f9`, update it to use the token (`var(--severity-warning)`) instead. Search for those two specific hex strings to find any leaks.

### Verification

After the change, the dashboard, anomaly detail page, timeline chart, drift gauge, and severity pills should all show peach (warning) and sky (info) in dark mode. Spot-check the timeline chart specifically — that's where the colors are most visible.

---

## Part 2 — Firebase setup

### Step 2.1 — Environment variables

Create a `.env` file in `/frontend` (gitignored) with:

```
VITE_FIREBASE_API_KEY=...
VITE_FIREBASE_AUTH_DOMAIN=...
VITE_FIREBASE_PROJECT_ID=...
VITE_FIREBASE_STORAGE_BUCKET=...
VITE_FIREBASE_MESSAGING_SENDER_ID=...
VITE_FIREBASE_APP_ID=...
```

Also create `.env.example` (committed) with the same keys but empty values, so future devs know what's needed.

Add `.env` to `.gitignore` if not already there. Do NOT commit actual Firebase values.

### Step 2.2 — Firebase initialization

Create `src/lib/firebase.ts`:

```ts
import { initializeApp } from 'firebase/app';
import { getAuth } from 'firebase/auth';

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
};

const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);
```

### Step 2.3 — Auth context and hooks

Create `src/contexts/AuthContext.tsx` that exposes:
- `user` — the current Firebase user, or null
- `loading` — true while initial auth state is being determined
- `signUp(email, password, displayName)` — creates account, sets display name, returns the user
- `signIn(email, password)` — signs in, returns the user
- `signOut()` — signs out
- `error` — last auth error, or null

Use `onAuthStateChanged` to keep `user` in sync. Wrap `<App />` in `<AuthProvider />` in `main.tsx`.

Create a `useAuth()` hook in `src/hooks/useAuth.ts` that consumes the context.

### Step 2.4 — Protected routes

Create `src/components/ProtectedRoute.tsx`:

- If `loading` is true, show a centered spinner with the hexagon logo
- If `user` is null, redirect to `/login` with the attempted path stored in state so post-login can redirect back
- Otherwise, render the children

Apply this wrapper to all dashboard routes. Public routes (`/`, `/login`, `/signup`) do not get the wrapper.

### Step 2.5 — Public-only routes

Create `src/components/PublicOnlyRoute.tsx`:

- If user is signed in, redirect to `/dashboard`
- Otherwise, render the children

Apply this to `/login` and `/signup` so signed-in users don't see the auth pages.

### Step 2.6 — Updated routing

Update `src/App.tsx`:

```
Routes:
/                 → Landing (public)
/login            → Login (PublicOnlyRoute)
/signup           → Signup (PublicOnlyRoute)
/dashboard        → Dashboard (ProtectedRoute) — was at "/" before
/anomalies        → AnomalyList (ProtectedRoute)
/anomalies/:id    → AnomalyDetail (ProtectedRoute)
/feedback         → Feedback (ProtectedRoute)
/settings         → Settings (ProtectedRoute)
/admin/system     → System (ProtectedRoute)
/admin/training   → Training (ProtectedRoute)
/admin/incidents  → Incidents (ProtectedRoute)
```

Note: the dashboard's old path `/` becomes `/dashboard`. Update any internal links (sidebar nav, breadcrumbs, "view all" buttons) that pointed to `/` to now point to `/dashboard`.

The Layout component (with the sidebar) wraps all `ProtectedRoute` children. The Landing, Login, and Signup pages do NOT use the Layout — they're standalone full-page designs.

---

## Part 3 — Auth pages

Both pages share the same two-pane structure: marketing copy on the left, form on the right.

### File structure

```
src/pages/
├── Landing.tsx
├── Login.tsx
└── Signup.tsx

src/components/auth/
├── AuthLayout.tsx       # the two-pane shell
├── AuthLeftPane.tsx     # the marketing copy + stats
├── SignupForm.tsx
├── LoginForm.tsx
└── BrandStats.tsx       # the three stat numbers at the bottom
```

### AuthLayout shell

Two-column grid, full viewport height, hairline divider between panes:

```
┌─────────────────────┬─────────────────────┐
│                     │                     │
│   AuthLeftPane      │   children (form)   │
│   (marketing copy)  │                     │
│                     │                     │
└─────────────────────┴─────────────────────┘
```

Background: `var(--bg-page)`. The divider is `0.5px solid var(--border-subtle)`.

Padding inside each pane: `60px 56px`.

### AuthLeftPane content (shared by both /login and /signup)

Top: hexagon logo (24px) + "LogGuard" wordmark, sentence-case.

Middle (vertically centered):
- Eyebrow: "Anomaly intelligence" (uppercase, tertiary, tracking-wider)
- Headline (Inter Display, 36px, font-weight 500, letter-spacing -0.02em, line-height 1.2):
  ```
  AI that finds
  what your alerts miss.
  ```
- Subhead (14px, secondary text, line-height 1.6, max-width 380px):
  > Real-time log anomaly detection with explainable AI. Catches the failures threshold-based monitoring can't, and tells you why in plain English.

Bottom (BrandStats component, separated by a hairline divider above):
Three columns separated by thin vertical dividers. Each column:
- Big number in iris purple, mono font, 24px, font-weight 500, letter-spacing -0.02em
- Tiny label below in tertiary text, 11px

Stats:
1. `0.91` — F1 on held-out test
2. `12 min` — avg early warning
3. `100%` — on-prem, no cloud

Footer of left pane: small mono-font text in muted color: `© 2026 · Privacy-first AIOps`

### SignupForm

Centered max-width 360px in the right pane.

Top:
- Eyebrow "Get started"
- Heading "Create your account" (24px, font-weight 500)
- Sub-line: "Already have one? **Sign in**" (Sign in is iris colored, navigates to `/login`)

Form fields, each with an uppercase eyebrow label above:
1. Full name — text input, placeholder "Deepthi"
2. Email — email input, placeholder "you@company.com"
3. Password — password input, placeholder "••••••••", with a small helper text "Minimum 8 characters" below

Submit button: full-width, iris background, dark text, "Create account", `border-radius: 8px`, `padding: 12px 16px`

Below the button, small centered text: "By creating an account, you agree to the **terms of service** and **privacy policy**." (links iris colored — they can be `<a href="#">` placeholders for now).

### Form behavior

On submit:
1. Validate name is non-empty, email format is valid, password ≥ 8 chars
2. Show a small inline error if validation fails
3. Disable the button and show a loading state while signing up
4. Call `signUp(email, password, displayName)` from the auth context
5. On success: redirect to `/dashboard`
6. On Firebase error (`auth/email-already-in-use`, `auth/invalid-email`, `auth/weak-password`): show a toast or inline error with a friendly message, NOT the raw Firebase error string

Error message mapping:
- `auth/email-already-in-use` → "An account with this email already exists. Try signing in instead."
- `auth/invalid-email` → "That doesn't look like a valid email address."
- `auth/weak-password` → "Password must be at least 8 characters."
- Anything else → "Couldn't create your account. Please try again."

### LoginForm

Same shell as SignupForm with these differences:

Top:
- Eyebrow "Welcome back"
- Heading "Sign in"
- Sub-line: "No account? **Create one**" (links to `/signup`)

Form fields:
1. Email
2. Password — with a "Forgot password?" link in iris purple aligned to the right of the password label (placeholder for now — clicking it can show a "Coming soon" toast)

Submit button: full-width, iris background, "Sign in"

No terms/privacy text (login isn't a new agreement).

### LoginForm behavior

On submit:
1. Validate email format and password is non-empty
2. Call `signIn(email, password)`
3. On success: redirect to `/dashboard` (or to the path stored in route state if user was redirected here from a protected route)
4. On Firebase error: friendly mapping
   - `auth/invalid-credential` or `auth/wrong-password` or `auth/user-not-found` → "That email and password don't match. Try again or create an account."
   - `auth/too-many-requests` → "Too many attempts. Try again in a few minutes."
   - Anything else → "Couldn't sign you in. Please try again."

### Auth pages styling

Match the existing dashboard's design system:
- Inputs: `bg-card`, `border-subtle`, `border-radius: 6px`, padding `10px 14px`, `font-size: 13px`, focus state shows `border-iris` (no glow, no outline, just border color change)
- Eyebrow labels: `text-tertiary`, uppercase, tracking-wider, `font-size: 11px`, margin-bottom 8px
- Buttons: rounded-lg, font-weight 500, hover state slightly darkens iris color (use `--iris-deep` on hover)
- All sentence case (no Title Case anywhere)

---

## Part 4 — Landing page (`/`)

The marketing page. Public, no auth required. Scroll-triggered animations throughout. Six sections plus a sticky header.

### File structure

```
src/pages/Landing.tsx       # composes all sections
src/components/landing/
├── LandingHeader.tsx       # sticky nav with scroll-spy
├── HeroSection.tsx
├── ProblemSection.tsx
├── HowItWorksSection.tsx
├── FeaturesSection.tsx
├── ResultsSection.tsx
├── CtaSection.tsx
└── LandingFooter.tsx
```

### Animation philosophy

Tasteful, restrained, noticeable but not flashy. Specifically:

- Each section fades and slides in as it enters the viewport
- Direction alternates per section: hero fades up on initial load (no scroll), problem slides in from left, how-it-works from right, features from left, results from right, CTA fades up
- Slide distance is 30px (small), duration 600ms, ease-out cubic
- Each section animates ONCE — when re-entering viewport it stays in place (use `triggerOnce: true` from react-intersection-observer)
- Within a section, sub-elements (cards, list items) stagger in by 80ms each — gives a satisfying cascade
- All animations respect `prefers-reduced-motion: reduce` — when set, sections appear instantly without movement
- The Results section's count-up numbers animate from 0 to final value over 1500ms, slight 100ms stagger between numbers
- The sticky header has `backdrop-filter: blur(8px)` with translucent background

### LandingHeader (sticky)

Pinned to top, full width, padding `16px 56px`, background `rgba(10,10,10,0.85)` with `backdrop-filter: blur(8px)`, hairline border-bottom.

Layout: 3 columns, justify-between

**Left:** logo (22px hexagon) + "LogGuard" wordmark — clicking scrolls to top

**Center:** nav links — "Overview · Problem · How it works · Features · Results"
- Each link is 12px text, tertiary color when inactive, primary color when active
- Active state determined by IntersectionObserver — whichever section has the most intersection ratio is "active"
- Clicking a link smoothly scrolls to that section using `scrollIntoView({ behavior: 'smooth' })`

**Right:** "Sign in" link (12px, secondary text, no background) + "Get started" button (12px, padding 7px 16px, iris background, dark text)
- "Sign in" navigates to `/login`
- "Get started" navigates to `/signup`

### HeroSection

Full padding: `100px 56px 80px`, max-width 1100px centered.

Top: small pill — `display: inline-flex`, `gap: 8px`, padding `6px 14px`, background `rgba(167, 139, 250, 0.1)`, border `0.5px solid rgba(167, 139, 250, 0.3)`, border-radius 999px:
- Iris dot (6px) + "Research project · 2026" text (11px iris, tracking-wider)

Headline (Inter Display, 64px, font-weight 500, letter-spacing -0.03em, line-height 1.05, max-width 850px):
```
AI that finds
[in iris color] what your alerts [/in iris color] miss.
```

Subhead (17px, secondary text, line-height 1.6, max-width 620px):
> Real-time log anomaly detection with explainable AI. Catches the failures threshold-based monitoring can't, predicts them 12 minutes early, and tells you why in plain English.

Single CTA below: "Get started, it's free" — primary button, iris background, padding `12px 22px`, border-radius 8px, navigates to `/signup`.

(Note: comma after "Get started", not em dash. No second button — primary CTA only.)

Below the CTA, separated by 80px of vertical space, a **dashboard preview card**:
- Background `#0d0d10`, border `0.5px solid #1f1f1f`, border-radius 12px, padding 18px
- Faint glow: `box-shadow: 0 0 80px rgba(167, 139, 250, 0.04)`
- At top: three small dots (mac window-style), 10px, `bg-card` color
- Below: a 2-column miniature dashboard layout — small sidebar on the left with logo and 4 nav items, main area with 3 KPI cells, a small timeline bar chart, and 2 anomaly feed rows
- This is purely visual — not interactive. Use the same data as the existing dashboard mock for consistency.

Hero animations on initial page load (not scroll):
- Pill: fade in at 100ms, 400ms duration
- Headline: fade up 16px at 200ms, 600ms
- Subhead: fade up 16px at 350ms, 600ms
- Button: fade up 12px at 500ms, 500ms
- Dashboard preview: fade up 24px at 700ms, 800ms

### ProblemSection

Background `#0a0a0a`, padding `96px 56px`, max-width 1100px.

Eyebrow: "The problem"
Headline: "Most alerts are noise. The few that matter get buried."
Subhead: "Threshold-based monitoring fires thousands of false alarms while quietly missing the failures it wasn't told to look for. By the time something breaks, the warning signs were already in the logs, nobody read them."

Below: 3 cards in a 1-px-gap grid (cells separated by hairline lines, no card borders).

Each card has:
- Big number (Inter Display, 48px, font-weight 500, letter-spacing -0.02em, line-height 1)
- Title (13px, primary text, font-weight 500)
- Body (12px, tertiary text, line-height 1.6)

Cards (in order):
1. **73% — of alerts are false positives** — coral colored number — "On-call engineers spend most of their pages chasing alerts that never required action."
2. **34min — average time to root cause** — peach colored number — "Even after the alert fires, finding the cause means manually grepping logs across multiple services."
3. **0% — of failures predicted in advance** — sky colored number — "Threshold-based systems react. They can't tell you a failure is 12 minutes away, they only know once it's happening."

Section animation: slides in from the left (translateX -30px to 0) with fade. Sub-cards stagger 80ms each.

### HowItWorksSection

Background `#050505`, padding `96px 56px`, max-width 1100px.

Eyebrow: "How it works"
Headline: "A pipeline that learns, predicts, and explains."

Below: 4 numbered steps stacked vertically with 56px between them. Each step is a 2-column row: 60px-wide number column on the left, content column on the right with 28px gap.

Number column: a 36×36 square, `border: 0.5px solid #2a2a2e`, `border-radius: 8px`, with the number "01"–"04" in Inter Display, 14px, iris color, font-weight 500, centered.

Content column for each step:
- Title (18px, font-weight 500)
- Body paragraph (14px, secondary text, line-height 1.7, max-width 600px)
- Tech pill row at the bottom: each pill is `font-size: 11px`, `padding: 4px 10px`, `background: #16161a`, `border: 0.5px solid #2a2a2e`, `border-radius: 999px`, mono font

Steps:

**01 — Ingest, parse, embed**
> Logs flow into Redis Streams as a burst buffer. Drain3 extracts stable templates from messy log lines. SBERT embeddings turn each 20-event window into a dense vector, capturing meaning, not just keywords.

Pills: Redis Streams, Drain3, Sentence-BERT

**02 — Detect with a two-model ensemble**
> A Transformer encoder learns sequential failure patterns and predicts how many minutes until impact. An AutoEncoder learns what normal looks like and flags reconstruction outliers. Their scores combine with a confidence filter, only signals the model is sure about become alerts.

Pills: Transformer, AutoEncoder, PyTorch

**03 — Explain with retrieval-augmented LLaMA**
> A FAISS index of past incidents finds patterns similar to the new anomaly. Local LLaMA 3 8B, running on your hardware, reads the retrieved context and produces a root cause explanation plus a numbered fix, grounded in real prior incidents, not hallucinated.

Pills: FAISS, LLaMA 3, Ollama

**04 — Route, dedupe, learn**
> Critical anomalies wake on-call via PagerDuty; warnings go to Slack; info-level events email the team. Engineer feedback feeds back into retraining, the system learns from the corrections it gets in production.

Pills: PagerDuty, Slack, Drift detection

Section animation: slides in from the right with fade. Each step staggers 80ms.

### FeaturesSection

Background `#0a0a0a`, padding `96px 56px`, max-width 1100px.

Eyebrow: "Key features"
Headline: "Six things most AIOps tools don't do."

2x3 grid, hairline-divider style (1px gap with `bg-border-subtle`, items have `bg-card-shade` like `#0d0d10`):

Each feature card:
- 20px lucide icon (or hexagon SVG for the first card)
- Title (16px, font-weight 500)
- Body (13px, secondary, line-height 1.65)
- Padding `32px 28px`

Features (in this exact order):

1. **Two-model ensemble** (icon: hexagon brand mark) — "Transformer for sequential patterns, AutoEncoder for distributional drift. They fail in different ways, together they cover both."
2. **Failure prediction** (icon: lucide `Zap` or `TrendingUp`) — "The model doesn't just detect anomalies, it predicts how many minutes until impact. Time to act before things break."
3. **Confidence filtering** (icon: lucide `Filter` or `Clock`) — "A learned scorer suppresses borderline predictions. You only get pinged for signals the model is genuinely sure about."
4. **Explainable by design** (icon: lucide `MessageSquare` or `BookOpen`) — "Every alert comes with attention-weighted log lines and a plain-English root cause. No more reverse-engineering opaque scores."
5. **100% on-premises** (icon: lucide `Lock` or `Shield`) — "Local LLaMA via Ollama. Your logs never leave your network. No third-party API calls, no compliance headaches."
6. **Human-in-the-loop** (icon: lucide `MessageSquare` or `RefreshCw`) — "Engineers mark alerts as true or false positives. Those labels feed the next retrain. The system gets sharper with use."

Section animation: slides in from the left with fade. Each card staggers 80ms (so the 6 cards cascade in over ~480ms total).

### ResultsSection

Background `#050505`, padding `96px 56px`, max-width 1100px.

Eyebrow: "Results"
Headline: "Numbers from a real evaluation."
Subhead: "Trained on OpenStack, evaluated on held-out OpenStack, HDFS, and a fully unseen Apache distribution. Reproducible on any machine with 16GB RAM."

Below the subhead, 4 KPI cells in a row, separated by `36px` gaps, with hairline `border-top` and `border-bottom` framing the row:

Each KPI:
- Big number (Inter Display, 56px, iris color, font-weight 500, letter-spacing -0.03em, line-height 1, `font-variant-numeric: tabular-nums`)
- Title (12px, primary text, font-weight 500)
- Subtitle (11px, tertiary)

KPIs (use `react-countup` for the number):
1. **0.91** — F1 score / held-out OpenStack test (decimals: 2)
2. **12m** — avg early warning / before predicted failure (units handled with smaller "m" suffix at 28px)
3. **87%** — cache hit rate / on LLaMA explanations (units handled with smaller "%" suffix at 28px)
4. **100%** — on-prem inference / no third-party calls

Count-up should trigger when the section enters viewport, animate over 1500ms, with 100ms stagger between numbers (so number 1 starts at 0ms, number 2 at 100ms, etc.).

Below the KPIs, a 2-column comparison block:

**Left card — "Cross-dataset generalization":**
A simple key-value table:
- OpenStack (held-out) → 0.91
- HDFS (held-out) → 0.89
- Apache (fully unseen) → 0.83

Values mono font, iris colored, right-aligned. Hairline dividers between rows.

**Right card — "Beats prior baselines":**
- TF-IDF + Isolation Forest → 0.81
- DeepLog (reproduced) → 0.89
- LogGuard (ours) → 0.91

Last row in iris color and bold to stand out (the "ours" row is the headline). Other rows in tertiary.

Both cards have `bg-card` background, hairline gap between them, 28px padding inside, border-radius 12px on the outer container.

Section animation: slides in from the right with fade. Cards stagger 80ms.

### CtaSection

Background `#0a0a0a`, padding `96px 56px 64px`, max-width 1100px.

Inside, a single big card:
- Background: linear gradient `linear-gradient(135deg, rgba(167, 139, 250, 0.08) 0%, rgba(251, 113, 133, 0.04) 100%)`
- Border `0.5px solid #2a2a2e`, border-radius 16px, padding `80px 56px`, text-align center

Content:
- Pill at top: iris dot + "Free for self-hosted" (same style as hero pill)
- Headline (Inter Display, 48px): "Stop reading logs. Start reading insights."
- Subhead (16px, secondary): "LogGuard is open and free to self-host. Get started in under five minutes, no credit card, no email confirmation, no waiting."
- Single CTA button: "Get started, it's free" — primary iris button, padding `14px 28px`, font-size 14px, navigates to `/signup`

(No "View on GitHub" button.)

Section animation: fades up with no horizontal slide (different from siblings — gives the closing section a settled feel).

### LandingFooter

Background `#0a0a0a` (continues from CTA section seamlessly), padding `36px 0 0`, max-width 1100px, hairline `border-top: 0.5px solid #1f1f1f`, margin-top 36px.

Layout: flex justify-between align-center, single row:

**Left:** small hexagon (20px) + "LogGuard" wordmark (13px, secondary)

**Center:** three text links (12px, tertiary): "Documentation · GitHub · Paper"
- These can be placeholder anchors for now (`href="#"`)

**Right:** small mono text: "© 2026 · Research project"

No animation on the footer (it's barely visible content).

---

## Part 5 — Animation implementation details

### Section wrapper component

Create `src/components/landing/AnimatedSection.tsx`:

```tsx
import { motion } from 'framer-motion';
import { useInView } from 'react-intersection-observer';
import { useReducedMotion } from 'framer-motion';

interface Props {
  children: React.ReactNode;
  direction?: 'left' | 'right' | 'up';
  delay?: number;
  id?: string;
}

export function AnimatedSection({ children, direction = 'up', delay = 0, id }: Props) {
  const { ref, inView } = useInView({ threshold: 0.15, triggerOnce: true });
  const reducedMotion = useReducedMotion();

  const initial = reducedMotion ? { opacity: 1 } : {
    opacity: 0,
    x: direction === 'left' ? -30 : direction === 'right' ? 30 : 0,
    y: direction === 'up' ? 30 : 0,
  };

  return (
    <motion.section
      id={id}
      ref={ref}
      initial={initial}
      animate={inView ? { opacity: 1, x: 0, y: 0 } : initial}
      transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1], delay }}
    >
      {children}
    </motion.section>
  );
}
```

Use `<AnimatedSection direction="left">` to wrap each section. Hero gets `direction="up"`. Problem gets `left`. How-it-works gets `right`. Features gets `left`. Results gets `right`. CTA gets `up`.

### Staggered children

Within each section, child elements (cards, steps) should stagger. Use Framer Motion's stagger pattern:

```tsx
const containerVariants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.08 } },
};

const itemVariants = {
  hidden: { opacity: 0, y: 16 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.5 } },
};
```

Apply to feature cards, problem cards, how-it-works steps, and results KPIs.

### Scroll-spy active section

Use `useInView` on each section to track which is currently visible. The header's nav links read this state and apply `text-primary` to the active one.

---

## Part 6 — Final integration checks

After building, verify:

1. **`npm run build` succeeds** with no errors
2. **`npm run dev`** opens to the landing page at `/`
3. Scroll through the entire landing page — every section animates as designed, count-up triggers on Results section
4. Click "Get started" — navigates to `/signup`
5. Click "Sign in" — navigates to `/login`
6. On `/signup`: fill in name + email + password, submit, expect navigation to `/dashboard`
7. After sign-in, the dashboard loads and the sidebar shows
8. Sign out from a sidebar action (add a sign-out button in the sidebar bottom area near the connection pill)
9. After sign-out, refresh the page — get redirected to `/login`
10. Visit `/dashboard` while signed out — get redirected to `/login`
11. While signed in, visit `/login` — get redirected to `/dashboard`
12. Severity colors: open dashboard, see warning rows in peach (not amber) and info rows in sky (not cyan)
13. Light mode: toggle theme, verify peach and sky colors don't appear in light mode (the existing light values stay)
14. `prefers-reduced-motion: reduce` — toggle in DevTools, scroll the landing page, all animations should be disabled

If all 14 checks pass, the build is complete.

---

## Constraints

- Use sentence case everywhere (no Title Case)
- No em dashes anywhere in copy — use commas, periods, or colons instead
- All severity colors via tokens, never hardcoded hex
- All Firebase config via `.env`, never hardcoded
- Friendly error messages on auth failures, not raw Firebase strings
- Animations restrained: 30px slide max, 600ms duration max, 80ms stagger
- Respect `prefers-reduced-motion` everywhere
- All inputs use the existing dashboard's design tokens (don't introduce new input styles)
- The Layout component (sidebar wrapper) is NOT used on Landing/Login/Signup
- Landing page is a single page — no multi-page nav inside it (all nav is anchor scroll within the page)

Build all of this. Confirm at the end with the verification checklist above.
