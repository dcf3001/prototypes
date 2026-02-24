import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { getAlertTypes, getHistoricalAlerts } from '../api/client.js';

export default function HazardSelector({ selected, onSelect, historicalPreset }) {
  // Live mode: fetch type counts from server
  const { data: liveTypes = [] } = useQuery({
    queryKey: ['alertTypes'],
    queryFn: getAlertTypes,
    refetchInterval: 5 * 60 * 1000,
    staleTime: 4 * 60 * 1000,
    enabled: !historicalPreset,
  });

  // Historical mode: derive types from the Ian snapshot already in cache
  const { data: historicalData } = useQuery({
    queryKey: ['alerts', historicalPreset],
    queryFn: () => getHistoricalAlerts(historicalPreset),
    staleTime: Infinity,
    enabled: !!historicalPreset,
  });

  const types = historicalPreset
    ? deriveTypes(historicalData?.features || [])
    : liveTypes;

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, padding: '8px 12px', alignItems: 'center' }}>
      <button onClick={() => onSelect(null)} style={pillStyle(selected === null)}>
        All
      </button>
      {types.map(({ event, count }) => (
        <button
          key={event}
          onClick={() => onSelect(event)}
          style={pillStyle(selected === event)}
        >
          {event} <span style={{ opacity: 0.75 }}>({count})</span>
        </button>
      ))}
    </div>
  );
}

function deriveTypes(features) {
  const counts = {};
  for (const f of features) {
    const event = f.properties?.event || 'Unknown';
    counts[event] = (counts[event] || 0) + 1;
  }
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .map(([event, count]) => ({ event, count }));
}

function pillStyle(active) {
  return {
    padding: '4px 10px',
    borderRadius: 20,
    border: active ? '2px solid #1565c0' : '1.5px solid #bbb',
    background: active ? '#1565c0' : '#fff',
    color: active ? '#fff' : '#333',
    cursor: 'pointer',
    fontSize: 12,
    fontWeight: active ? 600 : 400,
    whiteSpace: 'nowrap',
    transition: 'all 0.15s',
  };
}
