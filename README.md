# AI News WeChat Mini Program

A WeChat Mini Program that fetches AI news daily and generates two-person audio discussions using Zhipu GLM.

## Features

- **News Page**: Browse AI news with importance scoring, pull-to-refresh, and detail view
- **Audio Page**: Generate audio discussions from selected news, with full playback controls
- **Settings Page**: Configure auto-fetch schedule, importance threshold, theme, and language

## Tech Stack

- **Backend**: Python FastAPI
- **Database**: MySQL 8.0
- **AI Services**: Zhipu GLM-4 (text) + GLM-TTS (audio)
- **News Source**: NewsAPI.org
- **Frontend**: WeChat Mini Program

## Quick Start

### 1. Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop)
- [WeChat DevTools](https://developers.weixin.qq.com/miniprogram/dev/devtools/download.html)

### 2. Get API Keys

| Service | Get From |
|---------|----------|
| Zhipu GLM | https://open.bigmodel.cn |
| NewsAPI | https://newsapi.org/register |
| WeChat MP | WeChat MP Console |

### 3. Configure Environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 4. Start Services

**Option A: Double-click**
- Double-click `start.command` (macOS)

**Option B: Command line**
```bash
docker-compose -f docker/docker-compose.yml up --build -d
```

### 5. Test Mini Program

1. Open WeChat DevTools
2. Import the `miniprogram` folder
3. Update `appid` in `project.config.json`
4. Enable "不校验合法域名" in DevTools settings
5. The app connects to `http://localhost:8000`

## Project Structure

```
News/
├── backend/                 # FastAPI Backend
│   ├── app/
│   │   ├── api/v1/         # API endpoints
│   │   ├── models/         # SQLAlchemy models
│   │   ├── schemas/        # Pydantic schemas
│   │   ├── services/       # Business logic
│   │   ├── main.py         # App entry
│   │   └── config.py       # Configuration
│   ├── storage/audio/      # Generated audio files
│   ├── Dockerfile
│   └── requirements.txt
│
├── miniprogram/            # WeChat Mini Program
│   ├── pages/
│   │   ├── news/          # News listing page
│   │   ├── audio/         # Audio listing page
│   │   └── settings/      # Settings page
│   ├── services/          # API service layer
│   ├── utils/             # Utilities
│   └── app.js             # App entry
│
├── docker/
│   ├── docker-compose.yml
│   └── mysql/init.sql
│
├── start.command          # One-click start (macOS)
└── .env.example           # Environment template
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/auth/login` | WeChat login |
| GET | `/api/v1/news` | List news |
| POST | `/api/v1/news/fetch` | Manual fetch |
| GET | `/api/v1/audio` | List audio |
| POST | `/api/v1/audio` | Create audio |
| GET | `/api/v1/settings` | Get settings |
| PUT | `/api/v1/settings` | Update settings |

Full API docs: http://localhost:8000/docs

## Commands

```bash
# Start services
docker-compose -f docker/docker-compose.yml up -d

# View logs
docker-compose -f docker/docker-compose.yml logs -f

# Stop services
docker-compose -f docker/docker-compose.yml down

# Rebuild after code changes
docker-compose -f docker/docker-compose.yml up --build -d
```

## Production Deployment

1. Deploy backend to server with HTTPS
2. Update `BASE_URL` in `miniprogram/utils/constants.js`
3. Add domain to WeChat MP whitelist
4. Submit Mini Program for review

## License

MIT
