CREATE TABLE IF NOT EXISTS retry_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger_type VARCHAR(50),
    processed_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
