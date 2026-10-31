# Sokosumi Coworker on the server: Eve (language model agent) + the worker, in one container.
# Build from the repository root: docker build -f deploy/agent.Dockerfile -t agroland-agent .
FROM node:24-bookworm-slim
RUN npm install -g @masumi_network/sokosumi@1.1.0 && npm cache clean --force
WORKDIR /app/agent
COPY agent/package.json agent/package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY config/ /app/config/
COPY agent/ ./
# A Windows checkout may turn the script's line endings into CRLF, which bash cannot run.
RUN sed -i 's/\r$//' server-run.sh && chmod +x server-run.sh && mkdir -p .local docs && chmod 700 .local
# Compile the agent here: `eve dev` compiles at start and does not fit a small server's memory. The model id and its
# context window are compiled in; the provider URL and API key are read from the environment at run time.
ARG ZAI_MODEL=gpt-4.1-mini
ARG ZAI_CONTEXT_WINDOW_TOKENS=128000
RUN ZAI_MODEL=$ZAI_MODEL ZAI_CONTEXT_WINDOW_TOKENS=$ZAI_CONTEXT_WINDOW_TOKENS ZAI_BASE_URL=http://build.invalid ZAI_API_KEY=build-time-placeholder \
    node node_modules/eve/bin/eve.js build --skip-sandbox-prewarm && rm -rf .eve/cache
ENV EVE_MODE=start
CMD ["./server-run.sh"]
