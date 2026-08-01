from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.profile import ExperienceLevel, ProfileUpsert


def test_profile_uses_safe_defaults() -> None:
    profile = ProfileUpsert()

    assert profile.timezone == "Asia/Hebron"
    assert profile.target_roles == []
    assert profile.excluded_technologies == []
    assert profile.availability == {}


def test_profile_normalizes_user_values() -> None:
    profile = ProfileUpsert(
        location="  Hebron,   Palestine ",
        target_roles=[
            " Junior Backend ",
            "junior backend",
            "DevOps",
        ],
        experience_level=ExperienceLevel.JUNIOR,
        minimum_salary="1200",
        salary_currency="usd",
        excluded_technologies=[
            "Node.js",
            " node.js ",
        ],
    )

    assert profile.location == "Hebron, Palestine"
    assert profile.target_roles == [
        "Junior Backend",
        "DevOps",
    ]
    assert profile.minimum_salary == Decimal("1200")
    assert profile.salary_currency == "USD"
    assert profile.excluded_technologies == ["Node.js"]


def test_profile_rejects_unknown_timezone() -> None:
    with pytest.raises(ValidationError, match="Unknown IANA timezone"):
        ProfileUpsert(timezone="Invalid/Timezone")


def test_profile_requires_currency_with_salary() -> None:
    with pytest.raises(ValidationError, match="salary_currency is required"):
        ProfileUpsert(minimum_salary=1000)
