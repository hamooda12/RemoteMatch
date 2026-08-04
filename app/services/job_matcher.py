import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

from app.services.cv_skill_extractor import extract_skills

SKILL_WEIGHT = 60
ROLE_WEIGHT = 20
EXPERIENCE_WEIGHT = 10
SALARY_WEIGHT = 10

_TOKEN_PATTERN = re.compile(r"[a-z0-9+#.]+", flags=re.IGNORECASE)

_ROLE_MODIFIERS = {
    "remote",
    "senior",
    "sr",
    "junior",
    "jr",
    "mid",
    "level",
    "lead",
    "staff",
    "principal",
}

_EXPERIENCE_RANKS = {
    "no_experience": 0,
    "internship": 1,
    "entry_level": 2,
    "junior": 3,
    "mid_level": 4,
    "senior": 5,
}


@dataclass(frozen=True, slots=True)
class CandidateMatchContext:
    skills: tuple[str, ...] = ()
    target_roles: tuple[str, ...] = ()
    experience_level: str | None = None
    minimum_salary: Decimal | None = None
    salary_currency: str | None = None
    excluded_technologies: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class JobMatchResult:
    score: int
    is_eligible: bool
    skill_score: int
    role_score: int
    experience_score: int
    salary_score: int
    matched_skills: tuple[str, ...]
    missing_skills: tuple[str, ...]
    excluded_skills: tuple[str, ...]
    reasons: tuple[str, ...]


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.casefold().split())


def _canonical_skill(value: str) -> tuple[str, str]:
    cleaned_value = " ".join(value.split())
    extracted_skills = extract_skills(cleaned_value)

    canonical_name = extracted_skills[0] if len(extracted_skills) == 1 else cleaned_value

    return _normalize(canonical_name), canonical_name


def _unique_skills(
    values: tuple[str, ...],
) -> tuple[tuple[str, str], ...]:
    unique_values: list[tuple[str, str]] = []
    seen_values: set[str] = set()

    for value in values:
        key, display_name = _canonical_skill(value)

        if not key or key in seen_values:
            continue

        seen_values.add(key)
        unique_values.append(
            (
                key,
                display_name,
            )
        )

    return tuple(unique_values)


def _role_tokens(value: str) -> set[str]:
    normalized_value = _normalize(value)

    return {
        token for token in _TOKEN_PATTERN.findall(normalized_value) if token not in _ROLE_MODIFIERS
    }


def _calculate_role_score(
    job_title: str,
    target_roles: tuple[str, ...],
) -> tuple[int, str | None]:
    if not target_roles:
        return 0, None

    title_tokens = _role_tokens(job_title)

    if not title_tokens:
        return 0, None

    best_score = 0
    best_role: str | None = None

    for target_role in target_roles:
        target_tokens = _role_tokens(target_role)

        if not target_tokens:
            continue

        overlap_count = len(
            title_tokens.intersection(target_tokens),
        )

        score = round(
            ROLE_WEIGHT * overlap_count / len(target_tokens),
        )

        if target_tokens.issubset(title_tokens):
            score = ROLE_WEIGHT

        if score > best_score:
            best_score = score
            best_role = target_role

    return best_score, best_role


def _calculate_experience_score(
    candidate_level: str | None,
    job_level: str | None,
) -> int:
    if candidate_level is None or job_level is None:
        return 0

    candidate_rank = _EXPERIENCE_RANKS.get(
        _normalize(candidate_level),
    )
    job_rank = _EXPERIENCE_RANKS.get(
        _normalize(job_level),
    )

    if candidate_rank is None or job_rank is None:
        return 0

    difference = job_rank - candidate_rank

    if difference <= 0:
        return EXPERIENCE_WEIGHT

    if difference == 1:
        return EXPERIENCE_WEIGHT // 2

    return 0


def _calculate_salary_score(
    *,
    minimum_salary: Decimal | None,
    preferred_currency: str | None,
    job_salary_min: Decimal | None,
    job_salary_max: Decimal | None,
    job_salary_currency: str | None,
) -> int:
    if minimum_salary is None:
        return SALARY_WEIGHT

    if preferred_currency is None or job_salary_currency is None:
        return 0

    if preferred_currency.upper() != job_salary_currency.upper():
        return 0

    offered_salary = job_salary_max if job_salary_max is not None else job_salary_min

    if offered_salary is None:
        return 0

    if offered_salary >= minimum_salary:
        return SALARY_WEIGHT

    return 0


def calculate_job_match(
    *,
    candidate: CandidateMatchContext,
    job_title: str,
    job_skills: tuple[str, ...],
    job_experience_level: str | None,
    job_salary_min: Decimal | None,
    job_salary_max: Decimal | None,
    job_salary_currency: str | None,
) -> JobMatchResult:
    candidate_skills = _unique_skills(candidate.skills)
    candidate_skill_keys = {key for key, _ in candidate_skills}

    excluded_technologies = _unique_skills(
        candidate.excluded_technologies,
    )
    excluded_technology_keys = {key for key, _ in excluded_technologies}

    normalized_job_skills = _unique_skills(job_skills)

    matched_skills = tuple(
        display_name for key, display_name in normalized_job_skills if key in candidate_skill_keys
    )

    missing_skills = tuple(
        display_name
        for key, display_name in normalized_job_skills
        if key not in candidate_skill_keys
    )

    excluded_skills = tuple(
        display_name
        for key, display_name in normalized_job_skills
        if key in excluded_technology_keys
    )

    if normalized_job_skills:
        skill_score = round(SKILL_WEIGHT * len(matched_skills) / len(normalized_job_skills))
    else:
        skill_score = 0

    role_score, matched_role = _calculate_role_score(
        job_title,
        candidate.target_roles,
    )

    experience_score = _calculate_experience_score(
        candidate.experience_level,
        job_experience_level,
    )

    salary_score = _calculate_salary_score(
        minimum_salary=candidate.minimum_salary,
        preferred_currency=candidate.salary_currency,
        job_salary_min=job_salary_min,
        job_salary_max=job_salary_max,
        job_salary_currency=job_salary_currency,
    )

    reasons: list[str] = []

    if normalized_job_skills:
        reasons.append(
            f"Matched {len(matched_skills)} of {len(normalized_job_skills)} identified job skills."
        )
    else:
        reasons.append(
            "The job has no identified skills to compare.",
        )

    if matched_role is not None:
        reasons.append(
            f'The job title aligns with the target role "{matched_role}".',
        )
    elif candidate.target_roles:
        reasons.append(
            "The job title does not align with the selected target roles.",
        )
    else:
        reasons.append(
            "No target roles were selected.",
        )

    if experience_score == EXPERIENCE_WEIGHT:
        reasons.append(
            "The candidate experience level satisfies the job level.",
        )
    elif experience_score > 0:
        reasons.append(
            "The candidate is one experience level below the job level.",
        )
    else:
        reasons.append(
            "The experience requirement could not be fully matched.",
        )

    if candidate.minimum_salary is None:
        reasons.append(
            "No minimum salary constraint was set.",
        )
    elif salary_score == SALARY_WEIGHT:
        reasons.append(
            "The advertised salary satisfies the minimum preference.",
        )
    else:
        reasons.append(
            "The salary preference could not be confirmed.",
        )

    if excluded_skills:
        reasons.append(
            "The job contains an excluded technology: " + ", ".join(excluded_skills) + "."
        )

        return JobMatchResult(
            score=0,
            is_eligible=False,
            skill_score=skill_score,
            role_score=role_score,
            experience_score=experience_score,
            salary_score=salary_score,
            matched_skills=matched_skills,
            missing_skills=missing_skills,
            excluded_skills=excluded_skills,
            reasons=tuple(reasons),
        )

    total_score = min(
        100,
        skill_score + role_score + experience_score + salary_score,
    )

    return JobMatchResult(
        score=total_score,
        is_eligible=True,
        skill_score=skill_score,
        role_score=role_score,
        experience_score=experience_score,
        salary_score=salary_score,
        matched_skills=matched_skills,
        missing_skills=missing_skills,
        excluded_skills=(),
        reasons=tuple(reasons),
    )
