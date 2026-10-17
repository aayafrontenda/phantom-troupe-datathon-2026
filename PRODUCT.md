# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Vite + React + TypeScript + Tailwind, as set in `docs/tasks/FRONTEND.md`. The build output `frontend/dist` is committed and served by the FastAPI backend, which falls back to `backend/static/` while `dist` is missing. Node is not required on the deployment machine.

## Users

Two audiences, weighted equally:

- **Bank cash-control reviewer.** A ForteBank employee who checks overhead-camera recordings of a teller's cash desk for possible cash-discipline violations. Today they watch the video by hand. They upload a recording, read the verdict, jump to each flagged moment, check the evidence frames against the cited rule, and confirm each finding or mark it as a false alarm. The result is a prompt for human review, not a final legal or disciplinary conclusion.
- **Datathon 26 jury.** They score the product through the API automatically, then open the public URL, possibly on a phone, to judge product readiness. Shortlisted teams give a 5-minute live pitch with 2 minutes of questions. A judge opening the link for the first time must be able to upload a video without any guidance.

## Product Purpose

CashGuard analyzes an overhead cash-desk video (.mov, about 29 MB, 10–145 s, no audio) and reports one of two verdicts: "No violation detected" or "Signs of possible violations detected". For each possible violation it gives:

- the violation type;
- a timecode in seconds;
- a plain description of what is visible and why it may be a violation;
- 1–3 JPEG evidence frames;
- the rule, from Republic of Kazakhstan regulations (NBRK acts, adilet.zan.kz): document, clause and quote.

Success means the reviewer reaches a defensible decision about a recording in a fraction of the time manual viewing takes, and every claim on screen can be traced to a visible frame and a real legal source.

## Positioning

The system shows its reasoning, not only its result. Data already produced by the backend makes the whole chain inspectable:

- per-frame state tracks (`timeline`: people, screen on, phone, drink, bag);
- the candidate moments the detector chose and why (`meta.candidates`);
- what the local vision-language model saw in each window (`meta.scenes`);
- each rule's kind (direct, indirect or internal regulation) and its caveat.

The UI can show the full path from video frame to observation to legal clause. It also states openly where a finding rests on an indirect norm or cannot be verified from video. Everything runs locally, and no frame leaves the server.

The UI takes its interaction conventions from professional video-surveillance consoles (camera-monitoring software): a scrub timeline with event markers, an alarm list with acknowledge, and frame stepping.

## Operating Context

- **Required flow (case section 4):** upload → processing status → verdict → per-violation cards (type, timecode, description, evidence frames, rule source). The same results come from a keyed REST API (`POST /api/v1/analyze`, `GET /api/v1/jobs/{id}`, `X-API-Key`), which the jury polls automatically. The UI uses parallel `/ui/api/*` endpoints with no key.
- **Processing time:** up to a few minutes per video. The hard limit is 5 minutes from upload, including queueing. A single GPU worker processes one job at a time, so a queue position exists.
- **Live mode:** the browser streams JPEG frames over WebSocket `/ui/api/live` and receives detections and alerts in real time. The planned sources are the laptop camera and RTSP.
- **Reviewer feedback:** confirm or reject per violation via `POST /ui/api/jobs/{id}/feedback`, stored as metadata only.
- **Hosting:** the service runs on a single team laptop (RTX 4070) exposed through a Cloudflare tunnel. The public URL may be opened from a phone over mobile data.
- **Rule data:** comes from `ml/rules_kb.yaml`, and `docs/norms.md` is generated from it.

## Capabilities and Constraints

- **Fully local.** No cloud AI services. The UI must load no external fonts, CDNs or remote assets, so the bundle works inside the bank's closed network (portability requirement).
- **Required API schema.** The API response schema is fixed by the case and must not change. Extra fields are allowed: `type_code`, `confidence`, `rule {kind, refs[], caveat}`, `source`, `stage`, `progress`, `timeline`, `meta`, `processing_sec`, `queue_position`, `error`.
- **Never assert the invisible.** Use "possible violation" and "not recorded on video" wording. Show caveats. Never invent legal references: only the knowledge base is cited.
- **No face recognition or identification** (FAQ 29). Analysis is strictly visual, without audio.
- **No authentication, check history, batch upload or report export required** (FAQ 27). Optional extras such as a printable review report are allowed.
- **Videos are deleted** about one hour after processing. The player uses a local blob URL of the uploaded file, so the video is not sent to the server a second time.
- **Language: English UI for now.** Violation types, descriptions and legal quotes currently arrive in Russian from the backend. Localizing that content is an open decision.
- **Violation types:** T01–T15 plus T99 "undetermined", listed in `AGENTS.md`. Unseen types may appear in testing.

## Brand Commitments

- Product name: **CashGuard**, presented as built for **ForteBank**. Forte name and color cues are allowed. The Forte logo appears on the case brief, but no logo asset is in the repo.
- Voice: careful and factual. The result is a hint for human review, not a final conclusion, and the UI states that explicitly.

## Evidence on Hand

- `examples/sample_response.json`: a full response with real evidence frames, timeline and meta.
- `docs/norms.md`, `ml/rules_kb.yaml`: the norm sources and the violation-to-rule mapping.
- `docs/dataset_notes.md`, `ml/eval/labels_typed.csv`: dataset description and typed labels for 40 training videos. The videos themselves may not be published.
- `backend/static/index.html`, `live.html`: a working fallback UI with the logic for reference, not a design reference.
- No accuracy figures, customer testimonials or production deployments exist yet. Do not fabricate them. Quality numbers come from `ml.eval.evaluate` once ML reports them.

## Product Principles

1. **Evidence before verdict.** Every claim is one click away from the frame that shows it and the clause that governs it.
2. **Honest uncertainty.** Show confidence, rule kind and caveats instead of hiding them. Flag where video can't settle the question.
3. **The reviewer stays in charge.** The system proposes and the human confirms or rejects. The UI never reads as a disciplinary verdict.
4. **Zero-instruction first use.** A first-time visitor (a judge on a phone) can upload and understand the result without help.
5. **Local by design.** Nothing in the experience depends on the internet or on identifying people.

## Accessibility & Inclusion

The UI must work on phone-width screens (a judge may open it on mobile). Verdict and severity must not be conveyed by color alone, because the verdict wording itself is required.
