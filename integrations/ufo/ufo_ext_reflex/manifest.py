"""Trusted self-hosted UFO extension; public SDK imports only."""

from ufo.sdk.manifest import HookSpec, Manifest, PromptSection
from ufo.sdk.tools import ToolDef

from ufo_ext_reflex.capture import observe
from ufo_ext_reflex.tools import ReviewInput, review_code_with_reflex


def manifest() -> Manifest:
    return Manifest(
        name="reflex", version="0.1.0",
        tools=(ToolDef(
            name="review_code_with_reflex",
            description=(
                "Ask the Reflex PR specialist to review an actual diff and repository context. "
                "Returns its decision and an experience ID for human feedback in Reflex. "
                "Auto uses the latest saved checkpoint when available, otherwise the base model. "
                "The learned condition requires a trained River checkpoint."
            ),
            input_model=ReviewInput, handler=review_code_with_reflex,
            side_effecting=True, binds_member_authority=False,
        ),),
        hooks=tuple(HookSpec(event=event, handler=observe) for event in (
            "user_prompt_submit", "post_tool_use", "post_tool_use_failure", "stop"
        )),
        prompt_sections=(PromptSection(
            name="reflex_reviewer",
            body=(
                "When asked to review a PR with Reflex, inspect the actual diff and relevant files, "
                "then call review_code_with_reflex once. Use the requested base, memory, or learned "
                "condition, or leave auto to use the latest saved model. State the returned review "
                "faithfully and show its experience ID and checkpoint. "
                "Human corrections are recorded in the Reflex app. Never fabricate test execution, "
                "tool outputs, human approval, training status, or a trained checkpoint."
            ),
        ),),
    )
