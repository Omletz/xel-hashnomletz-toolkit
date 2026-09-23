"""Official Xelis project PGP public key, pinned from https://github.com/xelis-project/xelis-blockchain/blob/master/SECURITY.md
(fetched 2026-09-22; verify this hasn't changed if the project ever rotates keys). Used to verify the detached signature on
every release's checksums.txt before we trust any checksum in it, so a compromised GitHub account/CDN alone can't slip in a
tampered binary without also compromising this key."""
XELIS_PUBKEY = """-----BEGIN PGP PUBLIC KEY BLOCK-----

mDMEako4IxYJKwYBBAHaRw8BAQdAL4+YrLHJEbrA8Xlst9tVvfpLtIPhGoEDDKBw
VcSX3Hu0GHhlbGlzIDxjb250YWN0QHhlbGlzLmlvPoiQBBMWCgA4FiEE0pNT7yHw
IefMhvVal7weh/qNk6wFAmpKOCMCGwMFCwkIBwIGFQoJCAsCBBYCAwECHgECF4AA
CgkQl7weh/qNk6yPlgD/QOSrQ9faMu7ds+/IePX2n3UMVAzrvFpLfwBHrMXbF/0A
/R1mLMeRlQifJMLW9Qvuu8D3ruIk6CKCzjPfOM+RjEgBuDgEako4IxIKKwYBBAGX
VQEFAQEHQIXf29Rtpe1C0ww64FI7tiZ8rmJK2JQJQ77Ih/g8lGEzAwEIB4h4BBgW
CgAgFiEE0pNT7yHwIefMhvVal7weh/qNk6wFAmpKOCMCGwwACgkQl7weh/qNk6yN
bwEAlODdY/mah1N1udbadvSN0tnTtj2PXZAz3UPLSN2frf0BANNxhDia69ZpAZ+H
OqCaQGIZxX830ygk/Yk4KDO034AL
=wnK6
-----END PGP PUBLIC KEY BLOCK-----
"""
