-- Migration: Add scraping retry fields to news table
-- Date: 2026-03-08
-- Purpose: Enable background retry for failed article content scraping

-- Add scraping retry fields
ALTER TABLE news ADD COLUMN scraping_retry_count INTEGER DEFAULT 0;
ALTER TABLE news ADD COLUMN scraping_last_error VARCHAR(512);
ALTER TABLE news ADD COLUMN scraping_next_retry_at DATETIME;

-- Add comment for documentation
-- scraping_retry_count: Number of times scraping has been retried
-- scraping_last_error: Last error message from scraping attempt
-- scraping_next_retry_at: Timestamp for next retry attempt
