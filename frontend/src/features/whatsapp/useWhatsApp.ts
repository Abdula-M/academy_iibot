import { useState } from 'react';
import { apiFetch } from '../../shared/api';

export const useWhatsApp = () => {
    const [qrCode, setQrCode] = useState<string | null>(null);
    const [status, setStatus] = useState<string>('Проверка статуса...');

    const loadStatus = async () => {
        try {
            const data = await apiFetch<any>('/whatsapp/status');
            const currentStatus = data.status?.toUpperCase();
            if (currentStatus === 'AUTHENTICATED' || currentStatus === 'READY') {
                setStatus('✅ WhatsApp подключен. Бот готов к работе.');
                setQrCode(null);
            } else if (currentStatus === 'QR_READY') {
                setStatus('Отсканируйте QR-код в приложении WhatsApp');
                setQrCode(data.qr_base64 || data.qr);
            } else {
                setStatus('⏳ Инициализация WhatsApp... Подождите.');
                setQrCode(null);
            }
            return currentStatus?.toLowerCase() || 'error';
        } catch (err) {
            console.error('Ошибка WhatsApp', err);
            setStatus('❌ Ошибка связи с WhatsApp сервисом.');
            return 'error';
        }
    };

    const logout = async () => {
        try {
            await apiFetch('/whatsapp/logout', { method: 'POST' });
            setStatus('Ожидание нового QR-кода...');
            setQrCode(null);
        } catch (err) {
            console.error(err);
        }
    };

    return { qrCode, status, loadStatus, logout };
};