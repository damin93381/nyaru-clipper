FROM node:20-alpine

WORKDIR /app

RUN corepack enable

COPY web/package.json ./package.json
COPY web/pnpm-lock.yaml ./pnpm-lock.yaml

RUN pnpm install --frozen-lockfile

COPY web/index.html ./index.html
COPY web/tsconfig.json ./tsconfig.json
COPY web/vite.config.ts ./vite.config.ts
COPY web/playwright.config.ts ./playwright.config.ts
COPY web/src ./src

EXPOSE 5173

CMD ["pnpm", "dev", "--host", "0.0.0.0", "--port", "5173"]
