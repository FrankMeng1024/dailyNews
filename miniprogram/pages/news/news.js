const newsService = require('../../services/newsService');
const { formatRelativeTime, getImportanceLabel, getImportanceColor } = require('../../utils/format');

const app = getApp();

Page({
  data: {
    newsList: [],
    loading: false,
    refreshing: false,
    page: 1,
    hasMore: true,
    selectedNews: null,
    showDetail: false,
    theme: 'light',
    // Fetch progress state
    fetchTaskId: null,
    fetchStatus: null,
    fetchProgress: ''
  },

  onLoad() {
    this.setData({ theme: app.globalData.theme });
    this.fetchNews();
  },

  onShow() {
    this.setData({ theme: app.globalData.theme });
  },

  onPullDownRefresh() {
    this.setData({ page: 1, hasMore: true });
    this.fetchNews(true);
  },

  onReachBottom() {
    if (this.data.hasMore && !this.data.loading) {
      this.loadMore();
    }
  },

  async fetchNews(isRefresh = false) {
    if (this.data.loading) return;

    this.setData({ loading: true, refreshing: isRefresh });

    try {
      const res = await newsService.getNewsList({
        page: 1,
        limit: 20
      });

      const newsList = res.items.map(item => ({
        ...item,
        relativeTime: formatRelativeTime(item.published_at),
        importanceLabel: getImportanceLabel(item.final_score),
        importanceColor: getImportanceColor(item.final_score)
      }));

      this.setData({
        newsList,
        page: 1,
        hasMore: res.page < res.total_pages
      });
    } catch (err) {
      wx.showToast({ title: 'Failed to load news', icon: 'none' });
    } finally {
      this.setData({ loading: false, refreshing: false });
      wx.stopPullDownRefresh();
    }
  },

  async loadMore() {
    const nextPage = this.data.page + 1;
    this.setData({ loading: true });

    try {
      const res = await newsService.getNewsList({
        page: nextPage,
        limit: 20
      });

      const newItems = res.items.map(item => ({
        ...item,
        relativeTime: formatRelativeTime(item.published_at),
        importanceLabel: getImportanceLabel(item.final_score),
        importanceColor: getImportanceColor(item.final_score)
      }));

      this.setData({
        newsList: [...this.data.newsList, ...newItems],
        page: nextPage,
        hasMore: nextPage < res.total_pages
      });
    } catch (err) {
      wx.showToast({ title: 'Failed to load more', icon: 'none' });
    } finally {
      this.setData({ loading: false });
    }
  },

  async onManualFetch() {
    if (this.data.refreshing || this.data.fetchTaskId) return;

    this.setData({
      refreshing: true,
      fetchStatus: 'starting',
      fetchProgress: 'Starting fetch...'
    });

    try {
      const res = await newsService.fetchNews(false);

      if (res.task_id) {
        this.setData({ fetchTaskId: res.task_id });
        this.pollFetchStatus(res.task_id);
      } else {
        wx.showToast({
          title: res.message || 'Fetch started',
          icon: 'none'
        });
        this.setData({ refreshing: false, fetchStatus: null, fetchProgress: '' });
      }
    } catch (err) {
      wx.showToast({ title: err.message || 'Fetch failed', icon: 'none' });
      this.setData({ refreshing: false, fetchStatus: null, fetchProgress: '' });
    }
  },

  async pollFetchStatus(taskId) {
    try {
      const status = await newsService.getFetchStatus(taskId);

      this.setData({
        fetchStatus: status.status,
        fetchProgress: status.progress || status.status
      });

      if (status.status === 'completed') {
        const msg = `Fetched ${status.saved_count || 0} new, ${status.skipped_count || 0} skipped`;
        wx.showToast({ title: msg, icon: 'success', duration: 2000 });

        this.setData({
          refreshing: false,
          fetchTaskId: null,
          fetchStatus: null,
          fetchProgress: ''
        });

        if (status.saved_count > 0) {
          this.fetchNews(true);
        }
      } else if (status.status === 'failed') {
        wx.showToast({ title: status.error || 'Fetch failed', icon: 'none' });
        this.setData({
          refreshing: false,
          fetchTaskId: null,
          fetchStatus: null,
          fetchProgress: ''
        });
      } else {
        setTimeout(() => this.pollFetchStatus(taskId), 2000);
      }
    } catch (err) {
      wx.showToast({ title: 'Status check failed', icon: 'none' });
      this.setData({
        refreshing: false,
        fetchTaskId: null,
        fetchStatus: null,
        fetchProgress: ''
      });
    }
  },

  onNewsClick(e) {
    const newsId = e.currentTarget.dataset.id;
    const news = this.data.newsList.find(n => n.id === newsId);

    if (news) {
      this.setData({
        selectedNews: news,
        showDetail: true
      });
    }
  },

  onDetailClose() {
    this.setData({
      showDetail: false,
      selectedNews: null
    });
  },

  onOpenSource() {
    const url = this.data.selectedNews?.source_url;
    if (url) {
      wx.setClipboardData({
        data: url,
        success: () => {
          wx.showToast({ title: 'Link copied', icon: 'success' });
        }
      });
    }
  }
});
