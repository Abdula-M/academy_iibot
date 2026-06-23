import { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '../../shared/api';
import type { User, PaginatedResponse } from '../../shared/types';

const PAGE_SIZE = 50;

export const useUsers = () => {
    const [users, setUsers] = useState<User[]>([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(true);
    const [loadingMore, setLoadingMore] = useState(false);

    const loadUsers = useCallback(async () => {
        try {
            const data = await apiFetch<PaginatedResponse<User>>(`/users?offset=0&limit=${PAGE_SIZE}`);
            setUsers(data.items);
            setTotal(data.total);
        } catch (err) {
            console.error('Ошибка загрузки пользователей', err);
        } finally {
            setLoading(false);
        }
    }, []);

    const loadMore = useCallback(async () => {
        if (loadingMore || users.length >= total) return;
        setLoadingMore(true);
        try {
            const data = await apiFetch<PaginatedResponse<User>>(
                `/users?offset=${users.length}&limit=${PAGE_SIZE}`,
            );
            setUsers(prev => [...prev, ...data.items]);
            setTotal(data.total);
        } catch (err) {
            console.error('Ошибка подгрузки пользователей', err);
        } finally {
            setLoadingMore(false);
        }
    }, [users.length, total, loadingMore]);

    useEffect(() => {
        loadUsers();
        const interval = setInterval(loadUsers, 10000);
        return () => clearInterval(interval);
    }, [loadUsers]);

    const hasMore = users.length < total;

    return { users, loading, loadingMore, hasMore, reloadUsers: loadUsers, loadMore };
};