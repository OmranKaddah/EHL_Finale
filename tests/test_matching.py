from hackathon_toolkit.matching import Constraint, MatchReport, Outcome, Specification, match_requirements, normalize_requirement


def test_units_and_mandatory_fail():
    report = match_requirements([
        Constraint(attribute="memory", operator="gte", value=64, unit="gigabyte"),
        Constraint(attribute="power", operator="lte", value=50, unit="watt", mandatory=False),
    ], {"memory": Specification(value=65536, unit="megabyte"),
        "power": Specification(value=60, unit="watt")})
    assert report.matches[0].outcome == Outcome.PASS
    assert report.matches[1].outcome == Outcome.FAIL
    assert report.overall == Outcome.PASS
    assert report.optional_score == 0


def test_unknown_conflict_and_model_hierarchy():
    report = match_requirements([
        Constraint(attribute="gpu", operator="or_better", value="RTX 4080"),
        Constraint(attribute="voltage", operator="gte", value=10, unit="volt"),
        Constraint(attribute="size", operator="range", value=[10, 20]),
    ], {"gpu": Specification(value="RTX 4090"), "voltage": Specification(value=10, unit="meter"),
        "size": [Specification(value=12), Specification(value=25)]},
        hierarchy={"RTX 4080": ["RTX 4090"]})
    assert [m.outcome for m in report.matches] == [Outcome.PASS, Outcome.UNKNOWN, Outcome.CONFLICT]
    assert report.overall == Outcome.CONFLICT


def test_or_better_without_hierarchy_is_unknown():
    result = match_requirements([Constraint(attribute="gpu", operator="or_better", value="RTX 4080")],
                                {"gpu": Specification(value="RTX 4090")})
    assert result.overall == Outcome.UNKNOWN


def test_requirement_phrase_normalization():
    requirement = normalize_requirement("At least 16 GB", "memory")
    assert (requirement.operator, requirement.value, requirement.unit) == ("gte", 16, "GB")
    assert normalize_requirement("Preferably supports ISO 9001", "standards").mandatory is False
    assert normalize_requirement("RTX 4080 or better", "gpu").operator == "or_better"
    with __import__("pytest").raises(ValueError): normalize_requirement("fast graphics", "gpu")
