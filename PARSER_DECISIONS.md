# Document Parser — Decisions for `agency_tracking` (Frappe)

This file records what was actually tested against the 4 sample template folders and
the exact strategy the implementing agent should follow. Do not re-litigate these
choices without re-running the same tests — they're based on empirical output, not
assumption.

Tested against:
- `kuwait contract style/KWAIT CONTRACT.docx`
- `saudi contract style/contract.pdf`
- `kuwait visa/EIKRAM S. ENDRIS VISA.pdf`
- `applicant passport/1.png`, `applicant passport/3.png`

## TL;DR decision table

| Source type | Extraction method | OCR needed? | Accuracy mechanism |
|---|---|---|---|
| `.docx` contracts | `python-docx` (tables/paragraphs) | No | regex on English column of each cell |
| Digital PDF contracts (Saudi-style) | `pymupdf` `page.get_text()` | No | regex on English lines only |
| Government PDF visas w/ obfuscated fonts (Kuwait-style) | `pymupdf` render → image, then MRZ parse | Yes | MRZ + checksum, not label OCR |
| Passport photos/scans (PNG/JPG) | `passporteye.read_mrz` | Yes (internal) | MRZ checksum digits — **mandatory** |

**Golden rule: wherever an MRZ (machine-readable zone) exists — passports and
visas — parse the MRZ and validate its checksums. Never trust free-text label OCR
for passport number / DOB / expiry / sex / nationality when an MRZ is present.**
MRZ is a fixed-width monospaced font designed for OCR and it carries per-field check
digits, so it is self-verifying. Printed label text is not.

## Dependencies to install in the bench's Python env

```
bench pip install pymupdf python-docx pytesseract passporteye opencv-python-headless scikit-image
```

System package (required by pytesseract/passporteye):
```
sudo apt install tesseract-ocr
```
Only the `eng` language pack is available/needed — do not waste time trying to get
an `ara` pack working. Every document tested has English mirrored alongside Arabic;
the Arabic text layer in these PDFs is frequently unrecoverable garbage anyway (see
below), so don't design extraction around it.

## Per-type findings and required implementation behavior

### 1. DOCX contracts (`python-docx`)
Parses natively, no OCR, no rasterization. But **do not assume clean key/value
table cells** — in the sample, each table cell is one big multi-line string with
label and value mashed together with tabs, e.g.:
```
"Employee Name:\tZENEBA AMID SHIFAW\nNationality: ETHIOPIA\nAge: 28"
```
Implementation: read `table.rows[i].cells[j].text`, then run **per-field regex**
against the English column specifically (columns are Amharic / English / Arabic in
that sample — confirm column order per template, it's not guaranteed universal).
Build one regex map per contract template/country, not a generic one — label
wording and line breaks differ by template.

### 2. Digital PDF contracts (Saudi-style, `pymupdf`)
Has a real embedded text layer — `fitz.open(path)` + `page.get_text()` returns
clean text for the English side. **The Arabic side of these PDFs comes out as
garbled Private-Use-Area glyphs** (broken/custom font encoding, no usable
ToUnicode CMap) — this is a font problem, not a code bug, and is not fixable by
switching libraries (pdfplumber gives the same garbage). Extraction plan:
1. `page.get_text()` per page.
2. Regex against English lines only (`Name:`, `Passport No:`, `Contract #`,
   `Visa Number #`, `Date of Issue:`, etc. — all present and clean).
3. Never attempt to parse the Arabic run in these documents.

Before trusting `get_text()` on any *new* PDF template, sanity-check: if the
extracted string contains a high ratio of control characters / repeats a single
short byte pattern, treat it as encoding-broken and fall through to strategy #3
(rasterize + OCR) instead.

### 3. Obfuscated-font PDFs — Kuwait e-Visa (`pymupdf` render + MRZ)
`page.get_text()` here returns pure garbage control-character sequences even for
the English label text — the font's own cmap is broken/obfuscated (this looks
deliberate, likely anti-scraping on the government's part). No text-layer strategy
works. Required pipeline:
1. Rasterize with `page.get_pixmap(dpi=300)`.
2. Full-page `pytesseract` OCR is usable for a human-review fallback but is noisy
   where Arabic and English overlap in the same visual block — **do not rely on it
   for passport-grade fields**.
3. Locate and OCR the MRZ band specifically (bottom ~10% of the visa card) and
   parse it as MRZ. In testing this reproduced the visa number, nationality, sex,
   DOB, and expiry with correct check digits, from an image where full-page OCR of
   the same fields was unreliable.
4. `passporteye.read_mrz()` also successfully parses this Kuwait visa MRZ (detected
   as `MRVA` type) with valid number/DOB/expiry checksums — prefer this over
   hand-rolled MRZ regex parsing since it validates check digits automatically.
   **Important: `read_mrz()` failed to auto-locate the MRZ on the full-page render**
   here — it only succeeded once fed a bottom-band crop. Always try full-image
   first, and if `read_mrz()` returns `None`, retry on a crop of the bottom 20–30%
   of the page before giving up.

### 4. Passport photo/scan images (highest accuracy requirement)
Use `passporteye.read_mrz(path)` as the primary and default path — this is the
most accuracy-critical document type per the user's requirement, and it is also
the one type where a purpose-built, checksum-validating tool is available and
confirmed working. Findings from the two test images:

- `3.png` (389×259, low-res, tightly cropped): full-image `read_mrz()` succeeded
  directly. `valid_score=98`, and **all** checksum flags true (`valid_number`,
  `valid_date_of_birth`, `valid_expiration_date`, `valid_composite`,
  `valid_personal_number`).
- `1.png` (745×831, higher-res but with a visible pink/yellow guilloche
  security-pattern background bleeding through the page): full-image `read_mrz()`
  returned `None`. Cropping to the **bottom ~20% of the image** before calling
  `read_mrz()` fixed it — same 98% score, same all-true checksums. The security
  background pattern appears to confuse PassportEye's region-detection step, not
  its OCR step.

Required implementation behavior:
1. Call `read_mrz(image)` on the original image first.
2. If it returns `None`, crop to the bottom 20–30% of the image (band containing
   the two/three MRZ lines) and retry.
3. If still `None`, queue for manual review — do not fall back to generic label
   OCR and present it as equally trustworthy.
4. **Never accept a passport-derived field into the record unless its
   corresponding `valid_*` checksum flag is `True`.** If any checksum fails,
   flag the whole record for human review rather than silently trusting a
   partially-parsed MRZ.
5. Store the raw MRZ text and the individual `valid_*` flags alongside the parsed
   fields in the doctype (as an audit trail / debug field), not just the final
   values — this lets support staff see *why* something was flagged instead of
   only seeing a wrong value.
6. Treat `names`/`surname` from the MRZ as lower-confidence than the numeric/date
   fields — MRZ separators (`<`) are the most common OCR confusion (e.g. `<` misread
   as `K`), and there's no checksum over the name fields to catch it. Where the
   source document also has printed (non-MRZ) name text, prefer that if you're also
   OCRing it, or at minimum diff the two and flag mismatches.

## Overall dispatcher logic the agent should implement

```
def parse(path):
    if path.suffix == ".docx":
        return parse_docx_contract(path)          # python-docx, no OCR
    if path.suffix == ".pdf":
        text = get_text_per_page(path)             # pymupdf
        if looks_garbled(text):                     # control chars / low printable ratio
            return parse_pdf_via_rasterize_and_mrz(path)   # render -> OCR/MRZ
        return parse_pdf_text(text)                 # regex on English lines
    if path.suffix in (".png", ".jpg", ".jpeg"):
        return parse_passport_image(path)           # passporteye first, crop-retry fallback
```

`looks_garbled(text)`: check for a high proportion of non-printable / control
characters, or the same short byte sequence repeating — this is what a
broken/obfuscated font's `get_text()` output looks like in practice (confirmed on
the Kuwait visa PDF).

## What NOT to do

- Don't try to get Arabic OCR/text working for these templates — every field
  needed is mirrored in English, and the Arabic layer is frequently either
  encoding-broken (PDFs) or not worth the added tesseract language-pack complexity
  (images). Time is better spent on per-template English regexes.
- Don't build one universal regex/label map across all contract templates —
  Kuwait-style and Saudi-style contracts differ enough (layout, wording, even
  whether fields are one column or three) that each template/country needs its own
  field map, versioned so a template redesign doesn't silently break extraction for
  old documents already in the system.
- Don't treat full-page generic OCR output as authoritative for any field that also
  appears in an MRZ. It's a fallback/human-review aid only.
- Don't skip the checksum validation step to "just get a value" — for a
  visa/immigration tracking system, a checksum-failed passport number is worse than
  no value, because it looks correct until someone acts on it.

## Suggested Frappe-side data model note

Whatever Doctype captures parsed passport/visa data should store per-field
confidence/validation flags (e.g. `passport_no_verified`, `dob_verified`), not just
the field value, so downstream workflows (e.g. approvals) can gate on "was this
machine-verified" vs "needs human confirmation."
