FROM node:20-alpine

WORKDIR /app

# Копируем package.json и устанавливаем зависимости
COPY whatsapp/baileys/package*.json ./
RUN npm install

# Копируем исходный код и собираем
COPY whatsapp/baileys/ .


RUN npm run build

EXPOSE 3000

CMD ["node", "dist/index.js"]
