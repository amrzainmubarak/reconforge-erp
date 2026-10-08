# ADR0840 — Refresh the exact container subject without weakening security gates

Date: 2026-10-08. Status: accepted implementation decision; image acceptance is
recorded separately in the execution evidence.

Manual exact-image scan37728310528 refused a41day-old OpenVEX review under the
existing30day bound. Fresh scan of initial image71d found6unsuppressedHigh:
Python3.12.14, zlib1.3.2-r0 and libuuid2.42.1-r0. Package-only Python/npm audits
and an image doctor pass did not cover these OS/interpreter findings.

Pin both Docker stages to official `python:3.12.15-alpine3.24` index
`sha256:1b668429b3511ab407d8e00648891631b0b1a4d7e15e3ca70f38ab5b91ad4ab4`.
Keep checksum-bound OpenSSL3.5.9 updates and add signed zlib1.3.2-r1 APK with
SHA256 `63aeea03c15a2f9018f81805cfc8aa926bdf5cd68921f22149c2fbb5d0ee9f47`.
The reviewed base already contains libuuid2.42.3-r1. Actual base probes verify
Python3.12.15, Expat2.8.5, OpenSSL3.5.9 and control-character cookie rejection.

Create a new exact-product OpenVEX document for Python3.12.15, version1, using
only the three existing independently sourced fixed decisions. Bind its bytes
in the existing closed policy. Tighten the schema to the reviewed explicit
image tag; retain the30day review limit,120h scanner DB limit, unknown-severity
refusal and Critical/High release gate. Add no CVE exception or wildcard.
Preserve raw Syft/Grype outputs even when validation refuses publication.

Sources: [Python3.12.14 security record](https://www.python.org/downloads/release/python-31214/),
[Python3.12.15 security record](https://www.python.org/downloads/release/python-31215/),
[Alpine3.24 security database](https://secdb.alpinelinux.org/v3.24/main.json).
The Alpine APK signature is checked by `apk verify` and ordinary `apk add`;
the build adds no untrusted-package option.

Financial application source, migrations and Studio are unchanged. Verify the
affected closed-policy contracts, actual packaged runtime, fresh exact-image
SBOM/vulnerability/license gate and Docker parity. Historical images and failed
reports retain their identities; they are not an approved release fallback.
This pin refresh performs no deployment and no database downgrade.
