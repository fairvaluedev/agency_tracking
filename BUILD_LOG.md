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
- [x] 2. CV generation + Musaned gate wired in
- [x] 3. Portal + atomic selection + `active_placement` locking
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

## Step 2 — what was built

`agency_tracking/agency_tracking/doctype/cv_record/` — `cv_record.json` (Submittable,
`applicant` Link, `generated_on`/`generated_by` auto-set on insert) + `cv_record.py` +
`test_cv_record.py`. Plus `cv_api.py` (`generate_cv`, Part F module-scoped whitelisted
function). `state_machine.py` gained the `("Registered", "CV Generated")` edge and its gate
(`cv_generation_gate`), which composes the existing `musaned_gate_passed` stub with an
entry-track check — this is the "wired in" part of the step's name. CV Record's own
`validate()` independently re-checks Standard-track + Registered-status + Musaned gate with
specific error messages (checked first, before `transition()`'s generic gate runs as a
backstop) — belt-and-braces per the production-quality directive: a CV Record should never be
able to exist for a candidate that violates these invariants, regardless of which code path
created it.

**Scope call:** did not build actual CV/dossier PDF rendering (the "two-page CV" visual
output) — the technical spec (Part B/C/F) only requires `CV Record` to exist as a submittable
audit artifact gating the Applicant's status move; the visual document is a presentation
concern more naturally handled by a Frappe Print Format or the Step 14 SPA, not called out
anywhere in the state-machine/RBAC spec that's been the basis for every other decision so far.
Flagging so it isn't mistaken for an oversight — build if/when it's actually needed.

**Verified:** `bench migrate` synced cleanly; 6/6 new tests passing, all 15 Step-1 tests still
passing (21/21 total) — Kuwait Standard candidates generate CVs with no Musaned involvement,
Saudi Standard candidates are blocked until `ALTEYAZECHEM`, Muayena and un-Registered
Applicants are rejected outright.

**Not yet done (deferred):** portal visibility of CV-Generated candidates is Step 3's
concern (that's literally what "Portal" means in Step 3's name) — nothing here exposes CV
Records to any agency-facing query yet.

## Step 3 — what was built

`Contractor` doctype (minimal: `contractor_name`, `country`, one `user` Link per contractor —
see assumption below) and `Placement` doctype (minimal: `applicant`, `contractor`,
`destination_country`, `status` — options just `"Selected"` for now, `cv_record`; richer
Part B fields — `contract_signed_date`, `manual_commission_amount`, `is_free_replacement` —
deliberately **not** added yet, see "Standing decisions" correction below). `Applicant`
gained `active_placement` (Link -> Placement, read-only, set only through the API). New
`portal_api.py`: `list_portal_candidates()` (own-country catalog, non-PII field subset —
judgment call, spec doesn't enumerate exact portal fields) and `select_candidate()` — the
atomic, globally-exclusive selection, using `SELECT ... FOR UPDATE` on the Applicant row to
close the race window between two agencies both reading `active_placement` as empty.

**Resolved an open question from Step 1's log:** whether Applicant needs a 4th status value
once Placement exists. Answer: no. Part B splits ownership — Applicant's own `status` only
ever covers the pre-Placement pipeline (Draft/Registered/CV Generated); once a Placement
exists, the real lifecycle state lives on `Placement.status` and `active_placement` is simply
the pointer/lock. This also explains why Muayena candidates (who skip CV/portal) will end up
with `Applicant.status` frozen at `"Registered"` forever once Step 4 gives them a Placement —
that's correct, not a bug.

**Standing-decision correction:** Step 1/2 added `musaned_status` and (implicitly) treated
Part B's per-doctype field notes as license to add fields ahead of the logic using them. On
reflection that's the same "fields exist, nothing uses them" smell flagged in the
Gemini-prototype gap analysis as an anti-pattern to avoid. Revised rule going forward: add a
field only in the step that actually gates or reads it (`musaned_status` gets a pass — it was
explicitly named "Musaned gate stub" in Step 1's own title, a deliberate one-step-early
exception, not the general pattern). `Placement.contract_signed_date` lands in Step 4,
`manual_commission_amount` in Step 8, `is_free_replacement` in Step 10 — not now.

**Assumption flagged:** one Contractor <-> one portal User. The spec doesn't describe
multi-user agencies; if an agency needs several staff logging in, `Contractor.user` becomes a
child table later — cheap to extend, not blocking anything downstream.

**Verified:** `bench migrate` synced cleanly; 4/4 new Placement tests + 6/6 new portal API
tests (catalog country-filtering, atomic select, cross-agency invisibility, double-selection
rejection, cross-country rejection, non-Foreign-Agency rejection) — 31/31 total across the
whole app.

**Not yet done (deferred):** Muayena's direct-to-Selected entry path (no portal, contract
already in hand) is Step 4, alongside the contract-parsing utility that fills
`contract_signed_date` for both tracks.
