"""The OIDC device grant against an actual local TLS issuer."""

import base64
import hashlib
import json
import secrets
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from fixtures.tls import localhost_tls


@pytest.fixture
def issuer(tmp_path, monkeypatch):
    from etl_craft.config.model import AuthConfig

    context, certificate = localhost_tls(tmp_path)
    state = {"nonce": None, "requests": [], "redirect": False, "wrong_issuer": False, "errors": []}

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    jwk.update(kid="test-signing", use="sig", alg="RS256")
    codes = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path)
            if path.path == "/logout":
                params = parse_qs(path.query)
                state["logout_requests"] = params
                self.send_response(302)
                self.send_header("Location", params["post_logout_redirect_uri"][0])
                self.end_headers()
                return
            if path.path == "/jwks":
                self.reply({"keys": [jwk]})
                return
            if path.path == "/authorize":
                params = {k: v[0] for k, v in parse_qs(path.query).items()}
                code = secrets.token_urlsafe(24)
                codes[code] = params
                self.send_response(302)
                self.send_header(
                    "Location",
                    params["redirect_uri"]
                    + "?"
                    + urlencode(
                        {
                            "code": code,
                            "state": params["state"],
                        }
                    ),
                )
                self.end_headers()
                return
            if state["redirect"]:
                self.send_response(302)
                self.send_header("Location", "http://localhost/insecure")
                self.end_headers()
                return
            self.reply(
                {
                    "issuer": "https://other" if state["wrong_issuer"] else address,
                    "device_authorization_endpoint": address + "/device",
                    "token_endpoint": address + "/token",
                    "authorization_endpoint": address + "/authorize",
                    "jwks_uri": address + "/jwks",
                    **(
                        {"end_session_endpoint": state["end_session_endpoint"]}
                        if "end_session_endpoint" in state
                        else {}
                    ),
                }
            )

        def do_POST(self):
            data = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
            state["requests"].append((self.path, data))
            browser = data.get("grant_type") == ["authorization_code"]
            if browser:
                given = codes.pop(data.get("code", [""])[0], None)
                verifier = data.get("code_verifier", [""])[0]
                challenge = (
                    base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                    .decode()
                    .rstrip("=")
                )
                if (
                    not given
                    or given["code_challenge"] != challenge
                    or given["code_challenge_method"] != "S256"
                    or given["redirect_uri"] != data.get("redirect_uri", [""])[0]
                ):
                    self.reply({"error": "invalid_grant"}, 400)
                    return
                state["nonce"] = given["nonce"]
            if self.path == "/device" and state.get("device_status"):
                self.reply({"error": "invalid_client"}, state["device_status"])
            elif self.path == "/device":
                state["nonce"] = data["nonce"][0]
                self.reply(
                    {
                        "device_code": "private-device-code",
                        "user_code": "ABCD-EFGH",
                        "verification_uri": address + "/verify",
                        "expires_in": 30,
                        "interval": 1,
                    }
                )
            elif state["errors"]:
                self.reply({"error": state["errors"].pop(0)}, state.get("error_status", 200))
            else:

                def encode(obj):
                    return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

                claims = {
                    "iss": address,
                    "aud": "etl",
                    "sub": "known-subject",
                    "nonce": state["nonce"],
                    "iat": time.time() - 1,
                    "exp": time.time() + 60,
                    **state.get("extra_claims", {}),
                }
                for omitted in state.get("omit_claims", ()):
                    claims.pop(omitted, None)
                token = (
                    jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-signing"})
                    if browser
                    else encode({"alg": "RS256"}) + "." + encode(claims) + ".signature"
                )
                if browser and state.get("bad_signature"):
                    token = token.rsplit(".", 1)[0] + ".invalid"
                self.reply({"id_token": token})

        def reply(self, value, status=200):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(value).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("localhost", 0), Handler)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    server.socket = context.wrap_socket(server.socket, server_side=True)
    address = f"https://localhost:{server.server_port}"
    monkeypatch.setenv("SSL_CERT_FILE", str(certificate))
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield AuthConfig(12, address, "etl"), state
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
