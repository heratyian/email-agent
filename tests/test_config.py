from email_agent.config import Settings


def test_profiles_are_valid_and_sending_is_disabled():
    settings = Settings()
    for name in ("personal", "receipt_ai_support"):
        profile = settings.profile(name)
        assert settings.account_for(profile)
        assert profile.safety.allow_send is False
