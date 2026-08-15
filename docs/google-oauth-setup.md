# Google OAuth setup

RetroPyClip cannot ship a private client credential on behalf of every self-hosting
user. Create an OAuth client in a Google Cloud project you control.

Google's current documentation confirms that `appDataFolder` is hidden from the
ordinary Drive UI and other Drive apps, and that `drive.appdata` is a non-sensitive
scope: [app-data guide](https://developers.google.com/workspace/drive/api/guides/appdata)
and [scope guide](https://developers.google.com/workspace/drive/api/guides/api-specific-auth).

1. Create or select a Google Cloud project.
2. Enable **Google Drive API**.
3. Configure the OAuth consent screen. Add yourself as a test user while developing.
4. Create an OAuth client of type **Desktop app** for macOS and desktop Linux.
5. Download the JSON to a private location outside this repository.
6. Run `retropyclip login --client-secrets /path/to/client_secret.json`.
7. Approve only `https://www.googleapis.com/auth/drive.appdata`.

For a limited-input/headless device, create Google's appropriate TV/limited-input
client and run `retropyclip login --headless --client-secrets ...`. Google controls
which OAuth client types and scopes are permitted for device authorization, so test
this with the exact Pi deployment and Cloud project before relying on it. Google's
[limited-input guide](https://developers.google.com/identity/protocols/oauth2/limited-input-device)
currently lists `drive.appdata` as an allowed device-flow scope.

OAuth apps left in External/Testing mode can receive refresh tokens that expire
after seven days. Move an appropriate personal deployment to Production for durable
testing; see Google's [app-audience guidance](https://support.google.com/cloud/answer/15549945).
Public distribution additionally needs accurate branding, support contact,
privacy policy, and Google's current compliance requirements.

The app requests only the `drive.appdata` scope. It cannot browse ordinary Drive
files. Removing the app's Drive data deletes its remote records.

## Credential discovery

The explicit `--client-secrets` path is copied into the private configuration
directory with mode `0600`. You can instead set
`RETROPYCLIP_GOOGLE_CLIENT_SECRETS` for the login command. Never commit the file.
