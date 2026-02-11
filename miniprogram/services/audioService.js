const { get, post, del } = require('../utils/request');
const { BASE_URL, STORAGE_KEYS } = require('../utils/constants');

/**
 * Get audio list with pagination
 */
const getAudioList = (params = {}) => {
  const { page = 1, limit = 20, status } = params;

  let url = `/audio?page=${page}&limit=${limit}`;
  if (status) url += `&status=${status}`;

  return get(url);
};

/**
 * Get audio detail with associated news
 */
const getAudioDetail = (audioId) => {
  return get(`/audio/${audioId}`);
};

/**
 * Create new audio from selected news
 */
const createAudio = (newsIds, language = 'zh') => {
  return post('/audio', {
    news_ids: newsIds,
    language: language
  });
};

/**
 * Check audio generation status
 */
const getAudioStatus = (audioId) => {
  return get(`/audio/${audioId}/status`);
};

/**
 * Get audio stream URL
 */
const getAudioStreamUrl = (audioId) => {
  const token = wx.getStorageSync(STORAGE_KEYS.TOKEN);
  return `${BASE_URL}/audio/${audioId}/stream?token=${token}`;
};

/**
 * Delete audio
 */
const deleteAudio = (audioId) => {
  return del(`/audio/${audioId}`);
};

module.exports = {
  getAudioList,
  getAudioDetail,
  createAudio,
  getAudioStatus,
  getAudioStreamUrl,
  deleteAudio
};
