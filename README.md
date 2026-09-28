# Reflex

**Turn engineering work into intelligence you own.**

Reflex is a repair workspace for recurring engineering failures. Reproduce a broken customer flow, inspect a River-generated patch, execute behavioral checks, and turn accepted repairs into a specialist model. UFO supplies the agent runtime and observable work; Reflex retains the evidence and dataset lineage; River updates the model's weights.

**The live loop:** verified repairs became **24 training examples**. River saved **`reflex-repair-v4-48steps-20260927` after 48 weight updates and 122,752 processed training tokens**. The installed UFO SDK's real `repair_code_with_reflex` tool then used that checkpoint to repair the stock-replay training case: **2/4 → 4/4 executed checks in about 5.7 seconds**, with its observable trace saved. This was a programmatic SDK invocation; a full authenticated UFO conversation has not been demonstrated. [Training receipt](docs/evidence/reflex-v4-training.json) · [Live UFO receipt](docs/evidence/ufo-live-v4.json).

**Measured limits:** the earlier complete v3 held-out comparison remains **base 4/4 · memory 4/4 · learned 4/4**, with matching memory/learned prompts. No accuracy gain was measured. The later v4 replay had a base execution permission error; that infrastructure failure does not establish a learning advantage. The first checkout repair also remains recorded: **2/4 → 4/4 checks in 15.4 seconds**. [Full receipts and limits](docs/verification.md).

The local Repository tab also inspects Python source and executes its regression tests in an isolated snapshot; a real source/test pair returned **7 passed, 1 skipped**. The complete backend suite passed **240 tests and 88 subtests**, and global Ruff passed.

**[Watch the narrated demo](https://ankitshah009.github.io/Reflex_own_intelligence_hack/)** · [Submission fields](docs/submission.md) · [Live UFO receipt](docs/evidence/ufo-live-v4.json)

Source: [Reflex on GitHub](https://github.com/ankitshah009/Reflex_own_intelligence_hack).

For the presentation, use the [final narrated transcript](docs/demo-assets/narration.txt) and [submission fields](docs/submission.md).

The [recorded v3 evidence](docs/evidence/reflex-v3.json) contains the saved training and evaluation results in JSON.

This repository implements the workflow with real provider adapters. It never substitutes a fabricated review, training run, checkpoint, or accuracy score when credentials are unavailable.

## How it works

```mermaid
---
config:
  flowchart:
    diagramPadding: 20
    wrappingWidth: 320
---
flowchart TB
    subgraph S1["1 · Collect: repairs are executed, not judged"]
        direction LR
        R["<b>Reproduce</b><br/>replay the failing events<br/>against the real handler"]
        P["<b>Repair</b><br/>River writes a complete<br/>handler, or you edit it"]
        V["<b>Verify</b><br/>behavioral checks run<br/>in the macOS sandbox"]
        R --> P --> V
    end
    subgraph S2["2 · Learn: only verified repairs become data"]
        direction LR
        A["<b>Accept</b><br/>operator approval or<br/>curriculum verification"]
        F["<b>Freeze</b><br/>immutable SHA-256<br/>training snapshot"]
        T["<b>Train</b><br/>River LoRA SFT<br/>on Qwen3.5-9B"]
        A --> F --> T
    end
    subgraph S3["3 · Reuse: the specialist handles the next failure, and its work re-enters step 1"]
        direction LR
        C[("<b>Checkpoint</b><br/>river:// adapter<br/>tied to its dataset")]
        U["<b>UFO agent</b><br/>calls the specialist<br/>on the next failure"]
        E["<b>Held-out test</b><br/>base vs memory<br/>vs learned"]
        C --> U
        C --> E
    end
    S1 --> S2 --> S3

    classDef reflex fill:#0969da,fill-opacity:0.14,stroke:#0969da,stroke-width:1.5px
    classDef data fill:#1a7f37,fill-opacity:0.14,stroke:#1a7f37,stroke-width:1.5px
    classDef river fill:#bc4c00,fill-opacity:0.14,stroke:#bc4c00,stroke-width:1.5px
    classDef ufo fill:#8250df,fill-opacity:0.14,stroke:#8250df,stroke-width:1.5px
    class R,P,V,E reflex
    class A,F data
    class T,C river
    class U ufo
    style S1 fill:#0969da,fill-opacity:0.04,stroke:#0969da,stroke-dasharray:5 4
    style S2 fill:#1a7f37,fill-opacity:0.04,stroke:#1a7f37,stroke-dasharray:5 4
    style S3 fill:#bc4c00,fill-opacity:0.04,stroke:#bc4c00,stroke-dasharray:5 4
```

The gates between stages are enforced in code. A repair becomes training data only after its exact source passes executed checks. Training snapshots are immutable and addressed by SHA-256, and held-out handlers are rejected from training by AST fingerprint. [Architecture](#architecture) shows each part in detail.

## Who would use it

The initial buyer hypothesis is an engineering team maintaining checkout,
billing, inventory, or webhook integrations. Repeated incident fixes become a
team-specific repair specialist. The product would charge for a shared team
workspace plus metered training; pricing and customer demand are not validated.
The useful metric is fewer developer corrections per verified repair, measured
against the same base model with memory. A small synthetic benchmark is the
first experiment, not proof of production savings.

## Run locally

Requirements: Python 3.13 or newer, `uv`, and a current Node.js/npm installation. The verified development environment uses Python 3.14 and Node.js 26. All application data stays under this directory unless you change its configuration.

```sh
cp .env.example .env
# Edit .env to set your RIVER_API_KEY. Do not commit credentials.
sh scripts/dev.sh
```

Open **http://127.0.0.1:5173** for the repair workbench. The original PR-review workspace remains at **http://127.0.0.1:5173/#review**. The API listens on `127.0.0.1:8000`. Reproduction, source editing, behavioral checks, and exports run locally. Inference and training require River access and consume account credits. Executable repair checks currently require macOS with Seatbelt available.

To start the services separately:

```sh
UV_CACHE_DIR="$PWD/.uv-cache" uv sync
uv run uvicorn reflex.app:app --app-dir backend --host 127.0.0.1 --port 8000
```

In another terminal:

```sh
cd frontend
npm ci
npm run dev
```

Use one API worker. Jobs run in its process and persist progress in SQLite. On restart, unfinished jobs become interrupted; Reflex does not automatically repeat billable operations. A provider timeout does not establish whether remote computation stopped. Inspect the River Console before retrying an interrupted training run.

## Repair workflow

1. **Reproduce:** replay duplicate checkout, inventory, refund, or cancellation events and inspect the actual resulting state.
2. **Repair:** ask River for replacement handler code or edit it yourself. Run the same behavioral checks in a bounded local sandbox.
3. **Accept:** review a passing patch and explicitly approve it for training. Editing invalidates earlier verification; the server rechecks acceptance.
4. **Learn:** train SFT on an immutable snapshot of accepted repairs and machine-verified generated samples. Provenance distinguishes those two sources. A checkpoint appears only after River confirms it.
5. **Compare:** evaluate four excluded cases against base, memory, and learned weights. Memory and learned use identical input tokens.
6. **Reuse through UFO:** the installed SDK tool calls the saved specialist and imports its observable work into the experience ledger. The live v4 stock-repair receipt demonstrates this path.

You can bring a Python `apply(state, event)` handler with its initial state,
events, and expected outputs. The supplied six training incidents and four
held-out variants are clearly identified samples. The generated curriculum produced 19 verified repairs from 23 River requests across 24 attempted tasks. Those variants come from six templates. Together with five operator-accepted repairs, they supplied the 24-example v3 training set. See [repair scope and limits](docs/repair.md).

The **Repository** tab selects a local `backend/**/*.py` source file and a `tests/**/*.py` test file, reproduces the selected tests, and lets you inspect and verify a candidate patch. Tests run against a bounded snapshot; the original working files are preserved. The completed learning experiment above used event handlers, so it does not establish learned-model improvement on repository tasks.

## PR-review workflow

1. **Review.** Paste a patch and repository context, or inspect a clearly labeled fictional sample. Choose base, memory, or a completed learned checkpoint. The review records only observed actions and final output.
2. **Correct.** Confirm the decision, explain it, and select the relevant issue tags. Only explicitly confirmed training feedback qualifies for export or learning. You can also label a patch directly; it will not claim an AI reviewed it.
3. **Learn.** Train from the frozen set of confirmed examples. Start with at least ten varied examples including approvals. Choose SFT or SFT followed by bounded reward learning on that same model. RL scores sampled reviews against confirmed training labels; it skips the update when rewards do not vary. A training job records actual steps/losses and only adds a checkpoint after River confirms it was saved.
4. **Replay.** Run the held-out suite against base, memory, and learned conditions. Memory and learned receive identical prompts, frozen feedback, and generation settings. The UI shows actual counts, including invalid answers. Failed runs preserve their partial evidence.
5. **Use it in UFO.** Install the [verified self-hosted extension](docs/ufo.md), then call `review_code_with_reflex` with `condition="learned"`. It returns the specialist judgment and captures observable UFO turn events against the same experience.

The supplied curriculum contains fictional engineering PRs. Its proposed labels are in [sample-labeling.md](docs/sample-labeling.md); they are not silently inserted as human corrections. The held-out set is a small synthetic benchmark. It can test the mechanism but cannot establish generalization to your real repository or guarantee improvement.

## What is persisted

`data/reflex.sqlite3` stores experiences, corrections, job events, checkpoint identifiers, immutable training snapshots, and evaluation artifacts. Each checkpoint's training data can be exported even after later feedback changes. Combined runs save a recoverable SFT checkpoint before attempting RL. Secrets remain server-side. Common credential patterns are redacted, but this is not complete PII or secret detection: inspect an export before sending sensitive repository data to River.

River receives the approved training examples and inference context. Learned checkpoints are hosted by River and refer to adapters requiring their original base model. A `river://` URI is not a local download or a perpetual storage guarantee. See [the source and API research](docs/research.md) for the verified lifecycle, pricing, and limits.

## Architecture

Color key: blue is Reflex, purple is UFO, orange is River, green is verified data, red is an isolation or safety boundary, and gray is a person or input.

### System overview

```mermaid
---
config:
  flowchart:
    diagramPadding: 20
    wrappingWidth: 320
    nodeSpacing: 40
    rankSpacing: 46
---
flowchart TB
    OP["<b>Operator</b><br/>React + Vite workbench<br/>REST + live SSE events"]
    subgraph UFO["UFO runtime · self-hosted ufo-core"]
        TOOLS["<b>Specialist tools</b><br/>repair_code_with_reflex<br/>review_code_with_reflex"]
        HOOKS["<b>Lifecycle hooks</b><br/>prompt · tool result · stop"]
    end
    subgraph API["Reflex API · FastAPI on 127.0.0.1:8000"]
        GUARD["<b>Local boundary</b><br/>loopback + origin allowlist<br/>1 MB cap · UFO bearer token"]
        JOBS["<b>Job runner</b><br/>one active run · durable events<br/>SSE replay · no auto-retry"]
        ENG["<b>Engines</b><br/>repair · repository · curriculum<br/>evaluation · leakage guards"]
        ADAPT["<b>River adapter</b><br/>local tokenizer · sampling<br/>LoRA SFT · input-token hashes"]
        GUARD --> JOBS --> ENG --> ADAPT
    end
    SB["<b>Seatbelt sandbox</b><br/>handler worker<br/>pytest snapshot runner"]
    DB[("<b>SQLite ledger</b><br/>WAL · experiences · jobs<br/>immutable snapshots")]
    subgraph CLOUD["Cloud"]
        RIVER["<b>River</b><br/>Qwen3.5-9B sampling<br/>LoRA SFT"]
        CKPT[("<b>river:// checkpoints</b><br/>immutable LoRA adapters")]
        HF["<b>Hugging Face Hub</b><br/>tokenizer files only"]
    end

    OP --> GUARD
    TOOLS -->|"Idempotency-Key"| GUARD
    HOOKS -->|"trace import"| GUARD
    JOBS <-->|"transactions"| DB
    ENG -->|"JSON over pipes"| SB
    ADAPT -->|"sample (base or checkpoint) · train"| RIVER
    RIVER -->|"save_weights"| CKPT
    ADAPT -.->|"tokenizer, cached"| HF

    classDef human fill:#6e7781,fill-opacity:0.12,stroke:#6e7781,stroke-width:1.5px
    classDef ufo fill:#8250df,fill-opacity:0.14,stroke:#8250df,stroke-width:1.5px
    classDef reflex fill:#0969da,fill-opacity:0.14,stroke:#0969da,stroke-width:1.5px
    classDef guard fill:#cf222e,fill-opacity:0.12,stroke:#cf222e,stroke-width:1.5px
    classDef data fill:#1a7f37,fill-opacity:0.14,stroke:#1a7f37,stroke-width:1.5px
    classDef river fill:#bc4c00,fill-opacity:0.14,stroke:#bc4c00,stroke-width:1.5px
    class OP human
    class TOOLS,HOOKS ufo
    class GUARD,SB guard
    class JOBS,ENG,ADAPT reflex
    class DB data
    class RIVER,CKPT,HF river
    style UFO fill:#8250df,fill-opacity:0.05,stroke:#8250df,stroke-dasharray:5 4
    style API fill:#0969da,fill-opacity:0.05,stroke:#0969da
    style CLOUD fill:#bc4c00,fill-opacity:0.04,stroke:#bc4c00,stroke-dasharray:5 4
```

The frontend uses React, TypeScript, and Vite. The backend uses FastAPI and the pinned River Python client. UFO is a separately installable extension pinned to a verified upstream source revision. Review requests do not execute patches. Repair requests execute restricted Python handlers in a mandatory macOS sandbox with CPU, wall-time, output, and memory observation limits; expected results stay in the parent process. If UFO independently executes repository commands, its carrier determines that execution boundary.

### Anatomy of a repair run

```mermaid
---
config:
  sequence:
    mirrorActors: false
    width: 120
    actorMargin: 40
    diagramMarginX: 20
---
sequenceDiagram
    autonumber
    actor OP as Operator
    participant API as Reflex API
    participant SB as Sandbox
    participant RV as River
    participant DB as Ledger

    OP->>API: POST /api/repairs/run
    API->>DB: queue job (409 if one is active)
    API-->>OP: 202 + job_id, then SSE events
    rect rgba(207, 34, 46, 0.08)
        Note over API,SB: Reproduce
        API->>SB: run the original handler
        SB-->>API: baseline, e.g. 2/4 checks
    end
    rect rgba(188, 76, 0, 0.08)
        Note over API,RV: Repair
        API->>RV: sample at T=0, seed 42
        RV-->>API: full handler + input-token hash
    end
    rect rgba(26, 127, 55, 0.08)
        Note over API,DB: Verify
        API->>SB: run the candidate, same checks
        SB-->>API: e.g. 4/4, bound to code SHA-256
        API->>DB: save diff, reports, hashes
    end
    rect rgba(9, 105, 218, 0.08)
        Note over OP,DB: Accept
        OP->>API: approve (after review or edits)
        API->>SB: re-run the exact code
        SB-->>API: passed
        API->>DB: approval: training-eligible
    end
```

Every step is appended to the job's durable event log and streamed over SSE. Each execution report carries the SHA-256 of the exact code that ran, so an edited patch loses its verification, and acceptance re-executes the approved code on the server.

### How UFO calls the specialist

```mermaid
---
config:
  sequence:
    mirrorActors: false
    width: 120
    actorMargin: 40
    diagramMarginX: 20
---
sequenceDiagram
    autonumber
    actor H as Human
    box rgba(130, 80, 223, 0.08) UFO runtime
        participant AG as UFO agent
        participant EXT as Reflex extension
    end
    box rgba(9, 105, 218, 0.08) Reflex
        participant API as Reflex API
    end

    H->>AG: repair case repair-stock-replay
    AG-)EXT: hook: user_prompt_submit
    EXT->>EXT: buffer event in UFO store
    AG->>EXT: repair_code_with_reflex(case_id)
    EXT->>EXT: reserve turn (compare-and-set)
    EXT->>API: POST /api/repairer
    Note over API: bearer, runtime UUIDs, SDK pin<br/>auto mode: latest checkpoint<br/>sandbox, River, sandbox
    API-->>EXT: experience_id, code, diff, report
    EXT-->>AG: ToolResult
    AG-)EXT: hook: post_tool_use
    AG->>H: final answer
    AG-)EXT: hook: stop
    EXT->>API: POST /api/repairs/import
    Note over API: identity must match saved repair<br/>observable events only
    EXT->>EXT: keep export receipt
    Note over H,API: Approval stays human: only the Reflex UI accepts a repair for training
```

Each UFO turn gets one specialist request, reserved with compare-and-set before any HTTP call. A stable `ufo-repair:<workspace>:<turn>` idempotency key means a retry returns the saved result instead of triggering a second model call. Only observable events are imported, never model reasoning or approval labels.

### Execution sandbox

```mermaid
---
config:
  flowchart:
    diagramPadding: 20
    wrappingWidth: 320
---
flowchart TB
    subgraph PARENT["Reflex API process · trusted · expected outputs stay here"]
        CODE["<b>Candidate handler.py</b><br/>from River or the developer"]
        GATE["<b>1 · Static gate</b><br/>AST allowlist · one apply(state, event)<br/>no imports, dunders, or reflection"]
        WATCH["<b>5 · Watchdog</b><br/>3 s wall clock · 256 KiB output<br/>256 MiB RSS, sampled every 100 ms"]
        JUDGE["<b>6 · Judge</b><br/>state + responses vs expected<br/>report bound to code SHA-256"]
        CODE --> GATE
        WATCH --> JUDGE
    end
    subgraph SPAWN["2 · Fresh interpreter · posix_spawn · inherited FDs closed"]
        subgraph SEAT["3 · Seatbelt · no network, file writes, fork, exec, or signals"]
            subgraph LIMITS["4 · rlimits · CPU 2 s · file size 0 · 32 FDs"]
                WORKER["<b>apply(state, event)</b><br/>allowlisted builtins<br/>JSON in, JSON out"]
                PROBE["<b>Self-check probe</b><br/>host read, write, network, signal<br/>must be denied, or execution stays off"]
                WORKER ~~~ PROBE
            end
        end
    end

    GATE -->|"source + JSON inputs"| WORKER
    WORKER -->|"JSON results"| WATCH

    classDef human fill:#6e7781,fill-opacity:0.12,stroke:#6e7781,stroke-width:1.5px
    classDef reflex fill:#0969da,fill-opacity:0.14,stroke:#0969da,stroke-width:1.5px
    classDef guard fill:#cf222e,fill-opacity:0.12,stroke:#cf222e,stroke-width:1.5px
    class CODE human
    class GATE,WATCH,JUDGE reflex
    class WORKER,PROBE guard
    style PARENT fill:#0969da,fill-opacity:0.04,stroke:#0969da
    style SPAWN fill:#cf222e,fill-opacity:0.03,stroke:#cf222e,stroke-dasharray:5 4
    style SEAT fill:#cf222e,fill-opacity:0.05,stroke:#cf222e
    style LIMITS fill:#cf222e,fill-opacity:0.07,stroke:#cf222e,stroke-dasharray:2 3
```

Candidate code runs in a separate interpreter under macOS Seatbelt, and the expected outputs never enter it. If the self-check probe cannot prove isolation, execution stays disabled; there is no unsandboxed fallback. Repository tests run under the same kind of boundary: a read-only snapshot, a disposable scratch directory, 45 seconds, and 512 MiB.

### Controlled comparison

```mermaid
---
config:
  flowchart:
    diagramPadding: 20
    wrappingWidth: 320
---
flowchart TB
    HO["<b>Held-out incidents</b><br/>source fingerprints never<br/>appear in training"]
    CK[("<b>Checkpoint record</b><br/>river:// adapter · frozen<br/>dataset and memory")]
    B["<b>Base</b><br/>prompt: case<br/>weights: Qwen3.5-9B"]
    M["<b>Memory</b><br/>prompt: case + memory<br/>weights: Qwen3.5-9B"]
    L["<b>Learned</b><br/>prompt: case + memory<br/>weights: + LoRA adapter"]
    G{{"<b>Identity guard</b><br/>memory and learned prompts and<br/>input tokens must hash identically"}}
    X["<b>Sandbox execution</b><br/>malformed output counts as failure"]
    ART[("<b>Evaluation artifact</b><br/>eval-set · dataset · model-input hashes")]

    HO --> B
    HO --> M
    HO --> L
    CK -.-> M
    CK -.-> L
    M --> G
    L --> G
    B --> X
    G --> X
    X --> ART

    classDef human fill:#6e7781,fill-opacity:0.12,stroke:#6e7781,stroke-width:1.5px
    classDef reflex fill:#0969da,fill-opacity:0.14,stroke:#0969da,stroke-width:1.5px
    classDef guard fill:#cf222e,fill-opacity:0.12,stroke:#cf222e,stroke-width:1.5px
    classDef data fill:#1a7f37,fill-opacity:0.14,stroke:#1a7f37,stroke-width:1.5px
    classDef river fill:#bc4c00,fill-opacity:0.14,stroke:#bc4c00,stroke-width:1.5px
    class HO human
    class CK,L river
    class B,M reflex
    class G,X guard
    class ART data
```

Memory and learned receive token-identical inputs, so any difference between them comes from the weights. The recorded v3 run scored base 4/4, memory 4/4, and learned 4/4. The benchmark saturated, so no gain is claimed.

### Data lineage

```mermaid
erDiagram
    REPAIR_CASE ||--o{ REPAIR : "attempted as"
    JOB ||--o{ EVENT : "streams"
    JOB ||--o{ REPAIR : "produces"
    REPAIR }o--o{ DATASET : "frozen into"
    DATASET ||--o{ REPAIR_CHECKPOINT : "trains"
    REPAIR_CHECKPOINT ||--o{ REPAIR_EVALUATION : "measured by"

    REPAIR_CASE {
        string id PK
        text source "original handler.py"
        json checks "expected state and responses"
    }
    REPAIR {
        uuid id PK
        string case_id FK
        string condition "base, memory, or learned"
        sha256 prompt_hash
        sha256 input_token_hash
        json accepted_report "bound to code SHA-256"
        json human_feedback "operator approval"
        json machine_feedback "curriculum verification"
        json ufo "runtime UUIDs and SDK commit"
    }
    DATASET {
        sha256 id PK "hash of the examples"
        json examples "prompt, completion, provenance"
        text memory "frozen lessons"
    }
    REPAIR_CHECKPOINT {
        uuid id PK
        string checkpoint "river:// URI"
        sha256 dataset_hash FK
        json metrics "steps, losses, tokens"
    }
    REPAIR_EVALUATION {
        uuid id PK
        uuid checkpoint_id FK
        sha256 eval_set_hash
        sha256 model_input_hash
    }
    JOB {
        uuid id PK
        string kind
        string status
    }
    EVENT {
        int id PK
        uuid job_id FK
        json data
    }

    classDef work fill:#0969da1f,stroke:#0969da
    classDef frozen fill:#1a7f371f,stroke:#1a7f37
    classDef weights fill:#bc4c001f,stroke:#bc4c00
    classDef ops fill:#6e77811f,stroke:#6e7781
    class REPAIR_CASE,REPAIR work
    class DATASET frozen
    class REPAIR_CHECKPOINT,REPAIR_EVALUATION weights
    class JOB,EVENT ops
```

Every checkpoint points to the SHA-256 of the exact examples it was trained on, and dataset snapshots cannot be modified or deleted. The PR-review path mirrors this with experiences, checkpoints, and evaluations.

### Job lifecycle

```mermaid
stateDiagram-v2
    direction LR
    [*] --> queued: POST starts a run
    queued --> running
    running --> completed: result persisted
    running --> failed: sanitized error persisted
    running --> interrupted: shutdown or restart
    queued --> interrupted: restart
    completed --> [*]
    failed --> [*]
    interrupted --> [*]: never auto-retried

    classDef good fill:#1a7f37,fill-opacity:0.16,stroke:#1a7f37
    classDef bad fill:#cf222e,fill-opacity:0.14,stroke:#cf222e
    classDef halt fill:#bc4c00,fill-opacity:0.14,stroke:#bc4c00
    class completed good
    class failed bad
    class interrupted halt
```

One run at a time. A restart marks unfinished jobs as interrupted and never resubmits billable River work.

## Verify

```sh
uv run pytest -q
uv run ruff check backend tests integrations/ufo
cd frontend
npm run build
```

Tests exercise the actual API and SQLite through the primary workflow; only provider I/O is replaced. Adapter tests verify payload shapes, failure behavior, and SDK boundaries. These checks do not prove a live River account can train or that a learned model improves. Current evidence and remaining live steps are recorded in [verification.md](docs/verification.md).

## Integration references

- [River adapter and configuration](docs/river.md)
- [UFO extension, activation, and source pin](docs/ufo.md)
- [Research decisions and experiment contract](docs/research.md)
- [Manual sample-labeling guide](docs/sample-labeling.md)
- [Download the actual adapter weights](docs/export.md)

The local app is intended for a single operator and binds to loopback. UFO can authenticate its calls with `REFLEX_INGEST_TOKEN`. Remote multi-user hosting needs an authenticated application boundary and durable job workers before it is exposed publicly.
