from email_agent.config import AgentConfig
from email_agent.prompts import strip_quoted_text, system_prompt


def test_quoted_reply_content_is_removed():
    assert strip_quoted_text("New response\n\nOn Monday Person wrote:\n> old") == "New response"


def test_classification_prompt_uses_system_prompt_and_configured_categories(tmp_path):
    prompt_path = tmp_path / "prompts" / "system.md"
    prompt_path.parent.mkdir()
    prompt_path.write_text("Write warmly and escalate legal matters.")
    agent = AgentConfig.model_validate(
        {
            "name": "Test",
            "model": {"provider": "openai", "model": "test"},
            "system_prompt": "prompts/system.md",
            "categories": {
                "action": "Requires my response.",
                "travel": "Reservations and itinerary changes.",
            },
        }
    )

    rendered = system_prompt(tmp_path, agent, "classify")

    assert "Write warmly and escalate legal matters." in rendered
    assert "- action: Requires my response." in rendered
    assert "- travel: Reservations and itinerary changes." in rendered
    assert "unlisted category" in rendered
    assert "Return null" in rendered
