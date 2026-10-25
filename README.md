# TokenIQ — Live Crypto Market Dashboard & Trading Architecture

TokenIQ is an institutional-grade cryptocurrency market intelligence terminal and trading infrastructure built for the TokenIQ hackathon project.

The project is structured with a decoupled, high-performance **Frontend/Backend architecture**:
- **Backend (Python / FastAPI)**: Interfaces directly with Delta Exchange India public market-data REST endpoints and WebSockets, providing normalization, rate-limit caching, multi-chunk candle retrieval, and client WebSocket multiplexing.
- **Frontend (React 19 / TypeScript / Vite / Tailwind CSS)**: TradingView-inspired dark terminal featuring Canvas-based candlestick charting with Lightweight Charts, order-book spreads, market breadth metrics, and dynamic date-range controls.

---

## 📁 Repository Structure

```
TokenIQ/
├── frontend/                     # React + TypeScript + Vite frontend
│   ├── src/
│   │   ├── components/           # UI components (Chart, Table, Details, Sidebar, etc.)
│   │   ├── pages/                # Page layouts (DashboardPage.tsx)
│   │   ├── services/             # Backend API & WebSocket clients
│   │   │   ├── api.ts            # FastAPI REST client (/api/v1/market/*)
│   │   │   └── marketSocket.ts   # FastAPI WebSocket client (/api/v1/market/ws)
│   │   ├── hooks/                # React hooks (useMarketData, useMarketWebSocket)
│   │   ├── types/                # TypeScript interfaces (market.ts)
│   │   ├── App.tsx               # Root component mounting DashboardPage
│   │   ├── index.css             # Tailwind directives & terminal styling
│   │   └── main.tsx              # React DOM entry point
│   ├── package.json              # Frontend dependencies and scripts
│   └── vite.config.ts            # Vite config with /api and WebSocket proxy to backend
│
├── backend/                      # Python FastAPI market-data backend
│   ├── app/
│   │   ├── api/
│   │   │   └── routes/
│   │   │       └── market.py     # Endpoints: /tickers, /candles, /stats, /ws
│   │   ├── services/
│   │   │   ├── market_data.py    # Aggregation & TTL cache service
│   │   │   └── websocket_manager.py # Upstream Delta socket bridge & client broadcaster
│   │   ├── exchanges/
│   │   │   └── delta_client.py   # Public REST client for Delta Exchange India
│   │   ├── strategies/           # Inactive modular strategy interface for future phases
│   │   ├── risk/                 # Inactive modular risk management interface
│   │   ├── execution/            # Inactive modular order execution interface (read-only)
│   │   ├── core/
│   │   │   └── config.py         # Pydantic & environment settings
│   │   └── main.py               # FastAPI application entry point
│   ├── requirements.txt          # Python dependencies
│   ├── .env.example              # Environment variables template
│   └── .env                      # Local environment configuration (gitignored)
│
├── tests/                        # Backend test suite (pytest)
│   ├── conftest.py               # Pytest path and fixture configurations
│   ├── test_delta_client.py      # Unit tests for ticker parsing & resolutions
│   ├── test_market_routes.py     # Integration tests for FastAPI endpoints
│   └── test_websocket_manager.py # Unit tests for WebSocket client management
│
├── .gitignore                    # Comprehensive ignore rules
├── .env.example                  # Root environment variables template
└── README.md                     # Project documentation
```

---

## 🚀 Quickstart Guide

### 1. Prerequisites
- **Python**: 3.10+ (tested with 3.14)
- **Node.js**: v18+ (tested with v22)
- **npm**: v9+ (tested with v10)

---

### 2. Backend Setup & Run

1. Navigate to the `backend/` directory:
   ```bash
   cd backend
   ```

2. (Optional) Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   # Windows (PowerShell)
   .\.venv\Scripts\Activate.ps1
   # macOS / Linux
   source .venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Configure environment variables:
   ```bash
   cp .env.example .env
   ```

5. Start the FastAPI development server:
   ```bash
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
   ```
   * **API Docs**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
   * **Health Check**: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

---

### 3. Frontend Setup & Run

1. In a new terminal, navigate to the `frontend/` directory:
   ```bash
   cd frontend
   ```

2. Install dependencies:
   ```bash
   npm install
   ```

3. Start the Vite development server:
   ```bash
   npm run dev
   ```
   * Open the local URL displayed (typically [http://localhost:5173/](http://localhost:5173/)).
   * Vite automatically proxies `/api` and WebSocket `/api/v1/market/ws` requests directly to `http://localhost:8000`.

---

## 🧪 Running Tests

Run the backend test suite from the root directory:
```bash
python -m pytest tests -v
```

Run the frontend production build:
```bash
cd frontend
npm run build
```

---

## 📡 Backend API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/health` | System health check and upstream WebSocket status |
| `GET` | `/api/v1/market/status` | Market service operational state and active client count |
| `GET` | `/api/v1/market/tickers` | All 1,000+ normalized cryptocurrency products from Delta Exchange |
| `GET` | `/api/v1/market/ticker/{symbol}` | Real-time metrics for a specific symbol (e.g. `BTCUSD`, `ETHUSD`) |
| `GET` | `/api/v1/market/stats` | Aggregated market breadth (gainers/losers, turnover, BTC/ETH benchmarks) |
| `GET` | `/api/v1/market/candles` | Historical OHLCV bars (`symbol`, `resolution`, `start`, `end`) |
| `GET` | `/api/v1/market/products` | Exchange product contracts and metadata |
| `WS` | `/api/v1/market/ws` | Live WebSocket stream multiplexer for tickers and candlesticks |
| `GET` | `/api/v1/strategies` | List all available strategies, parameter schemas, and risk disclaimers |
| `GET` | `/api/v1/strategies/{strategy_id}` | Retrieve parameter schema and current configuration for a strategy |
| `POST` | `/api/v1/strategies/{strategy_id}/configure` | Update strategy parameters (e.g. `fast_period`, `slow_period`, RSI thresholds) |
| `POST` | `/api/v1/strategies/{strategy_id}/signal` | Calculate structured BUY/SELL/HOLD signal on completed candles (JSON body) |
| `GET` | `/api/v1/strategies/{strategy_id}/signal` | Convenience GET endpoint for signal generation (`?symbol=BTCUSD&resolution=1h`) |
| `GET` | `/api/v1/strategies/{strategy_id}/latest-signal` | Retrieve the latest cached signal for a specific symbol |
| `GET` | `/api/v1/strategies/signals/latest` | Retrieve all cached signals across strategies and symbols |
| `GET` | `/api/v1/backtesting/config-options` | Backtest options, supported resolutions, and execution modes |
| `POST` | `/api/v1/backtesting/run` | Execute historical backtest over real Delta Exchange candles |
| `GET` | `/api/v1/backtesting/results/{backtest_id}` | Retrieve cached backtest results by ID |

---

## 📈 Phase 2: Quantitative Strategy Engine

TokenIQ features a decoupled, testable strategy engine under `backend/app/strategies/`:
- **EMA Crossover (9/21) + RSI Filter**: Baseline trend-following strategy with configurable fast EMA (default 9), slow EMA (default 21), 14-period RSI filter, optional volume SMA confirmation, and explicit position intent (`OPEN_LONG`, `CLOSE_LONG`, `OPEN_SHORT`).
- **Completed Candle Evaluation**: Strategy signals are evaluated strictly on completed candles to prevent look-ahead bias and avoid repeated signals from partially formed bars.
- **Idempotency**: Repeated requests on the same completed candle return `HOLD` with `is_repeated: true`.

---

## 🔬 Phase 3: Historical Backtesting Engine

A realistic, event-driven backtesting engine located under `backend/app/backtesting/`:
- **Delta Exchange India Historical Feed**: Backtests run over authentic historical OHLCV data fetched dynamically.
- **Look-Ahead Prevention**: Strategy signals evaluated on completed candle $i$ execute strictly on the open of candle $i+1$ (`next_open` execution mode).
- **Realistic Friction**: Configurable taker trading fees (default 0.05%) and execution slippage (default 0.05%) modeled on both entry and exit.
- **Comprehensive Analytics**: Computes net profit, return %, win rate, profit factor, max drawdown (% and $), equity time-series curve, drawdown percentage curve, and complete trade logs with fees and holding duration.
- **Interactive UI**: Dedicated Backtesting view in the dashboard with parameter sliders, equity curve SVG chart, drawdown visualization, and trade audit log.

---

## 🔒 Security & Scope Notice

* **Analytical Signals & Backtesting Only**: TokenIQ signals and backtesting results are hypothetical and modeled for educational and research purposes. They do not claim profitability, do not constitute financial advice, and are **not connected to automated order execution**.
* No private exchange API credentials or wallet keys are used or accepted. Real market data is pulled solely from public Delta Exchange India APIs.
