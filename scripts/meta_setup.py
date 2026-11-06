"""One-time helper: turn a short-lived Graph API Explorer token into a never-expiring PAGE token
and find your Instagram Business account id.

  python scripts/meta_setup.py APP_ID APP_SECRET SHORT_LIVED_USER_TOKEN "Your Facebook Page name"

Graph API Explorer permissions to tick when generating the token:
  pages_show_list, pages_read_engagement, pages_manage_posts, pages_manage_engagement,
  instagram_basic, instagram_content_publish, instagram_manage_comments, business_management"""
import sys

import requests

if len(sys.argv) != 5:
    sys.exit(__doc__)
app_id, app_secret, short, page_name = sys.argv[1:]
G = "https://graph.facebook.com/v21.0"


def get(path, **p):
    r = requests.get(f"{G}/{path}", params=p, timeout=60).json()
    if "error" in r:
        sys.exit(f"Meta error on {path}: {r['error']}")
    return r


long_user = get("oauth/access_token", grant_type="fb_exchange_token", client_id=app_id,
                client_secret=app_secret, fb_exchange_token=short)["access_token"]
pages = get("me/accounts", access_token=long_user, fields="id,name,access_token", limit=100)["data"]
match = [p for p in pages if p["name"].strip().lower() == page_name.strip().lower()]
if not match:
    sys.exit("Page not found. Pages visible to this token: " + ", ".join(p["name"] for p in pages))
page = match[0]
ig = get(page["id"], access_token=page["access_token"], fields="instagram_business_account{id,username}")
iga = ig.get("instagram_business_account")
if not iga:
    sys.exit("This Page has no linked Instagram Professional account. Link it in Instagram settings first.")
print(f"\nPage: {page['name']}   Instagram: @{iga.get('username')}\n")
print("META_PAGE_ID    =", page["id"])
print("META_IG_USER_ID =", iga["id"])
print("META_PAGE_TOKEN =", page["access_token"], "  (derived from a long-lived token: does not expire)")
