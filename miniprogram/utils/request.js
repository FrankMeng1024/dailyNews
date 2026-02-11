const { BASE_URL, STORAGE_KEYS } = require('./constants');

/**
 * HTTP request wrapper for WeChat Mini Program
 */
const request = (options) => {
  return new Promise((resolve, reject) => {
    const token = wx.getStorageSync(STORAGE_KEYS.TOKEN);

    const header = {
      'Content-Type': 'application/json',
      ...options.header
    };

    if (token) {
      header['Authorization'] = `Bearer ${token}`;
    }

    wx.request({
      url: `${BASE_URL}${options.url}`,
      method: options.method || 'GET',
      data: options.data,
      header: header,
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data);
        } else if (res.statusCode === 401) {
          // Token expired, clear and redirect to login
          wx.removeStorageSync(STORAGE_KEYS.TOKEN);
          wx.removeStorageSync(STORAGE_KEYS.USER);
          reject({ code: 401, message: 'Unauthorized' });
        } else {
          reject({
            code: res.statusCode,
            message: res.data?.detail || res.data?.message || 'Request failed'
          });
        }
      },
      fail: (err) => {
        reject({
          code: -1,
          message: err.errMsg || 'Network error'
        });
      }
    });
  });
};

// Convenience methods
const get = (url, data) => request({ url, method: 'GET', data });
const post = (url, data) => request({ url, method: 'POST', data });
const put = (url, data) => request({ url, method: 'PUT', data });
const del = (url, data) => request({ url, method: 'DELETE', data });

module.exports = {
  request,
  get,
  post,
  put,
  del
};
