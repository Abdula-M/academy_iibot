import { useState, useEffect, useCallback, useRef } from 'react';
import { apiFetch } from '../../shared/api';
import type { Message, PaginatedResponse } from '../../shared/types';

const PAGE_SIZE = 50;

export const useChat = (telegramId: number | null) => {
    const [messages, setMessages] = useState<Message[]>([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);
    const [loadingOlder, setLoadingOlder] = useState(false);
    const prevTelegramId = useRef<number | null>(null);

    const loadMessages = useCallback(async () => {
        if (!telegramId) return;
        setLoading(true);
        try {
            const data = await apiFetch<PaginatedResponse<Message>>(
                `/messages/${telegramId}?offset=0&limit=${PAGE_SIZE}`,
            );
            setMessages(data.items);
            setTotal(data.total);
        } catch (err) {
            console.error('Ошибка загрузки сообщений', err);
        } finally {
            setLoading(false);
        }
    }, [telegramId]);

    const loadOlder = useCallback(async () => {
        if (!telegramId || loadingOlder || messages.length >= total) return;
        setLoadingOlder(true);
        try {
            const data = await apiFetch<PaginatedResponse<Message>>(
                `/messages/${telegramId}?offset=${messages.length}&limit=${PAGE_SIZE}`,
            );
            // Старые сообщения добавляются в начало (они хронологически раньше)
            setMessages(prev => [...data.items, ...prev]);
        } catch (err) {
            console.error('Ошибка подгрузки старых сообщений', err);
        } finally {
            setLoadingOlder(false);
        }
    }, [telegramId, messages.length, total, loadingOlder]);

    useEffect(() => {
        if (telegramId !== prevTelegramId.current) {
            setMessages([]);
            setTotal(0);
            prevTelegramId.current = telegramId;
        }
        loadMessages();
    }, [telegramId, loadMessages]);

    const hasOlder = messages.length < total;

    return { messages, total, loading, loadingOlder, hasOlder, reloadMessages: loadMessages, loadOlder };
};