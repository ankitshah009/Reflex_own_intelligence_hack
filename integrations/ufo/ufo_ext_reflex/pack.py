"""Small self-hosted pack using the official runtime's installed extensions."""

from ufo.sdk.manifest import Pack


def pack() -> Pack:
    return Pack(
        name="reflex-demo", version="0.1.0",
        extensions=("ufo", "context_compact", "index_default", "embed_openai", "flags_open", "reflex"),
    )
