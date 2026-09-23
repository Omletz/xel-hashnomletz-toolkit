"""Static list of Rigel's supported mining algorithms, read straight from `rigel --help` on the real
v1.23.2 binary (2026-09-23) -- not guessed from docs. This is the single source of truth for the GUI's
algorithm dropdown. Update this list (and re-check against `rigel --help`) whenever the bundled Rigel
version is bumped, since Rigel does add/remove algorithms between releases (1.23.2's changelog itself
removed `ethashb3`)."""

ALGORITHMS = [
    {"id": "abelian", "label": "Abelian (ABEL)"},
    {"id": "alephium", "label": "Alephium (ALPH)"},
    {"id": "autolykos2", "label": "Autolykos2 (ERG)"},
    {"id": "etchash", "label": "Etchash (ETC)"},
    {"id": "ethash", "label": "Ethash (ETHW, XPB, OCTA, ...)"},
    {"id": "fishhash", "label": "FishHash (IRON)"},
    {"id": "karlsenhashv2", "label": "KarlsenHashV2 (KLS)"},
    {"id": "kawpow", "label": "KawPow (RVN, QUAI, XNA, NEOX, ...)"},
    {"id": "nexapow", "label": "NexaPow (NEXA)"},
    {"id": "octopus", "label": "Octopus (CFX)"},
    {"id": "progpowz", "label": "ProgPowZ (ZANO)"},
    {"id": "sha256ton", "label": "SHA256TON (GRAM)"},
    {"id": "sha3x", "label": "SHA3x (XTM)"},
    {"id": "sha512256d", "label": "SHA512256d (RXD)"},
    {"id": "xelishashv3", "label": "XelisHashV3 (XEL)"},
    {"id": "zil", "label": "Zil (ZIL)"},
]
