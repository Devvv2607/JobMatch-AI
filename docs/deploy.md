# Deploying JobMatch

The full zero-cost deploy guide arrives in Phase 10. This file already holds the settings
that must be right on any deploy.

## Client IP behind a proxy (`TRUSTED_PROXY_COUNT`)

Rate limits on login and register are per client IP, so the API must know the real
client address.

- **Default `TRUSTED_PROXY_COUNT=0`:** the client IP is the TCP peer address and
  `X-Forwarded-For` is ignored. Any client can send that header, so trusting it by
  default would let anyone pick a fresh IP for every request and bypass the limit.
- **Behind N reverse proxies** (a load balancer, a CDN plus a load balancer, and so on),
  set `TRUSTED_PROXY_COUNT=N`. Each proxy appends the address it received the request
  from, so the client is the Nth entry from the right of `X-Forwarded-For`. Entries further
  left were supplied by the client and are ignored. If the header has fewer than N
  entries, the request did not come through the expected chain and the peer address is
  used.
- Only set N > 0 when the API is **not** reachable except through those proxies.
  Otherwise a client could connect directly and send any header it likes.
- uvicorn runs with `--no-proxy-headers`, so this setting is the only thing that decides
  the client IP.

Example: the host terminates TLS at one load balancer that appends to
`X-Forwarded-For` → `TRUSTED_PROXY_COUNT=1`.

## Topology: the API is same-site, behind the frontend

Decided in [ADR 0002](decisions/0002-same-site-api-via-nextjs-rewrite.md). The browser
only talks to the frontend's origin, and the frontend proxies `/api/*` to the backend
with a Next.js rewrite. The refresh cookie stays `SameSite=Lax`.

**Client IP in this topology:** the Next.js rewrite proxy does not append to
`X-Forwarded-For`, and passes a client-supplied value through unchanged. Per-IP limits
are only safe when a platform load balancer that appends the client address sits in
front of Next.js, `TRUSTED_PROXY_COUNT=1`, and the API is reachable only from the
frontend. See the table and the go-live checks in ADR 0002.

## Cookies and origins

- `COOKIE_SECURE=true` in production. The app refuses to start in production without it.
- `COOKIE_SAMESITE=lax` (the default). This is what the chosen topology uses.
- Alternative, **not used:** if the frontend and API were served on different sites (not
  just different subdomains of one registrable domain), the refresh cookie would need
  `COOKIE_SAMESITE=none`, which browsers only accept with `Secure`, and which breaks
  where third-party cookies are blocked.
- `CORS_ORIGINS` is a comma-separated list of exact frontend origins, such as
  `https://jobmatch.example`. The same list drives the CORS policy and the Origin check
  on cookie-authenticated endpoints. Add the production frontend URL here; no code
  change is needed.
- `JWT_SECRET` must be at least 32 characters in production. The app refuses to start
  otherwise.
