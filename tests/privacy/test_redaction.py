import pytest

from email_agent.privacy import SensitiveDataError, redact


def test_redaction_is_stable_and_reversible():
    result = redact(
        "Email Jordan Smith at jordan@example.com or call (312) 555-0192. "
        "Jordan Smith can also answer.",
        known_names=["Jordan Smith"],
    )

    assert result.sanitized_text == (
        "Email [NAME_1] at [EMAIL_1] or call [PHONE_1]. [NAME_1] can also answer."
    )
    assert result.placeholder_map.restore(result.sanitized_text) == result.original_text


def test_short_known_name_does_not_redact_part_of_another_word():
    result = redact("Al called about allocation", known_names=["Al"])

    assert result.sanitized_text == "[NAME_1] called about allocation"


def test_sensitive_identifiers_and_urls_are_replaced():
    result = redact(
        "SSN 123-45-6789 account: 92844102 https://example.com/reset?token=secret-value"
    )

    assert "123-45-6789" not in result.sanitized_text
    assert "92844102" not in result.sanitized_text
    assert "secret-value" not in result.sanitized_text
    assert "[SSN_1]" in result.sanitized_text
    assert "[FINANCIAL_1]" in result.sanitized_text
    assert "[SENSITIVE_URL_1]" in result.sanitized_text


@pytest.mark.parametrize(
    "content",
    [
        "password: swordfish",
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
        "api_key=abcdefghijklmnop",
        "-----BEGIN PRIVATE KEY-----",
    ],
)
def test_credentials_block_the_model_input(content):
    with pytest.raises(SensitiveDataError, match="not sent"):
        redact(content)


def test_restore_leaves_unknown_placeholders_unchanged():
    result = redact("Jordan Smith at jordan@example.com", known_names=["Jordan Smith"])

    restored = result.placeholder_map.restore(
        "Hello [NAME_1]. Reply to [EMAIL_1]. Keep [NAME_99] unchanged."
    )

    assert restored == (
        "Hello Jordan Smith. Reply to jordan@example.com. Keep [NAME_99] unchanged."
    )
