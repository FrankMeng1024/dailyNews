const settingsService = require('../../services/settingsService');

const app = getApp();

Page({
  data: {
    hours: Array.from({ length: 24 }, (_, i) => i),
    selectedHours: ['8', '12', '18'],
    thresholdPercent: 50,
    selectedTheme: 'system',
    selectedLanguage: 'zh',
    saving: false,
    theme: 'light',
    themeOptions: [
      { value: 'light', label: 'Light', icon: 'sun' },
      { value: 'dark', label: 'Dark', icon: 'moon' },
      { value: 'system', label: 'System', icon: 'auto' }
    ],
    languageOptions: [
      { value: 'zh', label: '中文', desc: '新闻摘要和音频使用中文' },
      { value: 'en', label: 'English', desc: 'News and audio in English' },
      { value: 'bilingual', label: '双语', desc: '中英双语内容' }
    ]
  },

  onLoad() {
    this.setData({ theme: app.globalData.theme });
    this.loadSettings();
  },

  onShow() {
    this.setData({ theme: app.globalData.theme });
  },

  async loadSettings() {
    try {
      const settings = await settingsService.getSettings();

      this.setData({
        selectedHours: settings.fetch_hours || ['8', '12', '18'],
        thresholdPercent: Math.round((settings.importance_threshold || 0.5) * 100),
        selectedTheme: settings.theme || 'system',
        selectedLanguage: settings.audio_language || 'zh'
      });
    } catch (err) {
      console.error('Failed to load settings:', err);
      // Use local settings as fallback
      const localSettings = settingsService.getLocalSettings();
      if (localSettings) {
        this.setData({
          selectedHours: localSettings.fetch_hours || ['8', '12', '18'],
          thresholdPercent: Math.round((localSettings.importance_threshold || 0.5) * 100),
          selectedTheme: localSettings.theme || 'system',
          selectedLanguage: localSettings.audio_language || 'zh'
        });
      }
    }
  },

  onHourToggle(e) {
    const hour = e.currentTarget.dataset.hour.toString();
    let { selectedHours } = this.data;

    if (selectedHours.includes(hour)) {
      // Don't allow removing all hours
      if (selectedHours.length <= 1) {
        wx.showToast({ title: 'At least one hour required', icon: 'none' });
        return;
      }
      selectedHours = selectedHours.filter(h => h !== hour);
    } else {
      selectedHours = [...selectedHours, hour].sort((a, b) => parseInt(a) - parseInt(b));
    }

    this.setData({ selectedHours });
  },

  onThresholdChange(e) {
    this.setData({ thresholdPercent: e.detail.value });
  },

  onThemeChange(e) {
    const theme = e.currentTarget.dataset.theme;
    this.setData({ selectedTheme: theme });

    // Preview theme change
    const actualTheme = theme === 'system' ? settingsService.getTheme() : theme;
    this.setData({ theme: actualTheme });
    app.applyTheme(actualTheme);
  },

  onLanguageChange(e) {
    const language = e.currentTarget.dataset.language;
    this.setData({ selectedLanguage: language });
  },

  async onSave() {
    if (this.data.saving) return;

    this.setData({ saving: true });

    const settings = {
      fetch_hours: this.data.selectedHours,
      importance_threshold: this.data.thresholdPercent / 100,
      theme: this.data.selectedTheme,
      audio_language: this.data.selectedLanguage
    };

    try {
      await settingsService.updateSettings(settings);
      settingsService.saveLocalSettings(settings);

      // Update global settings
      app.globalData.settings = settings;

      // Apply theme
      const actualTheme = settings.theme === 'system'
        ? (wx.getSystemInfoSync().theme || 'light')
        : settings.theme;
      app.globalData.theme = actualTheme;
      app.applyTheme(actualTheme);

      wx.showToast({ title: 'Settings saved', icon: 'success' });
    } catch (err) {
      wx.showToast({ title: 'Failed to save', icon: 'none' });
    } finally {
      this.setData({ saving: false });
    }
  },

  onFeedback() {
    wx.setClipboardData({
      data: 'feedback@ainews.app',
      success: () => {
        wx.showToast({ title: 'Email copied', icon: 'success' });
      }
    });
  }
});
