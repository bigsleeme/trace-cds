from tracecds.guardrails import check_input, check_statement, find_directive


def test_blocks_images_and_attachments():
    assert check_input("Analyze this rash photo please").status == "blocked"
    assert check_input("What is in the file?", has_attachment=True).status == "blocked"


def test_blocks_identifiers():
    assert check_input("MRN 1234567 on warfarin").status == "blocked"
    assert check_input("SSN 123-45-6789").status == "blocked"


def test_time_critical_needs_acute_context():
    assert check_input("My patient is having anaphylaxis, what now?").status == "time_critical"
    assert check_input("Code blue, patient unresponsive").status == "time_critical"
    # Informational questions about the same conditions are allowed.
    assert check_input("What does the label say about anaphylaxis?").status == "ok"
    assert check_input("Does the boxed warning mention suicidal thoughts?").status == "ok"


def test_patient_specific_flag():
    assert check_input("What dose should I give my patient?").patient_specific


def test_directive_detection():
    assert find_directive("Give 500 mg twice daily [S1].")
    assert find_directive("You should stop the drug [S1].")
    assert find_directive("The correct dose is 500 mg [S1].")
    # Reporting what the label says is not a directive.
    assert find_directive('According to the label: "Discontinue if lactic acidosis is suspected." [S1]') is None
    assert find_directive("The label states the starting dose is 500 mg [S1].") is None


def test_statement_requires_citation(passages):
    sources = dict(enumerate(passages, 1))
    assert not check_statement("The starting dose is 500 mg.", sources).ok


def test_statement_rejects_unsupported_numbers(passages):
    dose = next(i for i, p in enumerate(passages, 1) if "starting dose" in p.text)
    sources = dict(enumerate(passages, 1))
    bad = check_statement(f"The label states the starting dose is 850 mg [S{dose}].", sources)
    assert not bad.ok and "850" in bad.reason
    good = check_statement(f"The label states the recommended starting dose is 500 mg orally twice a day [S{dose}].",
                           sources)
    assert good.ok, good.reason


def test_statement_rejects_directive(passages):
    dose = next(i for i, p in enumerate(passages, 1) if "starting dose" in p.text)
    sources = dict(enumerate(passages, 1))
    res = check_statement(f"Give the recommended starting dose of 500 mg orally twice a day with meals [S{dose}].",
                          sources)
    assert not res.ok and "Criterion 3" in res.reason
