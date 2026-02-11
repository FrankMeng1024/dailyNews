const { get, post } = require('../utils/request');
const { STORAGE_KEYS } = require('../utils/constants');

/**
 * WeChat login and get token
 */
const login = () => {
  return new Promise((resolve, reject) => {
    wx.login({
      success: async (res) => {
        if (res.code) {
          try {
            const data = await post('/auth/login', { code: res.code });
            // Save token and user info
            wx.setStorageSync(STORAGE_KEYS.TOKEN, data.access_token);
            wx.setStorageSync(STORAGE_KEYS.USER, data.user);
            resolve(data);
          } catch (err) {
            reject(err);
          }
        } else {
          reject({ message: 'WeChat login failed' });
        }
      },
      fail: (err) => {
        reject({ message: err.errMsg });
      }
    });
  });
};

/**
 * Development login (bypasses WeChat)
 */
const devLogin = async () => {
  const data = await post('/auth/dev-login');
  wx.setStorageSync(STORAGE_KEYS.TOKEN, data.access_token);
  wx.setStorageSync(STORAGE_KEYS.USER, data.user);
  return data;
};

/**
 * Get current user info
 */
const getCurrentUser = () => {
  return get('/auth/me');
};

/**
 * Check if user is logged in
 */
const isLoggedIn = () => {
  return !!wx.getStorageSync(STORAGE_KEYS.TOKEN);
};

/**
 * Logout
 */
const logout = () => {
  wx.removeStorageSync(STORAGE_KEYS.TOKEN);
  wx.removeStorageSync(STORAGE_KEYS.USER);
};

module.exports = {
  login,
  devLogin,
  getCurrentUser,
  isLoggedIn,
  logout
};
