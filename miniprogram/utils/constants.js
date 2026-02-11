// API base URL - change for production
const BASE_URL = 'https://bell-aggregate-aid-safe.trycloudflare.com/api/v1';

// Storage keys
const STORAGE_KEYS = {
  TOKEN: 'auth_token',
  USER: 'user_info',
  SETTINGS: 'user_settings',
  THEME: 'app_theme'
};

// Audio playback speeds
const PLAYBACK_SPEEDS = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0];

// Theme colors
const THEMES = {
  light: {
    primary: '#007AFF',
    background: '#F5F5F7',
    card: '#FFFFFF',
    text: '#1D1D1F',
    textSecondary: '#86868B',
    border: '#E5E5EA'
  },
  dark: {
    primary: '#0A84FF',
    background: '#000000',
    card: '#1C1C1E',
    text: '#FFFFFF',
    textSecondary: '#98989D',
    border: '#38383A'
  }
};

module.exports = {
  BASE_URL,
  STORAGE_KEYS,
  PLAYBACK_SPEEDS,
  THEMES
};
