# PROJECT_ARCHITECTURE_AND_ROADMAP

## Executive Summary

This project is a Telegram-first AI image generation system with a clear MVP architecture: **aiogram bot + SQLAlchemy repository layer + local filesystem storage + in-process async worker + pluggable AI providers** (Google Gemini/Imagen and OpenRouter). The implementation is practical and deployable, but it currently has constraints that become material at scale:

- Storage durability risk on ephemeral filesystems (especially Railway without mounted volume).
- Queueing and worker execution coupled to a single process.
- Limited user-facing queue transparency and lack of explicit cancellation UX.
- Mixed language UI (RU + EN) in some user-visible paths.
- Security for secrets is present but cryptographically weak (XOR-based obfuscation).

---

## TASK 1: Structural Analysis

### 1.1 Current Project Structure (Subsystem View)

| Subsystem | Key Files | Role | Notes |
|---|---|---|---|
| Bot handlers (UI & orchestration) | `app/bot/main.py` | Telegram menu logic, FSM states, validation, queue enqueue, callbacks | Single-entry UX and control plane.
| Worker (async processing) | `app/worker.py` | Poll queued jobs, process AI pipeline, store outputs, notify users | In-process worker started from bot runtime.
| Database schema | `app/models.py` | Users, profile, photos, scene, settings, jobs, generations, keys | Solid normalized MVP schema.
| Repository/data access | `app/repo.py` | Encapsulates CRUD and business queries | Keeps handler/worker lean.
| Queue abstraction | `app/queue.py` | Pops next queued job, startup recovery | Thin wrapper over repo transactional claim.
| API clients | `app/ai/gemini_analyzer.py`, `app/ai/nanobanana_client.py`, `app/ai/openrouter_client.py` | Provider integrations with retries/backoff | Distinct roles mostly respected.
| Prompt builder | `app/prompt_builder.py` | Deterministic prompt assembly | Clear separation from handlers.
| Storage module | `app/storage.py` | Local path generation and file lifecycle | Local FS only (no object storage abstraction yet).
| Security/secrets | `app/security.py`, `app/services/keys.py` | API key retrieval/encryption/decryption logic | Better than plaintext, but not strong cryptography.
| Config/infra | `app/config.py`, `app/db.py`, `Dockerfile`, `railway.json` | Settings, DB normalization, runtime startup | Railway-oriented deployment assumptions.

### 1.2 End-to-End Data Flow

#### Visual-Textual Flow Chart

```text
[Telegram User]
    |
    | 1) Main menu interactions (Профиль / Фото / Сцена / Камера / API ключи / Генерация)
    v
[aiogram Handlers + FSM in app/bot/main.py]
    |
    | 2) Persist user state/data via NeuroPhotoshootRepo
    v
[PostgreSQL/SQLite via SQLAlchemy]
    |  - users
    |  - profiles
    |  - photo_assets (paths)
    |  - scene_prompts
    |  - shoot_settings
    |  - jobs (QUEUED/RUNNING/...)
    |  - generations
    |
    | 3) On “Генерация”: create Job(status=QUEUED)
    v
[JobQueue.pop_next_job -> claim_next_queued_job]
    |
    | 4) Worker marks job RUNNING and loads profile/scene/photos/settings
    v
[Worker pipeline in app/worker.py]
    |
    | 5a) Read reference files from LocalStorage paths
    | 5b) Analyze face photos via GeminiAnalyzer (Google provider only)
    | 5c) Build deterministic final prompt
    | 5d) Call generation API:
    |     - Google Imagen client (NanoBananaClient)
    |     - or OpenRouterClient
    v
[Generated image bytes]
    |
    | 6) Save result to LocalStorage/results, persist Generation row
    | 7) Mark Job SUCCEEDED (or FAILED + error)
    v
[Telegram delivery]
    |
    | 8) send_photo captioned with lens/angle/size
    |    and make downloadable in “История” -> “Отправить результат”
    v
[End user receives output]
```

### 1.3 Potential Bottlenecks & Failure Points

#### A) Storage & Durability
- **Ephemeral filesystem risk**: DB can keep file paths while referenced files disappear after restart/deploy (already acknowledged by current code with explicit checks and “Перезагрузить фото” remediation).
- **No object storage abstraction at infra level**: `LocalStorage` is path-centric and ties availability to node disk.

#### B) Queue & Throughput
- **Single-process coupling**: bot + worker in one runtime means queue progress depends on polling process health.
- **Polling interval + sequential processing**: worker loop sleeps/polls every second and processes jobs with timeout guard; acceptable for MVP, but not ideal for high concurrency.
- **Per-user concurrency cap** is good, but there is no global worker pool scaling model.

#### C) API Limits and Third-Party Constraints
- Gemini and Imagen both have retry/backoff, but:
  - **Quota and billing hard stops** can block flow (handled with user messages but still a UX interruption).
  - OpenRouter depends on external hosted URLs in response and a second download call.
- Prompt truncation and provider-specific payload differences may reduce consistency across providers.

#### D) Security / Key Management
- OpenRouter key is obfuscated using XOR + derived key; this is not equivalent to modern authenticated encryption.
- Gemini/Imagen keys appear stored as plaintext in DB fields (via repo upsert methods), while OpenRouter uses encryption path.
- No key rotation policy, key age visibility, or per-key health checks in UX.

#### E) UX/Operational Observability
- User sees queue acceptance and start message, but no live queue position or ETA.
- No user-initiated cancellation while job is queued/running.
- History retrieval is functional but limited to 10 recent generations and no filtering/sorting controls.

---

## TASK 2: UX & Button Logic Audit

### 2.1 Main Menu Buttons Mapping

| Button | Where does it lead? (Current sequence) | Is it logical? | Dead End Check | Gaps |
|---|---|---|---|---|
| **Профиль** | Starts FSM: height -> weight -> hair -> eyes -> body type -> save -> back to main menu. | Yes, sequence is coherent for profile completion. | Mild dead-end: after save, no CTA suggesting next step (“Теперь загрузите фото”). | Add next-step nudges and completion meter.
| **Фото** | Opens photo submenu with counts and actions: upload face/full-body, reset, done. | Mostly logical. | Moderate dead-end: individual upload success often returns to main menu, which breaks batch upload momentum. | Keep user in photo flow after each upload + progress indicator (e.g., 3/5 face, 1/2 full-body).
| **Сцена** | Prompts one text message -> saves scene -> back to main menu. | Logical and simple. | Mild dead-end after save (no suggestion to proceed to camera or generation). | Offer “Настроить камеру” and “Запустить генерацию” quick actions post-save.
| **Камера** | Inline menu with two branches: technical (lens/size) and angles; values persist in shoot settings. | Logical from settings standpoint. | Minor dead-end: callback confirms “Сохранено”, but user may not know if to return or generate. | Add explicit “✅ Готово, к генерации” button in camera inline flow.
| **Генерация** | Validates keys/provider -> validates profile completeness -> checks photo counts/files -> scene -> active jobs -> enqueue job. | Strong backend gating; logical dependencies enforced. | Good error messages, but “what next” can still be unclear (especially on limits/queue). | Add queue position, ETA, and “Отменить задачу” actions.
| **История** | Shows last generations with metadata + inline “Отправить результат”. | Logical read-only retrieval flow. | Not a dead-end per se; user can request result file repeatedly. | Add “Повторить с теми же настройками” and “Удалить запись” options.
| **Помощь** | Sends static numbered instructions. | Logical but static. | Dead-end: no actionable buttons after help content. | Turn into guided help with quick-reply buttons.
| **API ключи** | Inline provider switch + set key callbacks + provider-specific help. | Good structure for power users. | Moderate dead-end after key set: user not guided to “Генерация” or missing remaining keys. | Add status panel: key presence/last-validated/check connection.

### 2.2 Sequence Logic Assessment (Cross-Button)

**Current de facto user path** is approximately: `Профиль -> Фото -> Сцена -> Камера (optional) -> API ключи -> Генерация -> История`.

- This is **mostly correct**, but UX can be improved by explicitly guiding the user in that order.
- **Camera before Generation** is correct; camera settings are generation modifiers and should be done before enqueue.
- API key setup could be moved earlier in onboarding or validated lazily only when needed (current implementation already does lazy checks at generation).

### 2.3 Dead-End Inventory

1. After profile save: no directional CTA.
2. After scene save: no directional CTA.
3. After help: no branching options.
4. In photo mode: successful upload often exits to main menu, causing context switching.
5. In API keys setup: no completion dashboard or next-step recommendation.

### 2.4 Missing UX Controls (Functional Gaps)

- **Cancel job button** (queued/running cancellation).
- **Queue status** (position, active workers, estimated wait).
- **Retry last job** shortcut.
- **Readiness status panel** (“Profile ✅, Photos 4/7 ⚠️, Scene ✅, Keys ✅”).
- **Provider health/test call** button.
- **Cost/balance awareness** for paid APIs.
- **Multilingual consistency** (current RU/EN mix can feel unfinished).

---

## TASK 3: Logical Improvements (Add/Remove)

### 3.1 What to Remove / Consolidate

1. **Reduce menu cognitive load**:
   - Consider merging “Показать профиль” into “Профиль” submenu as “Просмотр/редактирование профиля”.
2. **Minimize duplicated confirmations**:
   - Replace repeated generic “Сохранено” with context-aware confirmations + next action.
3. **Avoid mixed messaging in queue confirmation**:
   - “Job queued” mixed with Russian should be unified per selected locale.

### 3.2 What to Add (High-Impact UX)

#### A) Core flow upgrades (must-have)
- **Onboarding Wizard**: first-run guided path with step indicators.
- **Readiness Checklist** card with one-tap navigation to missing items.
- **Queue Center**:
  - “Мои задачи”
  - status badges (QUEUED/RUNNING/SUCCEEDED/FAILED)
  - queue position + ETA
  - cancel queued job.

#### B) Product growth features (should-have)
- **Prompt Gallery** (prebuilt scene styles/presets).
- **One-click Presets** for camera + style bundles.
- **Regenerate variations** from a successful generation.
- **Referral System** with invite tracking and usage rewards.
- **Usage/Balance panel**:
  - estimated token/image costs by provider,
  - today/month usage,
  - warnings before expensive generation.

#### C) Trust & safety UX
- Show whether key is stored and last validated (without revealing key).
- Explain failures with structured reason categories: quota, billing, invalid key, provider outage.

### 3.3 Translation / Language Consistency Check

Current UI is predominantly Russian with occasional English fragments (“Job queued”, internal provider labels, some prompts in English for AI instruction). For a Telegram consumer product, this should be normalized.

**Recommendation:**
1. Define target language policy:
   - RU-only by default for current audience, or
   - RU/EN i18n with user language setting.
2. Externalize all user-facing strings into locale dictionaries.
3. Keep technical provider/model names in original language, but surrounding explanations localized.

---

## TASK 4: Evolution & Future-Proofing

### 4.1 Phase 2 Development Plan

#### Phase 2A — Reliability Foundation (2–4 weeks)
- Introduce object storage abstraction and provider implementation (S3-compatible/Cloudinary).
- Add migration for storing **storage_key** instead of raw local path dependency.
- Implement queue/job status endpoints and bot-level status screens.
- Add cancellable queued jobs and idempotent retry semantics.

#### Phase 2B — Scale & Observability (3–6 weeks)
- Decouple worker into separate scalable process/container.
- Add distributed queue backend (Redis/RQ, Celery, or Dramatiq).
- Structured metrics: queue depth, time-to-start, processing duration, failure reason codes.
- Alerting on provider error rates and storage miss rates.

#### Phase 2C — Monetization & Product Layer (4–8 weeks)
- Subscription tiers (Free / Pro / Studio).
- Credits and usage accounting.
- Priority queue for Pro users.
- Provider routing by plan (fast/quality models).

### 4.2 Scaling Strategy: Local Storage -> S3/Cloudinary

#### Target architecture
1. Upload Telegram files -> transient memory/disk buffer.
2. Persist originals to object storage bucket (`raw/{user_id}/{uuid}.jpg`).
3. Store object keys + metadata in DB.
4. Worker fetches references via signed URLs/SDK.
5. Store results in `results/{user_id}/{job_id}/{uuid}.jpg`.
6. Serve back via Telegram upload from bytes or short-lived signed links.

#### Benefits
- Survives restarts/deploys.
- Enables multi-instance workers.
- Easier retention lifecycle policies and CDN integration.

### 4.3 Pro Version (Subscription-Based Faster Models)

#### Product model
- **Free**: standard queue, limited daily generations, baseline models.
- **Pro**: priority queue, higher limits, faster models, advanced presets.
- **Studio/Business**: team seats, branded styles, API/webhook access.

#### Technical implementation building blocks
- Add `subscriptions`, `plans`, `usage_events`, `credits_ledger` tables.
- Middleware checks entitlement before queue enqueue.
- Queue scheduler supports weighted priority (Pro > Free).
- Provider routing policy engine:
  - Free -> lower-cost models
  - Pro -> high-speed/high-quality models

### 4.4 AI Model Expansion Roadmap

| Model/Provider | Integration path | Use case | Risks/Notes |
|---|---|---|---|
| **Flux (via hosted APIs)** | Add new client in `app/ai/` + provider flag + key handling | Stylized/high quality alternates | Output consistency and moderation policy differences.
| **Midjourney (if official API available for your account/region)** | Separate async job adapter (likely webhook/poll pattern) | Artistic premium styles | Terms/compliance and asynchronous orchestration complexity.
| **Stable Diffusion variants** | Self-hosted or API-based backend | Cost control, customization | Infra overhead for self-hosting GPUs.
| **Additional OpenRouter image models** | Extend model catalog + capability metadata | Dynamic routing by speed/cost/quality | Provider response schema variability.

### 4.5 Recommended Target Architecture (Future)

```text
[Telegram Bot Gateway]
   -> [Command/UX Service]
   -> [Readiness + Policy Engine]
   -> [Queue Service (Redis/SQS)]
   -> [Worker Pool N replicas]
       -> [Model Router]
           -> [Google Imagen / Gemini]
           -> [OpenRouter Models]
           -> [Future Providers]
       -> [Object Storage]
   -> [PostgreSQL]
   -> [Metrics + Logs + Alerts]
```

---

## Priority Action List (Architecture + UX)

### Top 10 Actions (ordered)
1. Migrate storage to durable object storage.
2. Add queue status and cancel capabilities in bot UX.
3. Introduce readiness checklist and guided onboarding sequence.
4. Externalize/localize all user-facing copy (remove RU/EN mixed strings).
5. Decouple worker from bot process for horizontal scaling.
6. Improve secret management (replace XOR obfuscation with strong encryption/KMS).
7. Add subscription/priority logic scaffolding for Pro plan.
8. Add provider/model routing matrix with fallback strategy.
9. Improve observability (job timings, provider failures, queue depth).
10. Add regression smoke tests for critical menu flows and callback transitions.

---

## Final Assessment

The project has a **clean MVP backbone** with good modularization and practical guardrails (validation, retries, and failure messaging). The strongest immediate risks are **durability and queue UX transparency**. Addressing those first will significantly improve reliability, user trust, and readiness for paid tiers.

