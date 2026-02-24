import React from 'react';
import { SEVERITY_COLORS } from '../hooks/useAlerts.js';

export default function SeverityLegend() {
  return (
    <div style={{
      position: 'absolute',
      bottom: 30,
      right: 10,
      zIndex: 1000,
      background: 'rgba(255,255,255,0.93)',
      borderRadius: 8,
      padding: '10px 14px',
      boxShadow: '0 2px 8px rgba(0,0,0,0.2)',
      fontSize: 13,
      minWidth: 130,
    }}>
      <div style={{ fontWeight: 700, marginBottom: 6, color: '#333' }}>Severity</div>
      {Object.entries(SEVERITY_COLORS).map(([label, color]) => (
        <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <div style={{
            width: 14, height: 14, borderRadius: 3,
            background: color, flexShrink: 0,
          }} />
          <span style={{ color: '#444' }}>{label}</span>
        </div>
      ))}
    </div>
  );
}
