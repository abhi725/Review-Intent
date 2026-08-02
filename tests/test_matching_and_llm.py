import pytest

from intentdesk.llm import LLMError, validate_against
from intentdesk.llm.gemini_provider import _sanitise
from intentdesk.services.importer import _int_or_none
from intentdesk.services.matching import normalize_domain, normalize_name

# ------------------------------------------------------------------ matching


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Acme Retail Pvt. Ltd.", "acme retail"),
        ("ACME RETAIL PRIVATE LIMITED", "acme retail"),
        ("Acme Retail", "acme retail"),
        ("Acme  Retail,  Inc.", "acme retail"),
    ],
)
def test_corporate_boilerplate_normalizes_away(raw, expected):
    assert normalize_name(raw) == expected


def test_distinct_companies_do_not_collide():
    """The suffix stripper must not make different companies look identical —
    a false match means emailing the wrong company."""
    assert normalize_name("Acme Retail") != normalize_name("Acme Logistics")


def test_name_of_only_boilerplate_is_empty():
    """'Pvt Ltd' alone carries no identity; an empty result must not match."""
    assert normalize_name("Pvt Ltd") == ""
    assert normalize_name("") == ""


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://www.Acme.IN/contact", "acme.in"),
        ("http://acme.in", "acme.in"),
        ("WWW.ACME.IN", "acme.in"),
        ("acme.in/", "acme.in"),
        ("  acme.in  ", "acme.in"),
    ],
)
def test_domain_normalization(raw, expected):
    assert normalize_domain(raw) == expected


# ------------------------------------------------------- gemini schema dialect


def test_union_type_becomes_nullable():
    """Gemini rejects {"type": ["string","null"]}; sending it silently drops the
    call into free-form JSON."""
    out = _sanitise({"type": ["string", "null"]})
    assert out == {"type": "string", "nullable": True}


def test_unsupported_keywords_stripped():
    out = _sanitise(
        {"type": "object", "properties": {"a": {"type": "string"}},
         "additionalProperties": False, "$schema": "http://x"}
    )
    assert "additionalProperties" not in out
    assert "$schema" not in out
    assert out["properties"]["a"] == {"type": "string"}


def test_property_ordering_is_preserved():
    out = _sanitise(
        {"type": "object", "properties": {"b": {"type": "string"}, "a": {"type": "string"}}}
    )
    assert out["propertyOrdering"] == ["b", "a"]


def test_sanitise_recurses_into_nested_objects():
    out = _sanitise(
        {"type": "object",
         "properties": {"inner": {"type": ["integer", "null"], "additionalProperties": False}}}
    )
    assert out["properties"]["inner"] == {"type": "integer", "nullable": True}


# ---------------------------------------------------------- response validator

SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": ["a", "b"]},
        "note": {"type": ["string", "null"]},
    },
    "required": ["category", "note"],
}


def test_valid_response_passes():
    validate_against({"category": "a", "note": None}, SCHEMA)


def test_missing_required_field_is_rejected():
    """This is the degraded-schema signature: plausible output, wrong keys."""
    with pytest.raises(LLMError, match="missing required field"):
        validate_against({"complaint": "x", "employer": None}, SCHEMA)


def test_value_outside_enum_is_rejected():
    with pytest.raises(LLMError, match="not one of"):
        validate_against({"category": "Value for Money", "note": None}, SCHEMA)


def test_non_object_is_rejected():
    with pytest.raises(LLMError):
        validate_against(["a"], SCHEMA)


# ------------------------------------------------------------------- importer


@pytest.mark.parametrize(
    "raw,expected",
    [("40", 40), (" 40 ", 40), ("", None), (None, None), ("many", None), ("4.5", None)],
)
def test_agent_count_parsing_never_raises(raw, expected):
    """A malformed agents_est must yield None, not abort the whole import."""
    assert _int_or_none(raw) == expected
