import pytest

from jarvis.speech.text import SentenceBuffer, to_speech


def collect(parts, max_length=300):
    buffer = SentenceBuffer(max_length=max_length)
    result = []
    for part in parts:
        result.extend(buffer.feed(part))
    result.extend(buffer.flush())
    return result


@pytest.mark.parametrize("locale,dot,slash,at", [
    ("en-GB", "dot", "slash", "at"),
    ("pl-PL", "kropka", "ukośnik", "małpa"),
    ("ru-RU", "точка", "слэш", "собака"),
])
def test_explicit_locale_controls_url_and_email_words(locale, dot, slash, at):
    # Deliberately ASCII-only Polish/Russian input: never infer English by script.
    result = to_speech("Adres https://example.com/docs i a.b@example.org.", locale)
    assert f"example {dot} com {slash} docs" in result
    assert f"a {dot} b {at} example {dot} org." in result


def test_default_locale_and_normalization_copied_from_tts():
    assert to_speech("https://www.example.com/a_b-c") == (
        "example dot com slash a b c"
    )
    assert to_speech("At 12:30 on 01/02/2026: 12345!") == (
        "At 12 30 on 01 02 2026: 1 2 3 4 5!"
    )
    assert to_speech("Price 3.14, version 2.7.") == "Price 3.14, version 2.7."


def test_locale_not_inferred_from_script_and_unknown_locale_uses_english_words():
    assert " dot " in to_speech("Żółć https://example.com", "en-GB")
    assert " kropka " in to_speech("abc https://example.com", "pl-PL")
    assert " точка " in to_speech("abc https://example.com", "ru-RU")
    assert " dot " in to_speech("https://example.com", "de-DE")


@pytest.mark.parametrize("fence", ["```", "~~~", "````"])
def test_normalization_omits_closed_and_unclosed_fenced_code(fence):
    assert to_speech(f"Before {fence}py\nprint('secret')\n{fence} after.") == "Before after."
    assert to_speech(f"Before {fence}py\nsecret") == "Before"


def test_markdown_inline_syntax_and_link_destinations_are_not_spoken():
    assert to_speech("# **Hello** [world](https://example.com) and `code`.") == (
        "Hello world and code."
    )
    assert to_speech("_underlined_ ~~removed~~ 😀 <>") == "underlined removed"


def test_punctuation_requires_confirmation_and_flush_emits_tail():
    buffer = SentenceBuffer()
    assert buffer.feed("Hello.") == []
    assert buffer.feed(" ") == ["Hello."]
    assert buffer.feed("Second!") == []
    assert buffer.feed("\nUnfinished tail") == ["Second!"]
    assert buffer.flush() == ["Unfinished tail"]
    assert buffer.flush() == []


def test_closing_markdown_emphasis_does_not_delay_sentence_boundaries():
    assert collect(list("**Hello.** _Next!_ Tail")) == ["Hello.", "Next!", "Tail"]


def test_multiple_sentences_and_quoted_punctuation():
    assert collect(['He said "Hello." Next?! ', "Last."]) == [
        'He said "Hello."', "Next?!", "Last.",
    ]


@pytest.mark.parametrize("width", [1, 2, 3, 4, 7, 19, 1000])
def test_fragmented_fences_never_leak_code_or_language_header(width):
    text = "First.\n```python\nSECRET.foo().\n```\nSecond!\n~~~js\nHIDDEN\n~~~\nTail"
    result = collect([text[i:i + width] for i in range(0, len(text), width)])
    assert result == ["First.", "Second!", "Tail"]


def test_fences_do_not_join_words_and_inline_code_remains_readable():
    assert collect(["Before`", "``py\nsecret\n`", "``after."]) == ["Before after."]
    assert collect(list("Use `inline` **words**. ")) == ["Use inline words."]


def test_other_fence_character_inside_code_cannot_close_it():
    assert collect(list("Before ```\n~~~\nSECRET.\n``` after.")) == ["Before after."]


def test_unterminated_code_is_discarded_even_at_flush():
    assert collect(list("Before. ```python\nSECRET!")) == ["Before."]
    assert collect(["``", "`secret"]) == []
    assert collect(["```", "x" * 100000]) == []


def test_turns_use_separate_buffers():
    first = SentenceBuffer()
    first.feed("```unterminated")
    assert first.flush() == []
    second = SentenceBuffer()
    assert second.feed("New turn. ") == ["New turn."]


def test_decimals_abbreviations_and_urls_survive_character_deltas():
    text = "Dr. Smith paid 3.14 at https://example.com/a.b?x=2.7 today. Next."
    assert collect(list(text)) == [
        "Dr. Smith paid 3.14 at https://example.com/a.b?x=2.7 today.", "Next.",
    ]
    assert collect(list("Use e.g. U.S. examples. Fine.")) == [
        "Use e.g. U.S. examples.", "Fine.",
    ]
    assert collect(list("Np. jutro o 3.14. Dalej.")) == ["Np. jutro o 3.14.", "Dalej."]


def test_url_at_sentence_end_keeps_its_internal_dots():
    assert collect(list("See https://example.com/docs. Next.")) == [
        "See https://example.com/docs.", "Next.",
    ]
    assert collect(list("Email a.b@example.com now. Done.")) == [
        "Email a.b@example.com now.", "Done.",
    ]


@pytest.mark.parametrize("text", ["x" * 100000, "word " * 20000])
def test_huge_unpunctuated_stream_is_bounded_and_lossless(text):
    buffer = SentenceBuffer(max_length=300)
    result = []
    for i in range(0, len(text), 137):
        result.extend(buffer.feed(text[i:i + 137]))
        assert len(buffer._pending) < 300
    result.extend(buffer.flush())
    assert result and max(map(len, result)) <= 300
    assert "".join(result).replace(" ", "") == text.replace(" ", "")


def test_very_long_url_may_split_at_hard_limit_instead_of_growing_forever():
    result = collect(["https://example.com/" + "a" * 2000], max_length=80)
    assert len(result) > 20
    assert all(len(item) <= 80 for item in result)


def test_empty_and_whitespace_inputs_and_small_limit():
    assert collect(["", " \n\t"]) == []
    assert to_speech("") == ""
    with pytest.raises(ValueError):
        SentenceBuffer(max_length=0)
