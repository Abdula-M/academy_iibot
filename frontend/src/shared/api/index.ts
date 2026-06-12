export const apiFetch = async <T>(endpoint: string, options?: RequestInit): Promise<T> => {
    const res = await fetch(`/api${endpoint}`, options);
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    return res.json();
};