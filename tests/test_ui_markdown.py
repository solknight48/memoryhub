"""The UI's markdown-lite renderer, exercised through `tests/mdrender.mjs`.

Dialog is shown as markdown, and pipe tables are the one construct with enough
structure to get subtly wrong — alignment, ragged rows, escaped pipes, and the
line between "a table" and "prose that happens to contain a bar". Everything
still has to go through textContent, never innerHTML.
"""

from __future__ import annotations

import re

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
    "bare_table": "a | b\n--- | ---\n1 | 2",
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
    "bare": "open http://127.0.0.1:7777/?t=abc-DEF_1 now",
    "bold_url": "**http://127.0.0.1:7777/?t=vfy2JsyTV_4pjOqV73D6OA**",
    "punct": "docs at https://example.com/x. (also https://example.com/y) done",
    "wrapped": "see https://en.wikipedia.org/wiki/Path_(computing) for more",
    "in_code": "`https://example.com/raw` stays code",
    "no_scheme": "javascript:alert(1) and ftp://x/y and www.example.com",
    "cpp": (
        "```cpp\n"
        "// on_venue_terminal 需要 now_ms\n"
        "#include <string>\n"
        'const std::string vo = venue_submit_(now_ms, buy, 1.5, "PEG");\n'
        "const Alias claim = it->second;\n"
        "```"
    ),
    "pyfence": "```python\ndef halve(x):  # in two\n    return x / 2\n```",
    "shfence": "```\n$ uv run pytest -q  # the suite\ngrep -n foo bar.py\n```",
    "plainfence": "```\njust some prose sitting in a fence\n```",
}


def unmarked(html: str) -> str:
    """The code back out of the rendered block: spans stripped, entities undone."""
    inner = html.split("<code>", 1)[1].split("</code>", 1)[0]
    bare = re.sub(r"</?span[^>]*>", "", inner)
    return bare.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


@pytest.fixture(scope="session")
def rendered() -> dict[str, str]:
    """Render every case in one node run — process startup dwarfs the work."""
    keys = list(CASES)
    out = run_ui_js(md=[CASES[k] for k in keys])
    return dict(zip(keys, out["md"], strict=True))


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
    assert '<td style="text-align:right"><strong>+902,390</strong></td>' in rendered["quant"]
    assert "<code>md()</code>" in rendered["rich"]
    assert '<a href="https://example.com"' in rendered["rich"]


def test_the_delimiter_row_sets_alignment(rendered):
    html = rendered["align"]
    assert '<th style="text-align:left">l</th>' in html
    assert '<th style="text-align:center">c</th>' in html
    assert '<th style="text-align:right">r</th>' in html
    assert "<th>d</th>" in html  # no colon, no style


def test_outer_pipes_are_optional(rendered):
    html = rendered["bare_table"]
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


# --- links -------------------------------------------------------------------
# A URL you cannot click is a URL you retype, and dialog is full of them —
# every `mh ui` line mh itself prints is one.


def test_a_bare_url_becomes_a_link(rendered):
    html = rendered["bare"]
    assert 'href="http://127.0.0.1:7777/?t=abc-DEF_1"' in html
    assert 'target="_blank"' in html and 'rel="noopener noreferrer"' in html
    assert html.startswith('<div class="md"><p>open <a')
    assert html.endswith(" now</p></div>")  # the prose around it is untouched


def test_a_url_inside_bold_is_still_a_link(rendered):
    # mh prints its own URL in bold; before this it rendered as dead text
    html = rendered["bold_url"]
    assert '<strong><a href="http://127.0.0.1:7777/?t=vfy2JsyTV_4pjOqV73D6OA"' in html
    assert html.endswith("</a></strong></p></div>")


def test_sentence_punctuation_stays_out_of_the_href(rendered):
    html = rendered["punct"]
    assert 'href="https://example.com/x"' in html
    assert ">https://example.com/x</a>. (also" in html  # the full stop is prose
    assert ">https://example.com/y</a>) done" in html  # so is the closing paren


def test_a_bracket_the_url_opened_itself_stays_in(rendered):
    html = rendered["wrapped"]
    assert 'href="https://en.wikipedia.org/wiki/Path_(computing)"' in html
    assert ">https://en.wikipedia.org/wiki/Path_(computing)</a> for more" in html


def test_a_url_in_backticks_stays_code(rendered):
    html = rendered["in_code"]
    assert "<code>https://example.com/raw</code>" in html
    assert "<a " not in html


def test_only_http_urls_are_ever_linked(rendered):
    html = rendered["no_scheme"]
    assert "<a " not in html
    assert "javascript:" not in html.replace("javascript:alert(1)", "")  # text, not href


# --- syntax colour ------------------------------------------------------------
# It may colour nothing, but it must never change what the code says.


@pytest.mark.parametrize("case", ["cpp", "pyfence", "shfence", "plainfence"])
def test_highlighting_never_alters_a_character(rendered, case):
    body = CASES[case].split("\n", 1)[1].rsplit("\n```", 1)[0]
    assert unmarked(rendered[case]) == body


def test_cpp_gets_its_keywords_strings_and_comments(rendered):
    html = rendered["cpp"]
    assert '<span class="k">const</span>' in html
    assert '<span class="s">"PEG"</span>' in html
    assert '<span class="c">// on_venue_terminal 需要 now_ms</span>' in html
    assert '<span class="f">venue_submit_</span>' in html  # a call, by its "("
    assert '<span class="n">1.5</span>' in html
    assert '<span class="c">#include' not in html  # a preprocessor line, not a comment
    assert '<span class="t">Alias</span>' in html  # CamelCase reads as a type
    assert '<span class="t">PEG' not in html  # ALL-CAPS does not


def test_python_treats_hash_as_a_comment(rendered):
    html = rendered["pyfence"]
    assert '<span class="c"># in two</span>' in html
    assert '<span class="k">def</span>' in html and '<span class="k">return</span>' in html
    assert '<span class="f">halve</span>' in html


def test_a_fence_of_prose_is_left_alone(rendered):
    html = rendered["plainfence"]
    assert 'class="k"' not in html and 'class="c"' not in html


def test_the_language_is_taken_from_the_fence_then_guessed():
    out = run_ui_js(
        codeLang=[
            ["cpp", ""],
            ["c++", ""],
            ["py", ""],
            ["bash", ""],
            ["klingon", ""],
            ["", "auto x = std::move(y);"],
            ["", "def f(x):\n    return x"],
            ["", "const f = () => 1;"],
            ["", "$ grep -n foo bar"],
            ["", "the quick brown fox"],
        ]
    )["codeLang"]
    assert out == [
        "cpp",
        "cpp",
        "python",
        "shell",
        "generic",
        "cpp",
        "python",
        "js",
        "shell",
        "generic",
    ]


def test_a_header_only_table_renders(rendered):
    assert "<tbody></tbody>" in rendered["header_only"]


def test_cell_content_is_escaped_like_every_other_node(rendered):
    html = rendered["html"]
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "<img" not in html
