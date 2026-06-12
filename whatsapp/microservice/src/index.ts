import { Client, LocalAuth, MessageMedia } from 'whatsapp-web.js';
import qrcode from 'qrcode-terminal';
import express from 'express';
import axios from 'axios';
import fs from 'fs';
import path from 'path';

const app = express();
app.use(express.json());

const FASTAPI_WEBHOOK_URL = process.env.WEBHOOK_URL || 'http://localhost:8000/api/whatsapp/webhook';
const PORT = process.env.PORT || 3000;

// Путь к папке с данными авторизации (LocalAuth хранит здесь сессию)
const AUTH_DIR = path.join(process.cwd(), '.wwebjs_auth');

// Состояние для передачи на фронтенд
let currentStatus = 'STARTING';
let currentQR = '';

let client: Client;

/**
 * Удаляет папку сессии, чтобы при следующем старте
 * LocalAuth сгенерировал свежий QR-код.
 */
function clearSessionData(): void {
    try {
        if (fs.existsSync(AUTH_DIR)) {
            fs.rmSync(AUTH_DIR, { recursive: true, force: true });
            console.log('Папка сессии очищена:', AUTH_DIR);
        }
    } catch (err) {
        console.error('Ошибка при очистке папки сессии:', err);
    }
}

async function startWhatsApp() {
    let puppeteerArgs = [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--disable-accelerated-2d-canvas',
        '--no-first-run',
        '--no-zygote',
        '--disable-gpu'
    ];
    
    client = new Client({
        authStrategy: new LocalAuth(),
        puppeteer: {
            executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || '/usr/bin/chromium',
            args: puppeteerArgs
        },
        webVersionCache: {
            type: 'none',
        }
    });

    client.on('qr', (qr: string) => {
        console.log('Отсканируйте этот QR-код в приложении WhatsApp:');
        qrcode.generate(qr, { small: true });
        currentStatus = 'QR_READY';
        currentQR = qr;
    });

    client.on('authenticated', () => {
        currentStatus = 'AUTHENTICATED';
        currentQR = '';
    });

    client.on('loading_screen', (percent: string, message: string) => {
        console.log(`[LOADING] ${percent}% - ${message}`);
    });

    client.on('ready', async () => {
        console.log('WhatsApp клиент успешно запущен и готов к работе!');
        currentStatus = 'READY';
        currentQR = '';
        
        try {
            await client.pupPage?.evaluate(() => {
                const w = window as any;
                if (w.mR && w.mR.findModule) {
                    const lidModule = w.mR.findModule('WAWebLid1X1MigrationGating')[0];
                    if (lidModule && lidModule.Lid1X1MigrationUtils) {
                        lidModule.Lid1X1MigrationUtils.isLidMigrated = () => false;
                        console.log('Patch isLidMigrated applied successfully');
                    }
                }
            });
        } catch (err) {
            console.error('LID patch injection failed:', err);
        }
    });

    client.on('auth_failure', (msg) => {
        console.error('Ошибка аутентификации WhatsApp:', msg);
        currentStatus = 'DISCONNECTED';
        currentQR = '';
        clearSessionData();
        console.log('Перезапуск контейнера после auth_failure...');
        process.exit(1);
    });

    client.on('disconnected', async (reason) => {
        console.log('Client was logged out:', reason);
        currentStatus = 'DISCONNECTED';
        currentQR = '';
        try { await client.destroy(); } catch (e) {}
        clearSessionData();
        console.log('Перезапуск контейнера для очистки сессии...');
        process.exit(0);
    });

    // Обработчик для всех сообщений (включая отправленные с самого телефона) для дебага
    client.on('message_create', async (msg) => {
        if (msg.fromMe) {
            console.log(`[DEBUG] Отправлено исходящее сообщение (или с этого же аккаунта): ${msg.from} -> ${msg.to}: ${msg.body.substring(0, 50)}`);
        }
    });

    // Слушаем входящие сообщения
    client.on('message', async (msg) => {
        console.log(`[DEBUG] Входящее сообщение от ${msg.from}: ${msg.body.substring(0, 50)} (type: ${msg.type})`);
        // Игнорируем сообщения из групп и статусы
        if (msg.isStatus || msg.from.endsWith('@g.us')) {
            console.log(`[DEBUG] Сообщение проигнорировано (status или группа)`);
            return;
        }

        try {
            // Параллельно загружаем контакт и медиа
            const [contact, media] = await Promise.all([
                msg.getContact(),
                (msg.hasMedia && (msg.type === 'ptt' || msg.type === 'audio')) ? msg.downloadMedia() : Promise.resolve(undefined)
            ]);
            
            let audioBase64: string | undefined;
            if (media) {
                audioBase64 = media.data;
            }
            
            await axios.post(FASTAPI_WEBHOOK_URL, {
                chat_id: msg.from,
                text: msg.body,
                sender_name: contact.pushname || contact.name || undefined,
                audio_base64: audioBase64
            }, { timeout: 30000 });
            
        } catch (error) {
            console.error('Ошибка при отправке вебхука в FastAPI:', error);
        }
    });

    console.log('Запуск WhatsApp клиента...');
    
    // Таймаут на инициализацию: если за 90 секунд клиент не стартовал — перезапуск
    const initTimeout = setTimeout(() => {
        if (currentStatus === 'STARTING') {
            console.error('TIMEOUT: WhatsApp клиент не запустился за 90 секунд. Перезапуск...');
            clearSessionData();
            process.exit(1);
        }
    }, 90_000);
    initTimeout.unref(); // Не блокируем завершение процесса

    client.initialize().catch((err) => {
        console.error('Ошибка при инициализации WhatsApp клиента:', err);
        clearSessionData();
        process.exit(1);
    });
}

// Эндпоинт для отправки сообщений из FastAPI в WhatsApp
app.post('/send', async (req, res) => {
    try {
        if (currentStatus !== 'READY' && currentStatus !== 'AUTHENTICATED') {
            return res.status(503).json({ error: 'WhatsApp client is not ready' });
        }

        const { chat_id, text, photo_path, media_path } = req.body;
        
        if (!chat_id || !text) {
            return res.status(400).json({ error: 'chat_id and text are required' });
        }

        let media: MessageMedia | undefined;
        const targetMedia = media_path || photo_path;
        
        console.log(`Received request to send message. targetMedia: ${targetMedia}`);

        if (targetMedia) {
            try {
                media = MessageMedia.fromFilePath(targetMedia);
                console.log(`Media loaded successfully. mimetype: ${media.mimetype}`);
            } catch (mediaError) {
                console.error(`Не удалось загрузить медиа по пути ${targetMedia}:`, mediaError);
            }
        }

        if (media) {
            const isPdf = targetMedia.toLowerCase().endsWith('.pdf');
            const chat = await client.getChatById(chat_id);
            await chat.sendMessage(media, { 
                caption: text,
                sendMediaAsDocument: isPdf
            });
            console.log('Message with media sent successfully.');
        } else {
            const chat = await client.getChatById(chat_id);
            await chat.sendMessage(text);
            console.log('Message (text only) sent successfully.');
        }

        res.json({ success: true });
    } catch (error) {
        console.error('Ошибка при отправке сообщения в WhatsApp:', error);
        res.status(500).json({ error: 'Internal server error' });
    }
});

// Эндпоинт для получения статуса и QR-кода
app.get('/status', (req, res) => {
    res.json({
        status: currentStatus,
        qr: currentQR
    });
});

// Эндпоинт для принудительной отвязки (разлогина)
app.post('/logout', async (req, res) => {
    try {
        console.log('Запрошен выход (отвязка) WhatsApp...');
        currentStatus = 'STARTING';
        currentQR = '';
        if (client) {
            try { await client.logout(); } catch(e) {}
            try { await client.destroy(); } catch(e) {}
        }
        clearSessionData();
        res.json({ success: true });
        
        // Выходим из процесса, чтобы Docker поднял его заново с чистым профилем
        setTimeout(() => {
            console.log('Перезапуск контейнера после принудительной отвязки...');
            process.exit(0);
        }, 1000);
    } catch (error) {
        console.error('Ошибка при отвязке WhatsApp:', error);
        res.status(500).json({ error: 'Failed to logout' });
    }
});

app.listen(PORT, () => {
    console.log(`Express сервер запущен на порту ${PORT}`);
    startWhatsApp().catch(console.error);
});

// Graceful shutdown
process.on('SIGTERM', async () => {
    console.log('SIGTERM signal received: closing HTTP server and WhatsApp client');
    try {
        if (client) {
            await client.destroy();
        }
    } catch (e) {
        console.error('Error destroying client on shutdown', e);
    }
    process.exit(0);
});

process.on('SIGINT', async () => {
    console.log('SIGINT signal received: closing HTTP server and WhatsApp client');
    try {
        if (client) {
            await client.destroy();
        }
    } catch (e) {
        console.error('Error destroying client on shutdown', e);
    }
    process.exit(0);
});
