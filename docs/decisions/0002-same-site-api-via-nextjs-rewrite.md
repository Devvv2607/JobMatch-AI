# ADR 0002: Serve the API same-site through a Next.js rewrite

- Status: accepted (implementation and verification in Phase 10)
- Date: 2026-11-17
- Decided by: project owner

## Context

The refresh token lives in an httpOnly cookie. If the browser talks to the API on a
different site from the frontend (for example `app.vercel.app` and `api.onrender.com`),
the cookie is third-party. It then needs `SameSite=None; Secure`, browsers that block
third-party cookies drop it, and CSRF protection rests entirely on the custom header and
Origin check.

## Decision

In production the browser only ever talks to the frontend's origin. The frontend proxies
`/api/*` to the backend with a Next.js rewrite. Requests are first-party and same-site,
so the refresh cookie keeps `SameSite=Lax`.

- `COOKIE_SAMESITE=lax` (the default) in every environment.
- `COOKIE_SAMESITE=none` stays documented in `docs/deploy.md` as the alternative for a
  split-site deployment. It is not used.
- The CSRF guard is unchanged. The `X-Requested-With` header and the `Origin` allow-list
  still apply. `CORS_ORIGINS` lists the frontend origin, which is what the browser sends
  as `Origin` even when the request goes through the rewrite.

## Consequence for client IP (must be handled before going live)

Per-IP rate limits (login/register, failed refreshes) need the real client address. I
read the Next.js 16.4.6 source in `node_modules/next`:

- External rewrites are proxied by `dist/server/lib/router-utils/proxy-request.js`. It
  uses `httpxy` with `changeOrigin: true` and sets `x-forwarded-host`, but not `xfwd`,
  so it does **not** append the client's address to `X-Forwarded-For`.
- A client-supplied `X-Forwarded-For` therefore reaches the API unchanged. Elsewhere,
  `base-server.js` only fills the header when it is absent (`??=`), which also keeps a
  client-supplied value.

So neither `TRUSTED_PROXY_COUNT` value is safe with Next.js alone in front of the API:

| Setup | `TRUSTED_PROXY_COUNT` | Result |
|---|---|---|
| Browser → Next.js → API | 0 | Every user shares the frontend's IP; one bucket for the whole site. **Unsafe (self-DoS).** |
| Browser → Next.js → API | 1 | The API trusts a header the client wrote. **Unsafe (bypassable).** |
| Browser → platform load balancer (appends XFF) → Next.js → API | 1 | The rightmost entry is the address the load balancer saw. Next.js adds nothing, so it is not counted. **Safe**, if the API is reachable only from the frontend. |

Required for go-live, in Phase 10:
1. Deploy the frontend behind a host or load balancer that appends the client address to
   `X-Forwarded-For`, and record which one in `docs/deploy.md`.
2. Make the API reachable only from the frontend (private network or an allow-list), so
   no client can reach it directly with a forged header.
3. Add an end-to-end check in the deployed environment. Send a request with a forged
   `X-Forwarded-For`, confirm the API logs the real client address, and confirm the
   per-IP limit still triggers.

This analysis comes from reading the source, not from a running test. Step 3 is the
verification.

## Alternatives considered

- **Split sites with `SameSite=None; Secure`:** works without a proxy hop, but depends on
  third-party cookies, which browsers increasingly block.
- **API on a subdomain of the frontend's registrable domain** (`app.example.com` and
  `api.example.com`): same-site and no proxy hop. It needs a custom domain, which free
  hosts may not give. Revisit if one is available at deploy time.
