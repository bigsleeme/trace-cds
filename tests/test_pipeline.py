from tracecds.pipeline import TraceCDS


class ScriptedLLM:
    """Stands in for an LLM that ignores instructions in different ways."""

    name = "llm"

    def __init__(self, lines):
        self.lines = lines

    def generate(self, question, passages):
        return self.lines


def test_answers_with_citations(passages):
    ans = TraceCDS(passages).ask("What are the contraindications for exampledrug?")
    assert ans.status == "answered"
    assert ans.citations and all(c.passage.source_url for c in ans.citations)
    assert all("[S" in s for s in ans.statements)
    assert all(c.passed for c in ans.criteria)


def test_blocks_time_critical(passages):
    ans = TraceCDS(passages).ask("My patient is having anaphylaxis on exampledrug, what now?")
    assert ans.status == "blocked"
    c4 = next(c for c in ans.criteria if c.criterion == 4)
    assert c4.passed and "declined" in c4.detail
    assert not ans.statements


def test_abstains_out_of_scope(passages):
    assert TraceCDS(passages).ask("What is the capital of France?").status == "abstained"


def test_guardrails_remove_bad_llm_output_and_fall_back(passages):
    llm = ScriptedLLM([
        "Give 850 mg twice daily [S1].",            # unsupported number + directive
        "You should stop exampledrug today [S2].",  # directive
        "Exampledrug cures diabetes.",              # no citation
    ])
    ans = TraceCDS(passages, generator=llm).ask("What is the starting dose of exampledrug?")
    assert len(ans.removed_statements) == 3
    assert ans.status == "answered"  # fell back to extractive quotes
    assert all(s.startswith("According to") for s in ans.statements)


def test_table_rows_are_quoted_with_headers(passages):
    ans = TraceCDS(passages).ask("How is the exampledrug dose adjusted by eGFR kidney function?")
    table_lines = [s for s in ans.statements if "eGFR (mL/min):" in s]
    assert table_lines, ans.statements


def test_patient_specific_note(passages):
    ans = TraceCDS(passages).ask("What dose of exampledrug should I give my patient?")
    assert ans.status == "answered"
    assert any("specific patient" in n for n in ans.limitations)


def test_llm_generator_parses_lines_and_strips_reasoning(monkeypatch):
    from tracecds.generate import LLMGenerator

    gen = LLMGenerator(base_url="http://localhost:9/v1", model="test")
    monkeypatch.setattr(gen, "complete", lambda system, user: "1. First [S1].\n- Second [S2].\n")
    assert gen.generate("q", []) == ["First [S1].", "Second [S2]."]
    monkeypatch.setattr(gen, "complete", lambda system, user: "INSUFFICIENT")
    assert gen.generate("q", []) == []
    assert not gen.available()  # nothing listening on port 9
