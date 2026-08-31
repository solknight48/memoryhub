"""The UI's markdown-lite renderer, exercised through `tests/mdrender.mjs`.

Dialog is shown as markdown, and pipe tables are the one construct with enough
structure to get subtly wrong — alignment, ragged rows, escaped pipes, and the
line between "a table" and "prose that happens to contain a bar". Everything
still has to go through textContent, never innerHTML.
"""

from __future__ import annotations

import pytest

from conftest import needs_node, run_ui_js

pytestmark = needs_node

QUANT = "\n".join(
    [
        "**Mixed target, 2013-04-02 → 2026-08-24, 3,278 trading days:**",
        "",
        "| bucket | days | net PnL | mean/day | win% | Sharpe | maxDD |",
        "|---|---:|---:|---:|---:|---:|---:|",
        "| day_range | 697 | **+902,390** | 1,294.7 | 54.2 | **1.95** | −84,662 |",
        "| non-day_range | 2,581 | +2,092,577 | 810.8 | 50.6 | 1.04 | −398,712 |",
        "",
        "Welch t-test 1.947 → **0.0355**, so the difference is significant.",
    ]
)

CASES = {
    "quant": QUANT,
    "align": "| l | c | r | d |\n|:---|:---:|---:|---|\n| 1 | 2 | 3 | 4 |",
    "bare": "a | b\n--- | ---\n1 | 2",
    "escaped": "| x | y |\n| --- | --- |\n| a \\| b | c |",
    "ragged": "| a | b | c |\n|---|---|---|\n| 1 |\n| 1 | 2 | 3 | 4 |",
    "mismatch": "| a | b | c |\n|---|---|\n| 1 | 2 | 3 |",
    "stray": "use a | b to pipe\nand then some more text",
    "rule": "above\n\n---\n\nbelow",
    "fenced": "```\n| a | b |\n|---|---|\n| 1 | 2 |\n```",
    "then_fence": "| a |\n|---|\n| 1 |\n```\ncode\n```",
    "header_only": "| a | b |\n|---|---|",
    "html": "| a |\n|---|\n| <img src=x onerror=alert(1)> |",
    "rich": "| what | where |\n|---|---|\n| `md()` | [docs](https://example.com) |",
}


@pytest.fixture(scope="session")
def rendered() -> dict[str, str]:
    """Render every case in one node run — process startup dwarfs the work."""
    keys = list(CASES)
    out = run_ui_js(md=[CASES[k] for k in keys])
    return dict(zip(keys, out["md"]))


def test_a_pipe_table_becomes_a_table(rendered):
    html = rendered["quant"]
    assert "<table>" in html
    assert "|---" not in html and "| bucket |" not in html  # no raw pipes leak
    assert html.count("<th>") + html.count("<th ") == 7  # not "<th", that is <thead>
    assert html.count("<td") == 14
    assert html.count("<tr>") == 3  # one header row, two body rows


def test_the_prose_around_a_table_is_untouched(rendered):
    html = rendered["quant"]
    assert html.startswith('<div class="md"><p><strong>Mixed target')
    assert "<p>Welch t-test 1.947 → <strong>0.0355</strong>" in html


def test_inline_markup_still_runs_inside_cells(rendered):
    assert (
        '<td style="text-align:right"><strong>+902,390</strong></td>'
        in rendered["quant"]
    )
    assert "<code>md()</code>" in rendered["rich"]
    assert '<a href="https://example.com"' in rendered["rich"]


def test_the_delimiter_row_sets_alignment(rendered):
    html = rendered["align"]
    assert '<th style="text-align:left">l</th>' in html
    assert '<th style="text-align:center">c</th>' in html
    assert '<th style="text-align:right">r</th>' in html
    assert "<th>d</th>" in html  # no colon, no style


def test_outer_pipes_are_optional(rendered):
    html = rendered["bare"]
    assert "<th>a</th><th>b</th>" in html
    assert "<td>1</td><td>2</td>" in html


def test_an_escaped_pipe_stays_inside_its_cell(rendered):
    assert "<td>a | b</td><td>c</td>" in rendered["escaped"]


def test_rows_are_padded_and_clipped_to_the_header(rendered):
    html = rendered["ragged"]
    assert "<td>1</td><td></td><td></td>" in html  # short row padded
    assert html.count("<td") == 6  # long row clipped, not 7


@pytest.mark.parametrize("case", ["mismatch", "stray", "fenced"])
def test_things_that_only_look_like_tables(rendered, case):
    assert "<table>" not in rendered[case]


def test_a_fence_still_wins_and_still_ends_a_table(rendered):
    assert "<pre><code>| a | b |" in rendered["fenced"]
    assert "<table>" in rendered["then_fence"] and "<pre>" in rendered["then_fence"]


def test_a_horizontal_rule_is_not_swallowed(rendered):
    assert "<hr>" in rendered["rule"]


def test_a_header_only_table_renders(rendered):
    assert "<tbody></tbody>" in rendered["header_only"]


def test_cell_content_is_escaped_like_every_other_node(rendered):
    html = rendered["html"]
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "<img" not in html
