# Gmail OAuth Setup

The email agent uses a Google OAuth **Desktop app** client to read Gmail and apply category labels. Keep the downloaded client configuration and generated token out of source control.

The app requests the `gmail.modify` scope because category synchronization creates and applies user labels. It still never sends email or modifies message content.

## 1. Create and configure a Google Cloud project

1. Open the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project, or select the project dedicated to the email agent.
3. Open **APIs & Services → Library** and enable the **Gmail API**.
4. Open the [Google Auth Platform](https://console.cloud.google.com/auth/overview).
5. Complete **Branding** with an app name, support email, and developer contact email.
6. Under **Audience**, select **External** for a personal Gmail account. An Internal audience is only appropriate when every user belongs to the selected Google Workspace organization.

## 2. Add yourself as a test user

An External OAuth app starts in **Testing** mode. Before signing in, explicitly allow the Gmail accounts that will use the development app:

1. In Google Auth Platform, open **Audience**.
2. Find **Test users** and click **Add users**.
3. Add the exact Gmail address you will select during the OAuth sign-in flow.
4. Save the change.

Public Google verification is not required for personal development while the app remains in Testing and all users are listed as test users. Testing-mode authorizations may expire after seven days, in which case rerun the command and authorize the account again.

## 3. Create the desktop OAuth client

1. In Google Auth Platform, open **Clients**.
2. Click **Create client**.
3. Choose **Desktop app** as the application type.
4. Create the client and download its JSON configuration.
5. Save it in this project as:

   ```text
   secrets/gmail_credentials.json
   ```

The `secrets/` directory and OAuth token files are ignored by Git. Do not commit or share either file.

## 4. Authorize the email agent

Run a command that connects to Gmail:

```bash
uv run email-agent inbox --account you@gmail.com
```

Your browser will open Google's consent flow. Sign in with the same address added under **Test users**. After successful authorization, the app stores the refresh token at:

```text
secrets/gmail_token.json
```

## Troubleshooting

### Error 403: `access_denied`

If Google says the app "has not completed the Google verification process" and can only be accessed by developer-approved testers:

- confirm the signed-in Gmail address appears under **Audience → Test users**;
- confirm you are editing the same Cloud project that created `gmail_credentials.json`;
- confirm the OAuth audience is External, unless the account belongs to the configured Workspace organization;
- wait a minute after adding the test user, then retry the command; and
- choose the exact approved account when Google asks which account to use.

### Error 403: Gmail API is disabled (`accessNotConfigured`)

If authorization succeeds but the command returns a message like:

```text
Gmail API has not been used in project PROJECT_ID before or it is disabled.
```

the OAuth client is valid, but the Gmail API is not enabled in the Google Cloud project that owns it:

1. Copy the project ID or project number from the error message.
2. Open the [Gmail API page](https://console.cloud.google.com/apis/library/gmail.googleapis.com) in Google Cloud Console.
3. Confirm that the selected project matches the project identified in the error.
4. Click **Enable**.
5. Wait a few minutes for the change to propagate, then rerun the `inbox` command.

You do not need to recreate `gmail_credentials.json`, remove `gmail_token.json`, or repeat authorization. The existing OAuth token should work after the Gmail API is enabled.

### OAuth client file not found

Confirm the downloaded file is named and located exactly at:

```text
secrets/gmail_credentials.json
```

### Authorization needs to be repeated

Testing-mode grants can expire. Rerun the `inbox` command to authorize again. If an obsolete token prevents a fresh flow, move `secrets/gmail_token.json` aside and retry; keep the backup until authorization succeeds.

The same one-time reauthorization is required when upgrading from the earlier read-only release to category synchronization. If the CLI says `gmail.modify` is required, move the account's configured token file aside and rerun the command. The new browser consent creates a replacement token with label permission.

For more detail, see Google's documentation for [managing an app audience](https://support.google.com/cloud/answer/15549945) and [OAuth verification setup](https://support.google.com/cloud/answer/13461325).
