# Sokosumi Coworker on the server: Eve (language model agent) + the worker, in one container.
# Build from the repository root: docker build -f deploy/agent.Dockerfile -t agroland-agent .
FROM node:24-bookworm-slim
RUN npm install -g @masumi_network/sokosumi@1.1.0 && npm cache clean --force
WORKDIR /app/agent
COPY agent/package.json agent/package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY config/ /app/config/
COPY agent/ ./
RUN chmod +x server-run.sh && mkdir -p .local docs && chmod 700 .local
CMD ["./server-run.sh"]
