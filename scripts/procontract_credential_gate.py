"""Provider key-info admission; no model calls, redirects, secret receipts or implicit renewal."""

import datetime
import json
import urllib.error
import urllib.parse
import urllib.request

PROFILE = "provider-key-info-v1"
MARGIN_SECS = 300


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def inspect(provider, credential, episode_secs):
    if not isinstance(credential, str) or not credential or len(credential) > 16384:
        raise ValueError("missing or excessive provider credential")
    base = urllib.parse.urlsplit(provider["base_url"])
    if base.username or base.password or base.scheme != "https" or not base.hostname:
        raise ValueError(
            "credential inspection requires the pinned HTTPS provider origin"
        )
    url = urllib.parse.urlunsplit((base.scheme, base.netloc, "/key/info", "", ""))
    request = urllib.request.Request(
        url, headers={"Authorization": "Bearer " + credential}
    )
    try:
        with urllib.request.build_opener(NoRedirect).open(
            request, timeout=15
        ) as response:
            raw = response.read(131073)
            if len(raw) > 131072:
                raise ValueError("credential metadata exceeds bound")
            value = json.loads(raw)
    except urllib.error.HTTPError as error:
        error.close()
        raise ValueError("provider credential metadata unavailable") from None
    except (urllib.error.URLError, OSError, ValueError):
        # Provider bodies may echo keys. Persist no body, exception string or key hash.
        raise ValueError("provider credential metadata unavailable") from None
    return assess(value, episode_secs, datetime.datetime.now(datetime.timezone.utc))


def assess(value, episode_secs, now):
    if type(episode_secs) is not int or not 0 < episode_secs <= 18000:
        raise ValueError("invalid credential admission window")
    info = value.get("info") if isinstance(value, dict) else None
    if (
        not isinstance(info, dict)
        or "expires" not in info
        or (info.get("blocked") is not None and info.get("blocked") is not False)
    ):
        raise ValueError("credential expiry or authorization is unknown")
    expires = info["expires"]
    if expires is not None:
        try:
            expiry = datetime.datetime.fromisoformat(expires)
        except (ValueError, TypeError):
            raise ValueError("invalid credential expiry") from None
        if (
            expiry.tzinfo is None
            or (expiry - now).total_seconds() < episode_secs + MARGIN_SECS
        ):
            raise ValueError(
                "credential does not cover the complete episode and safety margin"
            )
    return {
        "profile": PROFILE,
        "checked_at_utc": now.isoformat(),
        "expires_at": expires,
        "required_seconds": episode_secs + MARGIN_SECS,
        "scope": "provider-declared expiry only; not a guarantee against revocation; no key retained",
    }
