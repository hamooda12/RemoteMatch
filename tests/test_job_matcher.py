from decimal import Decimal

from app.services.job_matcher import (
    CandidateMatchContext,
    calculate_job_match,
)


def test_perfect_job_match_scores_one_hundred() -> None:
    candidate = CandidateMatchContext(
        skills=(
            "Python",
            "FastAPI",
            "PostgreSQL",
        ),
        target_roles=("Backend Engineer",),
        experience_level="mid_level",
        minimum_salary=Decimal("60000"),
        salary_currency="USD",
    )

    result = calculate_job_match(
        candidate=candidate,
        job_title="Senior Backend Engineer",
        job_skills=(
            "Python",
            "FastAPI",
            "PostgreSQL",
        ),
        job_experience_level="junior",
        job_salary_min=Decimal("50000"),
        job_salary_max=Decimal("70000"),
        job_salary_currency="USD",
    )

    assert result.score == 100
    assert result.is_eligible is True
    assert result.skill_score == 60
    assert result.role_score == 20
    assert result.experience_score == 10
    assert result.salary_score == 10
    assert result.matched_skills == (
        "Python",
        "FastAPI",
        "PostgreSQL",
    )
    assert result.missing_skills == ()
    assert result.excluded_skills == ()


def test_partial_skills_match_aliases_and_report_missing_skills() -> None:
    candidate = CandidateMatchContext(
        skills=(
            "python",
            "nodejs",
        ),
    )

    result = calculate_job_match(
        candidate=candidate,
        job_title="Platform Developer",
        job_skills=(
            "Python",
            "Node.js",
            "PostgreSQL",
        ),
        job_experience_level=None,
        job_salary_min=None,
        job_salary_max=None,
        job_salary_currency=None,
    )

    assert result.score == 50
    assert result.skill_score == 40
    assert result.salary_score == 10
    assert result.matched_skills == (
        "Python",
        "Node.js",
    )
    assert result.missing_skills == ("PostgreSQL",)


def test_excluded_technology_makes_job_ineligible() -> None:
    candidate = CandidateMatchContext(
        skills=("Python",),
        excluded_technologies=("docker",),
    )

    result = calculate_job_match(
        candidate=candidate,
        job_title="Python Infrastructure Engineer",
        job_skills=(
            "Python",
            "Docker",
        ),
        job_experience_level=None,
        job_salary_min=None,
        job_salary_max=None,
        job_salary_currency=None,
    )

    assert result.score == 0
    assert result.is_eligible is False
    assert result.skill_score == 30
    assert result.excluded_skills == ("Docker",)
    assert any("excluded technology" in reason for reason in result.reasons)


def test_candidate_one_experience_level_below_gets_partial_score() -> None:
    candidate = CandidateMatchContext(
        experience_level="junior",
    )

    result = calculate_job_match(
        candidate=candidate,
        job_title="Software Engineer",
        job_skills=(),
        job_experience_level="mid_level",
        job_salary_min=None,
        job_salary_max=None,
        job_salary_currency=None,
    )

    assert result.experience_score == 5
    assert result.salary_score == 10
    assert result.score == 15


def test_candidate_far_below_required_experience_gets_no_experience_score() -> None:
    candidate = CandidateMatchContext(
        experience_level="internship",
    )

    result = calculate_job_match(
        candidate=candidate,
        job_title="Principal Engineer",
        job_skills=(),
        job_experience_level="senior",
        job_salary_min=None,
        job_salary_max=None,
        job_salary_currency=None,
    )

    assert result.experience_score == 0
    assert result.score == 10


def test_role_matching_ignores_seniority_modifiers() -> None:
    candidate = CandidateMatchContext(
        target_roles=("Backend Engineer",),
    )

    result = calculate_job_match(
        candidate=candidate,
        job_title="Senior Backend Software Engineer",
        job_skills=(),
        job_experience_level=None,
        job_salary_min=None,
        job_salary_max=None,
        job_salary_currency=None,
    )

    assert result.role_score == 20
    assert result.salary_score == 10
    assert result.score == 30


def test_salary_score_requires_matching_currency_and_sufficient_salary() -> None:
    candidate = CandidateMatchContext(
        minimum_salary=Decimal("60000"),
        salary_currency="USD",
    )

    matching_salary = calculate_job_match(
        candidate=candidate,
        job_title="Software Engineer",
        job_skills=(),
        job_experience_level=None,
        job_salary_min=Decimal("50000"),
        job_salary_max=Decimal("70000"),
        job_salary_currency="USD",
    )

    different_currency = calculate_job_match(
        candidate=candidate,
        job_title="Software Engineer",
        job_skills=(),
        job_experience_level=None,
        job_salary_min=Decimal("70000"),
        job_salary_max=Decimal("90000"),
        job_salary_currency="EUR",
    )

    missing_salary = calculate_job_match(
        candidate=candidate,
        job_title="Software Engineer",
        job_skills=(),
        job_experience_level=None,
        job_salary_min=None,
        job_salary_max=None,
        job_salary_currency=None,
    )

    assert matching_salary.salary_score == 10
    assert matching_salary.score == 10

    assert different_currency.salary_score == 0
    assert different_currency.score == 0

    assert missing_salary.salary_score == 0
    assert missing_salary.score == 0
