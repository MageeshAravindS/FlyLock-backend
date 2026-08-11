# FlyLock Assessment Portal — Architecture & Design Document

**Companion to:** FocusLock/FlyLock Browser Architecture (v1.0)
**Scope:** Web platform with three surfaces — Attend, Create, Admin
**Status:** Draft for review

---

## 1. System Overview

Three distinct web surfaces, one shared backend:

| Surface | Who uses it | Where it can be opened | Auth model |
|---|---|---|---|
| **Attend** (`/assessment/:code`) | Students | **Only** from inside FlyLock Browser | Code + one-time launch token, no persistent account |
| **Create** (`/create/...`) | Instructors/creators | Anywhere (any normal browser) | Email login, gated by admin allowlist |
| **Admin** (`/admin/...`) | Administrators | Anywhere | Email login, admin role |

```
                     ┌─────────────────────────┐
                     │   Assessment Portal       │
                     │   (Next.js/Node backend)  │
                     │                            │
   ┌───────────┐     │  ┌──────────┐  ┌────────┐ │     ┌──────────────┐
   │ FlyLock    │────┼─►│ /assessment│  │ /create│ │◄────│  Instructor   │
   │ Browser    │     │  │ (locked)   │  │ (open) │ │     │  (any browser)│
   │ (kiosk)    │     │  └──────────┘  └────────┘ │     └──────────────┘
   └───────────┘     │        ▲            ▲       │
                     │        │            │       │     ┌──────────────┐
                     │        │        ┌────┴────┐  │◄────│    Admin      │
                     │        │        │ /admin  │  │     │ (any browser) │
                     │        │        └─────────┘  │     └──────────────┘
                     │        │                       │
                     │   ┌────┴─────────────────────┐ │
                     │   │  Session/Token Service    │ │
                     │   └──────────────────────────┘ │
                     └─────────────────────────────────┘
                                   │
                          ┌────────┴────────┐
                          │   Database        │
                          │ (Postgres/similar) │
                          └────────────────────┘
```

---

## 2. The Hard Problem: "Only Accessible From FlyLock Browser"

Be clear-eyed about this up front, the same way we were about Alt+Tab in the
browser's own security model: **an HTTP request carries no unforgeable proof
of which application sent it.** Anything FlyLock Browser can send (a header,
a user-agent string, a token embedded in its binary) can in principle be
extracted and replayed by someone willing to reverse-engineer the client.
The goal here, like the browser's focus-loss model, is **strong, layered
deterrence — not cryptographic impossibility** — unless you're willing to
add a server-validated hardware/TPM attestation layer, which is a much
bigger investment (noted as a v2 option below).

### Recommended layered design

**Layer 1 — One-time launch token (primary control)**

1. Student enters an access code *inside FlyLock Browser* on its built-in
   "Enter Code" screen (this stays in the browser shell, never a web page).
2. FlyLock Browser calls a backend endpoint directly (not via the visible
   browser view) to exchange the code for a **short-lived, single-use launch
   token**:
   ```
   POST /api/v1/sessions/launch
   { "examCode": "CS101-7X9B", "clientId": "<install-bound GUID>" }

   → 200 OK
   { "launchToken": "<signed JWT, 45s expiry, one-time nonce>",
     "assessmentUrl": "https://portal/assessment/CS101-7X9B" }
   ```
3. FlyLock Browser then navigates its `ChromiumWebBrowser` to
   `assessmentUrl?token=<launchToken>`.
4. Server middleware on `/assessment/*`:
   - Verifies JWT signature and expiry.
   - Checks the nonce hasn't been redeemed before (store redeemed nonces in
     Redis/DB with TTL = token expiry + buffer) — **this is what stops
     someone from copy-pasting the URL into a normal browser after the
     student loads it**, since the token is burned on first successful
     exchange.
   - On success, issues a normal **httpOnly, Secure, SameSite=Strict
     session cookie** scoped to that exam attempt; the token itself is
     never reusable again.
5. Anyone opening `/assessment/CS101-7X9B` directly (no valid token, no
   session cookie) gets a **"This assessment must be opened from FlyLock
   Browser"** page, never the exam content.

This is the load-bearing mechanism. It doesn't rely on trusting a
user-agent string at all — it relies on possession of a token that only a
successful FlyLock-Browser-initiated exchange produces, and that token is
consumed exactly once.

**Layer 2 — Client identity binding (defense-in-depth, not primary)**

- On first run, FlyLock Browser generates and persists a local `clientId`
  (GUID) and includes it in the launch-token request.
- The server can optionally require that `clientId` to be one seen before
  from a legitimate install pattern (e.g., rate-limit new/unknown
  `clientId`s attempting launches), and logs it against the attempt for
  audit purposes. This is a *fraud-signal*, not an access-control gate on
  its own — it raises the cost of automation, it doesn't make it
  impossible.

**Layer 3 — Custom header + weak secret (cheap extra friction, optional)**

- FlyLock Browser can send a header like `X-FlyLock-Client: <HMAC of
  clientId + timestamp, keyed by an embedded secret>` on the launch-token
  request specifically (not on every subsequent page request, to keep the
  attack surface small). Treat this exactly like the browser's own
  anti-tamper posture: **it raises the bar for casual bypass, and should
  never be described as unbypassable**, since any embedded secret can be
  extracted from a distributed binary by a sufficiently motivated user.

**Layer 4 — Mutual TLS client certificate (v2, stronger, higher cost)**

- If you later need a materially stronger guarantee, embed a client
  certificate at install time and require mTLS on the launch-token
  endpoint. This is the only layer here that approaches "hard to fake
  without extracting a private key," and is a legitimate future
  enhancement — flagged as out of v1 scope given the added PKI/ops
  overhead, consistent with keeping FlyLock Browser itself dependency-light.

### What this design explicitly does *not* claim

- It does not stop someone from screen-recording/photographing the exam
  content once legitimately loaded (no web architecture can prevent that;
  it's the same category of out-of-scope threat as a second physical
  device in the browser's own security model).
- It does not stop a student from extracting the launch token from
  FlyLock Browser's local network traffic in real time and replaying it —
  but the token is single-use and ~45 seconds, so this requires an active
  man-in-the-middle at the moment of launch, which is a materially higher
  bar than "just open the URL."

---

## 3. Single-Login / One-Session Enforcement

Applies to **creator/admin accounts** and, per your requirement, to the
**student's exam attempt** ("one user can only login once and can logout
once the assessment is over").

### Data model for session control

```
users
 ├─ id, email, role ('creator' | 'admin')
 ├─ active_session_id (nullable, FK → sessions.id)
 └─ ...

sessions
 ├─ id, user_id, created_at, revoked_at (nullable)
 └─ last_seen_at

exam_attempts
 ├─ id, assessment_id, student_identifier, exam_code
 ├─ launch_token_nonce (unique, redeemed marker)
 ├─ started_at, submitted_at (nullable)
 ├─ status ('not_started' | 'in_progress' | 'submitted' | 'terminated')
 └─ session_cookie_id
```

### Enforcement logic

- **Creator/admin login**: on successful login, create a new `sessions`
  row and set `users.active_session_id` to it, **revoking the previous
  one** (old session's cookie stops validating on next request — "logging
  in elsewhere kicks the old session out"). This matches typical
  single-device-login semantics. If instead you want "block the *new*
  login if one is already active" (rather than kick the old one), that's a
  one-line policy flip in the same check — worth deciding explicitly, since
  they're different UX.
- **Student exam attempt** (your specific requirement — *can log in once,
  can log out once, no re-entry after submit*):
  - `exam_attempts.status` starts `not_started`. On successful launch-token
    redemption, moves to `in_progress` and records `started_at`.
  - Any further launch-token request for the *same exam code + same
    student identifier* where `status` is already `in_progress` or
    `submitted` is **rejected** — this is what prevents "logout and log
    back in to reset the clock or re-attempt."
  - On explicit submission (or FlyLock Browser's `SessionTerminated` event
    from a focus-loss lockout — this is the natural integration point with
    the browser's own state machine), status moves to `submitted` or
    `terminated` and the session cookie is revoked server-side immediately.
  - Recommend an **admin override** to reset a specific `exam_attempts` row
    back to `not_started` for legitimate cases (crash, wrong code entered,
    proctor-approved restart) — otherwise your first real crash mid-exam
    becomes a support fire drill with no recovery path.

---

## 4. Assessment Creation

### 4.1 Manual MCQ builder

- Each question: text, an **ordered list of options (2–N, configurable
  min/max, default max e.g. 8)**, one or more correct answers (support
  single-answer now; design the schema to allow multi-answer later without
  a migration — store `is_correct` per option row rather than a single
  `answer` column on the question).
- Builder UI: add/remove option rows dynamically, drag-to-reorder,
  mark-correct toggle per option, optional per-question "reason/explanation"
  field for post-exam review.

### 4.2 CSV bulk import

Given schema:

```
Question | Option 1 | Option 2 | Option 3 | Option 4 | Answer | Reason
```

Design notes:

- **Answer column matching**: accept either the literal option text or a
  letter/number (`A`/`1`) referring to the option's position — support
  both, since instructors will do both; document one canonical format but
  don't hard-fail on the other.
- **Variable option counts**: rather than hard-coding exactly 4 `Option N`
  columns, parse headers dynamically — detect all columns matching
  `Option \d+` and treat blank cells in a row as "this question has fewer
  options than the widest row in the file." This lets a single CSV mix
  4-option and 2-option questions without forcing every row to pad with
  empty columns.
- **Validation pass before commit**: reject/report rows where the `Answer`
  value doesn't match any populated option for that row, where `Question`
  is blank, or where fewer than 2 options are present — show a per-row
  error summary to the creator before import, not a silent partial import.
- **CSV injection hardening**: sanitize any cell beginning with `=`, `+`,
  `-`, `@` (classic formula-injection vector if the CSV is later re-opened
  in Excel by someone) by prefixing with a single quote or stripping the
  leading character — small thing, easy to skip, worth doing explicitly.
- **Encoding**: accept UTF-8 with BOM (common Excel export artifact);
  detect and strip BOM rather than letting it corrupt the first header
  name.

### 4.3 Suggested schema

```
assessments
 ├─ id, exam_code, title, duration_minutes
 ├─ start_time, end_time, is_active
 └─ created_by (FK → users.id)

questions
 ├─ id, assessment_id, order_index, text, reason (nullable)

options
 ├─ id, question_id, order_index, text, is_correct (bool)
```

---

## 5. Admin Controls

### 5.1 Creator allowlist

```
creator_allowlist
 ├─ email (unique)
 ├─ added_by, added_at
 └─ status ('active' | 'revoked')
```

- Login/signup flow for the Create surface checks the entered email
  against `creator_allowlist` **before** allowing account creation or
  granting the `creator` role — reject with a clear "your email hasn't
  been approved for assessment creation, contact your admin" message
  rather than a generic auth failure.
- Admin UI: add/remove emails, view who's used their access, revoke access
  (revoking should also kill any active session for that user — reuse the
  `active_session_id` revocation logic from Section 3).

### 5.2 Admin dashboard responsibilities

- Manage creator allowlist (above).
- View/search all assessments and their `exam_attempts` status.
- Force-logout or reset a specific session or exam attempt (the recovery
  path flagged in Section 3).
- Audit log view: logins, launch-token issuance/redemption, exam
  terminations — this should visually tie back to the **FlyLock Browser
  session logs** (Section 12 of the browser architecture doc) via a shared
  `exam_code`/`sessionId`, so a support ticket can be traced end-to-end
  across both systems.

---

## 6. API Surface Summary

| Endpoint | Caller | Purpose |
|---|---|---|
| `POST /api/v1/sessions/launch` | FlyLock Browser only | Exchange exam code for one-time launch token |
| `GET /assessment/:code?token=...` | FlyLock Browser (via redirect) | Redeem token, establish session cookie, serve exam UI |
| `POST /api/v1/assessments/:code/submit` | Exam page (in-browser) | Submit answers, close attempt |
| `POST /api/v1/assessments/:code/heartbeat` | Exam page (in-browser) | Periodic autosave / liveness signal |
| `POST /api/v1/auth/login` | Create/Admin surfaces | Email-based login, allowlist check |
| `POST /api/v1/auth/logout` | Create/Admin surfaces | Revoke current session |
| `POST /api/v1/assessments` | Create surface | Create assessment + manual questions |
| `POST /api/v1/assessments/:id/import-csv` | Create surface | Bulk import, returns validation report |
| `GET/POST /api/v1/admin/allowlist` | Admin surface | Manage creator email allowlist |
| `POST /api/v1/admin/sessions/:id/revoke` | Admin surface | Force logout / reset an attempt |

---

## 7. Open Decisions to Confirm Before Building

1. **Kick-old vs. block-new** on creator re-login (Section 3) — pick one
   policy; they produce different UX.
2. **Multi-correct-answer support** — build the `is_correct`-per-option
   schema now even if v1 UI only exposes single-answer, to avoid a
   migration later.
3. **Autosave mechanism**: `localStorage` alone (per your notes) is fine
   for resilience against a page reload, but should **not** be the only
   copy of student answers — pair it with the periodic `heartbeat`/`submit`
   endpoint so a crashed FlyLock Browser session doesn't lose answers that
   only ever existed in that browser's local storage.
4. **How deep does client-identity binding (Layer 2/3) go for v1** — decide
   now whether the lightweight header-HMAC approach is sufficient or
   whether mTLS (Layer 4) is a launch requirement, since it changes the
   FlyLock Browser client work as well as the portal's.
5. **Admin override/reset path for `exam_attempts`** — confirm this ships
   in v1; without it, the very first crash mid-exam has no recovery story.