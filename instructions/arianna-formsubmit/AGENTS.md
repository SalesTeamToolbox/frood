# Arianna Dar - Contact Form Submitter Agent

> **This file is DOCUMENTATION, not a live prompt.** Unlike Arianna-Email
> and Arianna-Research (where the LLM reads AGENTS.md as its task prompt),
> this agent runs a Python workflow that bypasses the instructions file
> entirely. The only LLM interaction is one narrow message-generation call
> per prospect, and the prompt for that call is hardcoded inline in
> `frood/core/sidecar_orchestrator.py::_generate_form_message`. Edits here
> are for humans reading the Paperclip dashboard — they do not change
> the LLM's behavior.

You are Arianna Dar, Synergic Solar's dealer outreach specialist. This agent
reaches prospects who have a contact form on their website but no discoverable
email address. It's the third member of Arianna's outreach family, alongside
Arianna-Research (finds prospects) and Arianna-Email (handles inbound replies).

## Important: This agent runs a Python workflow, not a tool-use loop

Unlike Arianna-Research and Arianna-Email, most of this agent's work happens
in deterministic Python code inside the frood sidecar — not via LLM tool calls.
The LLM is used for exactly **one narrow task per prospect**: generating a 2-3
sentence personalized message to paste into the contact form.

Why this shape: earlier research-agent experiments showed that asking an LLM
to "call /check-duplicates and /import via http_request" dropped the required
`url` parameter, hallucinated company lists, and fumbled salvage synthesis
across three different models. Mechanical HTTP work belongs in code. The LLM's
only job here is the **creative** part: writing a good message. Code handles
everything else — selecting prospects, navigating the browser, detecting form
fields, filling, submitting, and writing the outcome back to Odoo.

See `frood/core/form_submitter.py` for the Playwright filler and
`frood/core/sidecar_orchestrator.py::_execute_form_submit_workflow` for the
orchestration.

## What each heartbeat does

1. **Fetch candidates** — GET `/api/v1/prospects/form-candidates?limit=5`
   (Odoo returns up to 5 prospects with `contact_form_url` set, no email,
   and no prior form-submission interaction).
2. **For each prospect, in sequence:**
   a. **Generate message** — one LLM call, 50-90 words, friendly tone,
      references their city and any `ai_personalization_context` the
      research phase captured. Ends with "Reply to arianna@synergicsolar.com
      if you'd like to learn more."
   b. **Navigate + fill + submit** — Playwright launches chromium headless,
      loads `contact_form_url`, checks for CAPTCHA (skip if present),
      detects name/email/company/phone/subject/message fields via CSS
      heuristics, fills them, captures a pre-submit screenshot, then either
      clicks submit (live mode) or stops (dry-run mode).
   c. **Log outcome** — POST `/api/v1/prospects/{id}/mark-form-submitted`
      with `{status, message_sent, response_text, screenshot_path, dry_run}`.
      Odoo creates an `interaction` row with `type=form_submission`,
      `channel=web_form`.
3. **Return a summary** — outcomes tallied by status, plus per-prospect lines
   for review in the Paperclip run log.

## Message voice (for the one LLM call per prospect)

Confident, analytical, helpful. NOT salesy. 2-3 sentences. 50-90 words.
- Mention Synergic Solar's dealer program.
- Mention that independent dealers **keep their own brand**.
- No emojis, no buzzwords, no exclamation points.
- End with: "Reply to arianna@synergicsolar.com if you'd like to learn more."
- No subject line, greeting, or signature — the form has separate fields
  for those, and the code fills them separately.

## Environment variables (controlled by ops, not by the LLM)

| Variable | Purpose | Default |
|---|---|---|
| `ARIANNA_FORM_SUBMIT_DRY_RUN` | `true` = fill but don't click submit; `false` = real submissions | **`true`** (safe default) |
| `ARIANNA_FORM_SUBMIT_LIMIT` | Max prospects to process per heartbeat | `5` |
| `ARIANNA_FORM_FILLER_NAME` | Name to use in the form's Name field | `Arianna Dar` |
| `ARIANNA_FORM_FILLER_EMAIL` | Email to put in the form's Email field (replies land here) | `arianna@synergicsolar.com` |
| `ARIANNA_FORM_FILLER_COMPANY` | Company field | `Synergic Solar` |
| `ARIANNA_FORM_FILLER_PHONE` | Phone field (set only if you want prospects calling) | `""` (empty → skipped) |
| `ARIANNA_FORM_FILLER_SUBJECT` | Subject field when present | `Solar dealer partnership opportunity` |
| `ARIANNA_FORM_SCREENSHOT_DIR` | Where pre/post screenshots are saved | `/opt/frood/.frood/form_submissions` |

## Business-hours guard

Enforced in code (`_BUSINESS_HOURS["form_submit"]`). Mon–Sat, 7 AM – 9 PM
US/Eastern. Outside those hours the run exits immediately with a "Skipped:
outside business hours" summary. Same guard as Arianna-Email and for the
same reason: these are real people on the other end of the form.

## Failure modes and their meanings

Each form-submit attempt creates a `synergic.dealer.prospect.interaction`
row with `interaction_type='form_submission'` and `channel='web_form'`.
The outcome status is captured in the `subject` field (e.g. `"Contact form
submission (captcha_blocked)"`) and in the `body` field, NOT in `sentiment`
— sentiment is a positive/neutral/negative enum reserved for reply analysis.

**Important retry semantics**: the `/form-candidates` endpoint excludes any
prospect that already has a `form_submission` interaction row, regardless
of its outcome. That means **every non-retry-able status below is a
permanent skip** — we will not attempt the same prospect twice. If you
want to retry a prospect (for example, a `captcha_blocked` site that has
since removed its CAPTCHA), manually delete the interaction row in Odoo
and the prospect will re-appear in the next candidate batch.

| Status | Meaning | Retryable? |
|---|---|---|
| `success` | Submit clicked, post-submit page redirected OR contained a known success marker ("thank you", "message sent", "received", etc.) | No — done |
| `submitted_unconfirmed` | Submit clicked but we couldn't prove the backend accepted it. Probably worked, but flagged for review. | No — assume success |
| `captcha_blocked` | reCAPTCHA, hCaptcha, or Cloudflare Turnstile detected on the page before fill. V1 does not attempt solves. | Only via manual interaction-row deletion |
| `no_form_detected` | Page loaded but we couldn't find both an email input and a textarea. Usually means the URL is wrong, the form is JS-rendered after a user action, or the page isn't actually a contact page. | Only via manual interaction-row deletion |
| `errored` | Navigation failed, timeout, unhandled exception. | Only via manual interaction-row deletion |
| `dry_run` | `ARIANNA_FORM_SUBMIT_DRY_RUN=true`. Fields filled, screenshots captured, submit button never clicked. | Yes — dry-run runs do NOT create interaction rows, so after flipping DRY_RUN off the same prospects re-appear in the candidate batch. Audit dry-runs via the frood journal and screenshots on disk. |

## Dogfood note

This agent was created partly to test the `/agent-prompt-review` skill
against a real-world case. The "good" review for this prompt should note
that almost all the work is already offloaded to Python — the only
creative step is message generation, which is the correct place for an
LLM. A prompt-review agent that flags this one as "high offload candidate"
would be wrong; this prompt is already post-refactor.

## What this agent does NOT do

- Does not handle reply emails (that's Arianna-Email)
- Does not find new prospects (that's Arianna-Research)
- Does not solve CAPTCHAs (skipped and marked captcha_blocked)
- Does not retry failed submissions (V1 design — wait for new heartbeat cycle)
- Does not contact prospects that already have a deliverable email address
  (email is preferred — form submission is the fallback channel)
