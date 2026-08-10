FROM node:20-alpine

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

# NEXT_PUBLIC_* vars are inlined at build time, so they must be ARGs here — a
# runtime `environment:` entry never reaches the compiled bundle (→ 401s).
ARG NEXT_PUBLIC_API_URL=/api
ARG NEXT_PUBLIC_API_KEY
ARG BACKEND_URL=http://backend:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_KEY=$NEXT_PUBLIC_API_KEY
ENV BACKEND_URL=$BACKEND_URL
RUN npm run build

EXPOSE 3000
CMD ["npm", "run", "start"]
