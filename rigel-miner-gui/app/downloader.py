"""Fetches the official Rigel miner release straight from GitHub (never repackaged by us). Unlike the
Xelis miner GUI, there is no GPG-signed checksums.txt published for Rigel -- see verify.py for the
trust-on-first-use pinning model this uses instead. Picks the asset for the current OS automatically."""
import json
import os
import platform
import ssl
import sys
import tarfile
import urllib.request
import zipfile

import certifi

from verify import VerificationError, verify_release_asset

REPO = "rigelminer/rigel"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
UA = {"User-Agent": "hashnomletz-rigel-gui"}


def _cacert_path() -> str:
    """certifi.where() internally uses importlib.resources.files("certifi") to locate cacert.pem --
    this is a known fragile path inside a PyInstaller onefile bundle (it depends on certifi's own
    package-resource resolution working correctly against the frozen/extracted layout, which isn't
    guaranteed just because the file was bundled via `datas=`). When frozen, read the file we bundled
    ourselves straight out of sys._MEIPASS instead of trusting certifi's own resolution -- build_windows.spec
    bundles it at exactly this path (datas=[(certifi.where(), 'certifi')]) for this reason. Falls back to
    certifi.where() in normal (non-frozen) dev runs."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        bundled = os.path.join(sys._MEIPASS, "certifi", "cacert.pem")
        if os.path.exists(bundled):
            return bundled
    return certifi.where()


def _build_ssl_context() -> ssl.SSLContext:
    """Trusts BOTH certifi's bundled public CA roots AND whatever this machine's own OS cert store
    already trusts -- deliberately a union, not a swap. ssl.create_default_context(cafile=...) REPLACES
    the trust store with only that file (confirmed against the stdlib docs: when cafile/capath/cadata is
    given, the system default CAs are NOT also loaded) -- an earlier version of this fix passed cafile
    alone, which silently stopped trusting the OS store. That's a real problem on a machine with a
    corporate/security-software root cert installed only in the OS store (common cause of "browser works
    fine, our exe doesn't" -- browsers also trust the OS store), and we have no way to know from here
    whether that's this specific machine's situation. load_default_certs() is additive (it adds into the
    same underlying trust store, verification succeeds if ANY trusted root chains), so calling both is
    strictly safer than either alone -- covers "our bundle is missing/stale" and "a needed root only
    lives in the OS store" simultaneously without having to diagnose which one applies."""
    cafile = _cacert_path()
    ctx = ssl.create_default_context(cafile=cafile)
    try:
        ctx.load_default_certs()
    except Exception as e:
        _log_diag(f"load_default_certs() failed (non-fatal, continuing with certifi bundle only): {e!r}")
    return ctx


_DIAG_LOG: list[str] = []


def _log_diag(msg: str) -> None:
    _DIAG_LOG.append(msg)


def get_ssl_diagnostics() -> dict:
    """Exposed to the GUI so a real failure shows exactly what was tried instead of a bare exception
    string -- after two blind guesses that both failed identically, the priority is making the NEXT
    failure (if any) self-diagnosing rather than guessing a third time."""
    cafile = _cacert_path()
    return {
        "frozen": bool(getattr(sys, "frozen", False)),
        "meipass": getattr(sys, "_MEIPASS", None),
        "cacert_path_used": cafile,
        "cacert_exists": os.path.exists(cafile),
        "cacert_size_bytes": os.path.getsize(cafile) if os.path.exists(cafile) else None,
        "log": list(_DIAG_LOG),
    }


# Explicit cert bundle rather than trusting each machine's own OS cert store alone -- confirmed 2026-09-23
# that a real outside miner hit "CERTIFICATE_VERIFY_FAILED" on a fresh Windows box, which urllib surfaced
# as a generic download error that looked like our own SHA256 verification failing (it wasn't -- see
# verify.py). certifi's bundle is pinned by our own requirements.txt/build, so it can't drift the way a
# stale/incomplete OS root store can -- but see _build_ssl_context()'s docstring for why this is a union
# with the OS store, not a replacement of it.
_SSL_CONTEXT = _build_ssl_context()


def _asset_name_for_platform(version: str) -> str:
    system = platform.system()
    if system == "Windows":
        return f"rigel-{version}-win.zip"
    if system == "Linux":
        return f"rigel-{version}-linux.tar.gz"
    raise VerificationError(f"unsupported platform: {system} (Rigel only ships Nvidia Windows/Linux builds)")


def _get(url: str, timeout=30) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as r:
            return r.read()
    except ssl.SSLError as e:
        diag = get_ssl_diagnostics()
        raise VerificationError(
            f"SSL error fetching {url}: {e}. cacert_path={diag['cacert_path_used']} "
            f"exists={diag['cacert_exists']} size={diag['cacert_size_bytes']} frozen={diag['frozen']} "
            f"meipass={diag['meipass']}. (Union of certifi bundle + OS store was tried, both failed.)"
        ) from e


def fetch_release_info() -> dict:
    return json.loads(_get(API_LATEST, timeout=15).decode())


def download_and_verify(dest_dir: str, progress_cb=None) -> dict:
    """Downloads the release archive, verifies it against a pinned, manually-vetted SHA256 (see
    verify.py), extracts the miner binary into dest_dir. Raises VerificationError on any failure --
    never returns a path to an unverified binary. If the release isn't in our pinned table yet (e.g.
    Rigel shipped a new version we haven't reviewed), this refuses to run it rather than trusting an
    unreviewed download."""
    os.makedirs(dest_dir, exist_ok=True)
    info = fetch_release_info()
    tag = info["tag_name"]
    assets = {a["name"]: a["browser_download_url"] for a in info["assets"]}
    asset_name = _asset_name_for_platform(tag)
    if asset_name not in assets:
        raise VerificationError(f"release {tag} is missing expected asset {asset_name}")

    if progress_cb: progress_cb(f"downloading {asset_name}...")
    archive_path = os.path.join(dest_dir, asset_name)
    with open(archive_path, "wb") as f:
        f.write(_get(assets[asset_name], timeout=180))

    if progress_cb: progress_cb("verifying against pinned SHA256...")
    sha256 = verify_release_asset(archive_path, tag, asset_name)

    if progress_cb: progress_cb("extracting...")
    binary_name = "rigel.exe" if asset_name.endswith(".zip") else "rigel"
    if asset_name.endswith(".zip"):
        with zipfile.ZipFile(archive_path) as z:
            member = next((n for n in z.namelist() if os.path.basename(n) == binary_name), None)
            if not member: raise VerificationError(f"{binary_name} not found inside {asset_name}")
            z.extract(member, dest_dir)
            extracted = os.path.join(dest_dir, member)
    else:
        with tarfile.open(archive_path) as t:
            member = next((m for m in t.getmembers() if os.path.basename(m.name) == binary_name), None)
            if not member: raise VerificationError(f"{binary_name} not found inside {asset_name}")
            t.extract(member, dest_dir)
            extracted = os.path.join(dest_dir, member.name)

    final_path = os.path.join(dest_dir, binary_name)
    if extracted != final_path:
        os.replace(extracted, final_path)
        leftover_dir = os.path.dirname(extracted)
        if leftover_dir != dest_dir and os.path.isdir(leftover_dir):
            try: os.removedirs(leftover_dir)   # only removes it if now empty
            except OSError: pass
    if platform.system() != "Windows":
        os.chmod(final_path, 0o755)
    os.remove(archive_path)

    if progress_cb: progress_cb(f"verified: {asset_name} sha256={sha256}")
    return {"version": tag, "binary_path": final_path, "sha256": sha256, "release_url": f"https://github.com/{REPO}/releases/tag/{tag}"}
