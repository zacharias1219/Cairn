"""A reference personal agent that talks to a business through Cairn's PAP gateway.

    python examples/pap_reference_agent.py --base http://localhost:8000 --business acme

It reads the business's manifest, asks a read-only question as a guest, is
refused when it tries to write without consent, then walks the customer
through consent (you complete the consent page in a browser) and makes the
change with write scope.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import urllib.parse

import httpx

AGENT = "agent://reference.cairn.dev/pap-agent"
REDIRECT = "http://localhost:9999/callback"


def show(label: str, r: httpx.Response) -> dict:
    data = r.json()
    print(f"\n{label}  [{r.status_code}]\n{json.dumps(data, indent=2)[:900]}")
    return data


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--business", default="acme")
    args = ap.parse_args()
    root = f"{args.base}/pap/v1/{args.business}"
    c = httpx.Client(timeout=30)

    manifest = show("Manifest", c.get(f"{root}/.well-known/pap.json"))
    print("\nCapabilities:", ", ".join(f"{x['name']} ({x['scope']})" for x in manifest["capabilities"]))

    guest = show("Guest session", c.post(f"{root}/sessions", json={"agent": AGENT}))
    gh = {"authorization": f"Bearer {guest['access_token']}"}
    show("Guest read: order status", c.post(f"{root}/actions/lookup_order", json={"arguments": {"order_id": "A1002"}}, headers=gh))
    show("Guest asks the business's own agent", c.post(f"{root}/messages", json={"content": "Is shipping free?"}, headers=gh))
    show("Guest write (expected: refused, insufficient_scope)",
         c.post(f"{root}/actions/issue_refund", json={"arguments": {"order_id": "A1001", "amount": 84, "reason": "Arrived damaged"}}, headers=gh))

    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    q = urllib.parse.urlencode({"agent": AGENT, "redirect_uri": REDIRECT, "code_challenge": challenge,
                                "code_challenge_method": "S256", "scope": "read write", "state": "demo"})
    print(f"\nOpen this consent page, sign in as maya.chen@example.com with order A1001, allow changes:\n  {root}/authorize?{q}")
    code = input("\nPaste the `code` from the redirect URL: ").strip()
    tok = show("Token", c.post(f"{root}/token", json={"code": code, "code_verifier": verifier, "agent": AGENT}))
    sh = {"authorization": f"Bearer {tok['access_token']}"}
    show("Signed-in write: refund", c.post(f"{root}/actions/issue_refund",
                                           json={"arguments": {"order_id": "A1001", "amount": 84, "reason": "Arrived damaged"}}, headers=sh))
    show("End session", c.delete(f"{root}/session", headers=sh))


if __name__ == "__main__":
    main()
