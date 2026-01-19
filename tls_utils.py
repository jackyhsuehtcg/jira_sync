import hashlib
import os
import tempfile

try:
    import certifi
except Exception:
    certifi = None


def build_ca_bundle(custom_ca_path: str) -> str:
    """Combine system CA bundle with a custom CA certificate when possible."""
    if not custom_ca_path or not certifi:
        return custom_ca_path

    digest = hashlib.sha256(custom_ca_path.encode("utf-8")).hexdigest()[:12]
    bundle_path = os.path.join(tempfile.gettempdir(), f"jira_ca_bundle_{digest}.pem")

    try:
        with open(certifi.where(), "rb") as base, open(custom_ca_path, "rb") as extra, open(
            bundle_path, "wb"
        ) as out:
            out.write(base.read())
            out.write(b"\n")
            out.write(extra.read())
    except Exception:
        return custom_ca_path

    return bundle_path
