"""Numbers in a report must exist in the evidence."""

import pytest

from app.finance.grounding import EvidencePool, check_text, extract_numbers

EVIDENCE = [
    (
        "ev_aaaaaaaaaaaaaaaa",
        {
            "columns": ["region", "margin", "revenue"],
            "rows": [["West", 0.2047, 39685803.0], ["East", 0.2743, 22019534.0]],
        },
    ),
    (
        "ev_bbbbbbbbbbbbbbbb",
        {"op": "growth", "values": {"total_change": -0.1042, "first": 0.3089}, "table": [{"change_pct": -0.3373}]},
    ),
    ("ev_cccccccccccccccc", {"columns": ["n", "empty"], "rows": [[1279400, None], [45, None]]}),
]
POOL = EvidencePool(EVIDENCE)


@pytest.mark.parametrize(
    "sentence",
    [
        "West gross margin was 20.5% in the quarter.",
        "West gross margin was 20.47%.",
        "Margin fell by 10.4 percentage points.",
        "Margin fell 10.42 pp from 30.9%.",
        "Revenue in the West was $39.7M.",
        "Revenue in the West was $39,685,803.",
        "East revenue reached 22.0 million.",
        "Orders totalled 1,279,400 units, about $1.28M.",
        "Customers paid 45 days late.",
        "The relative decline was 33.7%.",
        "Margin dropped to 0.2047.",
    ],
)
def test_figures_present_in_the_evidence_are_supported(sentence):
    result = check_text(sentence, POOL)
    assert result.unsupported == [] and result.cleaned == sentence and result.supported


@pytest.mark.parametrize(
    "sentence",
    [
        "West gross margin was 25.5% in the quarter.",
        "Revenue in the West was $41.2M.",
        "Margin fell by 12.9 percentage points.",
        "Costs rose 18% after the supplier increase.",
        "Customers paid 60 days late.",
    ],
)
def test_figures_absent_from_the_evidence_are_removed(sentence):
    result = check_text("Margins fell in the West. " + sentence + " Other regions held steady.", POOL)
    assert result.unsupported == [sentence]
    assert result.cleaned == "Margins fell in the West. Other regions held steady."


def test_which_evidence_supports_each_figure_is_recorded():
    result = check_text("West margin was 20.5% on revenue of $39.7M, down 10.4 points.", POOL)
    assert [(r.text, r.handle) for r in result.supported] == [
        ("20.5%", "ev_aaaaaaaaaaaaaaaa"), ("$39.7M", "ev_aaaaaaaaaaaaaaaa"), ("10.4 points", "ev_bbbbbbbbbbbbbbbb"),
    ]  # fmt: skip


@pytest.mark.parametrize(
    "text",
    [
        "In Q3 2026 margins fell compared with 2026-Q2.",
        "From 2026-07-01 the supplier raised prices.",
        "The 3rd quarter was the weakest of the 4 quarters in 2026.",
        "See ev_1234567812345678 and ev_0000beef0000beef0000beef for the detail.",
        "Three regions and the top 10 customers were reviewed in FY26 and H1.",
        "No figures here at all.",
    ],
)
def test_dates_periods_ordinals_small_counts_and_handles_are_not_figures(text):
    assert extract_numbers(text) == []
    assert check_text(text, POOL).cleaned == text


def test_null_and_boolean_evidence_values_never_match():
    pool = EvidencePool([("ev_x", {"rows": [[None, True, False, "12.5"]]})])
    assert check_text("The rate was 100%.", pool).unsupported == ["The rate was 100%."]
    assert check_text("The rate was 12.5%.", pool).unsupported == ["The rate was 12.5%."]  # strings are not numbers


def test_empty_evidence_supports_nothing_but_plain_prose():
    pool = EvidencePool([])
    assert check_text("Revenue was $5M.", pool).cleaned == ""
    assert check_text("The data does not include headcount.", pool).cleaned == "The data does not include headcount."


def test_printed_precision_sets_the_tolerance():
    assert check_text("Margin was 20%.", POOL).unsupported == []  # 20.47% printed to the nearest percent
    assert check_text("Margin was 20.9%.", POOL).unsupported == ["Margin was 20.9%."]
    assert check_text("Revenue was $40M.", POOL).unsupported == []  # 39.69M to the nearest million
    assert check_text("Revenue was $39.2M.", POOL).unsupported == ["Revenue was $39.2M."]


def test_a_percentage_range_states_two_percentages():
    assert check_text("Margin stayed at 20.5-27.4% across regions.", POOL).unsupported == []
    assert check_text("Margin stayed at 20.5 to 27.4% across regions.", POOL).unsupported == []
    assert check_text("Margin stayed at 20.5-29.9% across regions.", POOL).unsupported != []


def test_digits_inside_names_are_not_figures():
    """Found by the held-out evaluation: 'West Enterprise Customer 0179' lost its sentence."""
    pool = EvidencePool(
        [
            (
                "ev_n",
                {
                    "columns": ["customer_name", "revenue"],
                    "rows": [["West Enterprise Customer 0179", 2821560.5], ["Depot 4410", 5.0]],
                },
            )
        ]
    )
    sentence = "The largest customer was West Enterprise Customer 0179 with revenue of $2.82M."
    assert check_text(sentence, pool).cleaned == sentence
    assert check_text("Depot 4410 was second.", pool).unsupported == []
    assert check_text("We shipped 4411 units.", pool).unsupported == [
        "We shipped 4411 units."
    ]  # a real unsupported figure


def test_percent_written_as_a_word_is_a_figure():
    """Found in review: '25 percent' was skipped as a small bare count."""
    assert check_text("Revenue grew 25 percent.", POOL).unsupported == ["Revenue grew 25 percent."]
    assert check_text("West margin was 20.5 percent.", POOL).unsupported == []


@pytest.mark.parametrize("sentence", ["Margin moved -5% in the quarter.", "Margin moved −5% in the quarter."])
def test_an_explicit_minus_must_match_a_negative_value(sentence):
    positive = EvidencePool([("ev_aaaaaaaaaaaaaaaa", {"rows": [[5.0]]})])
    negative = EvidencePool([("ev_aaaaaaaaaaaaaaaa", {"rows": [[-5.0]]})])
    assert check_text(sentence, positive).unsupported == [sentence]
    assert check_text(sentence, negative).unsupported == []


def test_an_unsigned_figure_matches_either_sign():
    """Prose says 'fell 5%' for a value of -5%; magnitudes are how people write changes."""
    negative = EvidencePool([("ev_aaaaaaaaaaaaaaaa", {"rows": [[-5.0]]})])
    assert check_text("Margin fell 5% in the quarter.", negative).unsupported == []


def test_a_hyphen_between_two_numbers_is_not_a_minus():
    pool = EvidencePool([("ev_aaaaaaaaaaaaaaaa", {"rows": [[25]]})])
    assert check_text("Payment took 20-25 days.", pool).unsupported == []


def test_a_negative_amount_in_brackets_matches_a_negative_value():
    negative = EvidencePool([("ev_aaaaaaaaaaaaaaaa", {"rows": [[-3_200_000.0]]})])
    positive = EvidencePool([("ev_aaaaaaaaaaaaaaaa", {"rows": [[3_200_000.0]]})])
    sentence = "The cost movement was (-$3.2M) in July."
    assert check_text(sentence, negative).unsupported == []
    assert check_text(sentence, positive).unsupported == [sentence]


def test_a_figure_that_cites_its_handle_is_matched_only_against_that_result():
    """4.5 is in the second result, but the sentence cites the first, where only 20.5 appears."""
    pool = EvidencePool(
        [
            ("ev_aaaaaaaaaaaaaaaa", {"columns": ["region", "margin"], "rows": [["West", 20.5]]}),
            ("ev_bbbbbbbbbbbbbbbb", {"rows": [[4.5]]}),
        ]
    )
    cited = "West margin was 4.5% (ev_aaaaaaaaaaaaaaaa)."
    assert check_text(cited, pool).unsupported == [cited]
    assert check_text("West margin was 20.5% (ev_aaaaaaaaaaaaaaaa).", pool).unsupported == []
    assert check_text("West margin was 4.5%.", pool).unsupported == []  # uncited: any result may support it
