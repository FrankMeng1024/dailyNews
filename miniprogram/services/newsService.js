const { get, post } = require('../utils/request');

/**
 * Get news list with pagination
 */
const getNewsList = (params = {}) => {
  const { page = 1, limit = 20, minScore, dateFrom, dateTo } = params;

  let url = `/news?page=${page}&limit=${limit}`;
  if (minScore !== undefined) url += `&min_score=${minScore}`;
  if (dateFrom) url += `&date_from=${dateFrom}`;
  if (dateTo) url += `&date_to=${dateTo}`;

  return get(url);
};

/**
 * Get today's news
 */
const getTodayNews = (params = {}) => {
  const { minScore, limit = 50 } = params;

  let url = `/news/today?limit=${limit}`;
  if (minScore !== undefined) url += `&min_score=${minScore}`;

  return get(url);
};

/**
 * Get news detail by ID
 */
const getNewsDetail = (newsId) => {
  return get(`/news/${newsId}`);
};

/**
 * Manually trigger news fetch (returns task_id for polling)
 */
const fetchNews = (force = false) => {
  return post(`/news/fetch?force=${force}`);
};

/**
 * Get fetch task status by task_id
 */
const getFetchStatus = (taskId) => {
  return get(`/news/fetch/status/${taskId}`);
};

module.exports = {
  getNewsList,
  getTodayNews,
  getNewsDetail,
  fetchNews,
  getFetchStatus
};
