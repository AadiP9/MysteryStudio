"""One-time OAuth for ONE YouTube channel. Run on your laptop (opens a browser).

  python scripts/youtube_auth.py path/to/client_secret.json

Sign in with the Google account that owns the channel and, if asked, pick the right channel.
Prints the three values to store as GitHub secrets (YT1_*, YT2_*, YT3_*)."""
import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.force-ssl"]

if len(sys.argv) != 2:
    sys.exit(__doc__)
cfg = json.load(open(sys.argv[1]))
inst = cfg.get("installed") or cfg.get("web")
flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
ch = yt.channels().list(part="snippet", mine=True).execute()["items"][0]
print("\n=== Authorised channel:", ch["snippet"]["title"], "(", ch["id"], ") ===")
print("Make sure this is the channel you intended!\n")
print("CLIENT_ID     =", inst["client_id"])
print("CLIENT_SECRET =", inst["client_secret"])
print("REFRESH_TOKEN =", creds.refresh_token)
print("\nStore them as GitHub secrets, e.g. YT1_CLIENT_ID / YT1_CLIENT_SECRET / YT1_REFRESH_TOKEN.")
