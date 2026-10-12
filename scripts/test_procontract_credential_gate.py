"""Expiry admission is bounded and never persists provider secrets."""

import datetime
import io
import json
import unittest
from unittest import mock
import urllib.error

import procontract_credential_gate as gate


class CredentialTests(unittest.TestCase):
    def test_expiry_window_and_secret_free_receipt(self):
        now = datetime.datetime(2026, 10, 12, tzinfo=datetime.timezone.utc)
        expires = (now + datetime.timedelta(hours=6)).isoformat()
        value = {"info": {"expires": expires, "blocked": False, "key": "NEVER_PERSIST"}}
        self.assertEqual(
            gate.assess(value, 18000, now),
            {
                "profile": gate.PROFILE,
                "checked_at_utc": now.isoformat(),
                "expires_at": expires,
                "required_seconds": 18300,
                "scope": "provider-declared expiry only; not a guarantee against revocation; no key retained",
            },
        )
        for info in (
            {},
            {"expires": "2026-10-12"},
            {"expires": now.isoformat()},
            {"expires": expires, "blocked": True},
            {"expires": 123},
        ):
            with self.subTest(info=info), self.assertRaises(ValueError):
                gate.assess({"info": info}, 18000, now)

    def test_inspection_uses_only_provider_origin_and_does_not_expose_error_body(self):
        value = {"info": {"expires": None, "key": "SECRET_FIXTURE"}}
        opener = mock.Mock()
        opener.open.return_value = io.BytesIO(json.dumps(value).encode())
        provider = {"base_url": "https://provider.invalid/v1"}
        with mock.patch.object(
            gate.urllib.request, "build_opener", return_value=opener
        ):
            result = gate.inspect(provider, "SECRET_FIXTURE", 18000)
            request = opener.open.call_args.args[0]
            self.assertEqual(request.full_url, "https://provider.invalid/key/info")
            self.assertEqual(
                request.get_header("Authorization"), "Bearer SECRET_FIXTURE"
            )
            self.assertNotIn("SECRET_FIXTURE", json.dumps(result))
            opener.open.side_effect = urllib.error.URLError("SECRET_FIXTURE")
            with self.assertRaisesRegex(
                ValueError, "^provider credential metadata unavailable$"
            ):
                gate.inspect(provider, "SECRET_FIXTURE", 18000)
        self.assertIsNone(
            gate.NoRedirect().redirect_request(
                None, None, 302, "", {}, "https://elsewhere.invalid"
            )
        )
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            gate.inspect(
                {"base_url": "http://elsewhere.invalid"}, "SECRET_FIXTURE", 18000
            )


if __name__ == "__main__":
    unittest.main()
