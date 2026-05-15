"""
suggestion.py — Auto-fill ("Surprise Me") helper for the create-story form.

Exposes a single async function that calls a small LLM agent with structured
output to invent a fresh, internally-consistent set of seed values for every
text field on the form. The frontend's "Surprise Me" button POSTs to
``/api/suggest-story`` (wired in main.py), which delegates here.

Variety is driven by:
  * A randomized INSPIRATION block injected into the prompt on every call
    (random animal, setting flavor, and feeling word).
  * Random seed text appended to the prompt so the cache key changes.

The agent is constructed once at module import time and reused across calls.
"""
from __future__ import annotations

import logging
import random
import secrets

from agent_framework import Agent

from .agent_factory import build_chat_agent, run_structured
from .models import StorySuggestion
from .prompts import STORY_SUGGESTION_INSTRUCTIONS
from .utils import record_llm_usage

logger = logging.getLogger(__name__)


# Curated inspiration tokens. The lists are deliberately broad and tilted
# toward unusual/creative options so the LLM gets pushed away from the
# default "rabbit / forest / bravery" combo. Tokens are randomized on every
# call and shown to the model as "creative nudge" — the model is NOT required
# to copy them verbatim.
_ANIMALS_AND_PROTAGONISTS = [
    "an octopus librarian", "a forgetful lighthouse", "a brave teacup",
    "a paleontologist hedgehog", "a stargazing camel", "a mailbox who collects stories",
    "a snail who paints murals", "a curious snowman", "a tiny cloud who can't rain",
    "a young dragon who breathes bubbles", "a deep-sea diving raccoon",
    "a botanist beaver", "a gentle yeti chef", "a robot bee",
    "a moon-fishing cat", "a marbled marmoset weaver", "a forgetful golem",
    "a tea-making turtle", "a kite-builder bat", "a quokka cartographer",
    "a desert fox who builds windchimes", "a punctual capybara",
    "a stowaway field mouse on a hot-air balloon", "a polite swamp monster",
    "a tiny knight in a teapot kingdom", "an apprentice cloud-sculptor",
    "a clockwork sparrow", "a quiet whale who hums lullabies",
    "a woolly mammoth who paints constellations",
]

_SETTING_FLAVORS = [
    "a city built into the branches of one enormous tree",
    "a town where the houses change color with the season",
    "a desert oasis where the rocks tell jokes",
    "a quiet underwater post office",
    "a moonlit garden of glass flowers",
    "a fishing village on the back of a sleeping whale",
    "a frozen lake whose ice records footsteps from a hundred years ago",
    "a cloud-island where rain drops upward",
    "a museum of forgotten umbrellas",
    "a windy mountaintop teahouse",
    "a coral reef built around an old sunken bicycle",
    "a tunnel system carved by ancient, kind beetles",
    "a windmill that grinds memories into music",
    "a river where the current flows in both directions at once",
    "a city of paper houses that rustle in the wind",
    "a lighthouse at the edge of a starless sea",
    "a marketplace held inside a giant hollow pumpkin",
    "an abandoned train station where trains arrive only on Tuesdays",
    "a swamp where every stone is a sleeping creature",
    "a mountain pass between two countries that disagree about the time of day",
]

_FEELINGS = [
    "tender", "playful", "mysterious", "cozy", "adventurous", "silly",
    "brave", "thoughtful", "curious", "warm", "bittersweet", "hopeful",
    "patient", "mischievous", "gentle", "determined", "wide-eyed",
    "earnest", "whimsical", "sun-warmed", "starry-eyed",
]


def _build_inspiration_prompt() -> str:
    rng = random.Random(secrets.token_bytes(16))
    animal = rng.choice(_ANIMALS_AND_PROTAGONISTS)
    setting = rng.choice(_SETTING_FLAVORS)
    feeling_a, feeling_b = rng.sample(_FEELINGS, 2)
    seed = secrets.token_hex(4)

    return (
        "Suggest a fresh story seed for the form. Use the inspiration block "
        "below as a creative nudge — feel free to depart from it, but use it "
        "to push your suggestion somewhere it might not otherwise have gone.\n\n"
        "INSPIRATION (random — pick what serves the story):\n"
        f"  - Protagonist nudge:  {animal}\n"
        f"  - Setting nudge:      {setting}\n"
        f"  - Emotional register: {feeling_a} with a hint of {feeling_b}\n\n"
        f"(novelty seed: {seed})"
    )


class StorySuggestionService:
    """Single-method service used by the FastAPI endpoint."""

    def __init__(self) -> None:
        self._agent = build_chat_agent(
            name="StorySuggestionAgent",
            instructions=STORY_SUGGESTION_INSTRUCTIONS,
        )

    async def suggest(self) -> StorySuggestion:
        prompt = _build_inspiration_prompt()
        logger.info("[Suggestion] Generating new story seed…")
        result, suggestion = await run_structured(
            self._agent,
            prompt,
            response_format=StorySuggestion,
        )
        record_llm_usage(result)
        logger.info(
            "[Suggestion] Suggested main_character=%r, setting=%r",
            suggestion.main_character,
            suggestion.setting,
        )
        return suggestion
