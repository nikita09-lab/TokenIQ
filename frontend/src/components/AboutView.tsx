import React from 'react';
import {
  ShieldCheck,
  Zap,
  Activity,
  Layers,
  LineChart,
  Lock,
  Code2,
} from 'lucide-react';

export const AboutView: React.FC = () => {
  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Hero Card */}
      <div className="p-6 md:p-8 rounded-2xl bg-[#0F1422] border border-white/[0.08] relative overflow-hidden shadow-2xl">
        <div className="absolute top-0 right-0 w-80 h-80 bg-gradient-to-bl from-cyan-500/10 via-blue-500/5 to-transparent rounded-full blur-3xl pointer-events-none" />

        <div className="flex items-center gap-3 mb-4">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-cyan-400/20 via-blue-500/20 to-cyan-500/10 border border-cyan-400/30 flex items-center justify-center text-cyan-400 shadow-glow-cyan/20">
            <Zap className="w-6 h-6 fill-cyan-400/20" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white font-sans tracking-tight">
              TokenIQ — Live Crypto Market Dashboard
            </h1>
            <p className="text-sm text-cyan-400 font-mono">
              High-Frequency Market Terminal for Delta Exchange
            </p>
          </div>
        </div>

        <p className="text-slate-300 text-sm leading-relaxed max-w-2xl font-sans">
          TokenIQ is an institutional-grade financial intelligence dashboard designed for crypto traders and market
          analysts. Powered by live Delta Exchange market data and low-latency WebSockets, TokenIQ provides real-time
          candlesticks, continuous order book quotes, and dynamic market breadth analytics.
        </p>

        {/* Feature Pills */}
        <div className="flex flex-wrap gap-2.5 mt-6">
          <span className="px-3 py-1 rounded-full text-xs font-mono bg-cyan-500/10 text-cyan-300 border border-cyan-500/20 flex items-center gap-1.5">
            <Activity className="w-3.5 h-3.5 text-cyan-400" />
            Live WebSocket Streaming
          </span>
          <span className="px-3 py-1 rounded-full text-xs font-mono bg-emerald-500/10 text-emerald-300 border border-emerald-500/20 flex items-center gap-1.5">
            <LineChart className="w-3.5 h-3.5 text-emerald-400" />
            Lightweight Financial Charts
          </span>
          <span className="px-3 py-1 rounded-full text-xs font-mono bg-blue-500/10 text-blue-300 border border-blue-500/20 flex items-center gap-1.5">
            <Layers className="w-3.5 h-3.5 text-blue-400" />
            200+ Perpetual Futures
          </span>
          <span className="px-3 py-1 rounded-full text-xs font-mono bg-purple-500/10 text-purple-300 border border-purple-500/20 flex items-center gap-1.5">
            <ShieldCheck className="w-3.5 h-3.5 text-purple-400" />
            Zero Hardcoded Prices
          </span>
        </div>
      </div>

      {/* Architecture & Live Integration Details */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Data Integrity */}
        <div className="p-5 rounded-xl bg-[#0F1422] border border-white/[0.07] shadow-lg">
          <div className="flex items-center gap-2 mb-3">
            <Code2 className="w-5 h-5 text-cyan-400" />
            <h3 className="text-sm font-bold text-white">Delta Exchange Integration</h3>
          </div>
          <ul className="space-y-2 text-xs text-slate-300 font-sans">
            <li className="flex items-start gap-2">
              <span className="text-cyan-400 font-mono">▸</span>
              <span>
                <strong className="text-white font-mono">REST Public Tickers:</strong> Dynamically loads all active
                trading products from <code className="bg-white/[0.06] px-1 py-0.5 rounded text-cyan-300">/v2/tickers</code>.
              </span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-cyan-400 font-mono">▸</span>
              <span>
                <strong className="text-white font-mono">Historical Candles:</strong> Fetches exact OHLC bars across
                intervals (1m, 5m, 15m, 1h, 1d) via <code className="bg-white/[0.06] px-1 py-0.5 rounded text-cyan-300">/v2/history/candles</code>.
              </span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-cyan-400 font-mono">▸</span>
              <span>
                <strong className="text-white font-mono">Real-time WebSocket:</strong> Connected to{' '}
                <code className="bg-white/[0.06] px-1 py-0.5 rounded text-cyan-300">wss://public-socket.india.delta.exchange</code> with automatic reconnection and channel subscription.
              </span>
            </li>
          </ul>
        </div>

        {/* Security & Scope Scope Banner */}
        <div className="p-5 rounded-xl bg-[#0F1422] border border-white/[0.07] shadow-lg">
          <div className="flex items-center gap-2 mb-3">
            <Lock className="w-5 h-5 text-amber-400" />
            <h3 className="text-sm font-bold text-white">Security & Hackathon Scope</h3>
          </div>
          <div className="space-y-2.5 text-xs text-slate-300 font-sans leading-relaxed">
            <p>
              In strict accordance with project requirements, this version operates in <strong>read-only market intelligence mode</strong>.
            </p>
            <div className="p-2.5 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-200 text-[11px]">
              <strong>Out of scope for this version:</strong> No order execution, automated trading bots, private API keys, or wallet connections. All market data is publicly sourced.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
