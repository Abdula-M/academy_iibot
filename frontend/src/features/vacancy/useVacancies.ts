import { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '../../shared/api';
import type { VacancyApplication, PaginatedResponse } from '../../shared/types';

const PAGE_SIZE = 50;

export const useVacancies = () => {
    const [vacancies, setVacancies] = useState<VacancyApplication[]>([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(true);
    const [loadingMore, setLoadingMore] = useState(false);

    const loadVacancies = useCallback(async () => {
        try {
            const data = await apiFetch<PaginatedResponse<VacancyApplication>>(
                `/vacancy-applications?offset=0&limit=${PAGE_SIZE}`,
            );
            setVacancies(data.items);
            setTotal(data.total);
        } catch (err) {
            console.error('Ошибка загрузки заявок', err);
        } finally {
            setLoading(false);
        }
    }, []);

    const loadMore = useCallback(async () => {
        if (loadingMore || vacancies.length >= total) return;
        setLoadingMore(true);
        try {
            const data = await apiFetch<PaginatedResponse<VacancyApplication>>(
                `/vacancy-applications?offset=${vacancies.length}&limit=${PAGE_SIZE}`,
            );
            setVacancies(prev => [...prev, ...data.items]);
            setTotal(data.total);
        } catch (err) {
            console.error('Ошибка подгрузки заявок', err);
        } finally {
            setLoadingMore(false);
        }
    }, [vacancies.length, total, loadingMore]);

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

    const hasMore = vacancies.length < total;

    return { vacancies, loading, loadingMore, hasMore, reloadVacancies: loadVacancies, loadMore, markAsRead };
};