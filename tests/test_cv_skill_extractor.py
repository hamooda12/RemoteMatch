from app.services.cv_skill_extractor import (
    SKILL_EXTRACTION_VERSION,
    extract_skills,
)


def test_extracts_skills_in_first_appearance_order() -> None:
    text = """
    Built APIs using FastAPI and PostgreSQL.
    Containerized services using Docker.
    Developed automation scripts using Python.
    """

    assert extract_skills(text) == [
        "FastAPI",
        "PostgreSQL",
        "Docker",
        "Python",
    ]


def test_normalizes_aliases_and_removes_duplicates() -> None:
    text = """
    Experience with Amazon Web Services and AWS.
    Deployed workloads to Kubernetes and k8s.
    Used PostgreSQL and Postgres.
    """

    assert extract_skills(text) == [
        "AWS",
        "Kubernetes",
        "PostgreSQL",
    ]


def test_distinguishes_java_from_javascript() -> None:
    text = """
    JavaScript and TypeScript frontend development.
    Java and Spring Boot backend development.
    """

    assert extract_skills(text) == [
        "JavaScript",
        "TypeScript",
        "Java",
        "Spring Boot",
    ]


def test_extracts_devops_and_api_aliases() -> None:
    text = """
    Built RESTful APIs and microservice architecture.
    Automated CI/CD using GitHub Actions.
    Deployed to GCP using Terraform.
    """

    assert extract_skills(text) == [
        "REST API",
        "Microservices",
        "CI/CD",
        "GitHub Actions",
        "Google Cloud",
        "Terraform",
    ]


def test_does_not_match_unrelated_substrings() -> None:
    text = """
    I express ideas clearly and enjoy angular momentum problems.
    I go to work and collaborate with other engineers.
    """

    assert extract_skills(text) == []


def test_extraction_has_a_visible_version() -> None:
    assert SKILL_EXTRACTION_VERSION == "taxonomy-v1"


def test_detects_angular_after_rejected_physics_context() -> None:
    text = """
    Studied angular momentum during university.
    Later developed web applications using Angular and TypeScript.
    """

    assert extract_skills(text) == [
        "Angular",
        "TypeScript",
    ]
