from tracecds.chunking import chunk_text, split_sentences
from tracecds.tables import html_table_to_markdown


def test_table_to_markdown_keeps_rows_and_caption():
    md = html_table_to_markdown("<table><caption>Doses</caption><tr><th>A</th><th>B</th></tr>"
                                "<tr><td>1 | x</td><td>2</td></tr></table>")
    assert md.startswith("Doses")
    assert "| A | B |" in md and "| --- | --- |" in md
    assert "1 \\| x" in md  # pipes escaped


def test_colspan_padding():
    md = html_table_to_markdown("<table><tr><td colspan='2'>Wide</td></tr><tr><td>a</td><td>b</td></tr></table>")
    assert md.splitlines()[0] == "| Wide |  |"


def test_sentences_not_split_on_decimals():
    assert split_sentences("Take 0.5 mg daily. Then stop.") == ["Take 0.5 mg daily.", "Then stop."]


def test_chunks_respect_limit_and_keep_sentences():
    text = " ".join(f"Sentence number {i} is here." for i in range(50))
    chunks = chunk_text(text, max_chars=120)
    assert all(len(c) <= 120 for c in chunks)
    assert all(c.endswith(".") for c in chunks)


def test_label_passages_have_provenance(passages):
    assert any(p.is_table for p in passages)
    p = passages[0]
    assert p.source_url.startswith("https://dailymed.nlm.nih.gov/")
    assert p.effective_date == "2025-01-15"
    assert not p.text.startswith("1 ")  # section number stripped
    assert not p.text.startswith("INDICATIONS")  # heading stripped
