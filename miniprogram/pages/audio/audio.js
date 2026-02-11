const audioService = require('../../services/audioService');
const newsService = require('../../services/newsService');
const { formatDuration, formatRelativeTime } = require('../../utils/format');
const { PLAYBACK_SPEEDS } = require('../../utils/constants');

const app = getApp();

Page({
  data: {
    audioList: [],
    loading: false,
    showSelector: false,
    showPlayer: false,
    currentAudio: null,
    isPlaying: false,
    currentTime: 0,
    duration: 0,
    progress: 0,
    playbackRate: 1,
    currentTimeFormatted: '0:00',
    durationFormatted: '0:00',
    availableNews: [],
    selectedNewsIds: [],
    allSelected: false,
    languageOptions: [
      { value: 'zh', label: 'Chinese' },
      { value: 'en', label: 'English' },
      { value: 'bilingual', label: 'Bilingual' }
    ],
    selectedLanguage: { value: 'zh', label: 'Chinese' },
    theme: 'light'
  },

  audioContext: null,
  speedIndex: 2, // Index of 1.0 in PLAYBACK_SPEEDS

  onLoad() {
    this.setData({ theme: app.globalData.theme });
    this.initAudioContext();
    this.fetchAudioList();
  },

  onShow() {
    this.setData({ theme: app.globalData.theme });
  },

  onUnload() {
    if (this.audioContext) {
      this.audioContext.destroy();
    }
  },

  onPullDownRefresh() {
    this.fetchAudioList();
  },

  initAudioContext() {
    this.audioContext = wx.createInnerAudioContext();

    this.audioContext.onPlay(() => {
      this.setData({ isPlaying: true });
    });

    this.audioContext.onPause(() => {
      this.setData({ isPlaying: false });
    });

    this.audioContext.onStop(() => {
      this.setData({ isPlaying: false, currentTime: 0, progress: 0 });
    });

    this.audioContext.onEnded(() => {
      this.setData({ isPlaying: false, currentTime: 0, progress: 0 });
    });

    this.audioContext.onTimeUpdate(() => {
      const currentTime = this.audioContext.currentTime;
      const duration = this.audioContext.duration;

      if (duration > 0) {
        this.setData({
          currentTime,
          duration,
          progress: (currentTime / duration) * 100,
          currentTimeFormatted: formatDuration(currentTime),
          durationFormatted: formatDuration(duration)
        });
      }
    });

    this.audioContext.onError((err) => {
      console.error('Audio error:', err);
      wx.showToast({ title: 'Playback error', icon: 'none' });
    });
  },

  async fetchAudioList() {
    this.setData({ loading: true });

    try {
      const res = await audioService.getAudioList({ limit: 50 });

      const audioList = res.items.map(item => ({
        ...item,
        durationFormatted: formatDuration(item.duration),
        dateFormatted: formatRelativeTime(item.created_at)
      }));

      this.setData({ audioList });
    } catch (err) {
      wx.showToast({ title: 'Failed to load audio', icon: 'none' });
    } finally {
      this.setData({ loading: false });
      wx.stopPullDownRefresh();
    }
  },

  async onAddClick() {
    // Fetch available news
    try {
      const res = await newsService.getNewsList({ limit: 50 });
      this.setData({
        availableNews: res.items,
        selectedNewsIds: [],
        allSelected: false,
        showSelector: true
      });
    } catch (err) {
      wx.showToast({ title: 'Failed to load news', icon: 'none' });
    }
  },

  onSelectorClose() {
    this.setData({ showSelector: false });
  },

  onNewsSelect(e) {
    const newsId = e.currentTarget.dataset.id;
    let { selectedNewsIds } = this.data;

    if (selectedNewsIds.includes(newsId)) {
      selectedNewsIds = selectedNewsIds.filter(id => id !== newsId);
    } else {
      if (selectedNewsIds.length >= 10) {
        wx.showToast({ title: 'Max 10 articles', icon: 'none' });
        return;
      }
      selectedNewsIds = [...selectedNewsIds, newsId];
    }

    this.setData({
      selectedNewsIds,
      allSelected: selectedNewsIds.length === this.data.availableNews.length
    });
  },

  onSelectAll() {
    const { allSelected, availableNews } = this.data;

    if (allSelected) {
      this.setData({ selectedNewsIds: [], allSelected: false });
    } else {
      const ids = availableNews.slice(0, 10).map(n => n.id);
      this.setData({ selectedNewsIds: ids, allSelected: ids.length === availableNews.length });
    }
  },

  onLanguageSelect(e) {
    const index = e.detail.value;
    this.setData({
      selectedLanguage: this.data.languageOptions[index]
    });
  },

  async onCreateAudio() {
    const { selectedNewsIds, selectedLanguage } = this.data;

    if (selectedNewsIds.length === 0) {
      wx.showToast({ title: 'Select at least one article', icon: 'none' });
      return;
    }

    wx.showLoading({ title: 'Creating...' });

    try {
      await audioService.createAudio(selectedNewsIds, selectedLanguage.value);
      wx.showToast({ title: 'Audio generation started', icon: 'success' });
      this.setData({ showSelector: false });
      this.fetchAudioList();
    } catch (err) {
      wx.showToast({ title: err.message || 'Failed to create', icon: 'none' });
    } finally {
      wx.hideLoading();
    }
  },

  async onAudioClick(e) {
    const audioId = e.currentTarget.dataset.id;
    const audio = this.data.audioList.find(a => a.id === audioId);

    if (!audio) return;

    if (audio.status !== 'completed') {
      if (audio.status === 'processing') {
        wx.showToast({ title: 'Still generating...', icon: 'none' });
      } else if (audio.status === 'failed') {
        wx.showToast({ title: 'Generation failed', icon: 'none' });
      }
      return;
    }

    // If same audio, toggle play/pause
    if (this.data.currentAudio && this.data.currentAudio.id === audioId) {
      this.onPlayPause();
      return;
    }

    // Load new audio
    const streamUrl = audioService.getAudioStreamUrl(audioId);
    this.audioContext.src = streamUrl;

    this.setData({
      currentAudio: audio,
      showPlayer: true,
      isPlaying: false,
      currentTime: 0,
      progress: 0
    });

    this.audioContext.play();
  },

  onPlayPause() {
    if (this.data.isPlaying) {
      this.audioContext.pause();
    } else {
      this.audioContext.play();
    }
  },

  onSeek(e) {
    const progress = e.detail.value;
    const seekTime = (progress / 100) * this.data.duration;
    this.audioContext.seek(seekTime);
  },

  onSkipBackward() {
    const newTime = Math.max(0, this.audioContext.currentTime - 15);
    this.audioContext.seek(newTime);
  },

  onSkipForward() {
    const newTime = Math.min(this.data.duration, this.audioContext.currentTime + 15);
    this.audioContext.seek(newTime);
  },

  onSpeedChange() {
    this.speedIndex = (this.speedIndex + 1) % PLAYBACK_SPEEDS.length;
    const newRate = PLAYBACK_SPEEDS[this.speedIndex];
    this.audioContext.playbackRate = newRate;
    this.setData({ playbackRate: newRate });
  },

  async onDeleteAudio(e) {
    const audioId = e.currentTarget.dataset.id;

    wx.showModal({
      title: 'Delete Audio',
      content: 'Are you sure you want to delete this audio?',
      success: async (res) => {
        if (res.confirm) {
          try {
            await audioService.deleteAudio(audioId);

            // Stop if currently playing
            if (this.data.currentAudio && this.data.currentAudio.id === audioId) {
              this.audioContext.stop();
              this.setData({ currentAudio: null, showPlayer: false });
            }

            this.fetchAudioList();
            wx.showToast({ title: 'Deleted', icon: 'success' });
          } catch (err) {
            wx.showToast({ title: 'Delete failed', icon: 'none' });
          }
        }
      }
    });
  }
});
