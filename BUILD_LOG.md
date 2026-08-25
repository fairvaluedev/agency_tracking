# Build Log — agency_tracking

Running record of what's built, key decisions made without stopping to ask (per explicit
instruction: proceed autonomously, log decisions, keep this file current so a fresh session
can resume from it if interrupted), and what's next. Source of truth for *why* is
`../../../../agency/master-build-specification.md` (+ addendum + SRS) — this log doesn't
duplicate that content, only records build-order status and decisions made where the spec
was silent or where sequencing required a judgment call.

Bench: `test/` (site `agency-tracking.local`, MariaDB root pw `1234`, admin pw `admin`).
App lives at `test/apps/agency_tracking`, own git repo, **not** derived from
`test/apps/applicant_processing` (the old Gemini prototype — kept untouched as reference only,
see `[[project-agency-tracking-gap-analysis]]` memory for why it wasn't reused).

## Status: Part I sequence

- [x] 1. Core identity + track-aware field floor (Applicant, Standard/Muayena, Musaned gate stub)
- [ ] 2. CV generation + Musaned gate wired in
- [ ] 3. Portal + atomic selection + `active_placement` locking
- [ ] 4. Contract parsing (both tracks) → Placement creation
- [ ] 5. Corridor Definition engine (Saudi + Kuwait)
- [ ] 6. transition() + gate table + Manager Override (Medical 2 gate)
- [ ] 7. Clearance Step + ToDo permission scoping + LMIS→Ticketing→Departure auto-chain
- [ ] 8. Financial ledger (income/expense, FX, accrual, batching, visibility wall)
- [ ] 9. Reconciliation tool
- [ ] 10. Complaints
- [ ] 11. Notification pipeline
- [ ] 12. Chat
- [ ] 13. Reporting/dashboards
- [ ] 14. Frontend (SPA)
- [ ] 15. Deployment hardening

## Standing decisions (apply to every step, not re-litigated per step)

- **transition() built now, not deferred to Step 6.** CLAUDE.md's hard rule ("every status
  change goes through transition(), never doc.status = X directly") outranks Part I's
  sequencing, which only means the *gate table* grows complex at Step 6 — the function itself
  exists from Step 1 so no step ever bypasses it. Lives in `agency_tracking/state_machine.py`,
  shared across doctypes (`ALLOWED_TRANSITIONS`/`STAGE_GATES` keyed by doctype).
- **No raw `/api/resource/*`.** Every client-facing operation goes through a whitelisted
  function in a module-scoped `*_api.py` file (Part F), starting now with `applicant_api.py`,
  not deferred to later steps.
- **No Frappe Desk client-script UI (.js per doctype).** Part H is explicit the real frontend
  is a framework-agnostic SPA built in Step 14 against the headless API — building Desk
  form scripts now would be throwaway work against a UI nobody will use. Doctypes get
  JSON + Python controller only, per CLAUDE.md's pairing rule (JSON+Python, not JSON+JS).
- **Roles pre-declared.** All 8 Part G roles (Recruitment/Intake, Clearance Officer, Ticketing/
  Dispatch, Complaint Manager, Finance Manager, Manager, Admin, Foreign Agency) are created via
  `install.py:after_install` now rather than one at a time per step — cheap, avoids fragmented
  role creation, and the full RBAC table is already finalized in the spec.
- **Applicant vs Placement status split.** Part B's table only lists `entry_track`,
  `musaned_status`, `active_placement` for Applicant (not exhaustive — SRS clearly implies name/
  phone/gender/etc. too), while Placement explicitly owns `status`. Read this as: Applicant owns
  its own `status` for the pre-Placement stages only (Draft → Registered → CV Generated —
  everything before a foreign agency selects the candidate and a Placement gets created).
  Selected → Processing → Stamped → Ticketed → Departed live on `Placement.status` from Step 3+
  onward. Applicant's `status` Select options are therefore just `Draft`/`Registered`/
  `CV Generated` for now; whether Applicant needs a 4th "locked" marker once Placement exists
  is a Step 3 decision, not resolved here.
- **Environment fixed on the way in:** `test/apps/frappe` was shallow-cloned on `develop`
  (v17.0.0.dev0, needs Python 3.14 — this machine has 3.12), which is almost certainly why the
  old prototype never got a working site either (no site existed under `test/sites/` before this
  session). Re-fetched and checked out `version-15` (matches `applicant_processing`'s own
  `frappe~=15.0.0` pin and the installed Python). `bench setup requirements --python frappe` run
  to make it importable — scoped to `frappe` only, not `applicant_processing`'s heavy OCR deps
  (paddleocr/paddlepaddle), which agency_tracking doesn't need.

## Step 1 — what was built

`agency_tracking/agency_tracking/doctype/applicant/` — `applicant.json` + `applicant.py` +
`test_applicant.py`. Plus `state_machine.py` (shared `transition()`, `ALLOWED_TRANSITIONS`,
`STAGE_GATES`, and the Musaned gate stub) and `applicant_api.py` (whitelisted
`create_applicant`/`register_applicant`, no raw resource access). `install.py` creates the 8
roles on install.

Field-floor source: `business-workflow-srs.md` Stage 1 (Draft: name, gender, nationality, phone,
address) and Stage 2 (Registered, Standard: full list incl. national ID, labor ID, destination
country, salary+currency, religion, marital status, emergency contact, full passport details,
education, target job, photos, passport scan, medical FIT) + master spec A.1 (Muayena: lighter
global-only floor — passport, national ID, medical, photos).

**Assumptions made, not explicitly in spec (flagging per CLAUDE.md rather than silently
picking):**
- `passport_scan` included in *both* tracks' Registered floor. Spec's Muayena floor list says
  "passport" without clarifying whether that includes the scanned document or just passport
  data fields. Included the scan for both since OCR/contract-parsing (Step 4) needs it either
  way and it's needed for real operation regardless of track.
- Uniqueness on `passport_number`/`national_id` implemented as an app-level check in
  `validate()` (skips blank values), not a DB-level `unique=1` field flag — a DB unique index
  would reject multiple blank-passport Draft records (MySQL treats `''` as a real, colliding
  value, not `NULL`), which would break Draft-stage saves since passport isn't required until
  Registered.
- No `Cancelled` status added to Applicant, even though the old prototype had one — not in the
  new spec's documented lifecycle (A.2 lists exactly 9 stages, cancellation only appears later
  at the Ticketed→Stamped revert, which is a Placement-level concern). Not inventing beyond spec.

**Verified, not just written:** `bench migrate` synced the doctype cleanly; all 8 Part G roles
exist (`install.py:create_roles`, ran manually once since the app had already been
`install-app`'d before `install.py` existed — will fire automatically via `after_install` on
any fresh install from here on); `run-tests --module ...test_applicant` → 15/15 passing; a
console smoke test drove the actual `applicant_api` functions end-to-end (create → blocked at
register with a structured missing-fields message → filled the floor → registered → fetched)
to confirm the real API path works, not just the unit tests in isolation.

**Not yet done (explicitly deferred, not forgotten):**
- `active_placement` field — Part I Step 3 (needs Placement doctype to exist as a Link target
  first, and its atomic-lock semantics are literally what Step 3 is).
- Musaned gate is a stub (`musaned_gate_passed()` exists and is tested) but nothing calls it yet
  — wiring into CV generation is Step 2 by name.
- `Country` values used for `destination_country`/`nationality` rely on Frappe's shipped core
  Country doctype (standard ISO names e.g. "Saudi Arabia", "Kuwait", "Ethiopia") — no new
  doctype needed for this.
