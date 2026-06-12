import { useState, useEffect } from 'react';
import { apiFetch } from '../../shared/api';
import type { Stats } from '../../shared/types';

export const useStats = () => {
    const [stats, setStats] = useState<Stats | null>(null);
    const [lastUpdate, setLastUpdate] = useState<string>('');

    const loadStats = async () => {
        try {
            const data = await apiFetch<Stats>('/stats');
            setStats(data);
            setLastUpdate(new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
        } catch (err) {
            console.error('Ошибка загрузки статистики', err);
        }
    };

    useEffect(() => {
        loadStats();
        const interval = setInterval(loadStats, 10000);
        return () => clearInterval(interval);
    }, []);

    return { stats, lastUpdate, reloadStats: loadStats };
};