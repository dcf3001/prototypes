import React from 'react';
import { severityColor } from '../hooks/useAlerts.js';

export default function AlertSidebar({ features, onSelect, selected }) {
  return (
    <div style={{
      width: 300,
      flexShrink: 0,
      overflowY: 'auto',
      borderRight: '1px solid #ddd',
      background: '#fafafa',
    }}>
      {features.length === 0 && (
        <div style={{ padding: 16, color: '#888', fontSize: 13 }}>No active alerts.</div>
      )}
      {features.map(f => {
        const p = f.properties || {};
        const color = severityColor(p.severity);
        const isSelected = selected?.id === f.id;
        return (
          <div
            key={f.id}
            onClick={() => onSelect(f)}
            style={{
              padding: '10px 12px',
              borderBottom: '1px solid #e8e8e8',
              cursor: 'pointer',
              background: isSelected ? '#e3eefa' : 'transparent',
              borderLeft: `4px solid ${color}`,
              transition: 'background 0.1s',
            }}
          >
            <div style={{ fontWeight: 600, fontSize: 13, color: '#222', marginBottom: 2 }}>
              {p.event || 'Unknown'}
            </div>
            <div style={{ fontSize: 12, color: '#555', marginBottom: 2 }}>
              {p.areaDesc || ''}
            </div>
            <div style={{ fontSize: 11, color: color, fontWeight: 600 }}>
              {p.severity} · {p.urgency}
            </div>
          </div>
        );
      })}
    </div>
  );
}
