"""Verify real tokenizer preparation without a River key or model invocation."""

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("HF_HOME", str(ROOT / ".cache" / "huggingface"))
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
sys.path.insert(0, str(ROOT / "backend"))

from reflex.core import build_review_prompt  # noqa: E402
from reflex.fixtures import HELD_OUT_PRS, SAMPLE_PRS  # noqa: E402
from reflex.integrations.river import (  # noqa: E402
    _load_tokenizer,
    _render_prompt,
    _tokenizer_revision,
    make_sft_datum,
)

model = os.getenv("RIVER_BASE_MODEL") or "Qwen/Qwen3.5-9B"
tokenizer = _load_tokenizer(model)
counts = []
for case in [*SAMPLE_PRS, *HELD_OUT_PRS]:
    rendered = _render_prompt(tokenizer, build_review_prompt(case))
    counts.append(len(tokenizer(rendered, add_special_tokens=False)["input_ids"]))

# This completion checks tensor alignment only. It is never stored as feedback.
completion = json.dumps({"decision": "APPROVE", "summary": "Alignment check only.", "issues": []})
rendered = _render_prompt(tokenizer, build_review_prompt(SAMPLE_PRS[0]))
datum = make_sft_datum(tokenizer, rendered, completion)
assert len(datum["input_ids"]) == len(datum["target_tokens"]) == len(datum["weights"])
assert datum["target_tokens"][-1] == tokenizer.eos_token_id
assert datum["weights"][-1] == 1
print(
    json.dumps(
        {
            "model": model,
            "tokenizer": type(tokenizer).__name__,
            "revision": _tokenizer_revision(tokenizer),
            "cases": len(counts),
            "minimum_prompt_tokens": min(counts),
            "maximum_prompt_tokens": max(counts),
            "training_prompt_tokens_total": sum(counts[: len(SAMPLE_PRS)]),
            "aligned_sft_tokens": len(datum["input_ids"]),
            "cloud_inference_calls": 0,
        },
        indent=2,
    )
)
