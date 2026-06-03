# Fuzz Harnesses

These optional harnesses exercise security-sensitive local-first helpers with randomized input. They are for maintainer hardening work and are not required for normal ReconForge ERP use.

Install Atheris in an isolated Python 3.11+ environment, then run:

```bash
python fuzz/fuzz_safe_paths.py
```

Use synthetic input only. Do not add live ERP exports, customer data, financial records, credentials, or generated client packs as fuzz corpora.
