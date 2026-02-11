const authService = require('./services/authService');
const settingsService = require('./services/settingsService');

App({
  globalData: {
    userInfo: null,
    settings: null,
    theme: 'light'
  },

  onLaunch() {
    // Initialize theme
    this.initTheme();

    // Auto login if not logged in
    if (!authService.isLoggedIn()) {
      this.login();
    } else {
      this.globalData.userInfo = wx.getStorageSync('user_info');
      this.loadSettings();
    }

    // Listen for theme changes
    wx.onThemeChange((result) => {
      if (this.globalData.settings?.theme === 'system') {
        this.globalData.theme = result.theme;
        this.applyTheme(result.theme);
      }
    });
  },

  async login() {
    try {
      // Use dev login for testing, switch to authService.login() for production
      const data = await authService.devLogin();
      this.globalData.userInfo = data.user;
      this.loadSettings();
    } catch (err) {
      console.error('Login failed:', err);
      wx.showToast({
        title: 'Login failed',
        icon: 'none'
      });
    }
  },

  async loadSettings() {
    try {
      const settings = await settingsService.getSettings();
      this.globalData.settings = settings;
      settingsService.saveLocalSettings(settings);

      // Apply theme
      const theme = settingsService.getTheme();
      this.globalData.theme = theme;
      this.applyTheme(theme);
    } catch (err) {
      console.error('Failed to load settings:', err);
    }
  },

  initTheme() {
    const theme = settingsService.getTheme();
    this.globalData.theme = theme;
    this.applyTheme(theme);
  },

  applyTheme(theme) {
    // Update navigation bar
    const bgColor = theme === 'dark' ? '#000000' : '#FFFFFF';
    const textStyle = theme === 'dark' ? 'white' : 'black';

    wx.setNavigationBarColor({
      frontColor: theme === 'dark' ? '#FFFFFF' : '#000000',
      backgroundColor: bgColor
    });

    // Update tab bar
    wx.setTabBarStyle({
      backgroundColor: theme === 'dark' ? '#1C1C1E' : '#FFFFFF',
      borderStyle: theme === 'dark' ? 'black' : 'white',
      color: theme === 'dark' ? '#98989D' : '#86868B',
      selectedColor: theme === 'dark' ? '#0A84FF' : '#007AFF'
    });
  }
});
