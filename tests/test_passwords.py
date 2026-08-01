from app.security.passwords import hash_password, verify_password


def test_password_is_hashed_with_argon2id() -> None:
    plain_password = "StrongPassword123!"
    hashed_password = hash_password(plain_password)

    assert hashed_password != plain_password
    assert hashed_password.startswith("$argon2id$")
    assert verify_password(plain_password, hashed_password)


def test_wrong_password_is_rejected() -> None:
    hashed_password = hash_password("CorrectPassword123!")

    assert not verify_password(
        "WrongPassword123!",
        hashed_password,
    )
