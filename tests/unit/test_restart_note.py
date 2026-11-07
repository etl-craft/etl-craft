"""A pipeline's restart condition, said in words."""

import pytest

from etl_craft.core.restart import restart_note

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("value", "words"),
    [
        ("SCHEDULE", None),
        ("NONE", "Not started automatically"),
        ("SUCCESS|SKIPPED", "Restarts after a success or a skipped run"),
        ("SCHEDULE|FAILURE", "Restarts after a failure"),
        ("ALWAYS", "Restarts after every ending"),
        ("SKIPPED|FAILURE|SUCCESS", "Restarts after a success, a skipped run or a failure"),
    ],
)
def test_the_condition_is_said_in_words_only_when_it_adds_to_the_schedule(value, words):
    assert restart_note(value) == words
