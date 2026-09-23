"""Verifies a downloaded Rigel release against a SHA256 hash we've personally pinned after manually
vetting that release. Unlike the Xelis miner (BSD-3, GPG-signed checksums.txt -- see the sibling
xelis/miner-gui project), Rigel is closed-source freeware and publishes no checksums or signature with
its GitHub releases, so there is no independent signature chain to verify against.

This is trust-on-first-use instead: a human downloads a release, confirms it behaves as expected, and
pins its hash below. Any later automated download is checked against that pin and REFUSED if it doesn't
match -- closing the gap where GitHub (or a MITM) could swap the file after it was reviewed. Update this
table, with a matching manual review of the new release, whenever the bundled Rigel version is bumped."""
import hashlib


class VerificationError(Exception):
    pass


# {(version, asset_name): sha256}. Pinned 2026-09-23 by downloading both official 1.23.2 assets directly
# from github.com/rigelminer/rigel/releases and hashing them.
KNOWN_RELEASES = {
    ("1.23.2", "rigel-1.23.2-linux.tar.gz"): "eae492ffb64aeb4ab4ba7e66631567984a31d5adb1ef547bda6601aee1793f0d",
    ("1.23.2", "rigel-1.23.2-win.zip"): "0a35d37504e2595f2cd9bb25ae69eae39625be6f0ebbdbaf7427d4c381a7fd79",
}


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_release_asset(archive_path: str, version: str, asset_name: str) -> str:
    """Returns the verified sha256 on success. Raises VerificationError on any mismatch or on an
    unpinned (not-yet-reviewed) release -- never lets an unverified binary through."""
    digest = sha256_of(archive_path)

    pinned = KNOWN_RELEASES.get((version, asset_name))
    if pinned is None:
        raise VerificationError(
            f"no pinned hash for {asset_name} @ {version} -- this Rigel release hasn't been manually "
            "vetted yet. Refusing to run an unverified binary. Download it yourself, confirm it's "
            "legitimate, and add its hash to KNOWN_RELEASES in verify.py."
        )
    if digest != pinned:
        raise VerificationError(
            f"SHA256 mismatch for {asset_name} @ {version}: expected {pinned}, got {digest}. The "
            "downloaded file does not match the pinned, manually-vetted release -- refusing to run it."
        )
    return digest
