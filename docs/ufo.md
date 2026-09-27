# UFO experience integration

Reflex targets **[ufo-ai/ufo-core](https://github.com/ufo-ai/ufo-core)**, the business agent
operating system linked from UFO.ai. The SDK contract was inspected at commit
`63ba388ed449ff46c9d70744119dffc85df0fbf8` (September 27, 2026).

The integration is a Python extension installed in a **trusted self-hosted UFO runtime**.
It is not a hosted UFO API client. Hosted workspace availability or permission to install
custom Python extensions has not been established. The actual pinned UFO distribution
and this extension have been installed in the repository-local `.cache/ufo-env`. Its
real extension loader, SDK tool handler, lifecycle hook dispatcher, and complete example
configuration have passed the no-cloud contract check below. Actual initialization with
that configuration reached onboarding, then refused because the default model needs
`UFO_ANTHROPIC_API_KEY`. A full server boot and authenticated conversation remain unverified.

## What it does

`review_code_with_reflex(title, diff, context, repo, condition, checkpoint)` calls Reflex's
`POST /api/reviewer` from the UFO host. UFO continues to run its general agent; River serves
the specialist behind Reflex. The default condition is `auto`: a new turn uses the latest
saved checkpoint if one exists, otherwise the base model. This selects trained weights;
it does not claim they outperform the base. Choose `learned` after a
real checkpoint exists, optionally naming that checkpoint explicitly.

The extension subscribes to four actual SDK events:

| UFO event | Stored evidence |
| --- | --- |
| `user_prompt_submit` | The human's submitted instruction |
| `post_tool_use` | The dispatched tool's validated arguments and successful output |
| `post_tool_use_failure` | The dispatched tool's arguments and error output |
| `stop` | The final answer |

No model reasoning or compaction records are exported. Only turns that call the Reflex
reviewer enter its corpus. Events are buffered in UFO's workspace-scoped durable store;
the final export attaches them to the original Reflex experience. Identical event records
are deduplicated for recovery. Each turn keeps at most 128 events and each text field at
most 4096 characters, preserving the opening instruction and most recent results when full.
This is a bounded evidence trace, not a claim to retain every byte of execution history.

Human feedback is entered in the Reflex app. There is deliberately no tool that lets the
agent mark its own output as human-approved. The import normalizer rejects feedback labels,
rewards, held-out labels, unbounded output, and missing runtime UUIDs. These envelope checks
are not cryptographic attestation; use the shared bearer token to authenticate the sender.

## Install in a fresh self-hosted runtime

This recipe keeps source, runtime state, operator token, and terminal credentials inside
the Reflex repository. Run it from the repository root with Python 3.13 or newer, `uv`,
and the Rust build prerequisites required by UFO. It downloads the real upstream source
and dependencies; it does not provision a paid service.

```sh
export REFLEX_REPO="$PWD"
export UFOCTL_DIR="$REFLEX_REPO/integrations/ufo/.runtime/control"
export UFO_HOME="$REFLEX_REPO/integrations/ufo/.runtime/client-home"
export UFO_CONFIG="$REFLEX_REPO/integrations/ufo/.runtime/ufo.toml"
export UV_CACHE_DIR="$REFLEX_REPO/.uv-cache"
export UV_PYTHON="$(command -v python3.14)"
export CARGO_HOME="$REFLEX_REPO/integrations/ufo/.runtime/cargo-cache"
git clone https://github.com/ufo-ai/ufo-core.git integrations/ufo/.runtime
git -C integrations/ufo/.runtime checkout 63ba388ed449ff46c9d70744119dffc85df0fbf8
cd integrations/ufo/.runtime
make install
uv pip install --python .venv/bin/python "$REFLEX_REPO/integrations/ufo"
make build
```

Use your installed `python3.13` path instead if needed. `UV_PYTHON` is explicit because
upstream's pinned `.python-version` otherwise selects Python 3.12. The Reflex extension
requires Python 3.13 or newer.

Configure the runtime's model access using its `.env.template` and an already-funded
account. UFO's documented self-host setup names `UFO_ANTHROPIC_API_KEY` and
`UFO_OPENAI_API_KEY`; these are distinct from Reflex's River credential. Do not paste
credentials into a chat or commit them. Set `REFLEX_URL=http://127.0.0.1:8000` in the UFO
host process, and set the same `REFLEX_INGEST_TOKEN` in the Reflex API and UFO host process.
Remote Reflex URLs must use HTTPS. No credential is passed to the UFO model or sandbox.

Before initialization, copy the complete configuration for this **fresh** runtime:

```sh
cp "$REFLEX_REPO/integrations/ufo/ufo.example.toml" "$UFO_CONFIG"
```

Then initialize the workspace with your real email using the installed operator binary:

```sh
.venv/bin/ufoctl init --email you@example.com
```

The example supplies the required SQLite database and filesystem blob store,
binds the server to loopback, and selects the Reflex pack. Run `init` and `serve`
from the dedicated runtime directory so relative database/blob paths stay there.
Creating this file first avoids the stock `assistant` configuration's Perplexity search
selection, which requires an extension absent from this focused pack. When adapting an
existing configuration, remove its `[research] search_provider` setting if switching to
`reflex-demo`; the minimal pack has no web-search provider.

The package registers both a `ufo.extension` entry point named `reflex` and a `ufo.pack`
entry point selecting the `reflex-demo` pack. The pack contains the terminal surface,
context compaction, default index and embeddings, flag backend, and Reflex. UFO's built-in
file and command tools remain runtime capabilities. A stock `assistant` pack does not
activate an additional installed extension automatically.

This recipe assumes a **fresh dev runtime with no extension lockfile**. An existing UFO
deployment must include Reflex in its reviewed extension pins and its selected pack.
Do not remove an existing deployment's lockfile. `ufoctl ext install` manages catalog/pins;
it does not replace Python package installation.

Check entry point loading in the UFO environment, then start the actual runtime:

```sh
.venv/bin/python -c 'from ufo_ext_reflex.manifest import manifest; from ufo_ext_reflex.pack import pack; print(manifest().tools[0].name, pack().name)'
.venv/bin/ufoctl serve
```

In a second terminal, restore the three `UFO_*` path variables above and configure the
terminal client using the token created by `init`:

```sh
mkdir -p "$UFO_HOME"
install -m 600 "$UFOCTL_DIR/token" "$UFO_HOME/credentials"
printf '%s\n' 'http://localhost:8710' > "$UFO_HOME/workspace"
"$REFLEX_REPO/integrations/ufo/.runtime/client/target/debug/ufo" 'Inspect the current PR diff and call review_code_with_reflex using condition base. Report its experience ID.'
```

Start the client from the repository whose PR you intend to review. Use the actual UFO
UI/tool trace to check that `review_code_with_reflex` was called; then open the matching
experience in Reflex and record a human correction. After training, start a new turn and
request condition `learned` on an unseen PR.

UFO's local command carrier reads the host filesystem and does not enforce network egress
in the kernel. Use UFO's documented container carrier for untrusted PR execution. Reflex's
extension itself sends HTTP requests and observes events; it does not execute PR code.

## Failure behavior and validation

Review HTTP calls have a five-second connection timeout and a 120-second response timeout.
The stop hook's export has a three-second total deadline, within UFO's five-second hook budget.
Inference is never retried automatically. Authentication failures produce an instruction
to check the shared token. If final trajectory delivery fails, the buffered record remains
in UFO's store; the review and pre-review trace already saved by `/api/reviewer` remain
available in Reflex. A failed export is not a human correction or a successful training run.

```sh
.venv/bin/python -m pytest tests/test_ufo.py -q
.venv/bin/python -m ruff check backend/reflex/integrations/ufo.py integrations/ufo tests/test_ufo.py
.cache/ufo-env/bin/python integrations/ufo/verify_runtime.py
```

The tests cover envelope validation, label injection rejection, event limits, credential
redaction, replay deduplication, final trace linkage, token transport, and HTTP failures.
The fast unit suite uses a double at the external UFO SDK/store boundary. The separate
`verify_runtime.py` command loads the **actual installed UFO distribution**, discovers
the pack and extension, validates `ufo.example.toml` with UFO's actual configuration
model, validates the tool schema, invokes its handler with a real
`ToolContext`, and fires real `HookChain` events. Only HTTP responses and the workspace
store are fixtures. It proves registration and dispatch, and makes zero model calls.
A real initialization attempt was also made in the isolated `.cache/ufo-runtime`
directory using a fictional local owner address and no model credentials. The corrected
configuration passed, local schema migration completed, and onboarding explicitly
refused the default `auto` model without its Anthropic key. Generated local operator
secrets stay in ignored files with mode 600. That diagnostic workspace is not a
completed user workspace. A full UFO server boot, real model review, and River training
run still require a configured runtime and sponsor credentials.

## Verified source contracts

- [Official extension example](https://github.com/ufo-ai/ufo-core/blob/63ba388ed449ff46c9d70744119dffc85df0fbf8/extensions/sample/ufo_ext_sample/manifest.py)
- [Public lifecycle and pack declarations](https://github.com/ufo-ai/ufo-core/blob/63ba388ed449ff46c9d70744119dffc85df0fbf8/core/src/ufo/runtime/ext/manifest.py)
- [ToolContext and ToolResult](https://github.com/ufo-ai/ufo-core/blob/63ba388ed449ff46c9d70744119dffc85df0fbf8/core/src/ufo/runtime/tools/context.py)
- [Extension discovery and activation](https://github.com/ufo-ai/ufo-core/blob/63ba388ed449ff46c9d70744119dffc85df0fbf8/core/src/ufo/host/ext/loader.py)
- [Operator configuration paths](https://github.com/ufo-ai/ufo-core/blob/63ba388ed449ff46c9d70744119dffc85df0fbf8/core/src/ufo/cli.py)
- [Terminal configuration paths](https://github.com/ufo-ai/ufo-core/blob/63ba388ed449ff46c9d70744119dffc85df0fbf8/client/src/config.rs)
