FROM node:18-bookworm-slim

# Устанавливаем Chromium и зависимости для Puppeteer
RUN apt-get update && apt-get install -y \
    chromium \
    curl \
    fonts-ipafont-gothic fonts-wqy-zenhei fonts-thai-tlwg fonts-kacst fonts-freefont-ttf \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

WORKDIR /app

# Копируем package.json и устанавливаем зависимости
COPY whatsapp/microservice/package*.json ./
RUN npm install

# Копируем исходный код микросервиса и собираем
COPY whatsapp/microservice/ .

# Копируем базу данных медиа из корня проекта
COPY data/ ./data/

RUN npm run build

EXPOSE 3000

CMD ["npm", "start"]
