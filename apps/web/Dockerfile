# syntax=docker/dockerfile:1
# Next.js web app image (standalone server output).
# Build from the repo root:
#   docker build -f apps/web/Dockerfile --build-arg API_ORIGIN=http://api:8000 -t moneymoney-web .
#
# API_ORIGIN is where the `/api/*` rewrite forwards to. Next.js bakes rewrites in at build
# time, so it is a build argument. On Cloud Run the load balancer routes `/api/*` to the
# API service directly and this rewrite never fires.

ARG NODE_VERSION=24

# --- build ------------------------------------------------------------------------------
FROM node:${NODE_VERSION}-alpine AS build
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /repo

# Dependencies first: this layer only rebuilds when a manifest or the lockfile changes.
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/package.json
COPY packages/contracts/package.json packages/contracts/package.json
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund

COPY packages/contracts packages/contracts
COPY apps/web apps/web
ARG API_ORIGIN=http://127.0.0.1:8000
ENV API_ORIGIN=${API_ORIGIN}
RUN npm run build -w web

# --- runtime ----------------------------------------------------------------------------
FROM node:${NODE_VERSION}-alpine AS runtime
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
WORKDIR /app
# The standalone bundle mirrors the monorepo layout, so the server lives at apps/web/.
COPY --from=build /repo/apps/web/.next/standalone ./
COPY --from=build /repo/apps/web/.next/static ./apps/web/.next/static
USER node
EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=3 \
    CMD ["node", "-e", "fetch(`http://127.0.0.1:${process.env.PORT}/login`).then(r => process.exit(r.ok ? 0 : 1), () => process.exit(1))"]
CMD ["node", "apps/web/server.js"]
