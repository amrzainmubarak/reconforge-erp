# Same-origin browser hosting

This runbook describes the bounded self-hosted origin supported by ADR 0200.
It does not certify an internet-facing topology.

## Build and direct TLS

Build Studio with locked dependencies:

```text
npm --prefix apps/web ci
npm --prefix apps/web run build
```

Start the API and the built Studio on one reviewed hostname:

```text
reconforge api serve --db output/reconforge.db --web-root apps/web/dist --allowed-host reconforge.example.internal --host 0.0.0.0 --port 8443 --tls-certfile /run/secrets/reconforge-tls-chain.pem --tls-keyfile /run/secrets/reconforge-tls-key.pem
```

The certificate and private key are operator-managed inputs and must never be
committed. The certificate must match the browser hostname. Protect the key
with operating-system permissions and the organization's approved rotation
process.

## Reviewed upstream TLS termination

When an upstream component owns TLS, omit the certificate/key and pass
`--secure-transport`. The upstream must:

- accept only approved hostnames and overwrite the backend Host header with one
  of the exact `--allowed-host` values;
- redirect or reject plaintext at the edge and prevent direct backend access;
- preserve `/api/v1/*`, Studio routes, and cookie attributes on the same public
  origin;
- use a validated certificate and the organization's supported TLS policy;
- avoid trusting caller-supplied forwarded headers unless the edge replaces
  them and the deployment has a separate reviewed trust boundary.

## Verification

For the public origin, verify all of the following rather than only receiving a
200 response:

- `/admin-audit` and `/api/v1/health` have the same scheme, host, and port;
- TLS hostname verification succeeds and obsolete TLS is rejected by the
  deployment policy;
- HSTS, CSP, `nosniff`, frame denial, referrer policy, and permissions policy
  are present on HTML and API responses;
- an unapproved Host receives 400;
- an unknown asset path returns 404 and is not replaced with HTML;
- browser login creates only the `__Host-reconforge_session` Secure, HttpOnly,
  SameSite=Strict cookie, and unsafe cookie requests without the bound CSRF
  proof fail;
- no CSP violation occurs while loading the production bundle and executing
  the administration workflow.

## Rollback

Remove the web-root and secure-hosting options and return to API-only localhost
operation. This does not reverse identity, audit, integration, or retention
state. If a proxy was deployed, remove its route only after confirming no
active operators depend on that origin.
