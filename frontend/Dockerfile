FROM node:20-slim AS build
WORKDIR /web
# Baked into Next's rewrite manifest; the browser talks to :3000 and Next
# proxies /api/v1/* to the backend service inside the compose network.
ARG BACKEND_INTERNAL_URL=http://backend:8000
ENV BACKEND_INTERNAL_URL=$BACKEND_INTERNAL_URL
COPY package.json ./
RUN npm install
COPY . .
RUN mkdir -p ./public
RUN STANDALONE_OUTPUT=1 npm run build

FROM node:20-slim
WORKDIR /web
ENV NODE_ENV=production
ENV BACKEND_INTERNAL_URL=http://backend:8000
COPY --from=build /web/.next/standalone ./
COPY --from=build /web/.next/static ./.next/static
COPY --from=build /web/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
