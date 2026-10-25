import React from 'react';
import {
  BarChart3,
  LineChart,
  Star,
  Info,
  ChevronLeft,
  ChevronRight,
  Zap,
  ExternalLink,
  ShieldCheck,
  Layers,
  Wallet,
  ShieldAlert,
} from 'lucide-react';
import type { ActiveTab } from '../types/market';

interface SidebarProps {
  activeTab: ActiveTab;
  onTabChange: (tab: ActiveTab) => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
  watchlistCount: number;
}

export const Sidebar: React.FC<SidebarProps> = ({
  activeTab,
  onTabChange,
  collapsed,
  onToggleCollapse,
  watchlistCount,
}) => {
  const navItems = [
    {
      id: 'overview' as ActiveTab,
      label: 'Market Overview',
      icon: <BarChart3 className="w-4 h-4 shrink-0" />,
      badge: null,
    },
    {
      id: 'charts' as ActiveTab,
      label: 'Live Charts',
      icon: <LineChart className="w-4 h-4 shrink-0" />,
      badge: 'PRO',
    },
    {
      id: 'watchlist' as ActiveTab,
      label: 'Market Watchlist',
      icon: <Star className="w-4 h-4 shrink-0" />,
      badge: watchlistCount > 0 ? String(watchlistCount) : null,
    },
    {
      id: 'strategy-center' as ActiveTab,
      label: 'Strategy Center',
      icon: <Layers className="w-4 h-4 shrink-0" />,
      badge: null,
    },
    {
      id: 'wallet' as ActiveTab,
      label: 'Testnet Wallet',
      icon: <Wallet className="w-4 h-4 shrink-0" />,
      badge: 'TESTNET',
    },
    {
      id: 'safety' as ActiveTab,
      label: 'Trading Safety',
      icon: <ShieldAlert className="w-4 h-4 shrink-0" />,
      badge: 'SAFETY',
    },
    {
      id: 'about' as ActiveTab,
      label: 'About TokenIQ',
      icon: <Info className="w-4 h-4 shrink-0" />,
      badge: null,
    },
  ];

  return (
    <aside
      className={`relative z-20 flex flex-col bg-[#0B0F17] border-r border-white/[0.07] transition-all duration-300 ease-in-out shrink-0 select-none ${
        collapsed ? 'w-16' : 'w-64'
      }`}
    >
      {/* Brand Header */}
      <div className="flex items-center h-16 px-4 border-b border-white/[0.07] justify-between">
        {!collapsed ? (
          <div className="flex items-center gap-2.5 overflow-hidden">
            <div className="flex items-center justify-center w-9 h-9 rounded-xl bg-gradient-to-br from-cyan-400/20 via-blue-500/20 to-cyan-500/10 border border-cyan-400/30 text-cyan-400 shadow-glow-cyan/30">
              <Zap className="w-5 h-5 fill-cyan-400/20 text-cyan-400" />
            </div>
            <div className="flex flex-col">
              <div className="flex items-center gap-1.5">
                <span className="font-bold text-base tracking-tight text-white font-sans">
                  Token<span className="text-cyan-400">IQ</span>
                </span>
                <span className="text-[10px] px-1.5 py-0.2 rounded font-mono font-semibold bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
                  v1.0
                </span>
              </div>
              <span className="text-[11px] text-slate-400 font-mono tracking-tight truncate">
                Crypto Market Terminal
              </span>
            </div>
          </div>
        ) : (
          <div className="flex items-center justify-center w-full">
            <div className="flex items-center justify-center w-9 h-9 rounded-xl bg-gradient-to-br from-cyan-400/20 to-blue-500/20 border border-cyan-400/30 text-cyan-400">
              <Zap className="w-5 h-5 text-cyan-400" />
            </div>
          </div>
        )}

        <button
          onClick={onToggleCollapse}
          className="hidden md:flex items-center justify-center w-7 h-7 rounded-lg text-slate-400 hover:text-white hover:bg-white/[0.05] transition-colors"
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>
      </div>

      {/* Navigation Links */}
      <nav className="flex-1 px-2.5 py-4 space-y-1.5 overflow-y-auto">
        {!collapsed && (
          <div className="px-3 pb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-400 font-mono">
            Navigation
          </div>
        )}

        {navItems.map((item) => {
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onTabChange(item.id)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all group relative ${
                isActive
                  ? 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 font-semibold shadow-glow-cyan/10'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-white/[0.04]'
              }`}
              title={collapsed ? item.label : undefined}
            >
              {item.icon}

              {!collapsed && (
                <span className="flex-1 text-left truncate">{item.label}</span>
              )}

              {!collapsed && item.badge && (
                <span
                  className={`text-[10px] font-mono px-1.5 py-0.5 rounded font-bold ${
                    isActive
                      ? 'bg-cyan-400/20 text-cyan-300'
                      : 'bg-white/[0.08] text-slate-400 group-hover:text-slate-200'
                  }`}
                >
                  {item.badge}
                </span>
              )}

              {/* Active Indicator Strip */}
              {isActive && (
                <span className="absolute left-0 top-1.5 bottom-1.5 w-1 bg-cyan-400 rounded-r" />
              )}
            </button>
          );
        })}
      </nav>

      {/* Data Source Badge Footer */}
      <div className="p-3 border-t border-white/[0.07] bg-[#0A0D14]/60">
        {!collapsed ? (
          <div className="flex flex-col gap-2 p-2.5 rounded-lg bg-white/[0.02] border border-white/[0.05]">
            <div className="flex items-center gap-1.5 text-xs text-slate-300 font-medium">
              <ShieldCheck className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
              <span>Delta Exchange API</span>
            </div>
            <p className="text-[11px] text-slate-400 leading-relaxed font-sans">
              Live market quotes & institutional-grade websocket feeds.
            </p>
            <a
              href="https://india.delta.exchange"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-[11px] text-cyan-400/80 hover:text-cyan-300 font-mono transition-colors pt-1"
            >
              Exchange Portal <ExternalLink className="w-3 h-3" />
            </a>
          </div>
        ) : (
          <div className="flex justify-center" title="Powered by Delta Exchange">
            <ShieldCheck className="w-5 h-5 text-cyan-400/80" />
          </div>
        )}
      </div>
    </aside>
  );
};
