"""Check synthetic Gateway v1 fixtures with Python's independent RSA verifier.

This fixture checker is not production middleware. It assumes an authenticated
caller and an allowing live-policy stub for exchange cases. Receivers still need
their own transport authentication, role/resource checks and replay protection.
Run: python check_vectors.py [vectors.json]
Dependency: cryptography. No network or deployed credentials are used.
"""

import base64
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
HEX = re.compile(r"[0-9a-f]{64}\Z")
METHOD = re.compile(r"[A-Z]{1,20}\Z")
CALLERS = {"gateway", "session", "moderation", "discord-dms"}
AUDIENCES = {
    "player": "student-id-player-service",
    "session": "student-id-session-service",
    "university-record": "student-id-university-record-service",
}
BASE_FIELDS = {"v", "iss", "aud", "iat", "exp", "jti", "sub", "actor_exp", "actor_jti", "is_admin", "azp"}
REQUEST_FIELDS = {"method", "path", "query_sha256", "body_sha256", "idempotency_sha256", "session_id"}
SCOPE_FIELDS = {"target", "method", "path", "exact_path", "query", "body_sha256"}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON field")
        result[key] = value
    return result


def json_bytes(value):
    return json.loads(value, object_pairs_hook=unique_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid JSON number")))


def decode_segment(value):
    require(bool(re.fullmatch(r"[A-Za-z0-9_-]+", value)), "invalid base64url")
    decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    require(base64.urlsafe_b64encode(decoded).rstrip(b"=").decode() == value, "noncanonical base64url")
    return decoded


def digest(value):
    return hashlib.sha256(value).hexdigest()


def integer(value):
    return type(value) is int and -(2**63) <= value < 2**63


def path_valid(value):
    if not isinstance(value, str) or not value.startswith("/") or len(value.encode()) > 2048:
        return False
    if re.search(r"[?#\\\s]|%(?:2f|5c)", value, re.I) or re.search(r"%(?![a-fA-F0-9]{2})", value):
        return False
    decoded = unquote(value, errors="strict")
    return not any(ord(c) < 32 or ord(c) == 127 for c in decoded) and not any(s in {".", ".."} for s in decoded.split("/"))


def query_valid(value):
    return (isinstance(value, str) and len(value.encode()) <= 8192
            and all(33 <= ord(c) <= 126 and c not in "#;" for c in value)
            and not re.search(r"%(?![a-fA-F0-9]{2})", value))


def jwt_verify(token, suite, operation):
    require(0 < len(token) <= 16384, "token length")
    parts = token.split(".")
    require(len(parts) == 3, "compact JWT")
    header, claims = [json_bytes(decode_segment(part)) for part in parts[:2]]
    require(type(header) is dict and set(header) == {"alg", "kid", "typ"}, "header profile")
    require(all(type(header[k]) is str for k in header), "header types")
    require(header["alg"] == "RS256", "algorithm")
    require(type(claims) is dict, "claims object")
    if operation == "player":
        require(header["kid"] == "player-v1" and header["typ"] == "JWT", "Player header")
        pem = suite["player_public_key_pem"]
    else:
        require(header["kid"] == "gateway-v1", "Gateway key")
        permitted = {"gateway-workload+jwt"} if operation == "workload" else {"gateway-request+jwt"} if operation == "request" else {"gateway-delegation+jwt", "gateway-chat+jwt"}
        require(header["typ"] in permitted, "profile separation")
        pem = suite["gateway_public_key_pem"]
    key = serialization.load_pem_public_key(pem.encode())
    require(isinstance(key, rsa.RSAPublicKey) and key.key_size >= 2048 and key.public_numbers().e == 65537, "RSA key")
    key.verify(decode_segment(parts[2]), (parts[0] + "." + parts[1]).encode(), padding.PKCS1v15(), hashes.SHA256())
    return header["typ"], claims


def actor_result(claims, token):
    return {"sub": claims["sub"], "actor_exp": claims["exp"],
            "actor_jti": claims.get("jti", "sha256:" + digest(token.encode())),
            "is_admin": claims.get("is_admin", False)}


def player_validate(claims, token, now):
    known = {"iss", "aud", "sub", "exp", "iat", "nbf", "jti", "is_admin"}
    require(not any(k != k.lower() and k.lower() in known for k in claims), "Player case alias")
    require(claims.get("iss") == "student-id-please", "Player issuer")
    audience = claims.get("aud")
    require(audience == "student-id-players" or type(audience) is list
            and bool(audience) and all(type(a) is str and bool(a) for a in audience)
            and "student-id-players" in audience, "Player audience")
    require(type(claims.get("sub")) is str and bool(UUID.fullmatch(claims["sub"])), "Player subject")
    require(integer(claims.get("exp")) and claims["exp"] > now, "Player expiry")
    if "iat" in claims:
        require(integer(claims["iat"]) and 0 < claims["iat"] <= now and claims["iat"] < claims["exp"], "Player issued time")
    if "nbf" in claims:
        require(integer(claims["nbf"]) and 0 < claims["nbf"] <= now, "Player not-before")
    if "jti" in claims:
        require(type(claims["jti"]) is str and 0 < len(claims["jti"].encode()) <= 256, "Player token ID")
    require(type(claims.get("is_admin", False)) is bool, "Player admin boolean")
    return actor_result(claims, token)


def scope_validate(scope):
    require(type(scope) is dict and set(scope) <= SCOPE_FIELDS, "scope fields")
    require(scope.get("target") in AUDIENCES and METHOD.fullmatch(scope.get("method", "")) and path_valid(scope.get("path")), "scope route")
    require(type(scope.get("exact_path")) is bool, "scope path kind")
    if "query" in scope:
        require(query_valid(scope["query"]), "scope query")
    if "body_sha256" in scope:
        require(type(scope["body_sha256"]) is str and HEX.fullmatch(scope["body_sha256"]), "scope body")


def gateway_validate(claims, typ, now, binding):
    is_workload = typ == "gateway-workload+jwt"
    is_request = typ in {"gateway-request+jwt", "gateway-workload+jwt"}
    is_chat = typ == "gateway-chat+jwt"
    allowed = BASE_FIELDS | (REQUEST_FIELDS if is_request else {"scopes"} | ({"session_id"} if is_chat else set()))
    if is_workload:
        allowed -= {"sub", "actor_exp", "actor_jti", "is_admin", "session_id"}
    require(set(claims) <= allowed, "Gateway fields")
    require(integer(claims.get("v")) and claims["v"] == 1, "version")
    require(claims.get("iss") == "student-id-gateway", "Gateway issuer")
    require(type(claims.get("aud")) is str and claims["aud"] == (binding["audience"] if is_request else "student-id-gateway"), "Gateway audience")
    require(all(integer(claims.get(k)) for k in (("iat", "exp") if is_workload else ("iat", "exp", "actor_exp"))), "Gateway time types")
    require(0 < claims["iat"] <= now < claims["exp"] and claims["iat"] < claims["exp"], "Gateway times")
    require(is_workload or claims["exp"] <= claims["actor_exp"], "actor lifetime")
    require(is_chat or claims["exp"] - claims["iat"] <= 30, "synchronous lifetime")
    require(type(claims.get("jti")) is str and 0 < len(claims["jti"].encode()) <= 128 and claims.get("azp") in CALLERS, "Gateway identity")
    require(type(claims.get("is_admin", False)) is bool, "Gateway admin")
    for name in ("sub", "actor_jti", "session_id"):
        if name in claims:
            require(type(claims[name]) is str, "optional string")
    subject = claims.get("sub", "")
    if subject:
        require(UUID.fullmatch(subject) and 0 < len(claims.get("actor_jti", "").encode()) <= 256, "actor binding")
    elif not is_workload:
        require(is_request and claims["azp"] == "gateway" and not claims.get("is_admin", False)
                and not claims.get("actor_jti") and claims["actor_exp"] == claims["exp"], "anonymous profile")
    if is_workload:
        require(claims["azp"] != "gateway", "workload caller")
    if "session_id" in claims:
        require(UUID.fullmatch(claims["session_id"]), "session ID")
    if is_request:
        require(METHOD.fullmatch(claims.get("method", "")) and path_valid(claims.get("path")), "request route")
        require(all(type(claims.get(k)) is str and HEX.fullmatch(claims[k]) for k in ("query_sha256", "body_sha256", "idempotency_sha256")), "request digests")
        return
    require(bool(subject) and type(claims.get("scopes")) is list and 0 < len(claims["scopes"]) <= 64, "grant scopes")
    for scope in claims["scopes"]:
        scope_validate(scope)
    if is_chat:
        require(claims["azp"] == "discord-dms" and not claims.get("is_admin", False)
                and bool(UUID.fullmatch(claims.get("session_id", ""))), "chat identity")
        session = claims["session_id"]
        for scope in claims["scopes"]:
            require(scope["method"] == "GET" and scope["exact_path"] and "query" in scope, "chat read restriction")
            if scope["target"] == "session":
                require(scope["path"] == f"/internal/v1/sessions/{session}/context" and scope["query"] == f"player_id={subject}", "chat context resource")
            else:
                require(scope["target"] == "university-record"
                        and scope["path"] == f"/internal/v1/sessions/{session}/record-permissions/{subject}"
                        and scope["query"] == "", "chat permission resource")


def binding_validate(binding):
    require(binding["target"] in AUDIENCES and binding["audience"] == AUDIENCES[binding["target"]], "target audience")
    require(METHOD.fullmatch(binding["method"]) and path_valid(binding["path"]) and query_valid(binding["raw_query"]), "binding route")
    key = binding["idempotency_key"]
    require(type(key) is str and len(key) <= 1024 and all(33 <= ord(c) <= 126 and c != "," for c in key), "idempotency key")
    body = base64.b64decode(binding["body_base64"], validate=True)
    require(len(body) <= 16 * 1024 * 1024, "body bound")
    return body


def scope_allows(scope, binding, body):
    path = scope["path"]
    match = path == binding["path"] or not scope["exact_path"] and binding["path"].startswith(path.rstrip("/") + "/")
    return (scope["target"] == binding["target"] and scope["method"] == binding["method"] and match
            and ("query" not in scope or scope["query"] == binding["raw_query"])
            and ("body_sha256" not in scope or scope["body_sha256"] == digest(body)))


def check_case(case, suite):
    typ, claims = jwt_verify(case["token"], suite, case["operation"])
    if case["operation"] == "player":
        return player_validate(claims, case["token"], case["now"])
    binding = case["binding"]
    body = binding_validate(binding)
    gateway_validate(claims, typ, case["now"], binding)
    if case["operation"] in {"request", "workload"}:
        require(claims["method"] == binding["method"] and claims["path"] == binding["path"], "request binding")
        for name, value in (("query_sha256", binding["raw_query"].encode()), ("body_sha256", body),
                            ("idempotency_sha256", binding["idempotency_key"].encode())):
            require(claims[name] == digest(value), "request hash")
        return {"azp":claims["azp"],"sub": claims.get("sub", ""), "exp": claims["exp"], "actor_exp": claims.get("actor_exp",0), "is_admin": claims.get("is_admin", False), "session_id": claims.get("session_id", "")}
    require(case["caller"] == claims["azp"] and case["caller"] in CALLERS - {"gateway"}, "authenticated caller binding")
    require(any(scope_allows(s, binding, body) for s in claims["scopes"]), "signed scope")
    return {"sub": claims["sub"], "exp": min(case["now"] + 30, claims["exp"], claims["actor_exp"]),
            "actor_exp": claims["actor_exp"], "is_admin": claims.get("is_admin", False), "session_id": claims.get("session_id", "")}


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("vectors.json")
    suite = json.loads(path.read_text(encoding="utf-8"))
    failures = []
    for case in suite["cases"]:
        try:
            result = check_case(case, suite)
            accepted = True
        except Exception:
            result, accepted = {}, False
        if accepted != case["accept"] or accepted and any(result.get(k) != v for k, v in case.get("expected", {}).items()):
            failures.append(case["name"])
    require(not failures, "Failed cases: " + ", ".join(failures))
    print(f"Python RSA/profile/hash checks passed for {len(suite['cases'])} synthetic cases.")


def export_java_crypto(suite, destination):
    """Export a text transport for JDK crypto checks without a JSON dependency."""
    lines = []
    encode = lambda value: base64.b64encode(value).decode()
    for case in suite["cases"]:
        pem = suite["player_public_key_pem"] if case["operation"] == "player" else suite["gateway_public_key_pem"]
        key = serialization.load_pem_public_key(pem.encode())
        der = key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        parts = case["token"].split(".")
        signed = (parts[0] + "." + parts[1]).encode()
        signature = decode_segment(parts[2])
        signature_valid = True
        try:
            key.verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
        except Exception:
            signature_valid = False
        lines.append("\t".join(("rsa", case["name"], encode(der), encode(signed), encode(signature), str(signature_valid).lower())))
        if "binding" in case:
            binding = case["binding"]
            for name, value in (("query", binding["raw_query"].encode()), ("body", base64.b64decode(binding["body_base64"])),
                                ("idempotency", binding["idempotency_key"].encode())):
                lines.append("\t".join(("sha256", case["name"] + "/" + name, encode(value), digest(value))))
    Path(destination).write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--export-java-crypto":
        suite = json.loads(Path(__file__).with_name("vectors.json").read_text(encoding="utf-8"))
        export_java_crypto(suite, sys.argv[2])
    else:
        main()
