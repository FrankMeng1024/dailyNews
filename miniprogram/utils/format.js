const { STORAGE_KEYS } = require('./constants');

/**
 * Format date to time string (HH:MM:SS in Beijing time)
 * Backend already returns Beijing time in format "YYYY-MM-DD HH:MM:SS"
 */
const formatRelativeTime = (dateString) => {
  if (!dateString) return '';

  // Backend returns Beijing time as "YYYY-MM-DD HH:MM:SS"
  // Extract the time part directly
  const timePart = dateString.split(' ')[1];
  if (timePart) {
    return timePart;  // Returns "14:30:25"
  }

  // Fallback for ISO format
  const date = new Date(dateString);
  if (isNaN(date.getTime())) return '';

  const hours = date.getHours().toString().padStart(2, '0');
  const minutes = date.getMinutes().toString().padStart(2, '0');
  const seconds = date.getSeconds().toString().padStart(2, '0');
  return `${hours}:${minutes}:${seconds}`;
};

/**
 * Format duration in seconds to MM:SS
 */
const formatDuration = (seconds) => {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
};

/**
 * Format file size to human readable
 */
const formatFileSize = (bytes) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

/**
 * Truncate text with ellipsis
 */
const truncateText = (text, maxLength) => {
  if (!text || text.length <= maxLength) return text;
  return text.substring(0, maxLength) + '...';
};

/**
 * Get importance level label
 */
const getImportanceLabel = (score) => {
  if (score >= 0.8) return 'Hot';
  if (score >= 0.6) return 'Important';
  if (score >= 0.4) return 'Normal';
  return 'Low';
};

/**
 * Get importance level color
 */
const getImportanceColor = (score) => {
  if (score >= 0.8) return '#FF3B30';
  if (score >= 0.6) return '#FF9500';
  if (score >= 0.4) return '#34C759';
  return '#8E8E93';
};

module.exports = {
  formatRelativeTime,
  formatDuration,
  formatFileSize,
  truncateText,
  getImportanceLabel,
  getImportanceColor
};
