import { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '../../shared/api';
import type { User } from '../../shared/types';

export const useUsers = () => {
    const [users, setUsers] = useState<User[]>([]);
    const [loading, setLoading] = useState(true);

    const loadUsers = useCallback(async () => {
        try {
            const data = await apiFetch<User[]>('/users');
            setUsers(data);
        } catch (err) {
            console.error('Ошибка загрузки пользователей', err);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        loadUsers();
        const interval = setInterval(loadUsers, 10000);
        return () => clearInterval(interval);
    }, [loadUsers]);

    return { users, loading, reloadUsers: loadUsers };
};