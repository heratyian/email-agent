from email_agent.prompts import strip_quoted_text


def test_quoted_reply_content_is_removed():
    assert strip_quoted_text("New response\n\nOn Monday Person wrote:\n> old") == "New response"
