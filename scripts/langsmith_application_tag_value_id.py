"""Print the LangSmith resource-tag value ID for Application: email-agent.

Run this script from the project root after setting ``LANGSMITH_API_KEY`` in
``.env``. Copy the printed UUID to ``LANGSMITH_APPLICATION_TAG_VALUE_ID`` in
that file.
"""

import os

import requests
from dotenv import load_dotenv

load_dotenv(".env")

response = requests.get(
    f"{os.environ.get('LANGSMITH_ENDPOINT', 'https://api.smith.langchain.com')}"
    "/api/v1/workspaces/current/tags",
    headers={"x-api-key": os.environ["LANGSMITH_API_KEY"]},
    timeout=30,
)
response.raise_for_status()

tags = response.json()
value_id = next(
    value["id"]
    for tag in tags
    if tag["key"] == "Application"
    for value in tag["values"]
    if value["value"] == "email-agent"
)

print(value_id)
