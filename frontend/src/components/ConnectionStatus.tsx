import React from 'react';
import { Wifi, WifiOff, RefreshCw } from 'lucide-react';
import type { ConnectionStatusType } from '../types/market';

interface ConnectionStatusProps {
  status: ConnectionStatusType;
  lastMessageTime?: Date | null;
  onReconnect?: () => void;
  compact?: boolean;
}

export const ConnectionStatus: React.FC<ConnectionStatusProps> = ({
  status,
  lastMessageTime,
  onReconnect,
  compact = false,
}) => {
  const getBadgeConfig = () => {
    switch (status) {
      case 'connected':
        return {
          dotBg: 'bg-emerald-400',
          dotPing: 'bg-emerald-400/50',
          textColor: 'text-emerald-400',
          border: 'border-emerald-500/20',
          bg: 'bg-emerald-500/10',
          label: 'Connected',
          icon: <Wifi className="w-3.5 h-3.5 text-emerald-400" />,
        };
      case 'connecting':
        return {
          dotBg: 'bg-amber-400',
          dotPing: 'bg-amber-400/50',
          textColor: 'text-amber-400',
          border: 'border-amber-500/20',
          bg: 'bg-amber-500/10',
          label: 'Connecting...',
          icon: <RefreshCw className="w-3.5 h-3.5 text-amber-400 animate-spin" />,
        };
      case 'disconnected':
      default:
        return {
          dotBg: 'bg-rose-500',
          dotPing: 'bg-rose-500/30',
          textColor: 'text-rose-400',
          border: 'border-rose-500/20',
          bg: 'bg-rose-500/10',
          label: 'Disconnected',
          icon: <WifiOff className="w-3.5 h-3.5 text-rose-400" />,
        };
    }
  };

  const config = getBadgeConfig();

  if (compact) {
    return (
      <div
        className={`inline-flex items-center gap-2 px-2.5 py-1 rounded-full text-xs font-medium border ${config.bg} ${config.border} ${config.textColor}`}
        title={`Status: ${config.label}${lastMessageTime ? ` (Last update: ${lastMessageTime.toLocaleTimeString()})` : ''}`}
      >
        <span className="relative flex h-2 w-2">
          {status === 'connected' && (
            <span className={`animate-ping absolute inline-flex h-full w-full rounded-full ${config.dotPing} opacity-75`} />
          )}
          <span className={`relative inline-flex rounded-full h-2 w-2 ${config.dotBg}`} />
        </span>
        <span className="font-mono text-[11px] tracking-wide uppercase">{config.label}</span>
      </div>
    );
  }

  return (
    <div className={`flex items-center gap-2.5 px-3 py-1.5 rounded-lg border ${config.bg} ${config.border}`}>
      <div className="relative flex h-2.5 w-2.5 items-center justify-center">
        {status === 'connected' && (
          <span className={`animate-ping absolute inline-flex h-full w-full rounded-full ${config.dotPing} opacity-75`} />
        )}
        <span className={`relative inline-flex rounded-full h-2 w-2 ${config.dotBg}`} />
      </div>

      <div className="flex flex-col">
        <div className="flex items-center gap-1.5">
          <span className={`text-xs font-semibold uppercase tracking-wider ${config.textColor}`}>
            {config.label}
          </span>
          <span className="text-[10px] text-slate-500 font-mono">WS API</span>
        </div>
        {lastMessageTime && status === 'connected' && (
          <span className="text-[10px] text-slate-400 font-mono">
            Feed active {lastMessageTime.toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })}
          </span>
        )}
      </div>

      {status === 'disconnected' && onReconnect && (
        <button
          onClick={onReconnect}
          className="ml-2 text-xs text-rose-300 hover:text-white underline font-mono flex items-center gap-1 transition-colors"
          title="Retry connection"
        >
          <RefreshCw className="w-3 h-3" /> Retry
        </button>
      )}
    </div>
  );
};
