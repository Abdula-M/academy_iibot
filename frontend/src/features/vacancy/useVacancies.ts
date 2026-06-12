import { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '../../shared/api';
import type { VacancyApplication } from '../../shared/types';

export const useVacancies = () => {
    const [vacancies, setVacancies] = useState<VacancyApplication[]>([]);
    const [loading, setLoading] = useState(true);

    const loadVacancies = useCallback(async () => {
        try {
            const data = await apiFetch<VacancyApplication[]>('/vacancy-applications');
            setVacancies(data);
        } catch (err) {
            console.error('Ошибка загрузки заявок', err);
        } finally {
            setLoading(false);
        }
    }, []);

    const markAsRead = async (id: number) => {
        try {
            await apiFetch(`/vacancy-applications/${id}/read`, { method: 'POST' });
            setVacancies(prev => prev.map(v => v.id === id ? { ...v, is_read: true } : v));
        } catch (err) {
            console.error(err);
        }
    };

    useEffect(() => {
        loadVacancies();
    }, [loadVacancies]);

    return { vacancies, loading, reloadVacancies: loadVacancies, markAsRead };
};