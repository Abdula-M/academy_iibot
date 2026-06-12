export interface User {
    telegram_id: number;
    username: string;
    platform: string;
    last_question: string;
    last_time: string;
    msg_count: number;
}

export interface Message {
    question: string;
    answer: string;
    created_at: string;
}

export interface VacancyApplication {
    id: number;
    username: string;
    platform: string;
    application_text: string;
    created_at: string;
    is_read: boolean;
}

export interface Stats {
    total_users: number;
    today_users: number;
    today_messages: number;
    unread_applications: number;
}