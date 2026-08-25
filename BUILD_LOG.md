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
- [x] 4. Contract parsing (both tracks) → Placement creation
- [x] 5. Corridor Definition engine (Saudi + Kuwait)
- [x] 6. transition() + gate table + Manager Override (Medical 2 gate)
- [x] 7. Clearance Step + ToDo permission scoping + LMIS→Ticketing→Departure auto-chain
- [x] 8. Financial ledger (income/expense, FX, accrual, batching, visibility wall)
- [x] 9. Reconciliation tool
- [x] 10. Complaints
- [x] 11. Notification pipeline
- [x] 12. Chat
- [x] 13. Reporting/dashboards
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

## Step 4 — what was built

`contract_parser.py` (app root, not a doctype): PyMuPDF text extraction +
`extract_contract_signed_date()` (English and Arabic date-label regexes) + `parse_contract_file()`
wrapper that resolves a Frappe file_url to a filesystem path. **Deliberately narrow** — the old
Gemini prototype's equivalent (`applicant_processing/utils/contract_parser.py`) extracts ~20
sponsor/employer/agency sub-fields via ~1000 lines of regex; nothing in Part B ties any of that
to a Placement field, so building it here would be speculative surface with no spec-required
consumer. The one field the spec actually calls for (Part A.4: "contract-age clock starts from
the contract's own signed date, extracted at parse time") is what's built, tested against both
a synthetic and a real generated PDF (PyMuPDF smoke-tested end-to-end via console, not just the
missing-file fallback path).

`Placement` gained `contract_file` (Attach) and `contract_signed_date` (Date) — the two fields
flagged as deferred in Step 3's log. New `placement_api.py`: `upload_contract()` (Standard
track — attaches a contract to the Placement Step 3 already created) and
`create_muayena_placement()` (Muayena track — the direct "contract in hand" entry Part A.1
describes, no portal or CV involved at all).

**Placement.validate() invariant revised** (was: "Muayena blocked, not wired in yet"; now: a
track-aware floor) — Standard requires `Applicant.status == "CV Generated"` (came through the
portal), Muayena requires `"Registered"` (their terminal intake status, since they never touch
CV Generated). This also required updating three Step-3 tests that had been asserting against
the old "Registered is enough" placeholder invariant — not a regression, the invariant simply
didn't exist correctly until this step gave Muayena a real creation path to test against.

**Real bug caught and fixed before commit:** `upload_contract()`'s first draft gated the "is
this an agency or staff" branch on `"Foreign Agency" in frappe.get_roles()`. That's wrong — the
special `Administrator` user is assigned literally every role in the system (verified via
console), so the check always took the agency branch and rejected Administrator as "not the
right contractor." Fixed to key off whether the session user has an actual linked `Contractor`
record instead, which is the real signal and doesn't misfire for Administrator/System Manager.
Worth remembering for every future permission check in this codebase: never gate on role
membership alone when `Administrator` needs to be handled correctly, check a concrete
relationship (linked record, assignment, ownership) instead.

**Verified:** `bench migrate` clean; 8 new contract-parser tests + 8 new placement-api tests +
revised Placement tests — 46/46 total across the whole app. Console smoke test generated a real
PDF with PyMuPDF and confirmed `contract_signed_date` extraction end-to-end (not mocked).
`pymupdf` added to `pyproject.toml` (was working only because it leaked in from the other app's
shared venv — now properly declared).

**Not yet done (deferred):** no gate/transition wiring for Placement's own lifecycle yet
(Selected -> Processing -> ...) — that's Corridor Definition (Step 5) and the full gate table
(Step 6).

## Step 5 — what was built

`Corridor Definition` (one per `destination_country`, unique) + child table `Corridor Step`
(`step_type`, `sequence_order`, `is_mandatory`) — exactly Part B's schema. `validate()` enforces
unique `sequence_order` and unique `step_type` within one corridor. New `corridor_engine.py`:
`get_corridor_steps()`, `get_first_step_type()`, `get_next_step_type()`, `is_last_step()` — all
pure data lookups, no country names hardcoded anywhere in the module. `install.py` seeds Saudi
Arabia (LMIS Clearance → Taeshir → Injaz → Embassy/Wakala) and Kuwait (LMIS Police Clearance →
Telesign → Kuwait Embassy → LMIS Work Permit) per the business SRS's Stage 5 sequences, all
steps mandatory (the spec doesn't call out an optional step in either corridor yet — `Corridor
Step.is_mandatory` exists and works, just nothing sets it to 0 in the seed data).

**Proved the actual design goal, not just built the schema.** Part A.3's whole point is "new
corridors are added as data, never a code deployment" — `test_new_corridor_added_as_pure_data_no_code_change`
inserts a throwaway UAE corridor with an optional third step, using the exact same
`corridor_engine` functions already exercised against the seeded Saudi/Kuwait data, and gets
correct ordering/mandatory-flag results with zero code changes. That test is the actual
acceptance criterion for this step, not incidental coverage.

**Verified:** `bench migrate` clean; 8 new tests (3 Corridor Definition invariants, 5 corridor
engine, including the no-code-change proof) — 54/54 total. Manually ran `create_corridors()`
once via console (same catch-up situation as Step 1's roles — this site was installed before
the seeding code existed); confirmed `Saudi Arabia` and `Kuwait` both exist with correct steps.

**Not yet done (deferred):** nothing in this step touches Placement or Clearance Step yet —
Corridor Definition is pure reference data until Step 7 (Clearance Step) starts creating
per-candidate step records from it, gated by Step 6's expanded `STAGE_GATES`.

## Step 6 — what was built

**Retrofitted a gap from Step 1, not scope creep:** Part C says `transition()` "writes the
Process Event audit entry atomically" — that was true of every `transition()` call since Step 1,
but the `Process Event` doctype itself didn't exist yet (nothing needed it urgently until
Manager Override, this step's actual deliverable, needed somewhere to record the mandatory
written reason). Built now: `Process Event` (Part B's audit trail — `reference_doctype`/
`reference_name` dynamic link, `event_type` Transition/Override/Cancelled/Restored,
`from_status`/`to_status`/`actor`/`remarks`), immutable by design (no doctype permission grants
write/delete/create to anyone but System Manager — `transition()` writes rows via
`ignore_permissions=True`, the only sanctioned writer). `get_permission_query_conditions()` in
`process_event.py` is the addendum's own scoping function transcribed verbatim (Admin/Manager
see everything, Finance Manager sees Applicant-Transaction-linked rows only, everyone else sees
only their own actions) — wired into `hooks.py`. The Finance Manager and Complaint Manager
branches are inert until Step 8/10 create the doctypes they reference; the function is complete
now because CLAUDE.md says build permission logic alongside its doctype, not retrofit it later.

`transition()` gained `override`/`override_reason` params: a gate-blocked move throws normally
unless `override=True`, which then requires `{Manager, Admin}` role AND a non-empty
`override_reason` (business-workflow-srs.md: "always with a written reason") — enforced inside
`transition()` itself, not any caller. Every call now logs a `Process Event`, `Transition` or
`Override` depending on whether a gate was actually bypassed. **Override only ever bypasses a
gate, never the `ALLOWED_TRANSITIONS` topology itself** — flagging this as a judgment call since
the spec doesn't explicitly say either way, but nothing in the business workflow describes
skipping an entire lifecycle stage, only forcing past a blocked condition.

`Placement` gained its full status vocabulary (`Selected → Processing → Stamped → Ticketed →
Departed`, matching Part A.2 stages 5–9) and `medical_2_status` (the pre-departure ~72h check,
distinct from the Applicant's earlier registration-time FIT check). `STAGE_GATES` gained
`("Ticketed", "Departed")` → `medical_2_gate` — the step's explicitly-named deliverable.
`Selected→Processing` and `Stamped→Ticketed` are intentionally left ungated (nothing to check
yet); `Processing→Stamped`'s real gate ("all mandatory corridor steps issued") depends on
Clearance Step and is explicitly Step 7's job, not stubbed here.

New `placement_api.py:advance_placement()` — a direct/manual progression + override entry
point, restricted to internal staff (Placement's doctype permissions grant nothing to Foreign
Agency, verified by test). This is scaffolding for Step 7's real auto-chain (LMIS → Ticketing →
Departure), not a replacement for it.

**Verified:** `bench migrate` clean; 13 new tests (state machine mechanics — ungated transitions
log correctly, gate blocks, override requires role + reason, disallowed edges never overridable;
Process Event validation + permission scoping; `advance_placement` wiring) — 67/67 total across
the app.

**Not yet done (deferred):** the real Processing→Stamped gate, Clearance Step doctype, ToDo-based
per-row permission scoping, and the LMIS→Ticketing→Departure auto-chain are all Step 7.

## Step 7 — what was built

`Clearance Step` (standalone, Part B: `placement`, `step_type`, `status`, dates, `reference_no`,
`amount`, `payment_status`) + `Step Officer Mapping` (Part B's named support doctype:
`step_type` → `default_officer`, config data, Manager/Admin only). New `clearance_engine.py`:
`create_clearance_steps()` materializes one row per `Corridor Step` when a Placement enters
Processing (reads `corridor_engine`, doesn't hardcode any country), auto-assigning a ToDo where
a `Step Officer Mapping` exists. `clearance_api.py`: `start_clearance_step`/
`complete_clearance_step` (assigned officer or Manager/Admin only — Part G's "per-row" scoping
applies to writes, not just reads) and `reassign_clearance_step` (Manager/Admin only, Part A.2's
"reassignable by a manager if needed").

**ToDo-based permission scoping** (Part G: "Clearance Officer... cross-type, cross-candidate,
per-row"): `Clearance Step.get_permission_query_conditions()` restricts non-Manager/Admin users
to rows where an Open ToDo assigns them that exact row — nothing about step_type or which
placement, purely "am I assigned this one." Wired into `hooks.py` the same way as Process
Event's.

**The real Processing→Stamped gate landed** (`all_mandatory_clearance_steps_complete`, deferred
from Step 6): all `is_mandatory=1` Clearance Steps for the placement must be `Complete`.

**LMIS→Ticketing→Departure auto-chain**: `TRANSITION_SIDE_EFFECTS` (new mechanism in
`state_machine.py`, `(doctype, to_status) -> callable`, runs after a transition commits — same
shape as `STAGE_GATES` but for orchestration instead of validation) registers
`create_clearance_steps` on Placement reaching Processing, and `chain_lmis_officer_to_ticketing`/
`_departure` on reaching Stamped/Ticketed — both look up whoever was assigned the LMIS-family
Clearance Step (matched by `step_type` prefix, not a per-corridor exact-name list — "LMIS
Clearance", "LMIS Police Clearance", "LMIS Work Permit" all match) and auto-create a ToDo
against the Placement for that same officer.

**Real bug caught and fixed before commit:** the first cut of `get_lmis_officer()` only looked
at ToDos with `status="Open"`. By the time the chain actually fires (Stamped/Ticketed — i.e.
after Processing is done), the LMIS step is normally already Complete and its ToDo Closed by
`complete_clearance_step()`, so the officer lookup always returned `None` and the chain silently
did nothing. Fixed by dropping the status filter and taking the most recent ToDo instead —
"officer holding LMIS" means whoever held it, not whoever currently has it open.

**Real ordering bug caught and fixed:** `test_clearance_engine.py`'s tests need the Saudi/Kuwait
corridors to exist, but corridor seeding had only ever happened as a side effect of
`test_corridor_engine.py`'s own tests calling `create_corridors()`. Alphabetically,
`test_clearance_engine` < `test_corridor_engine`, so the clearance tests ran first and failed
against unseeded corridors. Fixed properly, not by sprinkling seed calls into every helper:
added `install.py:before_tests()` wired to Frappe's standard `before_tests` hook, so roles and
corridors exist before any test module runs, regardless of alphabetical order. This is also just
the correct fix for the same latent risk in production-adjacent scripts, not merely a test
artifact.

**Also learned (empirically, not assumed):** `frappe.get_list()` raises `PermissionError` for a
role with zero base doctype-permission grant — it does not silently return an empty list. A test
that assumed the latter was corrected to expect the former.

**Verified:** `bench migrate` clean; 26 new tests (Clearance Step permission scoping, corridor-
driven step creation, auto-assignment, the auto-chain, the real Processing→Stamped gate, a full
Selected→Departed lifecycle proof, and `clearance_api` permission checks) — 80/80 total across
the app.

**Not yet done (deferred):** flight-specific fields (reschedule history, cancel reason, the
Ticketed→Stamped cancel-reversion edge) weren't built — Part I doesn't name them under any
specific step and nothing downstream depends on them yet; can be added without disturbing this
step's work if/when needed. `Step Officer Mapping` has no seeded data (deliberately — it's real
staff-to-role config, not reference data like Corridor Definition, so there's nothing genuine to
seed yet).

## Step 8 — what was built

`Applicant Transaction` (the ledger — Part B: `transaction_type`, optional `placement`,
`stage_logged_at`, `amount_original`/`currency_original`/`fx_rate`/`fx_rate_date`/`amount_birr`,
`status` Active/Voided). `FX Rate` (a cache, not a live lookup — `currency`+`rate_date` →
`rate_to_birr`). `Contractor` gained `batch_mode`/`batch_threshold`/`default_commission_rates`
(child `Contractor Commission Rate`) at **field-level permlevel 1**, restricted to Finance
Manager/Admin/System Manager via a second permission row per addendum's "field-level, not
doctype-level" instruction — Manager can still edit the rest of Contractor but not this section.
`Placement` gained `manual_commission_amount`/`manual_commission_currency` (Muayena's
always-manual rate, Part A.1). `Commission Batch Request` + child `Commission Batch Item`.
`Process Event.event_type` gained `Voided` (the addendum's own snippet uses it; `validate()`
now requires remarks for both `Override` and `Voided`).

New `finance_engine.py` (pure logic, mirrors `clearance_engine.py`'s role) + `finance_api.py`
(whitelisted entry points, mirrors `clearance_api.py`): `get_fx_rate`/`record_fx_rate`
(exact-date cache lookup falling back to the most recent earlier rate — Part H's "historical
lookup for backdated entries"); `get_commission_rate` transcribed directly from Part D's
pseudocode (Muayena → `manual_commission_amount`, throws if unset; Standard →
`Contractor.default_commission_rates` for the destination country, throws if unconfigured);
`accrue_commission` (idempotency-guarded — checked by testing it twice back-to-back and
confirming only one transaction exists); `create_batch_request` as the single function both the
automatic (threshold-triggered) and manual batching paths converge on, per Part D's explicit
instruction not to duplicate that logic.

**The visibility wall is genuinely a hard zero, not just an absent grant.** Doctype-level
`read`/`write`/`create` on `Applicant Transaction` and `Commission Batch Request` are granted
only to Finance Manager/Admin/System Manager (so anyone else is denied outright, same as
Clearance Step in Step 7) — **and** `get_permission_query_conditions()` independently returns
`"1=0"` for everyone else, as explicit belt-and-suspenders matching Part D's own emphasis ("not
a soft filter, a hard zero") in case a future step ever broadens the doctype-level grant without
re-deriving this reasoning. Write is split from read exactly per the addendum:
`log_stage_expense`/`log_stage_income` insert with `ignore_permissions=True` after checking
`is_assigned_to_placement()` (an open ToDo on the placement's Clearance Step or on the Placement
itself, from Step 7's ToDo infrastructure) — an assigned officer can create a row but still
can't `frappe.get_list` the ledger. **No `delete: 1` granted to any role on `Applicant
Transaction` or `Commission Batch Request`, including System Manager** — a deliberate deviation
from every other doctype's permission template so far, because "no hard delete, ever" (addendum)
needs to actually hold, not just be a comment; `void_transaction()` (Finance Manager/Admin only,
mandatory reason, logs a `Voided` Process Event, row stays visible with status flagged) is the
only sanctioned way to deactivate a row.

**A real architectural bug was caught and fixed systemically, not patched locally.**
`TRANSITION_SIDE_EFFECTS` callables run *after* `transition()` has already called `doc.save()`
and logged the `Process Event` — both already committed. The first cut of `accrue_commission`
let `get_commission_rate`'s `ValidationError` (missing manual commission amount, a completely
normal state for a Placement that just reached Departed before Finance got to it) propagate
straight out of `transition()`. That makes the *whole transition* look like it failed to the
caller — while the status change had, in fact, already gone through. A caller that saw the
exception and assumed nothing happened, or retried, would be wrong; worse, it's silently
inconsistent with the "transition() is the only sanctioned status-change path" guarantee the
whole state machine is built on. This isn't specific to commission accrual — Step 7's
`create_clearance_steps` (which calls `get_corridor_steps`, itself capable of throwing if a
destination has no configured corridor) had the exact same latent exposure, just never
triggered by a test. Fixed at the one correct level — inside `transition()` itself, wrapping the
side-effect call in `try/except` and routing failures to `frappe.log_error` — rather than adding
defensive try/except to every individual side-effect function and hoping every future one
remembers to. The distinction this enforces going forward: `STAGE_GATES` may block a transition;
`TRANSITION_SIDE_EFFECTS` may not — they're best-effort automation layered on top of a
transition that has already legitimately happened.

**Verified:** `bench migrate` clean; 39 new tests (FX cache + historical fallback, rate
resolution for both tracks, idempotent accrual, a full lifecycle proof that accrual fires on
reaching Departed, manual and auto-threshold batching, the write/read split, the visibility wall
against a live `frappe.get_list` call — not just the query-condition function in isolation, void
with mandatory reason and Process Event logging, field-level permlevel on
`default_commission_rates`) — 109/109 total across the app. `fetch_daily_fx_rates()` (the
scheduled live-API fetch) is the one exception to "verified, not just written" in this entire
build: it's wired into `hooks.py`'s daily scheduler and calls a real, keyless API
(`frankfurter.app`), but nothing in this session exercised it against live network access, and
Gulf-currency (SAR/KWD/AED/QAR) coverage on a free ECB-sourced API isn't guaranteed. Flagged in
the function's own docstring — verify before relying on it in production (Step 15), and treat
`record_fx_rate`/manual entry as the load-bearing path until then.

**Not yet done (deferred):** the reconciliation half of Part A.6 ("official bank/payment
statements can be uploaded and matched automatically against what's owed") is explicitly Step 9,
not this one.

## Step 9 — what was built

`Bank Statement` (`statement_file`, `uploaded_by`, `status`, child `lines`) + `Bank Statement
Line` (`statement_date`, `reference`, `amount`, `match_status`, `matched_batch`) — Finance
Manager/Admin/System Manager only, same as the rest of the financial doctypes, no `delete: 1`
(consistent with Step 8's "no hard delete" stance — a source document shouldn't disappear
either). New `reconciliation_engine.py`: `parse_bank_statement_csv()` and
`match_statement_lines()`; `reconciliation_api.py`: `upload_bank_statement()` and
`manually_match_line()` (the escape hatch for ambiguous matches).

**Scope call, flagged rather than silently made:** Part A.6 says statements "can be uploaded and
matched automatically" but doesn't describe a specific bank's export format. Rather than guess
at a real bank's layout with no sample to build against — the exact anti-pattern flagged in Step
4's contract-parser scope note and in the original gap analysis of the Gemini prototype (~1000
lines of regex against an assumed format) — this defines its own plain CSV format (`date,
reference, amount`). The genuinely spec-required, testable part is the **matching logic**, not
the file format, so that's where the real engineering went.

**Matching algorithm** (`settle_batch_request()` — the same function `finance_api.settle_batch`
uses, per the "one function both paths converge on" pattern established for batching in Step
8): for each unmatched line, find unsettled `Commission Batch Request`s whose `total_amount_birr`
matches within a cent. Exactly one candidate → auto-match and settle. Multiple candidates → only
auto-match if exactly one candidate's batch name or contractor name appears in the line's
reference text; otherwise leave `Unmatched` for a human rather than guessing. Already-settled
batches are excluded from candidates so a statement re-matched twice doesn't misfire.

**Real bug caught and fixed:** the first test run had two failures where an amount that should
have matched exactly one candidate matched zero. Cause: `departed_placement()` (the Step 8 test
helper) always used the same hardcoded commission amount, so unsettled batches from *earlier*
tests in the same run (e.g. Step 8's own batching tests, which never settle what they create)
were still sitting in the DB with the identical `total_amount_birr` as the batch a reconciliation
test had just created — turning an intended single-candidate match into an accidental multi-
candidate one. Same root cause shape as Step 7's ordering bug (shared mutable DB state across a
whole test run), different manifestation. Fixed by making the test helper's amount a
deterministic function of the test tag rather than a shared constant, so unrelated tests can
never collide on `total_amount_birr` — a general lesson for any future test needing an
"amount," not just this step's.

**Verified:** `bench migrate` clean; 10 new tests (CSV parsing incl. malformed-row tolerance,
unambiguous match, ambiguous match correctly left unmatched, reference-text disambiguation,
already-settled batches excluded, end-to-end upload→parse→match, manual-match escape hatch, and
permission checks on both) — 119/119 total across the app.

## Step 10 — what was built

`Complaint` (Part B: linked to `Placement`, resolution states — `New`/`Unresolved` then one of
`Resolved`/`Returned - Free Replacement Required`/`Escalated`/`Dismissed`, `Dismissed` requiring
`resolution_notes` per business-workflow-srs.md). Default doctype sort is `creation asc` (oldest
first) matching the spec's explicit UX requirement directly, backed by `complaint_api.py`'s
`list_unresolved_complaints()` for the same guarantee at the API layer. `state_machine.py` gained
Complaint's transition graph and a new gate, `within_free_replacement_window` (Part A.4's 3-month
clock, measured from `Placement.departed_on` — a new field, stamped once by
`Placement.stamp_departed_on()` the first time a placement reaches `Departed`, deliberately not
reusing `modified` since that timestamp can move for unrelated reasons afterward).

**Resolution is genuinely restricted, not just documented as restricted.** Master spec Part A.5:
"Only Complaint Manager and Admin can move resolution status" — `complaint_api.py` enforces this
literally (not carving out an exception for the New→Unresolved acknowledgment step, since the
spec's sentence is unqualified). `create_complaint()` is broader (any recognized internal staff
role, or the owning agency's own linked Contractor for their own placement only) since creation
isn't the restricted action, resolution is.

**Free replacement wired all the way through, not just as a status label.** `Placement` gained
`is_free_replacement`, `free_replacement_for_complaint`. `portal_api.select_candidate()` gained
an optional `free_replacement_for_complaint` parameter — validated against the complaint's status
(must be exactly `Returned - Free Replacement Required`), the calling contractor (must be the
same one the complaint belongs to), and single-use (a second attempt against an already-consumed
complaint is rejected). This reuses the *exact same* selection function every Standard-track
candidate goes through, per business-workflow-srs.md's own instruction ("goes through the exact
same journey from Stage 4 onward as any newly selected candidate") — not a parallel, bespoke
"replacement" code path. `finance_engine.accrue_commission()` skips billing entirely for
`is_free_replacement` placements (not an idempotency no-op — there was never going to be a
commission transaction for this one).

**Real inconsistency caught before it shipped, not after:** the first cut of
`resolve_complaint()` restricted every call — ordinary resolution *and* Manager Override alike —
to `{Complaint Manager, Admin}`. But `transition()`'s own override enforcement requires `{Manager,
Admin}` specifically (established in Step 6, applied uniformly to every gate in this build). A
plain Manager — who business-workflow-srs.md's general override principle ("Manager/Owner — can
override a blocked step... always with a written reason") clearly means to cover — would pass
`transition()`'s internal check but never reach it, rejected by `resolve_complaint()`'s own gate
first. Fixed by widening `resolve_complaint()`'s allowed roles to include Manager specifically
when an `override_reason` is supplied, keeping ordinary (non-override) resolution moves at the
literal Complaint-Manager-and-Admin-only reading of Part A.5. Caught by writing the override test
itself and noticing the roles wouldn't line up — a reminder that a spec sentence naming one role
for the normal case doesn't override a *different*, already-established rule for the exceptional
case; the two need to be reconciled explicitly, not left to whichever check happens to run first.

**Verified:** `bench migrate` clean; 21 new tests (Dismissed reason requirement, complaint
creation permission split between agency/internal-staff/nobody, oldest-first ordering,
resolution-role restriction, the free-replacement window gate both inside and outside the 90-day
boundary — including via Manager Override — and the full select→bill-skip and single-use-credit
flows) — 140/140 total across the app.

**Not yet done (deferred):** notifying anyone that a complaint was logged, or that a free
replacement is now available, is Step 11 (Notification pipeline) — Complaints exist and resolve
correctly now, but nothing pushes a message about them yet.

## Step 11 — what was built

`Notification Config` (single doctype: VAPID keys, WhatsApp Cloud API credentials,
`contract_age_threshold_days`), `Push Subscription` (per-device, Part B), `Comms Log` (the
delivery queue, Part B). `notification_engine.py:notify()` transcribed directly from Part E's
pseudocode — insert a `Pending` `Comms Log` row, attempt delivery immediately,
`attempt_push_delivery()` never raises (catches everything, records `Failed` + the error +
increments `attempts`). Retried on next login (`hooks.py: on_login`) and on new Push Subscription
registration (`notification_api.subscribe_to_push`) — Part E's "notify even if offline, deliver
once back online," both halves wired, not just one.

**`notify()` is deliberately not whitelisted.** The first instinct (matching Part E's function
signature literally) was to expose it directly, but that would let any authenticated user
notify *any other* user by name — a real vector for harassment/spam that the rest of this
build's permission discipline would otherwise contradict. Caught before writing a single test
against it, by asking "who's allowed to call this with an arbitrary `user` argument?" the same
way every other whitelisted function in this build has been scoped. Only
`notification_api.subscribe_to_push` (self-service, `frappe.session.user` only) and the manual
watchdog trigger are client-facing; `notify()` itself is called only from other engine code
(`clearance_engine`, `watchdogs.py`, and Step 12's chat).

**Assignment alerts**: `clearance_engine.assign_clearance_step()` and the LMIS→Ticketing→
Departure auto-chain (Step 7) both now call `notify()` — the same event that creates a ToDo also
queues a notification, so nobody's assignment sits silently invisible until they happen to open
Desk.

**Three watchdogs** (`watchdogs.py`, Part E's named list, scheduled via `hooks.py`):
`medical_expiry_watchdog` (Applicant.medical_expiry_date at exactly 14/10/7/3/1 days out —
"repeatedly counting down... then closer warnings," daily), `contract_age_watchdog`
(`Placement.contract_signed_date` older than the admin-configured threshold and not yet
Departed, daily), `wakala_reminder_watchdog` (unpaid `Embassy/Wakala` Clearance Steps, both Push
and WhatsApp per the spec's explicit pairing, `hooks.py` cron `"0 9 * * 1,4"` for "twice a
week"), plus `notification_api.trigger_wakala_reminder` as the manual escape hatch
business-workflow-srs.md explicitly calls for. Recipient resolution reuses Step 7's
`get_lmis_officer()` — no new "who owns this placement" concept invented; a placement with no
assigned officer yet is silently skipped rather than guessing a recipient.

**Real bug caught and fixed by the test suite itself, not by inspection:** the first watchdog
tests manually created an `Embassy/Wakala` Clearance Step for assertions to check against — but
the Saudi corridor (Step 7) already auto-creates one when a placement enters Processing. Two
unpaid Wakala steps on the same placement meant the watchdog correctly found and notified about
both, and a test asserting "exactly one push notification" failed — correctly identifying the
test fixture as wrong, not the watchdog. Fixed by using the corridor's own auto-created step in
the fixture instead of inserting a redundant second one.

**Verified:** `bench migrate` clean; 19 new tests, including the queue/retry mechanics (a failed
delivery's error message changes from "no subscription" to a VAPID-config error after
registering one, proving the retry actually re-ran rather than being silently skipped) and a
mocked `pywebpush.webpush` call to exercise the success-path logic without needing real
credentials — 159/159 total across the app. Consistent with Steps 8/9's honesty standard: actual
push/WhatsApp delivery over a real network, with real credentials, has not been exercised in this
build and is flagged as such in `notification_engine.py`'s own module docstring.

**Not yet done (deferred):** Chat (Step 12) will reuse this exact pipeline per Part E ("Chat adds
`frappe.publish_realtime`... falling through to the same queued path when not [online]") — no
chat-specific doctypes or logic were built in this step.

## Step 12 — what was built

Added `Communication Manager` to `install.py`'s role list — it isn't in the master spec's
original Part G table, only introduced by the addendum ("Agencies talk only to Communication
Manager"), which explicitly overrides/extends Part G. `Chat Thread` (`thread_type`
Agency/Internal, `contractor` — the isolation boundary for Agency threads, `context_type`/
`context_reference`, child `participants`) + `Chat Thread Participant` (`user`,
`last_read_at` — read receipts as a per-participant marker, not a separate doctype) + `Chat
Message` (`sender`, `message`, `mentioned_applicant`/`mentioned_placement`). `Contractor` gained
`communication_manager` (validated to actually hold that role, same pattern as the existing
`user`/Foreign-Agency check).

**Resolved the addendum's explicitly-flagged open design call** ("round-robin or per-contractor
mapping — pick before building create_agency_thread"): per-contractor mapping when
`Contractor.communication_manager` is configured (continuity), round-robin among all
Communication Manager users otherwise (so an unconfigured contractor is never simply blocked).
Documented as a judgment call in `chat_engine.py`'s own docstring, not silently decided.

**Every rule from the addendum's Chat section is enforced, not just documented:**
`validate_thread_participants()` (agencies can't message each other or anyone but a
Communication Manager/Admin); Agency threads are structurally fixed at exactly two participants
(`Chat Thread.validate()`) and `add_participant()` refuses them outright — "adding participants
to an agency thread stays restricted," enforced at both the API and doctype level, not just one;
`@mentions` check the mentioned record's own read permission before allowing the message
(`send_message`) — "the mention is a link, not a permission grant"; `get_placement_officers()`
is transcribed from the addendum's own code snippet.

**The addendum's explicit test requirement was honored, not skipped.** "Agencies cannot know
other agencies exist... this needs an explicit test, not just reliance on the participant
filter" — `test_agency_cannot_see_another_agencys_thread` creates two agencies with their own
threads and asserts, from Agency B's own session, that Agency A's thread is absent from
`list_threads()` *and* that `get_thread_messages`/`send_message` against it both raise
`PermissionError`. `list_threads()` itself carries the belt-and-suspenders the addendum implies:
a Foreign Agency caller gets filtered by their own `contractor` in addition to the participant
filter, not instead of it.

**Two real bugs caught and fixed, both instances of lessons already learned earlier in this
build, not new categories:** (1) `validate_thread_participants()`'s first draft, transcribed
close to the addendum's literal pseudocode, checked `"Foreign Agency" in frappe.get_roles(...)`
— which breaks for Administrator (every role, confirmed back in Step 4) and wrongly rejected an
agency messaging Administrator as "agencies cannot message each other." Fixed the same way Step
4's `upload_contract()` was: key off an actual linked `Contractor` record, not role membership.
(2) A test assumed round-robin routing would land on the specific Communication Manager it had
just created — false by the time this test runs in a shared suite with many prior tests' managers
already accumulated. Fixed by pinning `Contractor.communication_manager` explicitly instead of
relying on round-robin's outcome, the same "don't assume isolation the shared DB doesn't
actually give you" lesson from Steps 7, 9, and 11.

**Verified:** `bench migrate` clean; 26 new tests (thread-shape invariants, participant
validation rules including the Administrator edge case, per-contractor vs. round-robin routing,
thread reopening instead of duplication, the full agency↔manager and internal staff↔staff message
flows, mention permission checks, read-receipt scoping to the caller's own row, and the
addendum's explicit isolation test) — 185/185 total across the app.

**Not yet done (deferred):** `frappe.publish_realtime` is called unconditionally alongside
`notify()` on every message (Part E: "falling through to the same queued path when not
[online]") — actual live browser presence/online-detection was not built or verified, consistent
with this build's running honesty standard about what's genuinely exercised (Steps 8/9/11) vs.
plausible-looking. The realtime call itself is a real, correct Frappe API call; what's unverified
is whether a real connected client actually receives it end-to-end, which needs a live socketio
client to exercise (Step 14, when a real frontend exists to test against).

## Step 13 — what was built

`report_api.py`: `get_daily_work_report`, `get_staff_performance_report`,
`get_complaint_aging_report` (Manager/Admin — "management visibility," business-workflow-srs.md
Part 8), `get_financial_overview` (Admin-only specifically, per Part F — the Step 8 financial
wall applies to reporting too, not just the raw ledger). `Clearance Step` gained `completed_by`
— the one genuinely new field this step needed, since nothing previously captured who finished a
step (the ToDo that tracked assignment is closed by completion time, per Step 7).

**Built on existing audit data wherever the question was really "how many transitions of this
kind happened," rather than adding new counters.** `Process Event` (Step 6) already records
every `Placement` status change with a real timestamp and actor — `tickets_booked` and
`departures_confirmed` (both the aggregate report and the per-staff breakdown) read directly
from it. No duplicate logging, no new doctype needed for something the state machine already
tracks faithfully.

**Deliberately did not invent staff attribution where none exists.** Per-staff performance
skips "medicals processed" specifically — nothing in this build records who recorded an
Applicant's medical result, and fabricating an attribution (e.g. guessing from whoever last
edited the record) would be presenting a guess as data. Flagged in the function's own docstring
rather than silently omitted or faked.

**Complaint aging returns individual per-complaint ages, not an average.** business-workflow-
srs.md's own framing — "how many are still open and *for how long*... forgotten at the bottom of
a list" — is explicitly about surfacing outliers, which a single averaged number would hide.
Sorted oldest-first, same guarantee as Step 10's `list_unresolved_complaints`.

**Real bug caught by the test suite, not inspection — the "plain date string as a Datetime
BETWEEN bound" trap:** the first cut of every date-range filter passed `from_date`/`to_date`
straight through as `["between", [from_date, to_date]]`. That's correct for `Date`-typed columns
(`medical_issue_date`, `Clearance Step.date_completed`, `Commission Batch Request.settled_on`)
but silently wrong for `Datetime`-typed ones (`CV Record.generated_on`, and the framework's own
`creation` field used throughout for `Process Event`/`Applicant Transaction`): MySQL treats a
bare date string as that day's midnight, so the upper bound of a same-day range excludes every
row with a nonzero time — which is nearly all of them. A test that explicitly backdated a CV
Record to `"2020-06-15 10:00:00"` and then queried the report for `2020-06-15` caught this
directly (`cvs_created` came back `0`). Fixed with a `_day_range()` helper (`00:00:00` to
`23:59:59`) applied specifically to the three `Datetime` fields, left alone for the genuinely
`Date`-typed ones — this needed distinguishing per-field, not a single blanket fix, since
applying `_day_range()` to an actual `Date` column would have been harmless but pointless, while
missing it on any `Datetime` column would have silently under-reported forever.

**Verified:** `bench migrate` clean; 9 new tests, every one backdated to a fixed historical date
(`2020-06-15`, used by no other test in the suite) rather than "today" — a deliberate departure
from this build's usual per-test-tag isolation strategy, because these functions `COUNT` across
the *entire* shared test-run database by date range, so hundreds of other tests' same-day
fixtures would otherwise inflate every assertion regardless of how uniquely each test's own
records were tagged — 193/193 total across the app.
