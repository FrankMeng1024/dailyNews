const { get, put } = require('../utils/request');
const { STORAGE_KEYS } = require('../utils/constants');

/**
 * Get user settings
 */
const getSettings = () => {
  return get('/settings');
};

/**
 * Update user settings
 */
const updateSettings = (settings) => {
  return put('/settings', settings);
};

/**
 * Get available fetch hours
 */
const getFetchHours = () => {
  return get('/settings/fetch-hours');
};

/**
 * Save settings to local storage
 */
const saveLocalSettings = (settings) => {
  wx.setStorageSync(STORAGE_KEYS.SETTINGS, settings);
};

/**
 * Get settings from local storage
 */
const getLocalSettings = () => {
  return wx.getStorageSync(STORAGE_KEYS.SETTINGS) || {};
};

/**
 * Get current theme
 */
const getTheme = () => {
  const settings = getLocalSettings();
  if (settings.theme === 'system') {
    const systemInfo = wx.getSystemInfoSync();
    return systemInfo.theme || 'light';
  }
  return settings.theme || 'light';
};

module.exports = {
  getSettings,
  updateSettings,
  getFetchHours,
  saveLocalSettings,
  getLocalSettings,
  getTheme
};
