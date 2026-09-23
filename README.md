# XEL Hashnomletz Toolkit

Windows-friendly GUI tools for mining and wallet-managing [Xelis (XEL)](https://xelis.io) on the
Hash'n'Omletz pool. Built for hobby miners who want to point-and-click instead of memorizing CLI flags —
both tools are thin wrappers around the **unmodified official Xelis binaries**, downloaded fresh and
cryptographically verified (checksum, and GPG-signature where the upstream project publishes one) before
they're ever run. We never repackage or fork the underlying mining/wallet code.

## What's in here

### [`rigel-miner-gui/`](rigel-miner-gui/) — GPU miner
A GUI wrapper around [Rigel](https://github.com/rigelminer/rigel), an Nvidia GPU miner. Pick your
algorithm from a dropdown (not locked to XEL — works with any pool Rigel supports), point it at a pool,
and mine. Verified end-to-end on real hardware: real shares accepted, Stop button actually stops the GPU,
packaged and iconed for Windows.

### [`xelis-wallet-gui/`](xelis-wallet-gui/) — Wallet
A GUI wrapper around the official `xelis_wallet`. Create or open a wallet, see your address (to point
pool payouts at) and balance, back up your seed phrase safely, and send/receive XEL — verified against a
real on-chain transfer, not just built against the docs.

## Download

Pre-built Windows `.exe`s are attached to [Releases](../../releases) — grab the latest one, no Python or
build tools needed. (If GitHub Actions is set up for this repo, tagging a release builds both exes
automatically — see `.github/workflows/build-windows.yml`.)

## Building from source

Both tools follow the same pattern (Python 3.11+, Windows):
```
cd rigel-miner-gui   # or xelis-wallet-gui
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python app\main.py
```
To package into a single-file `.exe`:
```
venv\Scripts\pyinstaller build_windows.spec
```
See each tool's own README for verification details, known limitations, and what's been tested live vs.
what's still open.

## Trust model

Every download goes through a verify-before-run chain: fetch the official release, check its checksum
(GPG-signed where the upstream project provides one — Xelis does; Rigel doesn't, so that one uses a
manually-vetted, pinned hash per release instead — see `rigel-miner-gui/README.md` for why), and only
then extract and run it. Any mismatch refuses to run rather than silently continuing. Source for both
wrapper GUIs is right here — nothing is obfuscated or built out-of-band.

## License

MIT — see [LICENSE](LICENSE). The wrapped binaries (Rigel, Xelis) keep their own upstream licenses; we
don't redistribute them, we download and verify them at runtime from their official sources.
