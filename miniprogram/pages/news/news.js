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
    activeTab: 'original',  // 'original' | 'summary' | 'link'
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
    if (this.data.fetchStatus) return;

    this.setData({ fetchStatus: '获取' });

    try {
      const res = await newsService.fetchNews(false);

      if (res.task_id) {
        this.setData({ fetchTaskId: res.task_id });
        this.pollFetchStatus(res.task_id);
      } else {
        this.setData({ fetchStatus: null, fetchTaskId: null });
      }
    } catch (err) {
      this.setData({ fetchStatus: null, fetchTaskId: null });
    }
  },

  async pollFetchStatus(taskId) {
    try {
      const status = await newsService.getFetchStatus(taskId);

      // Update status text based on progress
      if (status.status === 'running') {
        const progress = status.progress || '';
        if (progress.includes('GLM') || progress.includes('Processing')) {
          this.setData({ fetchStatus: '提炼' });
        } else {
          this.setData({ fetchStatus: '获取' });
        }
      }

      if (status.status === 'completed') {
        this.setData({
          fetchStatus: null,
          fetchTaskId: null
        });

        if (status.saved_count > 0) {
          this.fetchNews(true);
        }
      } else if (status.status === 'failed') {
        this.setData({
          fetchStatus: null,
          fetchTaskId: null
        });
      } else {
        setTimeout(() => this.pollFetchStatus(taskId), 2000);
      }
    } catch (err) {
      this.setData({
        fetchStatus: null,
        fetchTaskId: null
      });
    }
  },

  onNewsClick(e) {
    const newsId = e.currentTarget.dataset.id;
    const news = this.data.newsList.find(n => n.id === newsId);

    if (news) {
      this.setData({
        selectedNews: news,
        showDetail: true,
        activeTab: 'original'  // Default to original content
      });
    }
  },

  onDetailClose() {
    this.setData({
      showDetail: false,
      selectedNews: null,
      activeTab: 'original'
    });
  },

  async onToggleContent(e) {
    const type = e.currentTarget.dataset.type;
    this.setData({ activeTab: type });

    // When switching to summary tab, check if content needs refresh
    if (type === 'summary' && this.data.selectedNews) {
      const news = this.data.selectedNews;
      // If no content yet, start polling for it
      if (!news.content) {
        this.pollRefineStatus(news.id);
      }
    }
  },

  async pollRefineStatus(newsId) {
    if (this._refinePolling) return;
    this._refinePolling = true;

    try {
      const status = await newsService.getRefineStatus(newsId);

      if (status.status === 'completed' && status.content) {
        // Update selectedNews with new content
        const updatedNews = { ...this.data.selectedNews, content: status.content };
        this.setData({ selectedNews: updatedNews });

        // Also update in newsList
        const newsList = this.data.newsList.map(n =>
          n.id === newsId ? { ...n, content: status.content } : n
        );
        this.setData({ newsList });
        this._refinePolling = false;
      } else if (status.status === 'processing') {
        // Still processing, poll again
        setTimeout(() => {
          this._refinePolling = false;
          this.pollRefineStatus(newsId);
        }, 2000);
      } else {
        this._refinePolling = false;
      }
    } catch (err) {
      this._refinePolling = false;
    }
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
