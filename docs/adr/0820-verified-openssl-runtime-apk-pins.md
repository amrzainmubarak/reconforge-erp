# Independently verified OpenSSL runtime APK pins

Status: accepted locally; exact hosted image acceptance remains separate.
Date: 2026-10-03
Source commit: 68bfea5b.

PR113's Docker build and parity jobs fail closed because the returned libssl3
3.5.8-r0 checksum differs from the reviewed pin. A fresh local CDN fetch still
matches that old pin; another official mirror returns404. The unknown hosted
response bytes are unavailable. No CDN/network/root-cause explanation is claimed.

Review the current3.5.9-r0 libssl3/libcrypto3 artifacts from two official Alpine
hosts. Copies match byte-for-byte; signed APKINDEX records bind their versions,
architecture, size, source build commit and control checksums. Verify all four
packages and both indexes with the keys already present in the exact pinned
Python/Alpine base. No new key or trust override is used.

Pin both reviewed artifact URLs and whole-file SHA256s in both Docker stages.
Keep image/uv digests unchanged and retain checksum enforcement. A fresh offline
installation upgrades both libraries, with package database, imported OpenSSL,
known SHA256 answer, loaded-library maps and MemoryBIO ClientHello verified.

The actual full Docker build succeeds in52.180s on immutable68bfea5b. Container
doctor, sample validation, audit-pack validation, constrained offline/read-only
doctor and Python OpenSSL3.5.9 check all pass.34 supply-chain policy tests pass.
Image config digest and every command/log hash are retained. The original hosted
failures and an unrelated failed ldd diagnostic remain preserved separately.

This establishes reviewed x86_64 artifact provenance and a local image build.
It does not establish multiarchitecture support, zero vulnerabilities, hosted
acceptance, stable release or production deployment.

Rollback: preserve the verified image digest and redeploy the prior compatible
image if needed. Do not remove checksum/signature enforcement, accept the unknown
hosted response digest or install packages with --allow-untrusted.
