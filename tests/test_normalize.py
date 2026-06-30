from src import normalize as norm


def test_phone_us_local():
    assert norm.normalize_phone("(415) 555-0199") == "+14155550199"


def test_phone_already_e164():
    assert norm.normalize_phone("+91 98765 43210") == "+919876543210"


def test_phone_garbage_returns_none():
    assert norm.normalize_phone("call me maybe") is None
    assert norm.normalize_phone("") is None
    assert norm.normalize_phone(None) is None


def test_date_iso():
    assert norm.normalize_date("2020-01") == ("2020-01", "normalized_date")


def test_date_slash():
    assert norm.normalize_date("01/2020") == ("2020-01", "normalized_date")


def test_date_month_name():
    assert norm.normalize_date("Jan 2020") == ("2020-01", "normalized_date")
    assert norm.normalize_date("January 2020") == ("2020-01", "normalized_date")


def test_date_year_only_never_invents_month():
    value, method = norm.normalize_date("2020")
    assert value is None
    assert method == "year_only_no_month"


def test_date_garbage():
    value, method = norm.normalize_date("sometime last year")
    assert value is None
    assert method == "unparsed_date"


def test_skill_alias_collapses_variants():
    assert norm.canonical_skill("JS") == "JavaScript"
    assert norm.canonical_skill("javascript") == "JavaScript"
    assert norm.canonical_skill("Javascript") == "JavaScript"


def test_skill_unknown_passthrough():
    assert norm.canonical_skill("Figma") == "Figma"


def test_country_lookup():
    assert norm.normalize_country("United States") == "US"
    assert norm.normalize_country("india") == "IN"
    assert norm.normalize_country("Narnia") is None


def test_email_validation():
    assert norm.normalize_email("Jane.Doe@Example.com") == "jane.doe@example.com"
    assert norm.normalize_email("not-an-email") is None
    assert norm.normalize_email(None) is None
