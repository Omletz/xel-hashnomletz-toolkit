"""Supply-chain verification for the official xelis_miner release: GPG-verify checksums.txt against the pinned Xelis
project key, then SHA256-verify the downloaded binary against a checksum entry from that VERIFIED file. Both steps
must pass before the binary is ever executed. Fails closed: any error here blocks the binary, never silently continues."""
import hashlib

import pgpy

from pubkey import XELIS_PUBKEY


class VerificationError(Exception):
    pass


def verify_checksums_signature(checksums_text: str, signature_text: str) -> None:
    """Raises VerificationError unless checksums_text is validly signed by the pinned Xelis project key."""
    try:
        key, _ = pgpy.PGPKey.from_blob(XELIS_PUBKEY)
        sig = pgpy.PGPSignature.from_blob(signature_text)
    except Exception as e:
        raise VerificationError(f"could not parse key/signature: {e}")
    # checksums.txt is signed as-is (detached signature); pgpy verifies over the raw bytes
    verified = key.verify(checksums_text, sig)
    if not verified:
        raise VerificationError("GPG signature on checksums.txt does NOT verify against the pinned Xelis project key")


def find_checksum(checksums_text: str, filename: str) -> str:
    for line in checksums_text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[1].strip() == filename:
            return parts[0].strip().lower()
    raise VerificationError(f"no checksum entry found for {filename} in the (signature-verified) checksums.txt")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_release_asset(asset_path: str, asset_filename: str, checksums_text: str, signature_text: str) -> str:
    """Full chain: verify checksums.txt's signature, look up the asset's expected hash in it, verify the actual file
    matches. Returns the verified sha256 hex digest on success; raises VerificationError otherwise."""
    verify_checksums_signature(checksums_text, signature_text)
    expected = find_checksum(checksums_text, asset_filename)
    actual = sha256_file(asset_path)
    if actual != expected:
        raise VerificationError(f"SHA256 MISMATCH for {asset_filename}: expected {expected}, got {actual} -- refusing to run this binary")
    return actual
